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
 * Agent 轨迹（启用）：每次技能调用记输入/工具链/输出/时延。
 * 评测的原料 + 「能改、能评、能答辩」的前提。
 */
@Entity
@Table(name = "agent_traces")
public class AgentTrace {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(nullable = false, length = 20)
    private String skill;        // recommend / review-draft / analyze-ops...

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private String input;        // 用户输入快照（JSON 字符串）

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "tools_json", columnDefinition = "jsonb")
    private String toolsJson;    // 调了哪些 /internal、LLM 用量

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private String output;       // 最终输出（JSON 字符串）

    @Column(name = "latency_ms")
    private Integer latencyMs;

    @Column(name = "created_at")
    private Instant createdAt;

    @PrePersist
    void onCreate() { if (createdAt == null) createdAt = Instant.now(); }

    public Long getId() { return id; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public String getSkill() { return skill; }
    public void setSkill(String skill) { this.skill = skill; }
    public String getInput() { return input; }
    public void setInput(String input) { this.input = input; }
    public String getToolsJson() { return toolsJson; }
    public void setToolsJson(String toolsJson) { this.toolsJson = toolsJson; }
    public String getOutput() { return output; }
    public void setOutput(String output) { this.output = output; }
    public Integer getLatencyMs() { return latencyMs; }
    public void setLatencyMs(Integer latencyMs) { this.latencyMs = latencyMs; }
    public Instant getCreatedAt() { return createdAt; }
}
