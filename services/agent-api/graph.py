# graph.py —— 推荐五步编排（LangGraph）+ 程序化护栏。
#
# 对外方法论名 PRED：Preference(画像) → Restriction(硬约束) → Evidence(检索+证据) → Decide(对比生成)。
# 实现上是五个节点 + 护栏节点：
#   parse_intent  LLM：message → 硬约束（品类/预算）；缺品类且无画像 → 先问 1 个问题（短路）
#   load_profile  工具：画像（离线刷新，在线只读；冷启动只信本轮约束）
#   search_shops  工具：硬过滤检索（approved 强制、带距离、8~12 家——绝不把全世界塞给模型）
#   load_evidence 工具：候选逐家拉证据（正评3+差评3，带 evidenceId）
#   decide        LLM：对比生成 3 家（必须有缺点、必须引用 evidenceId）
#   guardrail     纯代码三查：店ID⊆候选 / 引用ID存在 / 缺点非空——违者 42201，绝不放行
#
# LLM 未配置或调用失败 → 诚实报错 50000（"AI 服务未连通"），不生成任何内容——
# 降级绝不伪装成正常回答（产品诚实性原则：宁可报错，不可冒充）。
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

import tools
from llm import chat_json, llm_available

GUARDRAIL_CODE = 42201

CATEGORY_LABELS = {"HOTPOT": "火锅", "COFFEE": "咖啡", "ENTERTAIN": "玩乐"}


class AgentState(TypedDict, total=False):
    # 输入
    user_id: int
    message: str
    lat: float
    lng: float
    session_id: str
    # 五步的中间产物
    constraints: dict          # {category, budgetYuan, radius}
    clarify_question: str      # 非空则短路：先问一个问题
    profile: dict
    candidates: list
    evidences: list
    tool_calls: list           # 工具调用清单（trace 的 tools_json 原料）
    # 输出
    answer: str
    shops: list
    pros: list
    cons: list
    evidence_ids: list
    error_code: int
    error_message: str


# ---------- 节点①：解析意图（LLM 小任务） ----------

PARSE_SYSTEM = (
    "你是推荐系统的意图解析器。从用户的话里抽取结构化约束，只输出 json："
    '{"category": "HOTPOT 或 COFFEE 或 ENTERTAIN 或 null", "budgetYuan": 数字或 null, "note": "其他约束原话或 null"}。'
    "无法判断的字段填 null，不要猜。"
)


def parse_intent(state: AgentState) -> dict:
    message = state["message"]
    category = None
    budget = None
    if llm_available():
        try:
            parsed = chat_json(
                PARSE_SYSTEM,
                f"用户说：{message}\n已知品类枚举：HOTPOT(火锅)/COFFEE(咖啡)/ENTERTAIN(展览玩乐)。",
                max_tokens=200,
            )
            cat = parsed.get("category")
            if cat in CATEGORY_LABELS:
                category = cat
            budget = parsed.get("budgetYuan")
        except Exception:
            pass  # 解析失败走冷启动路径（不阻塞主流程）
    return {"constraints": {"category": category, "budgetYuan": budget, "radius": 5000}}


# ---------- 节点②：读画像（工具） ----------

def load_profile(state: AgentState) -> dict:
    try:
        profile = tools.get_profile(state["user_id"])
    except Exception:
        profile = {"coldStart": True, "tags": [], "avgPrice": None, "topCategories": []}
    return {
        "profile": profile,
        "tool_calls": state.get("tool_calls", []) + [f"GET /internal/users/{state['user_id']}/profile"],
    }


# ---------- 节点③：检索候选（工具，approved 强制） ----------

def search_shops(state: AgentState) -> dict:
    cons = state.get("constraints", {})
    profile = state.get("profile", {})
    category = cons.get("category")
    # 画像兜底：本轮没说品类但历史偏好明确 → 用偏好（个性化；冷启动不用——不瞎猜）
    if category is None:
        top = profile.get("topCategories") or []
        if top and not profile.get("coldStart"):
            category = top[0]
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
        "constraints": {**cons, "category": category},
        "tool_calls": state.get("tool_calls", [])
                      + [f"GET /internal/shops/search?category={category}&radius={cons.get('radius', 5000)}"],
    }


# ---------- 节点④：拉证据（工具，正负评都要） ----------

def load_evidence(state: AgentState) -> dict:
    candidates = state.get("candidates", [])
    if not candidates:
        return {"evidences": []}   # 检索已空（或上游已报错），无需拉证据
    evidences = []
    failed = 0
    for c in candidates[:6]:   # 控成本：最多 6 家进对比池
        try:
            ev = tools.get_evidence(c["id"])
            if ev.get("exists", True):
                evidences.append(ev)
        except Exception:
            failed += 1
            continue
    if not evidences and failed > 0:
        return {
            "error_code": 50000,
            "error_message": "主站数据服务未连通：证据拉取全部失败，本次请求已中止，未生成任何内容。",
            "evidences": [],
        }
    return {
        "evidences": evidences,
        "tool_calls": state.get("tool_calls", [])
                      + [f"GET /internal/shops/{e['shopId']}/evidence" for e in evidences],
    }


# ---------- 节点⑤：对比生成（LLM 大任务） ----------

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
    """生成节点：只做真实生成。LLM 未配置或调用失败 → 诚实报错（50000），绝不降级成模板伪装成正常推荐。"""
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
    import json
    evidence_text = json.dumps(evidences, ensure_ascii=False)
    profile = state.get("profile", {})
    profile_text = "（冷启动，无历史偏好）" if profile.get("coldStart") else json.dumps(profile, ensure_ascii=False)
    out = chat_json(
        DECIDE_SYSTEM,
        f"用户诉求：{state['message']}\n用户画像：{profile_text}\n候选店铺证据（json）：\n{evidence_text}",
        max_tokens=1500,
    )
    shops = out.get("shops", [])
    return {
        "answer": out.get("answer", ""),
        "shops": shops,
        "pros": [s.get("reason", "") for s in shops],
        "cons": [s.get("cons", "") for s in shops],
        "evidence_ids": out.get("evidenceIds", []),
    }


# ---------- 节点⑥：护栏（纯代码，违者 42201） ----------

def guardrail(state: AgentState) -> dict:
    candidate_ids = {c["id"] for c in state.get("candidates", [])}
    evidence_ids = set()
    for e in state.get("evidences", []):
        for r in (e.get("positiveReviews") or []) + (e.get("negativeReviews") or []):
            if r.get("evidenceId"):
                evidence_ids.add(r["evidenceId"])

    for s in state.get("shops", []):
        if s.get("id") not in candidate_ids:
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：店 {s.get('name')}({s.get('id')}) 不在检索结果中（疑似编造）"}
        if not s.get("cons") or not str(s.get("cons")).strip():
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": "护栏拦截：存在无缺点推荐（禁止广告式输出）"}
    for eid in state.get("evidence_ids", []):
        if eid not in evidence_ids:
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：引用的证据 {eid} 不存在（疑似编造）"}
    return {}


# ---------- 组图 ----------

def _after_intent(state: AgentState) -> str:
    """条件边：缺关键约束（品类）且冷启动 → 先问一个问题；否则走主流程"""
    cons = state.get("constraints", {})
    profile = state.get("profile", {})
    if cons.get("category") is None and profile.get("coldStart"):
        return "clarify"
    return "search"


def _clarify(state: AgentState) -> dict:
    cat_text = "/".join(CATEGORY_LABELS.values())
    return {"clarify_question": f"想吃什么类型？{cat_text}，或者直接描述场景（如'朋友聚餐'）"}


def build_graph():
    """构建并编译推荐图（模块加载时执行一次）"""
    g = StateGraph(AgentState)
    g.add_node("parse_intent", parse_intent)
    g.add_node("load_profile", load_profile)
    g.add_node("clarify", _clarify)
    g.add_node("search", search_shops)
    g.add_node("evidence", load_evidence)
    g.add_node("decide", decide)
    g.add_node("guardrail", guardrail)

    g.add_edge(START, "parse_intent")
    g.add_edge("parse_intent", "load_profile")
    g.add_conditional_edges("load_profile", _after_intent,
                            {"clarify": "clarify", "search": "search"})
    g.add_edge("clarify", END)
    g.add_edge("search", "evidence")
    g.add_edge("evidence", "decide")
    g.add_edge("decide", "guardrail")
    g.add_edge("guardrail", END)
    return g.compile()


# 编译一次，进程内复用
recommend_graph = build_graph()


def run_recommend(user_id: int, message: str, lat: float, lng: float,
                  session_id: str | None) -> dict:
    """入口：跑图并整理输出（对齐统一信封的 data 结构）"""
    init: AgentState = {
        "user_id": user_id, "message": message, "lat": lat, "lng": lng,
        "session_id": session_id or "s-0",
    }
    result = recommend_graph.invoke(init)

    if result.get("error_code"):
        return {
            "code": result["error_code"], "message": result.get("error_message", "护栏拦截"),
            "data": None,
        }
    if result.get("clarify_question"):
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
