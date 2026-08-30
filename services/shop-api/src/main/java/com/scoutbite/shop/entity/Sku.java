package com.scoutbite.shop.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;

import java.time.Instant;

/**
 * SKU 实体：套餐（价格一律用分）。
 * stock 扣减走 Repository 的 CAS 原子 UPDATE（防超卖）；sales 在 核销时 +1。
 */
@Entity
@Table(name = "skus")
public class Sku {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "shop_id", nullable = false)
    private Long shopId;

    @Column(nullable = false, length = 100)
    private String title;

    @Column(nullable = false)
    private int price;          // 分

    @Column(nullable = false)
    private int stock;

    @Column(nullable = false)
    private int sales;

    @Column(name = "on_sale", nullable = false)
    private boolean onSale = true;

    @Column(name = "created_at")
    private Instant createdAt;

    @PrePersist
    void onCreate() { if (createdAt == null) createdAt = Instant.now(); }

    public Long getId() { return id; }
    public Long getShopId() { return shopId; }
    public void setShopId(Long shopId) { this.shopId = shopId; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public int getPrice() { return price; }
    public void setPrice(int price) { this.price = price; }
    public int getStock() { return stock; }
    public void setStock(int stock) { this.stock = stock; }
    public int getSales() { return sales; }
    public void setSales(int sales) { this.sales = sales; }
    public boolean isOnSale() { return onSale; }
    public void setOnSale(boolean onSale) { this.onSale = onSale; }
    public Instant getCreatedAt() { return createdAt; }
}
