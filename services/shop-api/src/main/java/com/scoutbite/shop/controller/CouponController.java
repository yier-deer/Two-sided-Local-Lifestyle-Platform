package com.scoutbite.shop.controller;

import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.Coupon;
import com.scoutbite.shop.entity.UserCoupon;
import com.scoutbite.shop.repository.CouponRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.repository.UserCouponRepository;
import com.scoutbite.shop.service.CouponService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Coupon 分组（变真）：商家建券（自动镜像 Redis）、用户领券（Lua 原子扣）。
 */
@RestController
@Tag(name = "Coupon", description = "建券与领券（Redis Lua 原子扣减）")
public class CouponController {

    private final CouponRepository couponRepo;
    private final UserCouponRepository userCouponRepo;
    private final ShopRepository shopRepo;
    private final CouponService couponService;

    public CouponController(CouponRepository couponRepo,
                            UserCouponRepository userCouponRepo,
                            ShopRepository shopRepo,
                            CouponService couponService) {
        this.couponRepo = couponRepo;
        this.userCouponRepo = userCouponRepo;
        this.shopRepo = shopRepo;
        this.couponService = couponService;
    }

    /** 商家建券：写 DB 模板 + 初始化 Redis 余量镜像 */
    @Operation(summary = "商家建券（自动镜像余量到 Redis）")
    @PostMapping("/api/merchant/coupons")
    public ApiResponse<?> create(@RequestBody Map<String, Object> body, HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        String role = (String) request.getAttribute("role");
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        if (!"MERCHANT".equals(role)) return ApiResponse.fail(ErrorCode.FORBIDDEN, "只有商家可以建券");

        Long shopId = toLong(body.get("shopId"));
        String title = (String) body.get("title");
        Integer threshold = toInt(body.get("threshold"));
        Integer amount = toInt(body.get("amount"));
        Integer total = toInt(body.get("total"));
        if (shopId == null || title == null || threshold == null || amount == null || total == null
                || threshold <= 0 || amount <= 0 || amount >= threshold || total <= 0) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR,
                    "shopId/title/threshold/amount/total 必填，且 0 < amount < threshold，total > 0");
        }
        var shop = shopRepo.findById(shopId).orElse(null);
        if (shop == null || !shop.getOwnerId().equals(userId)) {
            return ApiResponse.fail(ErrorCode.FORBIDDEN, "只能给自己的店铺建券");
        }

        Coupon c = new Coupon();
        c.setShopId(shopId);
        c.setTitle(title);
        c.setThreshold(threshold);
        c.setAmount(amount);
        c.setTotal(total);
        c.setPerUserLimit(1);   // MVP 固定每人一张
        c.setStartAt(Instant.now());
        c.setEndAt(Instant.now().plusSeconds(365 * 24 * 3600));   // 演示：一年有效
        couponRepo.save(c);

        // Redis 镜像初始化：券的领取余量从此刻起由 Redis 管辖
        couponService.initMirror(c.getId(), total);

        return ApiResponse.ok(toDto(c));
    }

    /** 店铺的在售券（店页公开） */
    @Operation(summary = "店铺可用券（公开）")
    @GetMapping("/api/shops/{shopId}/coupons")
    public ApiResponse<?> listByShop(@PathVariable Long shopId) {
        List<Map<String, Object>> list = couponRepo
                .findByShopIdAndEndAtAfter(shopId, Instant.now())
                .stream().map(this::toDto).toList();
        return ApiResponse.ok(list);
    }

    /** 领券：Lua 原子扣减（余量+限领两判断一步完成） */
    @Operation(summary = "领券（Lua 原子扣减，每人限一张）")
    @PostMapping("/api/coupons/{id}/claim")
    public ApiResponse<?> claim(@PathVariable Long id, HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");

        CouponService.ClaimResult r = couponService.claim(userId, id);
        if (r.coupon() == null) {
            return ApiResponse.fail(r.code(), r.message());
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("userCouponId", r.coupon().getId());
        m.put("couponId", r.coupon().getCouponId());
        m.put("status", r.coupon().getStatus());
        return ApiResponse.ok(m);
    }

    /** 我的券（我的-优惠券页） */
    @Operation(summary = "我的券（可按状态过滤）")
    @GetMapping("/api/coupons/mine")
    public ApiResponse<?> mine(HttpServletRequest request,
                               @org.springframework.web.bind.annotation.RequestParam(required = false) String status) {
        Long userId = (Long) request.getAttribute("userId");
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        List<UserCoupon> list = userCouponRepo.findByUserIdOrderByIdDesc(userId);
        if (status != null && !status.isBlank()) {
            list = list.stream().filter(c -> status.equals(c.getStatus())).toList();
        }
        return ApiResponse.ok(list.stream().map(c -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("userCouponId", c.getId());
            m.put("couponId", c.getCouponId());
            m.put("status", c.getStatus());
            m.put("orderId", c.getOrderId());
            return m;
        }).toList());
    }

    private Map<String, Object> toDto(Coupon c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", c.getId());
        m.put("shopId", c.getShopId());
        m.put("title", c.getTitle());
        m.put("threshold", c.getThreshold());
        m.put("amount", c.getAmount());
        m.put("total", c.getTotal());
        return m;
    }

    private Long toLong(Object o) { return o instanceof Number n ? n.longValue() : null; }
    private Integer toInt(Object o) { return o instanceof Number n ? n.intValue() : null; }
}
