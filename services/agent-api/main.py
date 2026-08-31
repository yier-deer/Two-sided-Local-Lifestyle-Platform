# main.py —— agent-api 的入口文件（Python 服务从这里启动）
#
# 【这个文件是什么】
#   整个 Python Agent 服务的「大门」。它定义 4 个 HTTP 接口（端点），
#   每个端点收到请求后，转交给对应的「图」（graph）去跑，再把结果包成统一信封返回。
#   类比 Java：它就是 @RestController 那一层（Controller），不放业务逻辑。
#
# 【在架构中的位置】
#   浏览器 → shop-api(Java:8081) 的 /api/agent/** 门面 → 【本文件】→ graph/review_graph/merchant_graph
#   注意：本服务不直接暴露给公网，只接收 Java 门面转发过来的请求（身份靠 X-User-Id 头）。
#
# 【四条边界铁律（面试必答，也是这个项目的核心设计）】
#   1. 不直连前端——统一由 shop-api 门面转发（身份走 X-User-Id 头）
#   2. 不直连数据库——数据回头调 shop-api 的 /internal 只读接口（带 X-Internal-Token 密钥）
#   3. 签字权在用户——本服务只能「起草」草稿，真正写库在 Java 门面（本服务没有写库通道）
#   4. 诚实降级——LLM/主站未连通一律返回 50000 明说，绝不生成假内容冒充
#
# 【本文件涉及的 Python 语法速览（Java 背景看这里）】
#   from fastapi import FastAPI   → 类似 Java 的 import，从包里引入类
#   @app.post("/path")            → 装饰器，类似 Java 的 @PostMapping 注解
#   def f(a: int, b: str) -> dict → 定义函数；: int 是参数类型注解，-> dict 是返回值类型注解
#   f"...{变量}..."               → f-string，字符串插值，类似 Java 的 String.format
#   dict / list                   → Python 字典(≈Map) / 列表(≈List)
#   None                          → 类似 Java 的 null
#   Header(alias="X-User-Id")     → 让 FastAPI 从请求头取值并注入到参数，类似 @RequestHeader
from fastapi import FastAPI, Header

import drafts  # 本目录下的 drafts.py（草稿仓）：用 import 模块名即可访问里面的函数
from graph import run_recommend  # 推荐图入口函数
from merchant_graph import run_merchant_analyze  # 商家分析图入口函数
from models import AnalyzeRequest, RecommendRequest, ReviewDraftRequest  # 请求体的类型定义
from review_graph import run_review_draft  # 评价草稿图入口函数

# 创建 FastAPI 应用实例。title/description 会自动渲染到 /docs 文档站上。
app = FastAPI(
    title="ScoutBite Agent API",
    description=(
        "Agent 大脑：LangGraph 编排。\n\n"
        "- **推荐**（PRED 五步）+ 程序化护栏\n"
        "- **评价草稿**（CASDG）：锚定订单事实，模型起草、用户签字\n"
        "- **商家分析**（观察/假设/建议三层）：数字可验、禁因果断言\n\n"
        "**不直连前端**（走 shop-api 门面）；**不直连数据库**（回头调 /internal 拿瘦事实）；"
        "**不写库**（发布在 Java 门面，签字权在用户）。"
    ),
    version="0.3.0",
)


@app.get("/health", tags=["system"])
def health() -> dict:
    """健康检查端点：运维探活/启动脚本用它判断服务是否起来了。

    返回：{"status": "UP"}（与 shop-api 的 actuator/health 语义一致）
    """
    return {"status": "UP"}


@app.post("/agent/recommend", tags=["user-agent"])
def recommend(req: RecommendRequest,
              x_user_id: int = Header(alias="X-User-Id")) -> dict:
    """对话式推荐（PRED 五步 + 护栏）。

    参数：
      req        —— 请求体，FastAPI 自动把 JSON 反序列化成 RecommendRequest 对象（含 message/lat/lng/sessionId）
      x_user_id  —— 从请求头 X-User-Id 取值；这个头是 Java 门面验完 JWT 后注入的，Python 侧不做鉴权

    返回：统一信封 {code, message, data}。注意本端点刻意不设 response_model——
         信封是跨服务合同，套 DTO 校验会把信封本身也校验掉（曾踩坑 500）。
    """
    # 调推荐图：真正跑「意图解析→画像→检索→证据→对比生成→护栏」五步
    result = run_recommend(x_user_id, req.message, req.lat, req.lng, req.sessionId)
    # 图内部若返回非 0 错误码（42201 护栏拦截 / 50000 服务未连通），原样透传给调用方
    if result["code"] != 0:
        return {"code": result["code"], "message": result["message"], "data": None}
    return {"code": 0, "message": "ok", "data": result["data"]}


@app.post("/agent/review-draft", tags=["user-agent"])
def review_draft(req: ReviewDraftRequest,
                 x_user_id: int = Header(alias="X-User-Id")) -> dict:
    """生成评价草稿（CASDG，绑订单事实，不发布）。身份由门面注入。

    关键点：这里只「起草」并存进草稿仓（drafts.py），不写数据库——
           发布由 Java 门面调 /publish 取走草稿后写库。
    """
    result = run_review_draft(x_user_id, req.orderId, req.userNote, req.preferScores)
    if result["code"] != 0:
        return {"code": result["code"], "message": result["message"], "data": None}
    return {"code": 0, "message": "ok", "data": result["data"]}


@app.post("/agent/review-draft/{draft_id}/publish", tags=["user-agent"])
def publish(draft_id: str, x_user_id: int = Header(alias="X-User-Id")) -> dict:
    """
    发布协作端点（被 Java 门面调用）：验归属 → 交出草稿并消费。
    真正的写库在 Java（ReviewService 二次校验）——本服务永远不写库。
    草稿发布即消费：二次调用返回"不存在或已消费"（幂等防连点双评）。

    参数：
      draft_id   —— 路径参数（URL 里 {draft_id} 的位置），如 /agent/review-draft/d-abc123/publish
      x_user_id  —— 门面注入的用户 ID，用来校验「这草稿是不是你的」

    返回：code=0 时 data 里带 orderId/scores/content（给 Java 门面写库用）
    """
    # pop = 取出并删除（发布即消费）。归属不符时返回 None 且不会删除别人的草稿
    d = drafts.pop(draft_id, x_user_id)
    if d is None:
        # 草稿还在仓库里 → 说明是「别人的草稿」，40300 拒绝
        if drafts.exists(draft_id):
            return {"code": 40300, "message": "草稿不属于当前用户", "data": None}
        # 仓库里也没有 → 说明已被消费过（或从来没生成过），40001
        return {"code": 40001, "message": "草稿不存在或已消费（勿重复发布）", "data": None}
    # 归属正确：把草稿内容交给 Java 门面（它拿去做二次校验并写库）
    return {
        "code": 0, "message": "ok",
        "data": {"orderId": d["orderId"], "scores": d["scores"], "content": d["content"]},
    }


@app.post("/agent/merchant/analyze", tags=["merchant-agent"])
def analyze(req: AnalyzeRequest, x_user_id: int = Header(alias="X-User-Id")) -> dict:
    """商家分析（三技能）：观察/假设/建议三层 + 护栏。归属校验已在 Java 门面完成。

    参数：
      req.shopId —— 要分析的店铺 ID
      req.skill  —— 三选一：ops(经营归因) / reviews(评论诊断) / competitors(竞品快照)

    注意：Java 门面已经校验过「这家店是不是你的」——Python 侧不再重复判权，
         这是「门面做安全、Python 做智能」的分工。
    """
    result = run_merchant_analyze(x_user_id, req.shopId, req.skill)
    if result["code"] != 0:
        return {"code": result["code"], "message": result["message"], "data": None}
    return {"code": 0, "message": "ok", "data": result["data"]}
