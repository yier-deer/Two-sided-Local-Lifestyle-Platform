package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.Shop;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.List;

/**
 * 店铺仓库：含 nearby 盒粗筛（原生 SQL）与状态机 CAS 迁移。
 */
public interface ShopRepository extends JpaRepository<Shop, Long> {

    /** 商家查自己的店（含各状态，"我的小店"页面用） */
    List<Shop> findByOwnerIdOrderByIdDesc(Long ownerId);

    /**
     * nearby 第一步：方盒粗筛（bounding box）。
     * status='approved' 在这里强制——未审核店绝不能进检索（思考点的事故防线）。
     * category 为 null 时 COALESCE 放行全部品类。
     */
    @Query(value = """
            SELECT * FROM shops
            WHERE status = 'approved'
              AND category = COALESCE(:category, category)
              AND lat BETWEEN :latMin AND :latMax
              AND lng BETWEEN :lngMin AND :lngMax
            """, nativeQuery = true)
    List<Shop> findInBox(@Param("latMin") double latMin,
                         @Param("latMax") double latMax,
                         @Param("lngMin") double lngMin,
                         @Param("lngMax") double lngMax,
                         @Param("category") String category);

    /**
     * 状态机心脏：带前置条件的原子迁移（CAS 思想）。
     * 例：从 pending 迁到 approved —— WHERE status='pending' 保证"已驳回又通过"的并发鬼畜不可能发生。
     * @return 影响行数：0 表示前态不对（迁移失败）
     */
    @Modifying
    @Query("UPDATE Shop s SET s.status = :to, " +
           "s.approvedAt = CASE WHEN :to = 'approved' THEN :at ELSE s.approvedAt END " +
           "WHERE s.id = :id AND s.status = :from")
    int casUpdateStatus(@Param("id") Long id,
                        @Param("to") String to,
                        @Param("from") String from,
                        @Param("at") Instant at);
}
