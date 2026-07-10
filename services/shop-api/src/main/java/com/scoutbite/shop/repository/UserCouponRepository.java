package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.UserCoupon;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

/**
 * 用户持券仓库：券状态机迁移全部 CAS 化。
 */
public interface UserCouponRepository extends JpaRepository<UserCoupon, Long> {

    /** 我的券列表（可按状态过滤） */
    List<UserCoupon> findByUserIdOrderByIdDesc(Long userId);

    /** 找一张指定的 UNUSED 券（下单选券用） */
    Optional<UserCoupon> findByIdAndUserIdAndStatus(Long id, Long userId, String status);

    /**
     * 冻结（CAS）：UNUSED → FROZEN，只认自己的 UNUSED 券。
     * 返回 0 = 券不存在/不是自己的/已用过 → 40902。
     */
    @Modifying
    @Query("UPDATE UserCoupon uc SET uc.status = 'FROZEN', uc.orderId = :orderId " +
           "WHERE uc.id = :id AND uc.userId = :userId AND uc.status = 'UNUSED'")
    int freeze(@Param("id") Long id, @Param("userId") Long userId, @Param("orderId") Long orderId);

    /** 核销（CAS）：FROZEN → USED，支付成功时（同事务）。只认绑定在本单上的那张 */
    @Modifying
    @Query("UPDATE UserCoupon uc SET uc.status = 'USED' " +
           "WHERE uc.orderId = :orderId AND uc.status = 'FROZEN'")
    int use(@Param("orderId") Long orderId);

    /** 释放（CAS）：FROZEN → UNUSED，关单/退单时回补（清掉订单绑定） */
    @Modifying
    @Query("UPDATE UserCoupon uc SET uc.status = 'UNUSED', uc.orderId = NULL " +
           "WHERE uc.orderId = :orderId AND uc.status = 'FROZEN'")
    int release(@Param("orderId") Long orderId);
}
