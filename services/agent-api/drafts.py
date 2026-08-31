# drafts.py —— 评价草稿仓：把 AI 写好的评价草稿暂存起来，等用户「签字」后取走。
#
# 【这个文件是什么】
#   AI 起草评价后不能直接写库（那违反「签字权在用户」原则）。
#   所以先把草稿存在这个「仓」里，返回一个 draftId 给前端；
#   用户点「确认发布」时，Java 门面拿 draftId 来这里取走草稿（取走即删除），再写库。
#
# 【为什么要进程内字典，而不是建数据库表（面试常问）】
#   草稿的生命周期是「分钟级、单用户、待签字」——为此建表（迁移/清理/状态同步）成本 > 收益。
#   诚实代价：服务重启会丢草稿（用户重新点一次生成即可，损失约一次 LLM 调用）。
#   升级路径：换成 Redis + TTL，函数签名和调用方都不用改——因为当初就把它抽象成了独立模块。
#
# 【本文件涉及的 Python 语法速览（Java 背景看这里）】
#   import threading                   → 线程锁库（FastAPI 是多线程跑的，共享 dict 必须加锁）
#   _store: dict[str, dict] = {}       → 模块级全局字典（draftId → 草稿内容），类型是「字符串→字典」
#   with _lock:                        → 上下文管理器：进块加锁、出块自动释放（≈ Java synchronized 块）
#   uuid.uuid4().hex[:12]              → 生成随机 ID 并取前 12 位十六进制字符
#   dict | None                        → 返回值类型：要么是 dict，要么是 None
#   d is None                          → 判断「是不是 None」（Java 用 == null）
#   del _store[draft_id]               → 从字典里删除这个键（≈ Map.remove）
#   _store.get(key)                    → 取值，键不存在返回 None（不会抛异常）
import threading
import uuid

# 全局锁：保证 create/pop 操作的原子性，防止并发写坏字典
_lock = threading.Lock()
# 草稿仓本体：draftId → {userId, orderId, scores, content, usedFacts}
_store: dict[str, dict] = {}


def create(user_id: int, order_id: int, scores: dict, content: str, used_facts: list) -> str:
    """存草稿，返回 draftId。

    参数：
      user_id    —— 草稿归属人（关键！发布时要靠它校验「是不是你的草稿」）
      order_id   —— 这草稿是为哪个订单写的（写库时要绑定）
      scores     —— 三维评分，如 {"taste":5, "wait":3, "env":4}
      content    —— 草稿正文
      used_facts —— 草稿引用了哪些订单事实（可追溯，防编造）
    返回：新生成的 draftId（形如 "d-a1b2c3d4e5f6"）
    """
    # 生成 12 位随机 ID，加 "d-" 前缀便于识别（草稿 draft）
    draft_id = "d-" + uuid.uuid4().hex[:12]
    with _lock:                       # 加锁写入，防并发
        _store[draft_id] = {
            "userId": user_id,
            "orderId": order_id,
            "scores": scores,
            "content": content,
            "usedFacts": used_facts,
        }
    return draft_id


def pop(draft_id: str, user_id: int) -> dict | None:
    """取走并删除（发布即消费）。归属不符返回 None（不算消费——防误删他人草稿）。

    参数：
      draft_id —— 要取的草稿 ID
      user_id  —— 当前请求的用户 ID（用来校验归属）
    返回：草稿内容 dict；取不到或不属于该用户时返回 None

    三个关键行为（面试可讲）：
      ① 取走即删除 → 连点两次发布，第二次取不到 → 天然防「重复发布/双评」
      ② 不是你的草稿 → 返回 None 但【不删除】→ 防止有人用别人的 draftId 恶意消费掉它
      ③ 完全不存在 → 也返回 None（调用方靠 exists() 区分这两种情况，给不同错误码）
    """
    with _lock:
        d = _store.get(draft_id)      # 查仓；没有就是 None
        if d is None:
            return None               # 情况③：从来没生成过，或已被消费
        if d["userId"] != user_id:
            return None               # 情况②：别人的草稿——注意这里没有 del，草稿还在仓里
        del _store[draft_id]          # 情况①：是自己的 → 取走并删除
        return d


def exists(draft_id: str) -> bool:
    """草稿是否还在仓里（用来区分「不存在」和「不属于你」两种失败）

    调用方逻辑（见 main.py 的 publish）：
      pop 返回 None 且 exists 为 True  → 草稿还在，说明是别人的 → 40300
      pop 返回 None 且 exists 为 False → 草稿已被消费/不存在 → 40001
    """
    return draft_id in _store     # in 运算符：判断键是否在字典里
