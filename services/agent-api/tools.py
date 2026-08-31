# tools.py —— 「瘦事实」工具层：agent-api 回头调 shop-api 的 /internal 只读接口取数据。
#
# 【这个文件是什么】
#   Agent 要推荐店铺，就需要「画像、店铺列表、评价证据」这些数据。
#   但本服务不连数据库——所以这里是唯一的取数出口：全部通过 HTTP 找 Java 主站要。
#   每个函数对应 Java 侧的一个 /internal 接口（只读、带服务间密钥）。
#
# 【为什么这么设计（面试必答）】
#   Agent 是概率系统，给它数据库连接串等于打开越权/误写/注入的攻击面。
#   所以：只读 + 走接口 + 业务过滤（如只返回已过审的店）留在 Java 侧，一处修改两处生效。
#
# 【本文件涉及的 Python 语法速览（Java 背景看这里）】
#   import os                  → 标准库，读环境变量用
#   os.getenv("A", "默认值")    → 读环境变量，读不到就用默认值（≈ System.getenv + 兜底）
#   httpx.Client(...)          → 创建 HTTP 客户端，≈ Java 的 RestClient/HttpClient 实例
#   base_url=...               → 之后每次请求只写相对路径（如 /internal/xxx）
#   f"/internal/users/{id}"    → f-string 拼路径
#   str | None = None          → 参数可选、默认 None
#   isinstance(x, list)        → 判断类型（≈ Java 的 x instanceof List）
#   _ 开头的函数/变量            → 约定「内部使用」，不对外暴露（Python 没有 private，靠命名约定）
import os

import httpx
from dotenv import load_dotenv

# 读取 services/agent-api/.env 文件里的配置（密钥不进代码、不进 Git）
load_dotenv()

# 主站地址与「服务间共享密钥」——密钥由 shop-api 的 InternalTokenFilter 校验
SHOP_API = os.getenv("SCOUTBITE_SHOP_API_URL", "http://localhost:8081")
INTERNAL_TOKEN = os.getenv("SCOUTBITE_INTERNAL_TOKEN", "")

# 模块级共享 HTTP 客户端（整个进程复用，自带连接池，避免每次请求重建连接）
# headers 里固定带上服务间密钥——本文件所有请求都会自动携带，不用每个函数重复写
_client = httpx.Client(
    base_url=SHOP_API,
    headers={"X-Internal-Token": INTERNAL_TOKEN},
    timeout=httpx.Timeout(10.0, connect=3.0),   # 总超时 10s + 建连 3s（四参须全给或用 default）
)


def _get(path: str) -> dict:
    """GET /internal/**，拆统一信封 {code, message, data}；非 0 抛异常。

    这是所有工具的公共底座：统一处理「HTTP 状态 + 业务码」两层错误。
    参数：path —— 相对路径，如 /internal/shops/3/evidence
    返回：信封里的 data 部分（业务数据）
    异常：HTTP 4xx/5xx 或业务码非 0 时抛异常——由上层（图节点）捕获后转 50000 诚实降级
    """
    resp = _client.get(path)
    resp.raise_for_status()          # HTTP 层错误（404/500…）直接抛
    body = resp.json()               # 把响应体解析成 dict
    if body.get("code") != 0:        # 业务层错误（信封里的 code 非 0）
        raise RuntimeError(f"internal 接口失败 {path}: {body.get('message')}")
    return body.get("data", {})      # 返回业务数据；没有 data 字段就给空 dict


def get_profile(user_id: int) -> dict:
    """用户画像：tags / avgPrice / topCategories（coldStart=true 表示冷启动/新用户）

    对应 Java 接口：GET /internal/users/{id}/profile
    用途：推荐图第②步——个性化兜底（用户没说品类时用历史偏好）
    """
    return _get(f"/internal/users/{user_id}/profile")


def search_shops(lat: float, lng: float, radius: int = 5000,
                 category: str | None = None, limit: int = 12) -> list[dict]:
    """硬过滤检索：approved 强制、带距离；返回候选 8~12 家（不是全世界）

    对应 Java 接口：GET /internal/shops/search?lat=&lng=&radius=&category=
    关键：距离计算复用主站 GeoService（方盒粗筛 + Haversine 精算）——
         保证 Agent 说的「附近」和用户在 App 里看到的「附近」完全一致（事实同源）。

    参数：lat/lng(坐标)、radius(米，默认5km)、category(品类，None=全部)、limit(条数)
    返回：店铺列表（每项含 id/name/category/distanceMeters/lat/lng）
    """
    params = f"lat={lat}&lng={lng}&radius={radius}&limit={limit}"
    if category:                     # 只有指定品类时才拼这个参数（None 表示不限）
        params += f"&category={category}"
    data = _get(f"/internal/shops/search?{params}")
    return data if isinstance(data, list) else []   # 防御：万一返回的不是列表就给空列表


def get_evidence(shop_id: int) -> dict:
    """店铺证据：评分/销量/券/正评3+差评3（每条评论带 evidenceId）

    对应 Java 接口：GET /internal/shops/{id}/evidence
    用途：推荐图第④步——给模型「可引用的事实」。evidenceId 是护栏校验的锚点：
         模型引用不存在的 evidenceId 会被护栏拦截（42201 疑似编造）。
    """
    return _get(f"/internal/shops/{shop_id}/evidence")


# ---------- 评价锚点 + 商家三件套 ----------

def get_order_facts(order_id: int, user_id: int) -> dict:
    """订单事实（评价锚点）：belongToUser 由显式传的 userId 比对（服务间信任）。

    对应 Java 接口：GET /internal/orders/{id}/facts?userId=
    用途：评价草稿图第①步——AI 只能基于这单的真实信息（店名/套餐/实付/时间）写评价。
    返回里含三个校验字段：exists(订单存在吗) / belongToUser(是你本人的吗) / canReview(状态可评吗)
    """
    return _get(f"/internal/orders/{order_id}/facts?userId={user_id}")


def get_metrics(shop_id: int) -> dict:
    """商家经营指标：新客/复购/券占比/曝光/评分（归因的数字基础）。

    对应 Java 接口：GET /internal/merchant/{id}/metrics
    用途：商家分析技能 ops（经营归因）——护栏要求「观察句里的数字必须来自这里」
    """
    return _get(f"/internal/merchant/{shop_id}/metrics")


def get_review_clusters(shop_id: int) -> list:
    """评论观点聚类（关键词分桶，每桶带原评×2）。

    对应 Java 接口：GET /internal/merchant/{id}/review-clusters
    用途：商家分析技能 reviews（评论诊断）
    诚实说明：这是「关键词分桶」不是语义聚类——known-issues 里记录的已知局限。
    """
    data = _get(f"/internal/merchant/{shop_id}/review-clusters")
    return data if isinstance(data, list) else []


def get_competitors(shop_id: int) -> list:
    """竞品快照：同品类 3km 公开信息（坐标由主站按本店自取，不用传）。

    对应 Java 接口：GET /internal/merchant/{id}/competitors
    用途：商家分析技能 competitors（竞品对比）——只用系统内公开信息，不抓外部数据。
    """
    data = _get(f"/internal/merchant/{shop_id}/competitors")
    return data if isinstance(data, list) else []
