# drafts.py —— 评价草稿仓（）：进程内字典，发布即消费。
# 生命周期"分钟级、单用户、待签字"——写库反而亏（建表/清理/状态同步）。
# 诚实代价：重启丢草稿（用户重新生成即可，损失为零）；升级路径 Redis+TTL，形状不变。
import threading
import uuid

_lock = threading.Lock()
_store: dict[str, dict] = {}   # draftId -> {userId, orderId, scores, content, usedFacts}


def create(user_id: int, order_id: int, scores: dict, content: str, used_facts: list) -> str:
    """存草稿，返回 draftId。"""
    draft_id = "d-" + uuid.uuid4().hex[:12]
    with _lock:
        _store[draft_id] = {
            "userId": user_id,
            "orderId": order_id,
            "scores": scores,
            "content": content,
            "usedFacts": used_facts,
        }
    return draft_id


def pop(draft_id: str, user_id: int) -> dict | None:
    """取走并删除（发布即消费）。归属不符返回 None（不算消费——防误删他人草稿）。"""
    with _lock:
        d = _store.get(draft_id)
        if d is None:
            return None
        if d["userId"] != user_id:
            return None   # 不是你的草稿：不删，返回 None 由调用方报"不存在或不属于你"
        del _store[draft_id]
        return d


def exists(draft_id: str) -> bool:
    return draft_id in _store
