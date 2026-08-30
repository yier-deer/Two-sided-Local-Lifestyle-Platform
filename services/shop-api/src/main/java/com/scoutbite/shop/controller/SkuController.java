package com.scoutbite.shop.controller;

import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.Sku;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.repository.SkuRepository;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.transaction.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Sku 分组（变真）：商家上架/管理套餐，店页查套餐。
 * 角色铁律：MERCHANT 只能操作自己名下店铺的 SKU。
 */
@RestController
@RequestMapping("/api/merchant/skus")
@Tag(name = "Sku", description = "商家上架与管理套餐")
public class SkuController {

    private final SkuRepository skuRepo;
    private final ShopRepository shopRepo;

    public SkuController(SkuRepository skuRepo, ShopRepository shopRepo) {
        this.skuRepo = skuRepo;
        this.shopRepo = shopRepo;
    }

    /** 上架套餐：校验店铺归属 + 价格为正整数分 */
    @Operation(summary = "上架套餐（价格用分）")
    @PostMapping
    public ApiResponse<?> create(@RequestBody Map<String, Object> body, HttpServletRequest request) {
        var identity = Identity.of(request);
        if (identity.userId() == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        if (!"MERCHANT".equals(identity.role())) return ApiResponse.fail(ErrorCode.FORBIDDEN, "只有商家可以上架套餐");

        Long shopId = toLong(body.get("shopId"));
        String title = (String) body.get("title");
        Integer price = toInt(body.get("price"));
        Integer stock = toInt(body.get("stock"));
        if (shopId == null || title == null || price == null || stock == null) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "shopId/title/price/stock 必填");
        }
        if (price <= 0 || price > 10_000_000) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "price 必须是 1~1000万分 之间的整数");
        }

        // 店铺归属校验：只能给自己的店上架
        var shop = shopRepo.findById(shopId).orElse(null);
        if (shop == null || !shop.getOwnerId().equals(identity.userId())) {
            return ApiResponse.fail(ErrorCode.FORBIDDEN, "只能给自己的店铺上架");
        }

        Sku s = new Sku();
        s.setShopId(shopId);
        s.setTitle(title);
        s.setPrice(price);
        s.setStock(stock);
        s.setSales(0);
        s.setOnSale(true);
        skuRepo.save(s);
        return ApiResponse.ok(toDto(s));
    }

    /** 改库存 / 上下架 / 改价 */
    @Operation(summary = "改库存/上下架/改价")
    @PatchMapping("/{id}")
    @Transactional
    public ApiResponse<?> update(@PathVariable Long id,
                                 @RequestBody Map<String, Object> body,
                                 HttpServletRequest request) {
        var identity = Identity.of(request);
        Sku s = skuRepo.findById(id).orElse(null);
        if (s == null) return ApiResponse.fail(ErrorCode.PARAM_ERROR, "套餐不存在");
        // 归属校验：通过店铺间接校验
        var shop = shopRepo.findById(s.getShopId()).orElse(null);
        if (shop == null || !shop.getOwnerId().equals(identity.userId())) {
            return ApiResponse.fail(ErrorCode.FORBIDDEN, "只能管理自己的套餐");
        }
        if (body.containsKey("title")) s.setTitle((String) body.get("title"));
        Integer price = toInt(body.get("price"));
        if (price != null) s.setPrice(price);
        Integer stock = toInt(body.get("stock"));
        if (stock != null) s.setStock(stock);
        if (body.containsKey("onSale")) s.setOnSale((Boolean) body.get("onSale"));
        skuRepo.save(s);
        return ApiResponse.ok(toDto(s));
    }

    private Map<String, Object> toDto(Sku s) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", s.getId());
        m.put("shopId", s.getShopId());
        m.put("title", s.getTitle());
        m.put("price", s.getPrice());           // 分
        m.put("stock", s.getStock());
        m.put("sales", s.getSales());
        m.put("onSale", s.isOnSale());
        return m;
    }

    private Long toLong(Object o) { return o instanceof Number n ? n.longValue() : null; }
    private Integer toInt(Object o) { return o instanceof Number n ? n.intValue() : null; }

    /** 身份小助手（JwtFilter 塞进 request 的 attribute） */
    record Identity(Long userId, String role) {
        static Identity of(HttpServletRequest request) {
            return new Identity((Long) request.getAttribute("userId"),
                    (String) request.getAttribute("role"));
        }
    }
}
