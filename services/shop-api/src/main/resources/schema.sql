-- ScoutBite schema（只建 users / shops 两张表）
-- 依赖纪律：skus/coupons/orders 等 建——功能没到不建表
-- 全部 IF NOT EXISTS：因为 sql.init.mode=always 每次启动都会执行本文件

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    phone         VARCHAR(20)  NOT NULL,
    password_hash VARCHAR(100) NOT NULL,
    role          VARCHAR(10)  NOT NULL,           -- USER / MERCHANT / ADMIN
    nickname      VARCHAR(50)  NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_phone UNIQUE (phone)       -- 注册防重靠唯一索引
);

CREATE TABLE IF NOT EXISTS shops (
    id          BIGSERIAL PRIMARY KEY,
    owner_id    BIGINT       NOT NULL,
    name        VARCHAR(100) NOT NULL,
    category    VARCHAR(20)  NOT NULL,             -- HOTPOT / COFFEE / ENTERTAIN
    city        VARCHAR(20)  NOT NULL DEFAULT '杭州',
    lat         DOUBLE PRECISION NOT NULL,
    lng         DOUBLE PRECISION NOT NULL,
    status      VARCHAR(12)  NOT NULL,             -- pending / approved / rejected
    approved_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shops_status ON shops(status);      -- 可见性过滤主战场
CREATE INDEX IF NOT EXISTS idx_shops_owner  ON shops(owner_id);    -- 商家查自己的店

-- ===== 交易四表 =====

CREATE TABLE IF NOT EXISTS skus (
    id       BIGSERIAL PRIMARY KEY,
    shop_id  BIGINT       NOT NULL,
    title    VARCHAR(100) NOT NULL,
    price    INT          NOT NULL,               -- 分（禁浮点，ADR-005）
    stock    INT          NOT NULL,
    sales    INT          NOT NULL DEFAULT 0,     -- 核销后 +1（），退单不计（ADR-011 规则5）
    on_sale  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_skus_shop ON skus(shop_id);

CREATE TABLE IF NOT EXISTS coupons (
    id              BIGSERIAL PRIMARY KEY,
    shop_id         BIGINT       NOT NULL,
    title           VARCHAR(100) NOT NULL,
    threshold       INT          NOT NULL,         -- 满减门槛，分
    amount          INT          NOT NULL,         -- 抵扣金额，分
    total           INT          NOT NULL,         -- 总量（领取余量镜像在 Redis：coupon:{id}:stock）
    per_user_limit  INT          NOT NULL DEFAULT 1,
    start_at        TIMESTAMPTZ  NOT NULL,
    end_at          TIMESTAMPTZ  NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_coupons_shop ON coupons(shop_id);

CREATE TABLE IF NOT EXISTS user_coupons (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT      NOT NULL,
    coupon_id  BIGINT      NOT NULL,
    status     VARCHAR(10) NOT NULL,               -- UNUSED / FROZEN / USED
    order_id   BIGINT,                             -- 冻结时关联订单
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_coupons_user   ON user_coupons(user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_coupons_coupon ON user_coupons(coupon_id);

CREATE TABLE IF NOT EXISTS orders (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT      NOT NULL,
    shop_id          BIGINT      NOT NULL,
    sku_id           BIGINT      NOT NULL,
    coupon_id        BIGINT,                       -- 可空：没用券
    price_snapshot   INT         NOT NULL,         -- 下单时价格快照（分）：之后改价不影响本单
    status           VARCHAR(20) NOT NULL,         -- CREATED/PAID/CANCELLED_TIMEOUT/CANCELLED_USER/REFUNDED/REDEEMED/REVIEWED
    expire_at        TIMESTAMPTZ NOT NULL,         -- CREATED 的死线（ZSET score 同款值）
    idempotency_key  VARCHAR(64),                  -- 幂等键：唯一索引兜底
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_idem   ON orders(idempotency_key);  -- 幂等防线（NULL 不受约束，正好）
CREATE INDEX IF NOT EXISTS idx_orders_user   ON orders(user_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_expire ON orders(expire_at, status);      -- 兜底扫表专用

-- ===== 内容五表 =====

CREATE TABLE IF NOT EXISTS reviews (
    id          BIGSERIAL PRIMARY KEY,
    order_id    BIGINT      NOT NULL,
    shop_id     BIGINT      NOT NULL,
    user_id     BIGINT      NOT NULL,
    scores_json JSONB       NOT NULL,               -- 多维分数 {taste,wait,env}（jsonb：维度是产品决策会变）
    content     TEXT        NOT NULL,
    images      TEXT,                               -- MinIO key 逗号分隔（MVP 简化；图片功能再升数组）
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_reviews_order ON reviews(order_id);  -- 反刷评第三道闸：一单只能评一次
CREATE INDEX IF NOT EXISTS idx_reviews_shop ON reviews(shop_id);

CREATE TABLE IF NOT EXISTS review_replies (
    id          BIGSERIAL PRIMARY KEY,
    review_id   BIGINT      NOT NULL,
    user_id     BIGINT      NOT NULL,
    content     TEXT        NOT NULL,
    is_merchant BOOLEAN     NOT NULL DEFAULT FALSE, -- 服务端判定写入，永不采信请求体
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_replies_review ON review_replies(review_id);

CREATE TABLE IF NOT EXISTS posts (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL,
    shop_id     BIGINT,                             -- 可空：纯分享不关联店
    content     TEXT        NOT NULL,
    images      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at);

CREATE TABLE IF NOT EXISTS likes (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL,
    target_type VARCHAR(10) NOT NULL,               -- POST / REVIEW / SHOP（画像原料）
    target_id   BIGINT      NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_likes UNIQUE (user_id, target_type, target_id)  -- 防重复点赞
);

CREATE TABLE IF NOT EXISTS impressions (
    id       BIGSERIAL PRIMARY KEY,
    user_id  BIGINT,                                 -- 可空（未登录）
    shop_id  BIGINT      NOT NULL,
    scene    VARCHAR(10) NOT NULL,                   -- nearby / hot / new
    position INT         NOT NULL,                   -- 出现在第几位（保新压热与归因的证据）
    ts       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_impressions_user ON impressions(user_id, ts);  -- 商家归因用

-- ===== 画像与 Agent 轨迹 =====

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id        BIGINT PRIMARY KEY,
    tags_json      JSONB,                            -- 偏好标签（"吃辣党"/"经济档"…）
    avg_price      INT,                              -- 历史客单价（分）；NULL=无订单（冷启动）
    top_categories JSONB,                            -- 偏好品类 top2
    refreshed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_traces (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL,
    skill       VARCHAR(20) NOT NULL,                -- recommend / review-draft / analyze-*
    input       JSONB,                               -- 用户输入快照
    tools_json  JSONB,                               -- 调了哪些 /internal、LLM 花费
    output      JSONB,                               -- 最终输出
    latency_ms  INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_traces_user ON agent_traces(user_id, created_at);  -- 评测捞取
