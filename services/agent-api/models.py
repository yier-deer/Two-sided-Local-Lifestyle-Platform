# models.py —— Pydantic 模型：请求/响应 DTO。
# 字段名与《接口实现》合同一字不差；FastAPI 读取这些模型自动生成 /docs 页面，
# 写错字段名页面上立刻看得见——这就是「合同强制力」的来源。
from typing import Literal

from pydantic import BaseModel, Field


# ---------- 用户侧 Agent：推荐 ----------

class RecommendRequest(BaseModel):
    """对话式推荐的请求体"""
    message: str = Field(description="用户原话，如：今晚想吃辣的，两个人，人均100左右")
    lat: float = Field(description="纬度")
    lng: float = Field(description="经度")
    sessionId: str | None = Field(default=None, description="多轮会话 ID，首轮为空")


class ShopBrief(BaseModel):
    """推荐结果里的单家店（瘦字段，只给模型该看的）"""
    id: int = Field(description="店铺 ID")
    name: str = Field(description="店名")
    reason: str = Field(description="一句话推荐理由")


class RecommendResponse(BaseModel):
    """推荐响应：pros / cons / evidenceIds 是合同强制字段"""
    sessionId: str = Field(description="会话 ID，多轮续接用")
    answer: str = Field(description="给用户看的自然语言回答")
    shops: list[ShopBrief] = Field(default_factory=list, description="推荐的店铺列表")
    pros: list[str] = Field(default_factory=list, description="推荐理由")
    cons: list[str] = Field(default_factory=list, description="风险或不足")
    evidenceIds: list[str] = Field(default_factory=list, description="引用的证据 ID，防编造")


# ---------- 用户侧 Agent：评价草稿 ----------

class ReviewDraftRequest(BaseModel):
    """评价草稿请求：必须绑订单——order_id 是防编造的锚点"""
    orderId: int = Field(description="已核销的订单 ID")
    userNote: str | None = Field(default=None, description="用户随手记的原话，可选")
    imageKeys: list[str] = Field(default_factory=list, description="MinIO 图片 key 列表")
    preferScores: dict[str, int] = Field(default_factory=dict, description="用户预设打分倾向，如 taste=5")


class ReviewDraft(BaseModel):
    """评价草稿响应：scores / content / usedFacts 是合同强制字段"""
    draftId: str = Field(description="草稿 ID，发布时要带")
    scores: dict[str, int] = Field(description="分维度打分，如 taste/wait")
    content: str = Field(description="草稿正文")
    usedFacts: list[str] = Field(default_factory=list, description="草稿引用的订单事实，可追溯")


# ---------- 商家侧 Agent：经营分析 ----------

class AnalyzeRequest(BaseModel):
    """商家分析请求：skill 三选一"""
    shopId: int = Field(description="店铺 ID")
    skill: Literal["ops", "reviews", "competitors"] = Field(description="分析技能：经营/评论/竞品")
