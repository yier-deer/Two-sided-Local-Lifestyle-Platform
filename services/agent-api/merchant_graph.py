# merchant_graph.py —— 商家分析 Agent（）：观察 / 假设 / 建议三层。
#
# 三个工具不是一个神提示词（行程原话）：ops→metrics / reviews→clusters / competitors→竞品。
#   collect   工具：按 skill 拉对应数据（归属校验已在 Java 门面做过）
#   analyze   LLM：{"observations":[含数字句], "hypotheses":[≥1个"可能"], "suggestions":[1~2条]}
#   gate      护栏：观察句数字必须存在于工具结果 / 假设禁因果断言词 / 建议≤2
# 相关≠因果：把"券和新客同时上升"说成"因为券"是 AI 商业分析死罪——护栏连措辞都管。
import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import tools
from llm import chat_json, llm_available

GUARDRAIL_CODE = 42201
DOWN_CODE = 50000

# 假设层的措辞规则（对齐行程原话「只能说可能相关」）：
#   必须含限定词（可能/或许/大概…）——带限定的因果连接词（因为/导致）可接受，因为整句已标明是推测
#   拦截的是【未限定的确定性断言】：证明了/肯定是/就是由于/百分百
HEDGE_WORDS = re.compile(r"可能|或许|大概|猜测|大概率|一种可能")
CERTAIN_ASSERTIONS = re.compile(r"证明了?|肯定是|就是由于|百分百|无疑")


class MState(TypedDict, total=False):
    user_id: int
    shop_id: int
    skill: str
    # 中间产物
    data: dict
    data_text: str
    tool_calls: list           # 工具调用清单
    # 输出
    observations: list
    hypotheses: list
    suggestions: list
    error_code: int
    error_message: str


SKILL_LABEL = {
    "ops": "经营归因（新客/复购/券/曝光）",
    "reviews": "评论诊断（正负观点聚类）",
    "competitors": "竞品快照（同品类同半径公开信息）",
}


def collect(state: MState) -> dict:
    """按 skill 拉数据——数据形状不同，所以是三个工具不是一个提示词。"""
    skill, shop_id = state["skill"], state["shop_id"]
    try:
        if skill == "ops":
            data = tools.get_metrics(shop_id)
        elif skill == "reviews":
            data = tools.get_review_clusters(shop_id)
        elif skill == "competitors":
            data = tools.get_competitors(shop_id)
        else:
            return {"error_code": 40001, "error_message": "skill 只能是 ops/reviews/competitors"}
    except Exception as e:
        return {"error_code": DOWN_CODE,
                "error_message": f"主站数据服务未连通（{type(e).__name__}）：取数失败，本次请求已中止。"}
    if not data:
        return {"error_code": 40001, "error_message": "该店铺暂无可分析的数据"}
    tool = {"ops": "metrics", "reviews": "review-clusters", "competitors": "competitors"}[skill]
    return {"data": data, "data_text": json.dumps(data, ensure_ascii=False),
            "tool_calls": [f"GET /internal/merchant/{shop_id}/{tool}"]}


ANALYZE_SYSTEM = (
    "你是本地生活商家经营分析助手。基于【工具数据】做三层分析，只输出 json："
    '{"observations": ["只陈述数据里有的数字，如：近7日新客2人，此前为0", ...]（2~4条，每条必须含数字）, '
    '"hypotheses": ["可能原因1（明确写\'可能\'，并列2个避免单因果）", ...]（1~2条）, '
    '"suggestions": ["可执行建议（必须能追溯到某条观察）", ...]（1~2条）}'
    "。硬规矩：1.观察句的每个数字必须来自工具数据，禁止编造或自行换算"
    "（聚合数字如均分/占比，直接引用数据里现成的字段值，不要自己计算）；"
    "2.每条假设必须含『可能/或许』类限定词（可以说『可能因为券活动导致新客上升』，"
    "但禁止『证明了/肯定是』式确定性断言）；"
    "3.建议最多2条且要具体可执行；4.评论诊断要引用原评内容；竞品只用公开信息；"
    "5.任何技能（包括竞品快照）都必须输出假设层——对观察到的差异给出2个可能的解读，"
    "假设层不允许为空。"
)


def analyze(state: MState) -> dict:
    if state.get("error_code"):
        return {}
    if not llm_available():
        return {"error_code": DOWN_CODE,
                "error_message": "AI 服务未连通（未配置 API Key）：本次请求已中止生成，未产出分析。"}
    try:
        out = chat_json(
            ANALYZE_SYSTEM,
            f"分析技能：{SKILL_LABEL.get(state['skill'], state['skill'])}\n"
            f"工具数据（json）：\n{state['data_text']}",
            max_tokens=1000,
        )
    except Exception as e:
        return {"error_code": DOWN_CODE,
                "error_message": f"AI 服务未连通（调用失败：{type(e).__name__}）：本次请求已中止生成，未产出分析。"}
    return {
        "observations": out.get("observations") or [],
        "hypotheses": out.get("hypotheses") or [],
        "suggestions": out.get("suggestions") or [],
    }


def gate(state: MState) -> dict:
    """护栏：数字可验 / 措辞管因果 / 建议限量。"""
    if state.get("error_code"):
        return {}
    obs, hyp, sug = state.get("observations", []), state.get("hypotheses", []), state.get("suggestions", [])
    data_text = state.get("data_text", "")

    # ① 观察句的数字必须存在于工具结果（粗存在性校验：去 % 后在 data_text 里找）
    for sentence in obs:
        for num in re.findall(r"\d+(?:\.\d+)?", str(sentence)):
            if num not in data_text:
                return {"error_code": GUARDRAIL_CODE,
                        "error_message": f"护栏拦截：观察句中的数字 {num} 不在工具数据中（疑似编造）"}
    # ② 假设层：必须含限定词；未限定的确定性断言才拦截（带"可能"的因果表述是合规推测）
    if not hyp:
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：缺少假设层（必须区分观察与推测）"}
    for h in hyp:
        s = str(h)
        if CERTAIN_ASSERTIONS.search(s):
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：假设含确定性断言（『{s}』）——相关不等于因果，禁止『证明/肯定』式表述"}
        if not HEDGE_WORDS.search(s):
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：假设缺少『可能』类限定（『{s}』）——推测必须明确标注为推测"}
    # ③ 建议 1~2 条
    if not sug or len(sug) > 2:
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：建议应为 1~2 条可执行动作"}
    return {}


def build_graph():
    g = StateGraph(MState)
    g.add_node("collect", collect)
    g.add_node("analyze", analyze)
    g.add_node("gate", gate)
    g.add_edge(START, "collect")
    g.add_edge("collect", "analyze")
    g.add_edge("analyze", "gate")
    g.add_edge("gate", END)
    return g.compile()


merchant_graph = build_graph()


def run_merchant_analyze(user_id: int, shop_id: int, skill: str) -> dict:
    result = merchant_graph.invoke({"user_id": user_id, "shop_id": shop_id, "skill": skill})
    if result.get("error_code"):
        return {"code": result["error_code"], "message": result.get("error_message", "失败"), "data": None}
    return {
        "code": 0, "message": "ok",
        "data": {
            "skill": skill,
            "observations": result.get("observations", []),
            "hypotheses": result.get("hypotheses", []),
            "suggestions": result.get("suggestions", []),
            "toolCalls": result.get("tool_calls", []),
        },
    }
