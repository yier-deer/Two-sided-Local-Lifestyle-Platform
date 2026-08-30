package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.Order;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * 订单仓库：状态机迁移全部 CAS——支付与关单赛跑的仲裁法庭。
 */
public interface OrderRepository extends JpaRepository<Order, Long> {

    /** 幂等查：按 key 找已存在的单（命中直接返回原单） */
    Optional<Order> findByIdempotencyKey(String idempotencyKey);

    /** 我的订单（可按状态过滤；null = 全部） */
    List<Order> findByUserIdOrderByIdDesc(Long userId);
    List<Order> findByUserIdAndStatusOrderByIdDesc(Long userId, String status);

    // ==================== 状态机 CAS 迁移（带前置条件） ====================

    /** 支付：CREATED → PAID。与关单赛跑时谁先成功谁赢；返回 0 = 输了 */
    @Modifying
    @Query("UPDATE Order o SET o.status = 'PAID' " +
           "WHERE o.id = :id AND o.userId = :userId AND o.status = 'CREATED'")
    int payCas(@Param("id") Long id, @Param("userId") Long userId);

    /** 用户取消（未支付）：CREATED → CANCELLED_USER */
    @Modifying
    @Query("UPDATE Order o SET o.status = 'CANCELLED_USER' " +
           "WHERE o.id = :id AND o.userId = :userId AND o.status = 'CREATED'")
    int cancelCas(@Param("id") Long id, @Param("userId") Long userId);

    /** 退单（已支付未核销）：PAID → REFUNDED */
    @Modifying
    @Query("UPDATE Order o SET o.status = 'REFUNDED' " +
           "WHERE o.id = :id AND o.userId = :userId AND o.status = 'PAID'")
    int refundCas(@Param("id") Long id, @Param("userId") Long userId);

    /** 核销：PAID → REDEEMED（评价的唯一入口，ADR-011 规则2） */
    @Modifying
    @Query("UPDATE Order o SET o.status = 'REDEEMED' " +
           "WHERE o.id = :id AND o.userId = :userId AND o.status = 'PAID'")
    int redeemCas(@Param("id") Long id, @Param("userId") Long userId);

    /** 超时关单：CREATED → CANCELLED_TIMEOUT。只认 CREATED——已支付的单关不掉 */
    @Modifying
    @Query("UPDATE Order o SET o.status = 'CANCELLED_TIMEOUT' " +
           "WHERE o.id = :id AND o.status = 'CREATED'")
    int timeoutCloseCas(@Param("id") Long id);

    // ==================== 兜底扫表 ====================

    /** 找出已过期但仍是 CREATED 的单（ZSET 丢消息时的第二道防线） */
    @Query("SELECT o.id FROM Order o WHERE o.expireAt < :now AND o.status = 'CREATED'")
    List<Long> findExpiredCreated(@Param("now") Instant now);
}
