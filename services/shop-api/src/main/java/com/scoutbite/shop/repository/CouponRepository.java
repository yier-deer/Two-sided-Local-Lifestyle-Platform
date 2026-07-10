package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.Coupon;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

/**
 * 券模板仓库：模板只读不更新（余量在 Redis）。
 */
public interface CouponRepository extends JpaRepository<Coupon, Long> {

    /** 店铺的可用券列表（店页展示） */
    List<Coupon> findByShopIdAndEndAtAfter(Long shopId, java.time.Instant now);
}
