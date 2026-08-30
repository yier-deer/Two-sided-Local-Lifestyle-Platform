package com.scoutbite.shop.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;

import java.time.Instant;

/**
 * 订单实体：ADR-011 两段式状态机（钱 / 履约）。
 * 状态迁移一律走 Repository 的 CAS——支付和关单赛跑时，谁先 UPDATE 成功谁赢。
 */
@Entity
@Table(name = "orders")
public class Order {

    public static final String CREATED = "CREATED";
    public static final String PAID = "PAID";
    public static final String CANCELLED_TIMEOUT = "CANCELLED_TIMEOUT";
    public static final String CANCELLED_USER = "CANCELLED_USER";
    public static final String REFUNDED = "REFUNDED";
    public static final String REDEEMED = "REDEEMED";
    public static final String REVIEWED = "REVIEWED";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "shop_id", nullable = false)
    private Long shopId;

    @Column(name = "sku_id", nullable = false)
    private Long skuId;

    @Column(name = "coupon_id")
    private Long couponId;     // 可空

    @Column(name = "price_snapshot", nullable = false)
    private int priceSnapshot; // 下单时价格快照，分

    @Column(nullable = false, length = 20)
    private String status = CREATED;

    @Column(name = "expire_at", nullable = false)
    private Instant expireAt;  // CREATED 的死线（ZSET score 同款值）

    @Column(name = "idempotency_key", length = 64)
    private String idempotencyKey;

    @Column(name = "created_at")
    private Instant createdAt;

    @PrePersist
    void onCreate() { if (createdAt == null) createdAt = Instant.now(); }

    public Long getId() { return id; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public Long getShopId() { return shopId; }
    public void setShopId(Long shopId) { this.shopId = shopId; }
    public Long getSkuId() { return skuId; }
    public void setSkuId(Long skuId) { this.skuId = skuId; }
    public Long getCouponId() { return couponId; }
    public void setCouponId(Long couponId) { this.couponId = couponId; }
    public int getPriceSnapshot() { return priceSnapshot; }
    public void setPriceSnapshot(int priceSnapshot) { this.priceSnapshot = priceSnapshot; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Instant getExpireAt() { return expireAt; }
    public void setExpireAt(Instant expireAt) { this.expireAt = expireAt; }
    public String getIdempotencyKey() { return idempotencyKey; }
    public void setIdempotencyKey(String idempotencyKey) { this.idempotencyKey = idempotencyKey; }
    public Instant getCreatedAt() { return createdAt; }
}
