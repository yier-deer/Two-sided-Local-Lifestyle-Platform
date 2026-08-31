# review_graph.py —— 评价草稿图 CASDG：模型起草，用户签字。
#
# ============================ 这个文件是干什么的 ============================
# 用户到店核销后要写评价，但「让 AI 直接写」有编造风险（写没吃过的菜、编价格）。
# 所以这里把写评价拆成四步固定流程，每一步都限制模型能碰什么：
#
#   collect  工具：取订单事实（belongsToUser + canReview = 已核销且未评）——这是唯一事实来源
#   align    纯代码：把事实压成「事实清单」（店/套餐/金额/时间）+ 用户笔记 + 用户预设分
#   draft    LLM：基于事实清单起草（三维分 + 短评 + usedFacts），禁止提清单外的菜名
#   gate     护栏：三维分齐全且1~5 / usedFacts 非空 / 正文不为空且不超 200 字
#   finish   把通过护栏的草稿存进草稿仓（drafts.py），返回 draftId
#
# ============================ 关键设计：Align 这一步为什么要存在 ============================
# 把订单 JSON 压缩成四行「事实清单」，是在【缩小模型的引用空间】——
# 提示词里写死「正文中的菜名/价格只能来自清单」，模型面对的原料越少，编造空间越小。
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
    tool_calls: list          # 工具调用清单（trace 用）
    # 输出
    draft_id: str
    scores: dict
    content: str
    used_facts: list
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
    return {"fact_list": fact_list}


# 系统提示词：四条硬规矩 → 分别对应事实锚定、区分主客观、尊重用户预设分、禁止全是夸
DRAFT_SYSTEM = (
    "你是评价起草助手。基于【订单事实清单】和【用户补充】写评价草稿，只输出 json："
    '{"scores": {"taste": 1-5, "wait": 1-5, "env": 1-5}, '
    '"content": "120字以内的评价正文", "usedFacts": ["你引用的事实（从清单原样摘录）"]}'
    "。硬规矩：1.正文中的菜名/套餐/价格/优惠只能来自事实清单，"
    "用户补充里提到的不在清单中的具体菜名、食材、荣誉（如清单外的菜品或评级）"
    "一律视为未经证实，禁止写入正文；"
    "2.用户补充的主观感受（好吃/等位久/吵）可以写；"
    "3.用户预设分(preferScores)必须原样保留，其余维度按正文合理给；"
    "4.有保留意见就写出来（具体、可验证、对其他用户有用），不要全是夸。"
)


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
    user_note = state.get("user_note") or "（无）"      # 用户没写笔记就给「（无）」，避免 None 拼进提示词
    prefer = state.get("prefer_scores") or {}
    try:
        out = chat_json(
            DRAFT_SYSTEM,
            # 拼提示词：事实清单（每行加 "- " 变成列表）+ 用户补充 + 用户预设分
            f"订单事实清单：\n" + "\n".join(f"- {x}" for x in state["fact_list"]) +
            f"\n用户补充：{user_note}\n用户预设分：{json.dumps(prefer, ensure_ascii=False)}",
            max_tokens=600,
        )
    except Exception as e:
        return {"error_code": DOWN_CODE,
                "error_message": f"AI 服务未连通（调用失败：{type(e).__name__}）：本次请求已中止生成，未产出草稿。"}

    scores = out.get("scores") or {}
    # 预设分以用户为准（LLM 只填其他维度）——这是「用户优先」，不是提示词请求，是代码强制
    for k, v in prefer.items():
        if k in DIMS:                 # 只认三个合法维度，防止用户传奇怪的键污染数据
            scores[k] = int(v)
    return {
        "scores": scores,
        "content": out.get("content", ""),
        "used_facts": out.get("usedFacts") or [],
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
        if not isinstance(v, (int, float)) or not (1 <= v <= 5):
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：分数维度 {d} 缺失或越界（1~5）"}
    content = state.get("content") or ""
    if not content.strip() or len(content) > 200:
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：正文为空或超长（≤200字）"}
    # usedFacts 必须非空（存在性校验：草稿得说清它引用了哪些事实）
    if not state.get("used_facts"):
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：草稿无事实引用（usedFacts 为空）"}
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
        # 字典推导式：把 scores 的值统一转成 int（模型可能给 "5" 这种字符串）
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
