# graph.py —— 推荐 Agent 的「五步图」（LangGraph 编排）+ 程序化护栏。
#
# ============================ 这个文件是干什么的 ============================
# 用户说一句「今晚想吃火锅，人均100」，模型要给出的不是一段自由发挥的文字，
# 而是一份「基于真实证据、带缺点、可追溯」的推荐。这个文件就是把这件事拆成固定步骤去执行。
#
# 方法论名 PRED：Preference(画像) → Restriction(硬约束) → Evidence(检索+证据) → Decide(对比生成)
# 实现上是五个节点 + 一个护栏节点：
#   parse_intent   LLM：用户话 → 硬约束（品类/预算）；缺品类且冷启动 → 先问一个问题（短路）
#   load_profile   工具：读画像（离线刷新，在线只读；冷启动只信本轮约束）
#   search_shops   工具：硬过滤检索（approved 强制、带距离、8~12 家——绝不把全世界塞给模型）
#   load_evidence  工具：候选逐家拉证据（正评3+差评3，带 evidenceId）
#   decide         LLM：对比生成 3 家（必须有缺点、必须引用 evidenceId）
#   guardrail      纯代码三查：店ID⊆候选 / 引用ID存在 / 缺点非空——违者 42201，绝不放行
#
# ============================ 核心设计思想（面试金句） ============================
# 「能用确定计算消灭的失败，不进生成」——
#   品类过滤、距离计算、证据抓取都是【确定的】（SQL 能算准），所以放在 LLM 之前由代码做；
#   LLM 只负责它真正擅长的「对比与表达」。
#   这样幻觉的空间被压缩到最小：模型手里只有 8~12 家店和它们的真实评论，编无可编。
#
# ============================ 诚实降级原则 ============================
# LLM 未配置或调用失败 → 返回 50000「AI 服务未连通，未生成任何内容」，
# 绝不降级成模板内容伪装成正常推荐（宁可报错，不可冒充）。
#
# ============================ 本文件涉及的 Python 语法速览（Java 背景看这里） ============================
#   from typing import Any, TypedDict  → 引入类型工具；TypedDict = 给字典规定「有哪些键、什么类型」
#   class AgentState(TypedDict, total=False) → 状态定义（total=False 表示所有键都可选）
#   state["message"] / state.get("k", 默认值) → 取字典值；[] 取不到会报错，.get() 取不到给默认
#   {c["id"] for c in 列表}            → 集合推导式（≈ Java stream().map().collect(toSet())）
#   state.get("tool_calls", []) + [新元素] → 列表拼接（造新列表，不修改原列表）
#   {**cons, "category": category}     → 字典展开合并（≈ Java 新建 Map 再 putAll）
#   f"文本{变量}"                       → f-string 字符串插值
#   for s in shops: ...                → 遍历
#   if not x / if x is None            → 假值判断 / 严格判 None
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

import tools  # 本目录 tools.py：所有「取数据」的函数都在那
from llm import chat_json, llm_available  # LLM 调用与「是否配置」的开关

GUARDRAIL_CODE = 42201   # 护栏拦截的错误码（项目约定的「AI 输出不合格」）

CATEGORY_LABELS = {"HOTPOT": "火锅", "COFFEE": "咖啡", "ENTERTAIN": "玩乐"}


class AgentState(TypedDict, total=False):
    """图的「共享状态」：所有节点都读写这个对象，它是贯穿五步的传话筒。

    节点函数的约定：接收完整 state，返回一个【增量 dict】（只写自己要改的键），
    LangGraph 负责把增量合并回 state。类比 Java：像一条流水线上的工件，每站加工一部分。
    """
    # 输入（run_recommend 塞进来）
    user_id: int
    message: str
    lat: float
    lng: float
    session_id: str
    # 五步的中间产物（节点之间传递）
    constraints: dict          # {category, budgetYuan, radius}
    clarify_question: str      # 非空则短路：先问一个问题
    profile: dict
    candidates: list
    evidences: list
    tool_calls: list           # 工具调用清单（trace 的 tools_json 原料，用于观测/演示）
    # 输出
    answer: str
    shops: list
    pros: list
    cons: list
    evidence_ids: list
    error_code: int
    error_message: str


# ---------- 节点①：解析意图（LLM 小任务） ----------

# 系统提示词：告诉模型「你只做一件事——把用户的话拆成结构化约束，判断不了就填 null」
# 注意提示词里出现了 "json" 字样和格式示例——这是 json_object 模式的硬要求
PARSE_SYSTEM = (
    "你是推荐系统的意图解析器。从用户的话里抽取结构化约束，只输出 json："
    '{"category": "HOTPOT 或 COFFEE 或 ENTERTAIN 或 null", "budgetYuan": 数字或 null, "note": "其他约束原话或 null"}。'
    "无法判断的字段填 null，不要猜。"
)


def parse_intent(state: AgentState) -> dict:
    """节点①：把用户自然语言解析成硬约束（品类/预算）。

    输入：state["message"]
    输出：{"constraints": {"category":..., "budgetYuan":..., "radius":5000}}
    设计要点：解析失败【不阻塞主流程】——静默走冷启动路径，后面会用画像或反问来兜。
    """
    message = state["message"]
    category = None
    budget = None
    if llm_available():                       # 没配 key 就跳过，直接返回空约束
        try:
            parsed = chat_json(
                PARSE_SYSTEM,
                f"用户说：{message}\n已知品类枚举：HOTPOT(火锅)/COFFEE(咖啡)/ENTERTAIN(展览玩乐)。",
                max_tokens=200,               # 小任务：输出很短，限制 200 token 省成本
            )
            cat = parsed.get("category")      # 取出模型给的品类
            if cat in CATEGORY_LABELS:        # 白名单校验：只认这三个枚举值，别的当没给
                category = cat
            budget = parsed.get("budgetYuan") # 预算（可能为 None）
        except Exception:
            pass  # 解析失败走冷启动路径（不阻塞主流程）
    return {"constraints": {"category": category, "budgetYuan": budget, "radius": 5000}}


# ---------- 节点②：读画像（工具） ----------

def load_profile(state: AgentState) -> dict:
    """节点②：读用户画像（历史偏好）。

    输入：state["user_id"]
    输出：{"profile": {...}, "tool_calls": [...]}
    设计要点：画像离线刷新（启动时聚合 likes/reviews/orders），在线只读——
             在线现算徒增时延，而偏好这类数据不需要实时。
             读失败也不报错，给一个「冷启动」默认值，让流程继续。
    """
    try:
        profile = tools.get_profile(state["user_id"])
    except Exception:
        # 取不到就给冷启动默认值：coldStart=True 会让后面的条件边走「先问一句」而不是瞎猜
        profile = {"coldStart": True, "tags": [], "avgPrice": None, "topCategories": []}
    return {
        "profile": profile,
        # 追加一条工具调用记录（+ 造新列表，不改原列表——避免节点间共享引用被意外修改）
        "tool_calls": state.get("tool_calls", []) + [f"GET /internal/users/{state['user_id']}/profile"],
    }


# ---------- 节点③：检索候选（工具，approved 强制） ----------

def search_shops(state: AgentState) -> dict:
    """节点③：硬过滤检索，拿到 8~12 家候选店。

    输入：constraints（品类/半径）+ profile（画像兜底用）
    输出：{"candidates": [...], "constraints": {...}, "tool_calls": [...]}
    两个设计要点：
      ① 画像兜底：用户这轮没说品类、但历史偏好明确 → 用偏好（个性化）；
         冷启动绝不兜底（不瞎猜，交给条件边去反问）
      ② 主站挂了 → 返回 50000，绝不拿空结果伪装成「附近没有店」
    """
    cons = state.get("constraints", {})
    profile = state.get("profile", {})
    category = cons.get("category")
    # 画像兜底：本轮没说品类但历史偏好明确 → 用偏好（个性化；冷启动不用——不瞎猜）
    if category is None:
        top = profile.get("topCategories") or []      # 取历史偏好品类列表；None 时给空列表
        if top and not profile.get("coldStart"):      # 有偏好 且 不是冷启动
            category = top[0]                         # 用排名第一的品类
    try:
        candidates = tools.search_shops(
            state["lat"], state["lng"], radius=cons.get("radius", 5000), category=category,
        )
    except Exception as e:
        # 主站未连通：诚实报错，不拿空结果伪装"附近没有店"
        return {
            "error_code": 50000,
            "error_message": f"主站数据服务未连通（{type(e).__name__}）：检索失败，本次请求已中止，未生成任何内容。",
            "candidates": [],
        }
    return {
        "candidates": candidates,
        "constraints": {**cons, "category": category},   # 合并：把最终使用的品类写回状态
        "tool_calls": state.get("tool_calls", [])
                      + [f"GET /internal/shops/search?category={category}&radius={cons.get('radius', 5000)}"],
    }


# ---------- 节点④：拉证据（工具，正负评都要） ----------

def load_evidence(state: AgentState) -> dict:
    """节点④：给候选店逐家拉「证据」（评分/销量/券 + 正评3条 + 差评3条）。

    输入：state["candidates"]
    输出：{"evidences": [...], "tool_calls": [...]}
    三个设计要点：
      ① 只取前 6 家（控成本：每拉一家就是一次 HTTP + 更多 token）
      ② 正评和差评都要——差评是「缺点」字段的事实来源（推荐必须说缺点）
      ③ 全部拉失败 → 50000；部分失败则容忍（有几家算几家）
    """
    candidates = state.get("candidates", [])
    if not candidates:
        return {"evidences": []}   # 检索已空（或上游已报错），无需拉证据
    evidences = []
    failed = 0
    for c in candidates[:6]:   # candidates[:6] 是「切片」：取前 6 个（≈ Java subList(0,6)）
        try:
            ev = tools.get_evidence(c["id"])
            if ev.get("exists", True):    # exists 默认 True：字段没给就认为是存在的
                evidences.append(ev)
        except Exception:
            failed += 1                   # 记失败数（+= 自增）
            continue                      # 单家失败不中断，继续拉下一家
    if not evidences and failed > 0:
        # 一家都没拉到且确实有失败 → 是服务故障，诚实报错
        return {
            "error_code": 50000,
            "error_message": "主站数据服务未连通：证据拉取全部失败，本次请求已中止，未生成任何内容。",
            "evidences": [],
        }
    return {
        "evidences": evidences,
        # 列表推导式：为每家证据生成一条工具调用记录
        "tool_calls": state.get("tool_calls", [])
                      + [f"GET /internal/shops/{e['shopId']}/evidence" for e in evidences],
    }


# ---------- 节点⑤：对比生成（LLM 大任务） ----------

# 系统提示词：这是「生成质量」的关键。四条硬规矩对应四个护栏检查：
#   最多3家 / cons必填 / 不许编造 / 理由要具体
DECIDE_SYSTEM = (
    "你是本地生活推荐助手。基于给定的候选店铺证据做对比推荐，只输出 json："
    '{"answer": "给用户看的总评(80字内)", '
    '"shops": [{"id": 店铺ID, "name": "店名", "reason": "推荐理由(50字内,必须引用证据里的具体事实)", '
    '"cons": "一个真实的可能缺点(30字内)"}], '
    '"evidenceIds": ["你引用过的证据ID列表"]}。'
    "硬规矩：1.最多推荐3家(候选不足则如实减少)；2.每家 cons 必填且必须来自差评或客观数字，禁止套话；"
    "3.禁止编造店名/菜名/折扣——一切事实只能来自证据；4.理由要具体(引用评分/销量/评论内容)。"
)


def decide(state: AgentState) -> dict:
    """节点⑤：让 LLM 基于证据做对比推荐（唯一的大生成步骤）。

    三种分支（面试可讲，体现「诚实降级」）：
      ① 上游已报错 → 直接跳过（return {} 表示不改状态），连模型都不调（省钱）
      ② 证据为空 → 如实回答「附近没有找到」，这是【真实结论】不是故障
      ③ LLM 未配置/调用失败 → 返回 50000 明说「未生成任何内容」，绝不用模板冒充
    """
    if state.get("error_code"):
        return {}   # 上游（检索/证据）已报错，不再生成
    evidences = state.get("evidences", [])
    if not evidences:
        # 检索结果为空是"真实结论"（附近确实没有），如实告知不算失败
        return {
            "answer": "附近没有找到符合条件的店，换个品类或扩大范围试试？",
            "shops": [], "pros": [], "cons": [], "evidence_ids": [],
        }
    if not llm_available():
        return {
            "error_code": 50000,
            "error_message": "AI 服务未连通（未配置 API Key）：本次请求已中止生成，未产出任何推荐内容。请配置 LLM 后重试。",
        }
    try:
        return _decide_llm(state, evidences)
    except Exception as e:
        # 诚实降级：明说没连上，不拿模板内容冒充 AI 推荐
        return {
            "error_code": 50000,
            "error_message": f"AI 服务未连通（调用失败：{type(e).__name__}）：本次请求已中止生成，未产出任何推荐内容。请稍后再试。",
        }


def _decide_llm(state: AgentState, evidences: list) -> dict:
    """decide 的内部实现：拼提示词 → 调 LLM → 把结果摊平成状态字段。

    为什么单独抽一个函数：让 decide() 专心做「分支判断与降级」，这里专心做「调模型」。
    """
    import json   # 局部 import：只有这个函数用到 json，放这里也能减少模块加载时的依赖
    evidence_text = json.dumps(evidences, ensure_ascii=False)   # 证据转 JSON 文本（ensure_ascii=False 保留中文）
    profile = state.get("profile", {})
    profile_text = "（冷启动，无历史偏好）" if profile.get("coldStart") else json.dumps(profile, ensure_ascii=False)
    out = chat_json(
        DECIDE_SYSTEM,
        # 拼装用户消息：诉求 + 画像 + 证据（模型只能看到这些，看到什么就只能写什么）
        f"用户诉求：{state['message']}\n用户画像：{profile_text}\n候选店铺证据（json）：\n{evidence_text}",
        max_tokens=1500,
    )
    shops = out.get("shops", [])
    return {
        "answer": out.get("answer", ""),
        "shops": shops,
        # 列表推导式：从 shops 里抽出 reason/cons 两个列表（便于前端分开渲染）
        "pros": [s.get("reason", "") for s in shops],
        "cons": [s.get("cons", "") for s in shops],
        "evidence_ids": out.get("evidenceIds", []),
    }


# ---------- 节点⑥：护栏（纯代码，违者 42201） ----------

def guardrail(state: AgentState) -> dict:
    """节点⑥：程序化护栏——纯 Python 代码，不调用任何模型。

    这是「幻觉从概率问题变成可拦截错误」的落点。三查：

      ① 候选集闭包：推荐列表里的每家店，id 必须在检索候选里
         （编造店名 → 拦）
      ② 引用存在性：模型引用的每个 evidenceId，必须真实存在于证据里
         （编造引用 → 拦）
      ③ 缺点非空：每家店必须有 cons（禁止广告式输出）

    为什么用代码而不是再问一次模型：确定性（同输入必同判断）、快（微秒级）、可单测。
    返回：{} 表示全部通过（空增量，不改状态）；否则返回 error_code=42201，整单拒绝。
    """
    # 集合推导式：把所有候选店的 id 压成一个集合，查成员是 O(1)
    candidate_ids = {c["id"] for c in state.get("candidates", [])}
    # 把所有证据里正评+差评的 evidenceId 收成「合法引用集合」
    evidence_ids = set()
    for e in state.get("evidences", []):
        # (正评列表 or 空) + (负评列表 or 空)：or [] 是防御——字段为 None 时不让它炸
        for r in (e.get("positiveReviews") or []) + (e.get("negativeReviews") or []):
            if r.get("evidenceId"):
                evidence_ids.add(r["evidenceId"])

    for s in state.get("shops", []):
        # 第①查：店必须在候选集里（否则疑似编造）
        if s.get("id") not in candidate_ids:
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：店 {s.get('name')}({s.get('id')}) 不在检索结果中（疑似编造）"}
        # 第③查：缺点不能空/不能是纯空格（str().strip() 去掉首尾空白再判空）
        if not s.get("cons") or not str(s.get("cons")).strip():
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": "护栏拦截：存在无缺点推荐（禁止广告式输出）"}
    # 第②查：引用的证据必须真实存在
    for eid in state.get("evidence_ids", []):
        if eid not in evidence_ids:
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：引用的证据 {eid} 不存在（疑似编造）"}
    return {}   # 全过


# ---------- 组图 ----------

def _after_intent(state: AgentState) -> str:
    """条件边的「路由函数」：返回一个字符串，告诉 LangGraph 下一步去哪个节点。

    规则：品类没解析出来【且】是冷启动（没有历史偏好可兜底）→ 先问一个问题（clarify）；
         否则直接进检索（search）。
    这就是「冷启动不瞎猜」的代码实现——一句话交代设计取舍。
    """
    cons = state.get("constraints", {})
    profile = state.get("profile", {})
    if cons.get("category") is None and profile.get("coldStart"):
        return "clarify"
    return "search"


def _clarify(state: AgentState) -> dict:
    """clarify 节点：生成那句反问（不调模型，纯拼字符串——固定话术更可控）。"""
    cat_text = "/".join(CATEGORY_LABELS.values())   # 把品类标签拼成「火锅/咖啡/玩乐」
    return {"clarify_question": f"想吃什么类型？{cat_text}，或者直接描述场景（如'朋友聚餐'）"}


def build_graph():
    """构建并编译推荐图（模块加载时执行一次，之后所有请求复用同一个图对象）。

    LangGraph 三件套：
      add_node(名字, 函数)            → 注册节点
      add_edge(A, B)                  → 固定顺序：A 跑完跑 B
      add_conditional_edges(A, 路由函数, {分支名: 目标节点}) → 条件跳转（if/else 路由）
    """
    g = StateGraph(AgentState)
    # 注册 7 个节点（5 个业务步骤 + 1 个反问分支 + 1 个护栏）
    g.add_node("parse_intent", parse_intent)
    g.add_node("load_profile", load_profile)
    g.add_node("clarify", _clarify)
    g.add_node("search", search_shops)
    g.add_node("evidence", load_evidence)
    g.add_node("decide", decide)
    g.add_node("guardrail", guardrail)

    # 连边：START → 解析意图 → 读画像 →（条件）→ 反问 或 检索 → 证据 → 生成 → 护栏 → END
    g.add_edge(START, "parse_intent")
    g.add_edge("parse_intent", "load_profile")
    # 条件边：挂在 load_profile 后面（因为路由要看画像是否冷启动）
    g.add_conditional_edges("load_profile", _after_intent,
                            {"clarify": "clarify", "search": "search"})
    g.add_edge("clarify", END)          # 问完问题直接结束——这就是「短路」
    g.add_edge("search", "evidence")
    g.add_edge("evidence", "decide")
    g.add_edge("decide", "guardrail")
    g.add_edge("guardrail", END)
    return g.compile()


# 编译一次，进程内复用（图结构是静态的，每次请求只是传入不同的初始 state）
recommend_graph = build_graph()


def run_recommend(user_id: int, message: str, lat: float, lng: float,
                  session_id: str | None) -> dict:
    """入口函数：被 main.py 的 /agent/recommend 端点调用。

    参数：用户 ID、用户原话、经纬度、会话 ID（可空）
    返回：统一信封 {code, message, data}；data 里含 answer/shops/evidenceIds/toolCalls
    三种出口：① 有 error_code → 报错（护栏 42201 / 服务 50000）
             ② 有 clarify_question → 需要澄清（needClarify=True，前端继续追问）
             ③ 正常 → 整理成前端要的结构返回
    """
    init: AgentState = {
        "user_id": user_id, "message": message, "lat": lat, "lng": lng,
        "session_id": session_id or "s-0",     # 没传会话 ID 就给个默认值
    }
    result = recommend_graph.invoke(init)      # 跑图：invoke = 执行一次

    if result.get("error_code"):
        # 出口①：护栏拦截或服务故障，原样透传错误码（门面/前端按码处理）
        return {
            "code": result["error_code"], "message": result.get("error_message", "护栏拦截"),
            "data": None,
        }
    if result.get("clarify_question"):
        # 出口②：需要先反问（冷启动且没说品类），返回问题让前端展示，shops 为空
        return {
            "code": 0, "message": "ok",
            "data": {
                "sessionId": session_id or "s-0",
                "answer": result["clarify_question"],
                "shops": [], "pros": [], "cons": [], "evidenceIds": [],
                "needClarify": True,
                "toolCalls": result.get("tool_calls", []),
            },
        }
    # 出口③：正常推荐——把内部字段名（evidence_ids）转成对外合同名（evidenceIds）
    shops = [
        {"id": s.get("id"), "name": s.get("name"),
         "reason": s.get("reason"), "cons": s.get("cons")}
        for s in result.get("shops", [])
    ]
    return {
        "code": 0, "message": "ok",
        "data": {
            "sessionId": session_id or "s-0",
            "answer": result.get("answer", ""),
            "shops": shops,
            "pros": result.get("pros", []),
            "cons": result.get("cons", []),
            "evidenceIds": result.get("evidence_ids", []),
            "needClarify": False,
            "toolCalls": result.get("tool_calls", []),
        },
    }
