# 名词表

面试和代码里只用这些词，不要中英混着发明第三套。

| 中文 | 代码 / 口述 | 含义 |
|---|---|---|
| 探店雷达 | ScoutBite | 产品名 |
| 主站 | shop-api | Java 21 业务服务 |
| Agent 服务 | agent-api | Python 编排，不写库存 |
| 前端 | web | Vue3，只打 HTTP |
| 用户 / 商家 / 管理员 | USER / MERCHANT / ADMIN | JWT role |
| 店铺状态 | draft/pending/approved/rejected | 可见性开关 |
| 套餐 | sku | 可买项，价格单位分 |
| 满减券占用 | FROZEN / USED | 下单冻，退单/超时释放，到店核销后才 USED |
| 订单状态 | CREATED / PAID / REDEEMED / REVIEWED / CANCELLED_TIMEOUT / REFUNDED | 支付≠到店 |
| 到店核销 | redeem | 电子套餐券到店履约，之后才能评价 |
| 未核销退单 | refund | 仅 `PAID` 可退 |
| 幂等键 | Idempotency-Key | 防重复下单 |
| 附近 | nearby | 已审核 + 距离 |
| 推流 | feed | nearby/hot/new |
| 探索 | exploreBoost | 新店保量 |
| 推荐流程 | PRED | 画像→约束→证据→决策 |
| 写评流程 | CASDG | 收集→对齐→打分→草稿→门禁 |
| 证据 | evidenceId | 必须能指到库里的评论 |
| 人机确认 | Gate / HITL | 未确认不落库 |
| 轨迹 | agent_trace | 一次调用的步骤回放 |
| 黄金集 | evals/datasets | 离线对错标准 |

相关但今天不必深挖：ReAct、虚拟线程、pgvector、威尔逊得分。听到名字知道「/8/9 才会用」即可。
