package com.scoutbite.shop.controller;

import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.service.OrderService;
import com.scoutbite.shop.service.ReviewService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * Review 分组（变真）：发布评价（绑 REDEEMED 订单）与回复（is_merchant 服务端判定）。
 * 铁律（ADR-009/011）：order_id 唯一，只有核销过的订单能评价——反刷评、反假评。
 */
@RestController
@Tag(name = "Review", description = "发布评价（绑已核销订单）与商家回复")
public class ReviewController {

    private final ReviewService reviewService;

    public ReviewController(ReviewService reviewService) {
        this.reviewService = reviewService;
    }

    /**
     * 发布评价：body { orderId, scores: {taste,wait,env}, content, imageKeys? }。
     * 四道校验：归属 → REDEEMED → 分数/正文格式 → order_id 唯一索引。
     */
    @Operation(summary = "发布评价（只有已核销订单可评，一单一评）")
    @PostMapping("/api/reviews")
    public ApiResponse<?> create(@RequestBody Map<String, Object> body, HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");

        Long orderId = toLong(body.get("orderId"));
        if (orderId == null) return ApiResponse.fail(ErrorCode.PARAM_ERROR, "orderId 必填");

        @SuppressWarnings("unchecked")
        Map<String, Integer> scores = (Map<String, Integer>) body.get("scores");
        String content = (String) body.get("content");
        String imageKeys = body.get("imageKeys") instanceof List<?> l ? String.join(",", l.stream().map(String::valueOf).toList()) : null;

        try {
            return ApiResponse.ok(reviewService.create(userId, orderId, scores, content, imageKeys));
        } catch (OrderService.BizException e) {
            return ApiResponse.fail(e.code, e.getMessage());
        }
    }

    /**
     * 回复评价：is_merchant 由服务端判定（token role + 店铺归属），
     * 请求体里的任何身份字段不采信。普通用户也能回，只是没商家标。
     */
    @Operation(summary = "回复评价（商家回复自动打标）")
    @PostMapping("/api/reviews/{id}/replies")
    public ApiResponse<?> reply(@PathVariable Long id,
                                @RequestBody Map<String, String> body,
                                HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        String role = (String) request.getAttribute("role");

        try {
            return ApiResponse.ok(reviewService.reply(userId, role, id, body.get("content")));
        } catch (OrderService.BizException e) {
            return ApiResponse.fail(e.code, e.getMessage());
        }
    }

    /** 店页评价列表（公开，/api/shops/** 白名单内）：带回复（含商家标） */
    @Operation(summary = "店铺评价列表（公开，含商家回复）")
    @GetMapping("/api/shops/{shopId}/reviews")
    public ApiResponse<?> listByShop(@PathVariable Long shopId) {
        return ApiResponse.ok(reviewService.listByShop(shopId));
    }

    private Long toLong(Object o) { return o instanceof Number n ? n.longValue() : null; }
}
