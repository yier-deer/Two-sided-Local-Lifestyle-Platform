# main.py —— agent-api 入口：Agent 大脑（完全体：推荐 + 评价草稿 + 商家分析）。
#
# 边界铁律（写在这防止将来手滑）：
#   1. 本服务不直连前端——统一由 shop-api 的 /api/agent 门面转发（身份走 X-User-Id 头）
#   2. 本服务不直连数据库——数据一律回头调 shop-api 的 /internal 只读接口（X-Internal-Token）
#   3. 签字权在用户——本服务只起草（drafts 草稿仓），发布由 Java 门面取草稿后走 ReviewService 写库
#      （本服务没有写库通道；publish 端点只负责"验归属+交出草稿+消费"）
#   4. 诚实降级——LLM/主站未连通一律 50000 明说，不生成任何内容（宁可报错，不可冒充）
from fastapi import FastAPI, Header

import drafts
from graph import run_recommend
from merchant_graph import run_merchant_analyze
from models import AnalyzeRequest, RecommendRequest, ReviewDraftRequest
from review_graph import run_review_draft

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
    """健康检查"""
    return {"status": "UP"}


@app.post("/agent/recommend", tags=["user-agent"])
def recommend(req: RecommendRequest,
              x_user_id: int = Header(alias="X-User-Id")) -> dict:
    """对话式推荐（PRED 五步 + 护栏）。返回统一信封（无 response_model——信封是跨服务合同）。"""
    result = run_recommend(x_user_id, req.message, req.lat, req.lng, req.sessionId)
    if result["code"] != 0:
        return {"code": result["code"], "message": result["message"], "data": None}
    return {"code": 0, "message": "ok", "data": result["data"]}


@app.post("/agent/review-draft", tags=["user-agent"])
def review_draft(req: ReviewDraftRequest,
                 x_user_id: int = Header(alias="X-User-Id")) -> dict:
    """生成评价草稿（CASDG，绑订单事实，不发布）。身份由门面注入。"""
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
    """
    d = drafts.pop(draft_id, x_user_id)
    if d is None:
        if drafts.exists(draft_id):
            return {"code": 40300, "message": "草稿不属于当前用户", "data": None}
        return {"code": 40001, "message": "草稿不存在或已消费（勿重复发布）", "data": None}
    return {
        "code": 0, "message": "ok",
        "data": {"orderId": d["orderId"], "scores": d["scores"], "content": d["content"]},
    }


@app.post("/agent/merchant/analyze", tags=["merchant-agent"])
def analyze(req: AnalyzeRequest, x_user_id: int = Header(alias="X-User-Id")) -> dict:
    """商家分析（三技能）：观察/假设/建议三层 + 护栏。归属校验已在 Java 门面完成。"""
    result = run_merchant_analyze(x_user_id, req.shopId, req.skill)
    if result["code"] != 0:
        return {"code": result["code"], "message": result["message"], "data": None}
    return {"code": 0, "message": "ok", "data": result["data"]}
