# models.py —— Pydantic 模型：请求/响应 DTO（Data Transfer Object，数据传输对象）。
#
# 【这个文件是什么】
#   定义接口的「数据结构」——请求体长什么样、响应长什么样。
#   类比 Java：就是那些 @RequestBody 的 DTO 类。
#
# 【Pydantic 是什么？为什么用它】
#   Pydantic 是 Python 的数据校验库。定义一个类继承 BaseModel 后：
#     ① 请求进来时，FastAPI 自动把 JSON 变成这个类的对象，并校验类型（缺字段/类型错自动返回 422）
#     ② 自动生成 /docs 的接口文档（字段说明、示例都从 Field(description=...) 来）
#     ③ 写错字段名，/docs 页面上立刻能看出来——这就是「合同强制力」的来源
#
# 【本文件涉及的 Python 语法速览（Java 背景看这里）】
#   class X(BaseModel):        → 定义类，括号里是父类（≈ Java extends）
#   字段: 类型 = 默认值          → Python 没有 private/public 关键字，直接写在类里就是字段
#   str | None                 → 联合类型：要么是 str，要么是 None（≈ Java 的 Optional<String>）
#   list[ShopBrief]            → 泛型列表（≈ Java 的 List<ShopBrief>）
#   dict[str, int]             → 字典类型（≈ Java 的 Map<String, Integer>）
#   Literal["ops","reviews"]   → 枚举式约束：值只能是列出的这几个之一
#   Field(default_factory=list)→ 默认值用「调用 list() 生成空列表」，避免多个对象共享同一个列表（Python 经典坑）
from typing import Literal

from pydantic import BaseModel, Field


# ---------- 用户侧 Agent：推荐 ----------

class RecommendRequest(BaseModel):
    """对话式推荐的请求体（前端 POST /api/agent/user/recommend 时带的数据）"""
    message: str = Field(description="用户原话，如：今晚想吃辣的，两个人，人均100左右")
    lat: float = Field(description="纬度")   # 必填：类型是 float，传 null 会 422（前端已做无定位兜底）
    lng: float = Field(description="经度")   # 必填
    sessionId: str | None = Field(default=None, description="多轮会话 ID，首轮为空")


class ShopBrief(BaseModel):
    """推荐结果里的单家店（瘦字段，只给模型该看的——不给价格明细等冗余信息）"""
    id: int = Field(description="店铺 ID")
    name: str = Field(description="店名")
    reason: str = Field(description="一句话推荐理由")


class RecommendResponse(BaseModel):
    """推荐响应：pros / cons / evidenceIds 是合同强制字段（前端与门面按此约定解析）

    注意：这个类目前主要作为「合同文档」存在——推荐端点是手写信封返回的，
         不设 response_model（原因见 main.py 注释：套 DTO 会校验信封本身导致 500）。
    """
    sessionId: str = Field(description="会话 ID，多轮续接用")
    answer: str = Field(description="给用户看的自然语言回答")
    shops: list[ShopBrief] = Field(default_factory=list, description="推荐的店铺列表")
    pros: list[str] = Field(default_factory=list, description="推荐理由")
    cons: list[str] = Field(default_factory=list, description="风险或不足")
    evidenceIds: list[str] = Field(default_factory=list, description="引用的证据 ID，防编造")


# ---------- 用户侧 Agent：评价草稿 ----------

class ReviewDraftRequest(BaseModel):
    """评价草稿请求：必须绑订单——orderId 是防编造的锚点（AI 只能基于这单的事实写）"""
    orderId: int = Field(description="已核销的订单 ID")   # 只有 REDEEMED 状态的订单能过校验
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
    """商家分析请求：skill 三选一（Literal 让 FastAPI 自动校验，传别的值直接 422）"""
    shopId: int = Field(description="店铺 ID")
    skill: Literal["ops", "reviews", "competitors"] = Field(description="分析技能：经营/评论/竞品")
