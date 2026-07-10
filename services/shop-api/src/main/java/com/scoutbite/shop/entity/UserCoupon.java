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
 * 用户持券：状态机 UNUSED → FROZEN（下单冻结）→ USED（支付核销）；
 * FROZEN → UNUSED（关单/退单释放）。
 * 所有状态迁移都走 Repository 的 CAS（带前置条件的 UPDATE）。
 */
@Entity
@Table(name = "user_coupons")
public class UserCoupon {

    public static final String UNUSED = "UNUSED";
    public static final String FROZEN = "FROZEN";
    public static final String USED = "USED";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "coupon_id", nullable = false)
    private Long couponId;

    @Column(nullable = false, length = 10)
    private String status = UNUSED;

    @Column(name = "order_id")
    private Long orderId;       // 冻结时关联

    @Column(name = "created_at")
    private Instant createdAt;

    @PrePersist
    void onCreate() { if (createdAt == null) createdAt = Instant.now(); }

    public Long getId() { return id; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public Long getCouponId() { return couponId; }
    public void setCouponId(Long couponId) { this.couponId = couponId; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Long getOrderId() { return orderId; }
    public void setOrderId(Long orderId) { this.orderId = orderId; }
    public Instant getCreatedAt() { return createdAt; }
}
