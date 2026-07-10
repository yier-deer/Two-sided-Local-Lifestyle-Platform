package com.scoutbite.shop.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.Instant;

/**
 * 用户画像（）：离线刷新（启动时重算），在线只读——推荐 Agent 的个性化原料。
 * avgPrice 为 null 表示无订单（新用户冷启动：只信本轮约束，不瞎猜）。
 */
@Entity
@Table(name = "user_profiles")
public class UserProfile {

    @Id
    @Column(name = "user_id")
    private Long userId;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "tags_json", columnDefinition = "jsonb")
    private String tagsJson;

    @Column(name = "avg_price")
    private Integer avgPrice;      // 分；null = 无订单

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "top_categories", columnDefinition = "jsonb")
    private String topCategories;  // JSON 数组字符串，如 ["HOTPOT","COFFEE"]

    @Column(name = "refreshed_at")
    private Instant refreshedAt;

    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public String getTagsJson() { return tagsJson; }
    public void setTagsJson(String tagsJson) { this.tagsJson = tagsJson; }
    public Integer getAvgPrice() { return avgPrice; }
    public void setAvgPrice(Integer avgPrice) { this.avgPrice = avgPrice; }
    public String getTopCategories() { return topCategories; }
    public void setTopCategories(String topCategories) { this.topCategories = topCategories; }
    public Instant getRefreshedAt() { return refreshedAt; }
    public void setRefreshedAt(Instant refreshedAt) { this.refreshedAt = refreshedAt; }
}
