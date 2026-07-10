package com.scoutbite.shop.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.Instant;

/**
 * 评价实体：锚定已核销订单（order_id 唯一索引 = 一单一评，反刷评第三道闸）。
 * scoresJson 存多维分数（如 {"taste":5,"wait":3,"env":4}）——jsonb 因为维度是产品决策会变。
 */
@Entity
@Table(name = "reviews")
public class Review {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "order_id", nullable = false, unique = true)
    private Long orderId;

    @Column(name = "shop_id", nullable = false)
    private Long shopId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    /** 多维分数 JSON 字符串（Hibernate 6 JSON 映射 ↔ PG jsonb） */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "scores_json", nullable = false, columnDefinition = "jsonb")
    private String scoresJson;

    @Column(nullable = false, columnDefinition = "text")
    private String content;

    /** MinIO key 逗号分隔（MVP 简化） */
    @Column(columnDefinition = "text")
    private String images;

    @Column(name = "created_at")
    private Instant createdAt;

    @PrePersist
    void onCreate() { if (createdAt == null) createdAt = Instant.now(); }

    public Long getId() { return id; }
    public Long getOrderId() { return orderId; }
    public void setOrderId(Long orderId) { this.orderId = orderId; }
    public Long getShopId() { return shopId; }
    public void setShopId(Long shopId) { this.shopId = shopId; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public String getScoresJson() { return scoresJson; }
    public void setScoresJson(String scoresJson) { this.scoresJson = scoresJson; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public String getImages() { return images; }
    public void setImages(String images) { this.images = images; }
    public Instant getCreatedAt() { return createdAt; }
}
