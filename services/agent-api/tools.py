# tools.py —— 瘦事实工具：agent-api 回头调 shop-api 的 /internal 只读接口。
# 铁律：本服务不直连数据库——数据一律从这里拿（带 X-Internal-Token 服务间密钥）。
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

SHOP_API = os.getenv("SCOUTBITE_SHOP_API_URL", "http://localhost:8081")
INTERNAL_TOKEN = os.getenv("SCOUTBITE_INTERNAL_TOKEN", "")

_client = httpx.Client(
    base_url=SHOP_API,
    headers={"X-Internal-Token": INTERNAL_TOKEN},
    timeout=httpx.Timeout(10.0, connect=3.0),   # 默认 10s + 连接 3s（四参须全或用 default）
)


def _get(path: str) -> dict:
    """GET /internal/**，拆统一信封 {code, message, data}；非 0 抛异常。"""
    resp = _client.get(path)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"internal 接口失败 {path}: {body.get('message')}")
    return body.get("data", {})


def get_profile(user_id: int) -> dict:
    """用户画像：tags / avgPrice / topCategories（coldStart=true 表示冷启动）"""
    return _get(f"/internal/users/{user_id}/profile")


def search_shops(lat: float, lng: float, radius: int = 5000,
                 category: str | None = None, limit: int = 12) -> list[dict]:
    """硬过滤检索：approved 强制、带距离；返回候选 8~12 家（不是全世界）"""
    params = f"lat={lat}&lng={lng}&radius={radius}&limit={limit}"
    if category:
        params += f"&category={category}"
    data = _get(f"/internal/shops/search?{params}")
    return data if isinstance(data, list) else []


def get_evidence(shop_id: int) -> dict:
    """店铺证据：评分/销量/券/正评3+差评3（每条评论带 evidenceId）"""
    return _get(f"/internal/shops/{shop_id}/evidence")


# ---------- 评价锚点 + 商家三件套 ----------

def get_order_facts(order_id: int, user_id: int) -> dict:
    """订单事实（评价锚点）：belongToUser 由显式传的 userId 比对（服务间信任）。"""
    return _get(f"/internal/orders/{order_id}/facts?userId={user_id}")


def get_metrics(shop_id: int) -> dict:
    """商家经营指标：新客/复购/券占比/曝光/评分（归因的数字基础）。"""
    return _get(f"/internal/merchant/{shop_id}/metrics")


def get_review_clusters(shop_id: int) -> list:
    """评论观点聚类（关键词分桶，每桶带原评×2）。"""
    data = _get(f"/internal/merchant/{shop_id}/review-clusters")
    return data if isinstance(data, list) else []


def get_competitors(shop_id: int) -> list:
    """竞品快照：同品类 3km 公开信息（坐标由主站按本店自取，不用传）。"""
    data = _get(f"/internal/merchant/{shop_id}/competitors")
    return data if isinstance(data, list) else []
