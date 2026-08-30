package com.scoutbite.shop.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

import java.time.Instant;

/**
 * 点赞实体：联合唯一 (user_id, target_type, target_id) 防重复点赞。
 * 画像（user_profiles.top_categories）的原料。
 */
@Entity
@Table(name = "likes", uniqueConstraints = @UniqueConstraint(
        name = "uq_likes", columnNames = {"user_id", "target_type", "target_id"}))
public class Like {

    public static final String TARGET_POST = "POST";
    public static final String TARGET_REVIEW = "REVIEW";
    public static final String TARGET_SHOP = "SHOP";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "target_type", nullable = false, length = 10)
    private String targetType;

    @Column(name = "target_id", nullable = false)
    private Long targetId;

    @Column(name = "created_at")
    private Instant createdAt;

    @PrePersist
    void onCreate() { if (createdAt == null) createdAt = Instant.now(); }

    public Long getId() { return id; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public String getTargetType() { return targetType; }
    public void setTargetType(String targetType) { this.targetType = targetType; }
    public Long getTargetId() { return targetId; }
    public void setTargetId(Long targetId) { this.targetId = targetId; }
    public Instant getCreatedAt() { return createdAt; }
}
