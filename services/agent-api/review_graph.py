# review_graph.py —— 评价草稿图 CASDG：模型起草，用户签字。
#
# ============================ 这个文件是干什么的 ============================
# 用户到店核销后要写评价，但「让 AI 直接写」有编造风险（写没吃过的菜、编价格）。
# 所以这里把写评价拆成四步固定流程，每一步都限制模型能碰什么：
#
#   collect  工具：取订单事实（belongsToUser + canReview = 已核销且未评）——这是唯一事实来源
#   align    纯代码：把事实压成「事实清单」（店/套餐/金额/时间）+ 用户笔记 + 用户预设分
#   draft    LLM：选择用户已提供的主观体验 ID 并评分；正文由真实订单与体验闭包组装
#   gate     护栏：整数评分 / 真实事实与体验引用 / 正文不为空且不超 200 字
#   finish   把通过护栏的草稿存进草稿仓（drafts.py），返回 draftId
#
# ============================ 关键设计：Align 这一步为什么要存在 ============================
# 把订单 JSON 压缩成四行「事实清单」，是在【缩小模型的引用空间】——
# 套餐名和金额由程序写入；模型只选择有限体验 ID，不拥有自由添加菜品事实的通道。
# 这是「检索裁剪」思想在评价场景的复用（推荐图里裁剪的是候选店，这里裁剪的是订单字段）。
#
# ============================ 本文件涉及的 Python 语法速览（Java 背景看这里） ============================
#   DIMS = ("taste", "wait", "env")   → 元组（≈ 不可变数组），用来存固定的三个维度名
#   f"...{表达式}"                     → f-string 里可以放表达式，如 {str(x)[:19]} 取前 19 个字符
#   "a" if 条件 else "b"               → 三元表达式（≈ Java 的 条件 ? a : b）
#   x or 默认值                        → 短路取值：x 为假值（None/空串/空列表）时用默认值
#   isinstance(v, (int, float))        → 判断类型是否属于其中一种（≈ v instanceof Number）
#   1 <= v <= 5                        → Python 支持链式比较（Java 要写 v>=1 && v<=5）
#   {k: int(v) for k, v in d.items()}  → 字典推导式（≈ Java stream().collect(toMap)）
#   for k, v in d.items()              → 同时遍历键和值（Java 用 entrySet）
import re
from decimal import Decimal
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import drafts
import tools
from llm import chat_json, llm_available

GUARDRAIL_CODE = 42201   # 护栏拦截（AI 输出不合格）
DOWN_CODE = 50000        # 依赖未连通（诚实降级）
DIMS = ("taste", "wait", "env")   # 三个评分维度：口味 / 等位 / 环境


class DraftState(TypedDict, total=False):
    """评价草稿图的共享状态（节点之间传递的「工件」）。"""
    # 输入
    user_id: int
    order_id: int
    user_note: str | None     # 用户随手写的感受（可为空）
    prefer_scores: dict       # 用户预设的分数，如 {"taste": 5}——用户定的维度模型必须原样保留
    # 中间产物
    facts: dict               # collect 拿到的订单事实原始数据
    fact_list: list           # align 压出来的四行事实清单
    experiences: list         # align 提取的、用户明确提供的主观体验（不含菜品/荣誉断言）
    tool_calls: list          # 工具调用清单（trace 用）
    # 输出
    draft_id: str
    scores: dict
    content: str
    used_facts: list
    experience_ids: list
    error_code: int
    error_message: str


def collect(state: DraftState) -> dict:
    """Collect（第①步）：取订单事实——整个流程唯一的事实来源。归属/状态不满足直接拒。

    三道校验（对应三个错误码）：
      订单不存在      → 40001
      不是你的订单    → 40300
      状态不可评价    → 40903（必须「已核销且未评过」）
    这道关卡在调模型之前——不合格的订单连模型都不会碰，省成本也防越权。
    """
    try:
        facts = tools.get_order_facts(state["order_id"], state["user_id"])
    except Exception as e:
        return {"error_code": DOWN_CODE,
                "error_message": f"主站数据服务未连通（{type(e).__name__}）：取订单事实失败，本次请求已中止。"}
    if not facts.get("exists"):                       # 订单不存在
        return {"error_code": 40001, "error_message": "订单不存在"}
    if not facts.get("belongToUser"):                 # 越权：不是本人的订单
        return {"error_code": 40300, "error_message": "只能评价自己的订单"}
    if not facts.get("canReview"):                    # 状态不对（未核销 / 已评过）
        return {"error_code": 40903,
                "error_message": f"该订单当前不可评价（状态 {facts.get('status')}，需已核销且未评过）"}
    return {
        "facts": facts,
        "tool_calls": [f"GET /internal/orders/{state['order_id']}/facts"],
    }


def align(state: DraftState) -> dict:
    """Align（第②步）：把订单事实压成「事实清单」——LLM 只能引用这里的东西（不可编造区）。

    输出形如：
      ["店铺：川味火锅·西湖11号店", "套餐：四人欢聚套餐", "实付：约135.0元", "下单时间：2026-09-08 18:20:15"]
    注意 [:]19 是「切片」：时间字符串只取前 19 个字符（去掉毫秒和时区后缀，更易读）。
    """
    if state.get("error_code") or "facts" not in state:
        return {}   # 上游（取事实）已报错，短路——不继续往下走
    f = state["facts"]
    fact_list = [
        f"店铺：{f.get('shopName')}",
        f"套餐：{f.get('skuTitle')}",
        f"实付：约{f.get('priceYuan')}元",
        f"下单时间：{str(f.get('orderedAt', ''))[:19]}",
    ]
    return {"fact_list": fact_list, "experiences": extract_experiences(state.get("user_note"))}


# 评价正文允许写用户亲身感受，但用户笔记中的菜品、食材、荣誉和质量断言
# 仍然是未经订单事实证明的内容。把可写体验先收敛成小白名单，再交给模型选择。
UNVERIFIED_TERMS = re.compile(
    r"龙虾|刺身|和牛|牛舌|燕窝|米其林|星级|荣誉|冠军|招牌|菜品|食材|新鲜|滋补|品质|水准|顶级|第一|最好"
)
DIRECTIVE_PREFIX = re.compile(r"^(?:顺便夸夸|顺便写上|必须提一下|记得写上|帮我(?:在评价里)?说|请写上|一定要写|写上)\s*")
EXPERIENCE_RULES = (
    ("taste-negative", r"不(?:太|怎么|算|够)?好吃|(?:算|称|谈)不上好吃|味道(?:很|比较)?差|难吃", "口味不太满意"),
    ("taste-positive", r"(?:很|挺|真)?好吃|(?:味道|口味)(?:很|挺|比较)?不错", "口味不错"),
    ("taste-acceptable", r"(?:味道|口味)(?:还|挺|比较)?可以", "口味还可以"),
    ("aroma-present", r"(?:锅底|汤底)(?:很|挺|比较|非常)?香", "锅底有香气"),
    ("experience-stable", r"稳定发挥", "体验比较稳定"),
    ("taste-salty", r"(?:有点|太|偏|较)咸", "口味有点咸"),
    ("taste-neutral", r"一般般|不功不过", "整体体验一般"),
    ("wait-long", r"等位(?:太|很|有点)?久|排队.{0,8}(?:分钟|小时|久)|等了.{0,8}(?:分钟|小时)", "等位较久"),
    ("wait-smooth", r"(?:上菜|出餐)(?:速度)?(?:还行|快|及时)", "上菜速度还行"),
    ("service-attentive", r"主动加水|服务(?:很|挺|比较|非常)?(?:热情|周到)|态度(?:很|挺|比较|非常)?好", "服务比较主动"),
    ("service-negative", r"(?:服务|态度)(?:不|没|未)(?:太|算|够|很)?(?:热情|周到|好)", "服务态度有待改善"),
    ("service-slow", r"喊了好几次|服务员态度一般|没人理", "服务回应有待改善"),
    ("environment-noisy", r"有点吵|太吵|比较吵", "环境有点吵"),
    ("environment-clean", r"(?:环境|小料台)(?:很|挺|比较|非常)?干净", "现场感觉整洁"),
    ("environment-unclean", r"(?:环境|小料台)(?:不|没|未)(?:太|算|够|很)?干净", "现场整洁度有待改善"),
    ("environment-bright", r"环境明亮", "环境明亮"),
    ("environment-photo", r"适合拍照", "适合拍照"),
    ("portion-sufficient", r"(?:分量|份量)(?:很|比较)?(?:足|够)", "分量比较足"),
    ("value-good", r"性价比(?:很|比较)?(?:高|不错)", "性价比不错"),
    ("return-willing", r"会回购|愿意再来|还会再来", "愿意再来"),
    ("return-unwilling", r"不会回购|不愿再来|不想再来", "不太愿意再来"),
    ("context-family", r"适合带(?:家里人|家人|孩子|娃)", "适合和家人一起体验"),
    ("context-relaxed", r"人不多.{0,5}体验(?:很)?好", "人少时体验比较好"),
    ("context-friends", r"聊得很开心", "和朋友聊得很开心"),
)
NEGATED_PREFIX = re.compile(r"(?:不|没|未|无)(?:太|很|怎么|算|够|是)?$|(?:算|称|谈)不上$")


def extract_experiences(user_note: str | None) -> list[dict]:
    """Extract supported subjective predicates into canonical phrases from the note.

    The returned IDs are deterministic and are the only IDs the model may select.
    Free model prose is never copied into the review body.
    """
    if not user_note:
        return []
    clauses = re.split(r"[，,。；;！？!?\n]+", str(user_note))
    result = []
    seen = set()
    for raw in clauses:
        clause = DIRECTIVE_PREFIX.sub("", raw.strip())
        if not clause or UNVERIFIED_TERMS.search(clause):
            continue
        # Copy only canonical subjective predicates, never the whole clause: an
        # unfamiliar dish name cannot enter the output through a user's note.
        for eid, pattern, text in EXPERIENCE_RULES:
            match = re.search(pattern, clause)
            # Avoid converting a negated user feeling into an affirmative claim.
            negated = match is not None and NEGATED_PREFIX.search(clause[:match.start()])
            if eid not in seen and match and not negated:
                result.append({"id": eid, "text": text})
                seen.add(eid)
    return result


# 系统提示词：四条硬规矩 → 分别对应事实锚定、区分主客观、尊重用户预设分、禁止全是夸
DRAFT_SYSTEM = (
    "你是评价起草助手。基于【订单事实清单】和【已过滤用户体验】生成评价，只输出 json："
    '{"scores": {"taste": 1-5, "wait": 1-5, "env": 1-5}, '
    '"experienceIds": ["从已过滤用户体验中选择的 id"]}'
    "。硬规矩：1.只返回 experienceIds，不要返回 content 或自由发挥的菜品描述；"
    "2.订单事实中的套餐名和实付金额由程序原样写入，禁止缩写、翻译或补充；"
    "3.只能选择用户明确提供且已过滤的体验 id，不能凭空增加口味、菜品、食材、荣誉或质量判断；"
    "4.用户预设分(preferScores)必须原样保留，其余维度按已选体验合理给。"
)


def _assembled_content(state: DraftState, selected: list[dict]) -> str:
    """Build review text solely from order facts and selected user clauses."""
    facts = state["facts"]
    title = str(facts.get("skuTitle") or "该套餐")
    price = format(Decimal(str(facts.get("priceYuan"))).normalize(), "f")
    content = f"已到店体验「{title}」，实付约{price}元。"
    if selected:
        content += "用户体验：" + "；".join(item["text"] for item in selected) + "。"
    else:
        content += "请补充口味、等位或环境体验后再发布。"
    return content


def draft(state: DraftState) -> dict:
    """Score+Draft（第③步）：让 LLM 起草评价。

    两个细节（面试可讲）：
      ① 上游报错时直接 return {} 短路——既防 KeyError（state 里没有 fact_list 会炸），又省一次 LLM 调用
      ② 出模型后【强制覆盖预设分】——用户给的分不许模型改（规则3 的代码级保证，不靠提示词自觉）
    """
    if state.get("error_code"):
        return {}   # 上游（事实校验）已报错，不再起草——防 KeyError 且省一次 LLM 调用
    if not llm_available():
        return {"error_code": DOWN_CODE,
                "error_message": "AI 服务未连通（未配置 API Key）：本次请求已中止生成，未产出草稿。"}
    import json
    prefer = state.get("prefer_scores") or {}
    try:
        out = chat_json(
            DRAFT_SYSTEM,
            # 拼提示词：事实清单（每行加 "- " 变成列表）+ 用户补充 + 用户预设分
            f"订单事实清单：\n" + "\n".join(f"- {x}" for x in state["fact_list"]) +
            f"\n已过滤用户体验（只能从这里选择 id）：{json.dumps(state.get('experiences', []), ensure_ascii=False)}" +
            f"\n用户预设分：{json.dumps(prefer, ensure_ascii=False)}",
            max_tokens=600,
        )
    except Exception as e:
        return {"error_code": DOWN_CODE,
                "error_message": f"AI 服务未连通（调用失败：{type(e).__name__}）：本次请求已中止生成，未产出草稿。"}

    if not isinstance(out, dict) or not isinstance(out.get("scores"), dict):
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：模型评分格式非法"}
    scores = out.get("scores") or {}
    experience_ids = out.get("experienceIds") or []
    if not isinstance(experience_ids, list) or not all(isinstance(x, str) for x in experience_ids):
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：experienceIds 格式非法"}
    # 预设分以用户为准（LLM 只填其他维度）——这是「用户优先」，不是提示词请求，是代码强制
    for k, v in prefer.items():
        if k in DIMS:                 # 只认三个合法维度，防止用户传奇怪的键污染数据
            scores[k] = int(v)
    return {
        "scores": scores,
        "content": _assembled_content(state, [e for e in state.get("experiences", []) if e["id"] in experience_ids]),
        "used_facts": list(state["fact_list"]),
        "experience_ids": experience_ids,
    }


def gate(state: DraftState) -> dict:
    """Gate（第④步）：护栏——纯代码校验，不过就整单拒绝（42201）。

    三查：
      ① 三个维度分都要有，且必须是 1~5 的数字（isinstance 同时挡掉字符串/None）
      ② 正文不能空、不能超 200 字
      ③ usedFacts 不能为空（草稿必须声明它引用了哪些事实——「无引用」本身就是可疑信号）
    """
    if state.get("error_code"):
        return {}
    scores = state.get("scores") or {}
    for d in DIMS:
        v = scores.get(d)
        # 既判类型又判范围：不是数字、或不在 1~5，都拦
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (1 <= v <= 5) or not float(v).is_integer():
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：分数维度 {d} 缺失或越界（1~5）"}
    content = state.get("content") or ""
    if not content.strip() or len(content) > 200:
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：正文为空或超长（≤200字）"}
    # 引用逐项属于真实订单清单，不能仅凭「非空」放行。
    if not state.get("used_facts"):
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：草稿无事实引用（usedFacts 为空）"}
    if any(not isinstance(fact, str) or fact not in state.get("fact_list", []) for fact in state["used_facts"]):
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：事实引用不在真实订单清单中"}
    valid_ids = {e["id"] for e in state.get("experiences", [])}
    if any(eid not in valid_ids for eid in state.get("experience_ids", [])):
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：体验引用不在用户事实中"}
    return {}


def _finish(state: DraftState) -> dict:
    """收尾：护栏全过 → 把草稿存进草稿仓（drafts.py），拿到 draftId。

    注意：这里【不写数据库】——只是暂存。真正写库要等用户点「确认发布」，
         由 Java 门面取走草稿后走 ReviewService 二次校验再写（签字权在用户）。
    """
    if state.get("error_code"):
        return {}
    draft_id = drafts.create(
        state["user_id"], state["order_id"],
        # 前面已验证为整数；这里统一 JSON 数值格式。
        {k: int(v) for k, v in state["scores"].items()},
        state["content"], state["used_facts"],
    )
    return {"draft_id": draft_id}


def build_graph():
    """组图：五个节点一条直线（Collect → Align → Draft → Gate → Finish）。"""
    g = StateGraph(DraftState)
    g.add_node("collect", collect)
    g.add_node("align", align)
    g.add_node("draft", draft)
    g.add_node("gate", gate)
    g.add_node("finish", _finish)
    g.add_edge(START, "collect")
    g.add_edge("collect", "align")
    g.add_edge("align", "draft")
    g.add_edge("draft", "gate")
    g.add_edge("gate", "finish")
    g.add_edge("finish", END)
    return g.compile()


review_graph = build_graph()   # 编译一次，进程内复用


def run_review_draft(user_id: int, order_id: int, user_note: str | None,
                     prefer_scores: dict) -> dict:
    """入口函数：被 main.py 的 /agent/review-draft 端点调用。

    参数：用户 ID、订单 ID、用户笔记（可空）、预设分（可空）
    返回：统一信封；成功时 data = {draftId, scores, content, usedFacts, toolCalls}
    """
    if not isinstance(prefer_scores, dict) or any(
            key not in DIMS or isinstance(value, bool) or not isinstance(value, (int, float))
            or not (1 <= value <= 5) or not float(value).is_integer()
            for key, value in prefer_scores.items()):
        return {"code": 40001, "message": "预设评分须为 taste/wait/env 的 1~5 整数", "data": None}
    result = review_graph.invoke({
        "user_id": user_id, "order_id": order_id,
        "user_note": user_note, "prefer_scores": prefer_scores or {},
    })
    if result.get("error_code"):
        return {"code": result["error_code"], "message": result.get("error_message", "失败"), "data": None}
    return {
        "code": 0, "message": "ok",
        "data": {
            "draftId": result["draft_id"],
            "scores": result["scores"],
            "content": result["content"],
            "usedFacts": result["used_facts"],
            "toolCalls": result.get("tool_calls", []),
        },
    }
