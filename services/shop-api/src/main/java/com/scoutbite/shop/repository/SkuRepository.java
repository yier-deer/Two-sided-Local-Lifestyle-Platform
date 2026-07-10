package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.Sku;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

/**
 * SKU 仓库：库存的 CAS 原子扣减/回补都在这里。
 */
public interface SkuRepository extends JpaRepository<Sku, Long> {

    /** 店铺的套餐列表（店页/商家管理用） */
    List<Sku> findByShopIdOrderById(Long shopId);

    /**
     * 扣库存（CAS）：WHERE stock>0 AND on_sale 与 SET stock-1 在一条 UPDATE 里，
     * 行锁串行化并发——超卖的防线。返回 0 = 没扣到。
     */
    @Modifying
    @Query("UPDATE Sku s SET s.stock = s.stock - 1 " +
           "WHERE s.id = :id AND s.stock > 0 AND s.onSale = true")
    int tryDeductStock(@Param("id") Long id);

    /** 回补库存：状态 CAS 成功后才调用，加法无竞争不需要条件 */
    @Modifying
    @Query("UPDATE Sku s SET s.stock = s.stock + 1 WHERE s.id = :id")
    int restock(@Param("id") Long id);

    /** 核销加销量：核销成功才 +1（ADR-011 规则5：退单不计入销量，退单路径没动 sales，正好对称） */
    @Modifying
    @Query("UPDATE Sku s SET s.sales = s.sales + 1 WHERE s.id = :id")
    int incSales(@Param("id") Long skuId);
}
