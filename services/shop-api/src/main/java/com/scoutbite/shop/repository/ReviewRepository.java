package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.Review;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

/**
 * 评价仓库：order_id 唯一索引的反查（幂等：撞索引后查已有评价）。
 */
public interface ReviewRepository extends JpaRepository<Review, Long> {

    /** 幂等查：该订单是否已评（发布前预检 + 撞索引后取回） */
    Optional<Review> findByOrderId(Long orderId);

    /** 店页评价列表（Agent 证据 / 观点聚类的数据源） */
    List<Review> findByShopIdOrderByIdDesc(Long shopId);

    /** 店的评价数（推流 quality 因子） */
    long countByShopId(Long shopId);
}
