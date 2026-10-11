# merchant_graph.py —— 商家分析图：观察 / 假设 / 建议 三层输出。
#
# ============================ 这个文件是干什么的 ============================
# 商家问「为什么这周新客涨了」，AI 不能张口就来一句「因为你们发了券」——
# 数据和结论之间只有【相关】，没有【因果】证明。把相关说成因果，是 AI 商业分析的死罪
# （会误导商家砸钱在错误的地方）。
# 所以这里强制三层结构：
#   观察（Observations）——只陈述数据里有的数字，一个都不许编
#   假设（Hypotheses）  ——推测，必须带「可能/或许」限定词，并给 2 个并列可能（防单因果叙事）
#   建议（Suggestions） ——1~2 条可执行动作，且能追溯到某条观察
#
# ============================ 三个技能，三套数据，一个提示词 ============================
# 为什么是三个工具而不是一个「万能提示词」：
#   ops         → 经营指标（新客/复购/券占比/曝光）—— 数字表格
#   reviews     → 评论聚类（关键词分桶，每桶带原评）—— 文本列表
#   competitors → 竞品快照（同品类 3km 公开信息）—— 对比数据
# 三种数据形状完全不同，硬塞进一个提示词只会让模型更难用对。分开拉、分开喂。
#
# ============================ 本文件涉及的 Python 语法速览（Java 背景看这里） ============================
#   import re                          → 正则表达式库
#   re.compile(r"可能|或许")            → 预编译正则（r"..." 表示原始字符串，反斜杠不转义）
#   HEDGE_WORDS.search(文本)           → 在文本里搜有没有匹配（有则返回匹配对象，无则 None）
#   字典字面量 {..} / 下标取值 [key]    → ≈ Java Map
#   for skill in ("ops", "reviews")    → 遍历元组
#   state["skill"]                     → 取字典值（键不存在会报错）
#   json.dumps(x, ensure_ascii=False)  → 对象转 JSON 字符串（False = 保留中文不转 \uXXXX）
import json
import re
from decimal import Decimal
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import tools
from llm import chat_json, llm_available

GUARDRAIL_CODE = 42201   # 护栏拦截
DOWN_CODE = 50000        # 依赖未连通

# ============================ 假设层的措辞规则（踩坑后修正的版本） ============================
# 必须含限定词（可能/或许/大概…）——带限定的因果连接词（因为/导致）是可接受的，
# 因为整句已经标明这是推测（例：「可能因为券活动导致新客上升」= 合规推测）。
# 拦截的是【未限定的确定性断言】：证明了 / 肯定是 / 就是由于 / 百分百。
#
# 【踩过的坑】初版把「导致」一刀切进黑名单，结果把 LLM 合规的带限定假设也拦了（失败率 2/3）。
# 教训：护栏管的是「断言语气」（确定 vs 推测），不是连接词本身——过严的护栏和没有护栏一样伤产品。
HEDGE_WORDS = re.compile(r"可能|或许|大概|猜测|大概率|一种可能")           # 合规限定词
CERTAIN_ASSERTIONS = re.compile(r"证明了?|肯定是|就是由于|百分百|无疑")   # 违规确定性断言


class MState(TypedDict, total=False):
    """商家分析图的共享状态。"""
    user_id: int
    shop_id: int
    skill: str                 # ops / reviews / competitors
    # 中间产物
    data: dict                 # 工具拉到的原始数据
    data_text: str             # 上面的 JSON 文本（喂给模型 & 护栏比对用）
    tool_calls: list           # 工具调用清单
    observation_facts: dict    # 各技能原始字段对应的合法观察句，模型只能按 ID 选择
    # 输出
    observations: list
    hypotheses: list
    suggestions: list
    error_code: int
    error_message: str


# skill 值 → 中文标签（喂给模型时用，让它知道自己在做哪类分析）
SKILL_LABEL = {
    "ops": "经营归因（新客/复购/券/曝光）",
    "reviews": "评论诊断（正负观点聚类）",
    "competitors": "竞品快照（同品类同半径公开信息）",
}


def _format_number(value) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def metric_observations(data: dict) -> dict:
    """Bind each ops observation to one real source field; never derive ratios."""
    templates = {
        "totalValidOrders": "累计有效订单{value}笔",
        "totalCustomers": "累计消费用户{value}人",
        "newCustomers7d": "近{window}日新客{value}人",
        "repeatBuyers": "复购用户{value}人",
        "couponOrderShare": "用券订单占比{value}%",
        "impressions7d": "近{window}日曝光{value}次",
        "reviewCount": "累计评价{value}条",
        "avgRating": "平均评分{value}分",
    }
    result = {}
    for key, template in templates.items():
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if "{window}" in template and not isinstance(data.get("windowDays"), (int, float)):
            continue
        result[key] = template.format(value=_format_number(value), window=_format_number(data.get("windowDays", 0)))
    return result


def review_observations(data: list) -> dict:
    """Bind each review bucket to its count, score and quoted source reviews."""
    facts = {}
    for index, bucket in enumerate(data):
        if not isinstance(bucket, dict) or not bucket.get("topic") or bucket.get("count") is None:
            continue
        samples = []
        for sample in bucket.get("samples") or []:
            if not isinstance(sample, dict) or not sample.get("text"):
                continue
            quote = f"评价#{sample.get('reviewId')}：{sample['text']}"
            if sample.get("score") is not None:
                quote += f"（单条评分{_format_number(sample['score'])}分）"
            samples.append(quote)
        if not samples:
            continue
        score = bucket.get("avgScore")
        score_part = f"，桶内均分{_format_number(score)}分" if score is not None else ""
        facts[f"topic-{index}"] = (
            f"观点‘{bucket['topic']}’共{_format_number(bucket['count'])}条{score_part}；"
            + "；".join(samples)
        )
    return facts


def competitor_observations(data: list) -> dict:
    """Bind each competitor card to only fields returned by the public snapshot."""
    facts = {}
    for index, card in enumerate(data):
        if not isinstance(card, dict) or not card.get("name"):
            continue
        parts = [f"竞品‘{card['name']}’"]
        if card.get("distanceMeters") is not None:
            parts.append(f"距离{_format_number(card['distanceMeters'])}米")
        if card.get("rating") is not None:
            parts.append(f"评分{_format_number(card['rating'])}")
        if card.get("sales") is not None:
            parts.append(f"销量{_format_number(card['sales'])}")
        if card.get("reviewCount") is not None:
            parts.append(f"评价{_format_number(card['reviewCount'])}条")
        if card.get("minSkuPrice") is not None:
            parts.append(f"最低套餐价{_format_number(card['minSkuPrice'])}分")
        if card.get("hasCoupon") is not None:
            parts.append("有在售券" if card["hasCoupon"] else "无在售券")
        if card.get("topNegativeTopic"):
            parts.append(f"高频差评主题{card['topNegativeTopic']}")
        facts[f"competitor-{index}"] = "；".join(parts)
    return facts


def _source_numbers(value) -> set[Decimal]:
    """Exact numeric tokens, so 40.0 == 40.00 but 10 is not part of 100."""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float, Decimal)):
        return {Decimal(str(value))}
    if isinstance(value, dict):
        return set().union(*(_source_numbers(item) for item in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(_source_numbers(item) for item in value))
    if isinstance(value, str):
        return {Decimal(match) for match in re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])", value)}
    return set()


def collect(state: MState) -> dict:
    """第①步：按 skill 拉对应数据（三种技能走三个不同的接口）。

    归属校验（这家店是不是你的）已经在 Java 门面做过——Python 侧不再重复判权，
    这是「门面做安全、Python 做智能」的分工。

    错误处理：
      skill 非法      → 40001
      主站连不上      → 50000
      数据为空        → 40001（没数据没法分析）
    """
    skill, shop_id = state["skill"], state["shop_id"]
    try:
        if skill == "ops":
            data = tools.get_metrics(shop_id)              # 经营指标
        elif skill == "reviews":
            data = tools.get_review_clusters(shop_id)      # 评论聚类
        elif skill == "competitors":
            data = tools.get_competitors(shop_id)          # 竞品快照
        else:
            return {"error_code": 40001, "error_message": "skill 只能是 ops/reviews/competitors"}
    except Exception as e:
        return {"error_code": DOWN_CODE,
                "error_message": f"主站数据服务未连通（{type(e).__name__}）：取数失败，本次请求已中止。"}
    if not data:   # 空数据（空列表/空字典）→ 没东西可分析
        return {"error_code": 40001, "error_message": "该店铺暂无可分析的数据"}
    # 把 skill 映射成接口路径片段，用于生成工具调用记录（trace 展示用）
    tool = {"ops": "metrics", "reviews": "review-clusters", "competitors": "competitors"}[skill]
    facts = metric_observations(data) if skill == "ops" else (
        review_observations(data) if skill == "reviews" else competitor_observations(data))
    if not facts:
        return {"error_code": 40001, "error_message": "该店铺暂无可分析的可引用事实"}
    return {"data": data, "data_text": json.dumps(data, ensure_ascii=False),
            "observation_facts": facts,
            "tool_calls": [f"GET /internal/merchant/{shop_id}/{tool}"]}


# 系统提示词：五条硬规矩，其中 1/2/3 分别对应护栏的三项检查
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
OPS_SYSTEM = (
    "你是商家经营分析助手。只输出 json："
    '{"observationIds": ["合法观察字典中选取的字段ID，选2~4个"], '
    '"hypotheses": ["包含可能/或许限定词的推测，给两个可能解读"], '
    '"suggestions": ["从所选观察出发的1~2条可执行建议"]}。'
    "观察正文由程序按照原指标字段生成，不返回 observations，不自行计算占比或增长率。"
    "假设是推测，不得使用证明了/肯定是/百分百等确定性因果断言。"
    "选择数据中现成的字段；缺失指标不能猜。"
)
FACT_OBSERVATION_SYSTEM = (
    "你是商家分析助手。只输出 json："
    '{"observationIds": ["从合法观察事实字典中选择1~4个字段ID"], '
    '"hypotheses": ["包含可能/或许限定词的推测"], '
    '"suggestions": ["从所选观察出发的1~2条可执行建议"]}。'
    "观察正文由程序按原始评论桶或竞品卡片原样生成，禁止返回 observations，"
    "禁止补充5分制、满分、百分比、总数或缺失评分等数据。"
    "选择数据中现成的字段；缺失指标不能猜。"
)


def analyze(state: MState) -> dict:
    """第②步：LLM 生成三层分析。

    注意第 5 条硬规矩的由来（真实迭代）：竞品快照最初不输出假设层，
    但「只给观察不给解读」对商家没用——所以补上「假设层不允许为空」。
    """
    if state.get("error_code"):
        return {}   # 上游取数已失败，不再分析（省一次 LLM 调用）
    if not llm_available():
        return {"error_code": DOWN_CODE,
                "error_message": "AI 服务未连通（未配置 API Key）：本次请求已中止生成，未产出分析。"}
    try:
        out = chat_json(
            OPS_SYSTEM if state["skill"] == "ops" else FACT_OBSERVATION_SYSTEM,
            f"分析技能：{SKILL_LABEL.get(state['skill'], state['skill'])}\n"
            f"工具数据（json）：\n{state['data_text']}\n"
            f"合法观察字典（只按ID选择）：{json.dumps(state.get('observation_facts', {}), ensure_ascii=False)}",
            max_tokens=1000,
        )
    except Exception as e:
        return {"error_code": DOWN_CODE,
                "error_message": f"AI 服务未连通（调用失败：{type(e).__name__}）：本次请求已中止生成，未产出分析。"}
    if state["skill"] in ("ops", "reviews", "competitors"):
        ids = out.get("observationIds")
        facts = state.get("observation_facts", {})
        if not isinstance(ids, list) or not (1 <= len(ids) <= 4) or any(
                not isinstance(key, str) or key not in facts for key in ids):
            return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：观察必须引用原始事实字段"}
        observations = [facts[key] for key in dict.fromkeys(ids)]
    else:
        observations = out.get("observations") or []
    return {
        # or [] 兜底：模型可能没给某个字段，用空列表避免下游崩
        "observations": observations,
        "hypotheses": out.get("hypotheses") or [],
        "suggestions": out.get("suggestions") or [],
    }


def gate(state: MState) -> dict:
    """第③步：护栏——数字可验 / 措辞管因果 / 建议限量。三项检查："""
    if state.get("error_code"):
        return {}
    obs, hyp, sug = state.get("observations", []), state.get("hypotheses", []), state.get("suggestions", [])
    if not isinstance(obs, list) or not obs or not all(isinstance(sentence, str) and sentence.strip() for sentence in obs):
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：缺少有效观察层"}
    if state.get("skill") in SKILL_LABEL and any(sentence not in state.get("observation_facts", {}).values() for sentence in obs):
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：观察与原始事实字段不匹配"}
    source = state.get("data")
    if source is None:
        try:
            source = json.loads(state.get("data_text", "{}"), parse_float=Decimal)
        except (ValueError, TypeError):
            source = {}
    source_numbers = _source_numbers(source)

    # ① 数值精确等价，不以字符串子串作为证据；禁止未提供的自行换算。
    for sentence in obs:
        # re.findall 抽出所有数字（支持小数）：\d+ 整数部分，(?:\.\d+)? 可选的小数部分
        for num in re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])", str(sentence)):
            if Decimal(num) not in source_numbers:
                return {"error_code": GUARDRAIL_CODE,
                        "error_message": f"护栏拦截：观察句中的数字 {num} 不在工具数据中（疑似编造）"}
    # ② 假设层：必须存在、必须含限定词；未限定的确定性断言才拦截
    if not hyp:
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：缺少假设层（必须区分观察与推测）"}
    for h in hyp:
        s = str(h)
        # 先查「违规词」：出现「证明了/肯定是」直接拦
        if CERTAIN_ASSERTIONS.search(s):
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：假设含确定性断言（『{s}』）——相关不等于因果，禁止『证明/肯定』式表述"}
        # 再查「限定词」：没有「可能/或许」也拦（推测必须标明是推测）
        if not HEDGE_WORDS.search(s):
            return {"error_code": GUARDRAIL_CODE,
                    "error_message": f"护栏拦截：假设缺少『可能』类限定（『{s}』）——推测必须明确标注为推测"}
    # ③ 建议 1~2 条
    if not sug or len(sug) > 2:
        return {"error_code": GUARDRAIL_CODE, "error_message": "护栏拦截：建议应为 1~2 条可执行动作"}
    return {}   # 全过


def build_graph():
    """组图：三个节点一条直线（collect → analyze → gate）。"""
    g = StateGraph(MState)
    g.add_node("collect", collect)
    g.add_node("analyze", analyze)
    g.add_node("gate", gate)
    g.add_edge(START, "collect")
    g.add_edge("collect", "analyze")
    g.add_edge("analyze", "gate")
    g.add_edge("gate", END)
    return g.compile()


merchant_graph = build_graph()   # 编译一次，进程内复用


def run_merchant_analyze(user_id: int, shop_id: int, skill: str) -> dict:
    """入口函数：被 main.py 的 /agent/merchant/analyze 端点调用。

    参数：用户 ID、店铺 ID、技能名（ops/reviews/competitors）
    返回：统一信封；成功时 data 是严格的三层结构（observations/hypotheses/suggestions）
    """
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
