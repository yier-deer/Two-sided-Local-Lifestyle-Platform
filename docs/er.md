# ScoutBite ER 初稿 v0.1（）

> 约定：主键统一 `bigint` 自增；价格一律用整数「分」存 int（禁浮点，ADR-005）；
> 时间用 `timestamptz`；软删除不做，状态机表达生命周期。

## 1. users 用户

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| phone | varchar(20) | 登录号，唯一索引 |
| password_hash | varchar(100) | BCrypt（） |
| role | varchar(10) | USER / MERCHANT / ADMIN（枚举） |
| nickname | varchar(50) | |
| created_at | timestamptz | |

## 2. shops 店铺（状态机表）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| owner_id | bigint FK→users | 商家 |
| name | varchar(100) | |
| category | varchar(20) | HOTPOT / COFFEE / ENTERTAIN（种子三品类） |
| city | varchar(20) | 先杭州单城 |
| lat / lng | double | 经纬度 |
| status | varchar(12) | draft → pending → approved / rejected；rejected 可改资料回 pending |
| approved_at | timestamptz | 仅 approved 状态对用户可见 |

## 3. skus 套餐

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| shop_id | bigint FK→shops | |
| title | varchar(100) | |
| price | int | 分 |
| stock | int | 库存，下单 CAS 扣减 |
| sales | int | 展示销量：核销后 +1，退单不计（ADR-011） |
| on_sale | boolean | 上下架 |

## 4. coupons 券（库存镜像到 Redis，领取走 Lua）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| shop_id | bigint FK→shops | |
| title | varchar(100) | |
| threshold | int | 满减门槛，分 |
| amount | int | 抵扣金额，分 |
| total | int | 总量（镜像到 Redis） |
| per_user_limit | int | 每人限领 |
| start_at / end_at | timestamptz | 领取窗口 |

## 5. user_coupons 用户持券

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| user_id | bigint FK→users | |
| coupon_id | bigint FK→coupons | |
| status | varchar(10) | UNUSED / FROZEN（下单冻结）/ USED（核销后才算用掉，ADR-011） |
| order_id | bigint | 冻结/使用时关联 |

## 6. orders 订单（电子套餐券，两段式状态机）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| user_id | bigint FK→users | |
| shop_id | bigint FK→shops | |
| sku_id | bigint FK→skus | |
| price_snapshot | int | 下单时价格快照，分 |
| status | varchar(18) | CREATED→PAID→REDEEMED→REVIEWED；CANCELLED_TIMEOUT / REFUNDED（ADR-011） |
| expire_at | timestamptz | CREATED 后超时关单时刻（Redis ZSET 延迟队列） |
| idempotency_key | varchar(64) | **唯一索引**，防网络重试重复下单 |

状态规则：只有 REDEEMED 可评价；PAID 后未核销可退（回补库存+释放券）；核销后不可退。

## 7. reviews 评价（反刷评核心表）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| order_id | bigint | **唯一索引**——一单一评（ADR-009） |
| shop_id | bigint FK→shops | 冗余存，方便店页查询 |
| user_id | bigint FK→users | |
| scores_json | jsonb | 分维度打分 {taste, wait, env...} |
| content | text | 正文（Agent 只能起草，用户确认发布） |
| images | text[] | MinIO key 列表 |
| created_at | timestamptz | |

## 8. review_replies 评价回复

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| review_id | bigint FK→reviews | |
| user_id | bigint FK→users | 回复者 |
| content | text | |
| is_merchant | boolean | **服务端按 token 角色判定**，不信任请求体 |

## 9. posts 帖子

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| user_id | bigint FK→users | |
| shop_id | bigint | 可空（纯分享不关联店） |
| content | text | |
| images | text[] | MinIO key |

## 10. likes 点赞（画像原料）

| 字段 | 类型 | 说明 |
|---|---|---|
| user_id + target_type + target_id | 联合唯一 | target_type: POST / REVIEW / SHOP |

## 11. impressions 曝光日志（推流与归因）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | 量大，只插不改 |
| user_id | bigint | 可空（未登录） |
| shop_id | bigint | |
| scene | varchar(10) | nearby / hot / new |
| position | int | 出现在第几位（保新压热的证据） |
| ts | timestamptz | |

## 12. user_profiles 用户画像（离线刷新）

| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | bigint PK | |
| tags_json | jsonb | 吃辣党/亲子党/咖啡党… |
| avg_price | int | 历史客单价，分 |
| top_categories | jsonb | 偏好品类 |

## 13. agent_traces Agent 轨迹（评测原料）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint PK | |
| user_id | bigint | |
| skill | varchar(20) | recommend / review-draft / analyze-ops… |
| input | jsonb | 用户输入快照 |
| tools_json | jsonb | 调了哪些 /internal 接口、LLM 花了几个 token |
| output | jsonb | 最终输出 |
| latency_ms | int | 时延 |

## 关系速览

```
users 1─n shops 1─n skus
users 1─n orders n─1 skus（价格快照）
shops 1─n coupons 1─n user_coupons n─1 orders（冻结/核销）
orders 1─1 reviews 1─n review_replies
users 1─n posts / likes / impressions / user_profiles / agent_traces
```
