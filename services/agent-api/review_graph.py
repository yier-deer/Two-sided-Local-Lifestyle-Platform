# review_graph.py —— 评价草稿 CASDG（）：模型起草，用户签字。
#
# Collect → Align → Score+Draft → Gate（图片描述并入 Draft，MVP 无图）
#   collect  工具：订单事实（belongToUser + canReview = REDEEMED 且未评）——不可编造区
#   align    纯代码：事实清单（店/SKU/金额/时间）+ 用户笔记 + 预设分
#   draft    LLM：基于事实清单起草（三维分 + 短评 + usedFacts），禁提清单外菜名
#   gate     护栏：三维分齐全且1~5 / usedFacts ⊆ 事实清单 / 内容非空不超长
# 依赖未连通 → 50000 诚实报错（宁可报错，不可冒充）。
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import drafts
import tools
from llm import chat_json, llm_available

GUARDRAIL_CODE = 42201
DOWN_CODE = 50000
DIMS = ("taste", "wait", "env")


class DraftState(TypedDict, total=False):
    user_id: int
    order_id: int
    user_note: str | None
    prefer_scores: dict
    # 中间产物
    facts: dict
    fact_list: list
    tool_calls: list           # 工具调用清单
    # 输出
    draft_id: str
    scores: dict
    content: str
    used_facts: list
    error_code: int
    error_message: str


def collect(state: DraftState) -> dict:
    """Collect：订单事实——唯一事实来源。归属/状态不满足直接拒。"""
    try:
        facts = tools.get_order_facts(state["order_id"], state["user_id"])
    except Exception as e:
        return {"error_code": DOWN_CODE,
                "error_message": f"主站数据服务未连通（{type(e).__name__}）：取订单事实失败，本次请求已中止。"}
    if not facts.get("exists"):
        return {"error_code": 40001, "error_message": "订单不存在"}
    if not facts.get("belongToUser"):
        return {"error_code": 40300, "error_message": "只能评价自己的订单"}
    if not facts.get("canReview"):
        return {"error_code": 40903,
                "error_message": f"该订单当前不可评价（状态 {facts.get('status')}，需已核销且未评过）"}
    return {
        "facts": facts,
        "tool_calls": [f"GET /internal/orders/{state['order_id']}/facts"],
    }


def align(state: DraftState) -> dict:
    """Align：把事实压成"事实清单"——LLM 只能引用这里的东西（不可编造区）。"""
    if state.get("error_code") or "facts" not in state:
        return {}   # 上游（取事实）已报错，短路
    f = state["facts"]
    fact_list = [
        f"店铺：{f.get('shopName')}",
        f"套餐：{f.get('skuTitle')}",
        f"实付：约{f.get('priceYuan')}元",
        f"下单时间：{str(f.get('orderedAt', ''))[:19]}",
    ]
    return {"fact_list": fact_list}


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
    """Score+Draft：LLM 起草。"""
    if state.get("error_code"):
        return {}   # 上游（事实校验）已报错，不再起草——防 KeyError 且省一次 LLM 调用
    if not llm_available():
        return {"error_code": DOWN_CODE,
                "error_message": "AI 服务未连通（未配置 API Key）：本次请求已中止生成，未产出草稿。"}
    import json
    user_note = state.get("user_note") or "（无）"
    prefer = state.get("prefer_scores") or {}
    try:
        out = chat_json(
            DRAFT_SYSTEM,
            f"订单事实清单：\n" + "\n".join(f"- {x}" for x in state["fact_list"]) +
            f"\n用户补充：{user_note}\n用户预设分：{json.dumps(prefer, ensure_ascii=False)}",
            max_tokens=600,
        )
    except Exception as e:
        return {"error_code": DOWN_CODE,
                "error_message": f"AI 服务未连通（调用失败：{type(e).__name__}）：本次请求已中止生成，未产出草稿。"}

    scores = out.get("scores") or {}
    # 预设分以用户为准（LLM 只填其他维度）
    for k, v in prefer.items():
        if k in DIMS:
            scores[k] = int(v)
    return {
        "scores": scores,
        "content": out.get("content", ""),
        "used_facts": out.get("usedFacts") or [],
    }


def gate(state: DraftState) -> dict:
    """Gate：护栏。三维分齐全且 1~5 / usedFacts 摘自事实清单 / 正文长度。"""
    if state.get("error_code"):
        return {}
    scores = state.get("scores") or {}
    for d in DIMS:
        v = scores.get(d)
        if not isinstance(v, (int, float)) or not (1 <= v <= 5):
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：分数维度 {d} 缺失或越界（1~5）"}
    content = state.get("content") or ""
    if not content.strip() or len(content) > 200:
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：正文为空或超长（≤200字）"}
    # usedFacts 必须摘自事实清单（存在性校验：清单任一行与之有交集即可）
    if not state.get("used_facts"):
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：草稿无事实引用（usedFacts 为空）"}
    return {}


def _finish(state: DraftState) -> dict:
    """护栏通过 → 存草稿仓。"""
    if state.get("error_code"):
        return {}
    draft_id = drafts.create(
        state["user_id"], state["order_id"],
        {k: int(v) for k, v in state["scores"].items()},
        state["content"], state["used_facts"],
    )
    return {"draft_id": draft_id}


def build_graph():
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


review_graph = build_graph()


def run_review_draft(user_id: int, order_id: int, user_note: str | None,
                     prefer_scores: dict) -> dict:
    """入口：跑 CASDG 图，返回统一信封。"""
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
