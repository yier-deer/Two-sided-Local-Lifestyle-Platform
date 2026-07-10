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
 * 曝光日志：append-only（只插不改）。两个消费方：
 *  ① 已读降权（同店反复出现应降权）
 *  ② 商家 Agent 归因（新客从哪个曝光位来）
 */
@Entity
@Table(name = "impressions")
public class Impression {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id")
    private Long userId;      // 可空（未登录游客）

    @Column(name = "shop_id", nullable = false)
    private Long shopId;

    @Column(nullable = false, length = 10)
    private String scene;     // nearby / hot / new

    @Column(nullable = false)
    private int position;

    @Column(name = "ts")
    private Instant ts;

    @PrePersist
    void onCreate() { if (ts == null) ts = Instant.now(); }

    public Long getId() { return id; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public Long getShopId() { return shopId; }
    public void setShopId(Long shopId) { this.shopId = shopId; }
    public String getScene() { return scene; }
    public void setScene(String scene) { this.scene = scene; }
    public int getPosition() { return position; }
    public void setPosition(int position) { this.position = position; }
    public Instant getTs() { return ts; }
}
