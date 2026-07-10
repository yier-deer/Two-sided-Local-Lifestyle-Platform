package com.scoutbite.shop.controller;

import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.Order;
import com.scoutbite.shop.repository.OrderRepository;
import com.scoutbite.shop.service.OrderService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Order 分组（变真）：交易主链路。
 * 下单（幂等键）/ 支付 / 取消 / 退单 / 我的订单。
 * 状态机：CREATED → PAID → REDEEMED → REVIEWED；CANCELLED_TIMEOUT / CANCELLED_USER / REFUNDED。
 */
@RestController
@Tag(name = "Order", description = "下单支付与订单状态机（CAS 仲裁）")
public class OrderController {

    private final OrderRepository orderRepo;
    private final OrderService orderService;

    public OrderController(OrderRepository orderRepo, OrderService orderService) {
        this.orderRepo = orderRepo;
        this.orderService = orderService;
    }

    /**
     * 下单：Header 必带 Idempotency-Key（幂等）。
     * body: { skuId, userCouponId? }——userCouponId 是「我的券」里的那条记录 ID。
     */
    @Operation(summary = "下单（Header 带 Idempotency-Key，可选用券）")
    @PostMapping("/api/orders")
    public ApiResponse<?> create(@RequestHeader(value = "Idempotency-Key", required = false) String idemKey,
                                 @RequestBody Map<String, Object> body,
                                 HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        if (idemKey == null || idemKey.isBlank()) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "缺少 Idempotency-Key 头（幂等键）");
        }
        Long skuId = toLong(body.get("skuId"));
        Long userCouponId = toLong(body.get("userCouponId"));
        if (skuId == null) return ApiResponse.fail(ErrorCode.PARAM_ERROR, "skuId 必填");

        try {
            Order o = orderService.create(userId, skuId, userCouponId, idemKey);
            return ApiResponse.ok(toDto(o));
        } catch (OrderService.BizException e) {
            return ApiResponse.fail(e.code, e.getMessage());
        }
    }

    /** 模拟支付：CAS CREATED→PAID（与关单赛跑，谁先成功谁赢）；重复支付幂等返回成功 */
    @Operation(summary = "模拟支付（CAS 仲裁，幂等）")
    @PostMapping("/api/orders/{id}/pay")
    public ApiResponse<?> pay(@PathVariable Long id, HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        try {
            Order o = orderService.pay(id, userId);
            return ApiResponse.ok(toDto(o));
        } catch (OrderService.BizException e) {
            return ApiResponse.fail(e.code, e.getMessage());
        }
    }

    /** 核销：PAID→REDEEMED，销量+1；评价的唯一入口（ADR-011 规则2） */
    @Operation(summary = "核销（到店消费确认，销量+1，评价前提）")
    @PostMapping("/api/orders/{id}/redeem")
    public ApiResponse<?> redeem(@PathVariable Long id, HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        try {
            Order o = orderService.redeem(id, userId);
            return ApiResponse.ok(toDto(o));
        } catch (OrderService.BizException e) {
            return ApiResponse.fail(e.code, e.getMessage());
        }
    }

    /** 用户取消（未支付）：CREATED→CANCELLED_USER，回补库存与券 */
    @Operation(summary = "用户取消（未支付单）")
    @PostMapping("/api/orders/{id}/cancel")
    public ApiResponse<?> cancel(@PathVariable Long id, HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        try {
            Order o = orderService.cancel(id, userId);
            return ApiResponse.ok(toDto(o));
        } catch (OrderService.BizException e) {
            return ApiResponse.fail(e.code, e.getMessage());
        }
    }

    /** 退单（已支付未核销）：PAID→REFUNDED，回补库存与券 */
    @Operation(summary = "退单（未核销可退，ADR-011）")
    @PostMapping("/api/orders/{id}/refund")
    public ApiResponse<?> refund(@PathVariable Long id, HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        try {
            Order o = orderService.refund(id, userId);
            return ApiResponse.ok(toDto(o));
        } catch (OrderService.BizException e) {
            return ApiResponse.fail(e.code, e.getMessage());
        }
    }

    /** 我的订单（可按状态过滤；unreviewed=true 给 评价助手） */
    @Operation(summary = "我的订单（status 过滤 / unreviewed 候选）")
    @GetMapping("/api/orders")
    public ApiResponse<?> list(@RequestParam(required = false) String status,
                               @RequestParam(required = false, defaultValue = "false") boolean unreviewed,
                               HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        List<Order> list = (status == null || status.isBlank())
                ? orderRepo.findByUserIdOrderByIdDesc(userId)
                : orderRepo.findByUserIdAndStatusOrderByIdDesc(userId, status);
        return ApiResponse.ok(list.stream().map(this::toDto).toList());
    }

    private Map<String, Object> toDto(Order o) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", o.getId());
        m.put("userId", o.getUserId());
        m.put("shopId", o.getShopId());
        m.put("skuId", o.getSkuId());
        m.put("couponId", o.getCouponId());
        m.put("priceSnapshot", o.getPriceSnapshot());   // 分
        m.put("status", o.getStatus());
        m.put("expireAt", o.getExpireAt().toString());
        return m;
    }

    private Long toLong(Object o) { return o instanceof Number n ? n.longValue() : null; }
}
