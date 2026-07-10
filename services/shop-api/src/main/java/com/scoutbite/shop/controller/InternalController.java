package com.scoutbite.shop.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.entity.Coupon;
import com.scoutbite.shop.entity.Order;
import com.scoutbite.shop.entity.Review;
import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.entity.Sku;
import com.scoutbite.shop.entity.UserProfile;
import com.scoutbite.shop.repository.CouponRepository;
import com.scoutbite.shop.repository.OrderRepository;
import com.scoutbite.shop.repository.ReviewRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.repository.SkuRepository;
import com.scoutbite.shop.repository.UserProfileRepository;
import com.scoutbite.shop.service.GeoService;
import com.scoutbite.shop.service.MerchantAnalyticsService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Internal 分组（变真）：Agent 专用只读瘦事实出口。
 *
 * 三条铁律的代码化：
 *  1. 字段刻意裁剪——只给模型该看的（瘦事实），敏感字段（手机号/ownerId/哈希）永不出现
 *  2. status=approved 在 search 的 SQL 强制——未审核店绝不可能进 Agent 视野
 *  3. evidenceId 贯穿——模型生成的每条理由必须引用它（护栏校验的锚点）
 *
 * 门前有 InternalTokenFilter（X-Internal-Token）：人类走 JWT 门，机器走服务门。
 */
@RestController
@RequestMapping("/internal")
@Tag(name = "Internal", description = "Agent 专用只读瘦事实（X-Internal-Token 校验）")
public class InternalController {

    private final UserProfileRepository profileRepo;
    private final ShopRepository shopRepo;
    private final SkuRepository skuRepo;
    private final CouponRepository couponRepo;
    private final ReviewRepository reviewRepo;
    private final OrderRepository orderRepo;
    private final GeoService geoService;
    private final MerchantAnalyticsService analytics;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public InternalController(UserProfileRepository profileRepo,
                              ShopRepository shopRepo,
                              SkuRepository skuRepo,
                              CouponRepository couponRepo,
                              ReviewRepository reviewRepo,
                              OrderRepository orderRepo,
                              GeoService geoService,
                              MerchantAnalyticsService analytics) {
        this.profileRepo = profileRepo;
        this.shopRepo = shopRepo;
        this.skuRepo = skuRepo;
        this.couponRepo = couponRepo;
        this.reviewRepo = reviewRepo;
        this.orderRepo = orderRepo;
        this.geoService = geoService;
        this.analytics = analytics;
    }

    /** 用户画像：tags / avgPrice / topCategories（新用户全空 = 冷启动标记） */
    @Operation(summary = "用户画像（给推荐用）")
    @GetMapping("/users/{id}/profile")
    public ApiResponse<?> userProfile(@PathVariable Long id) {
        UserProfile p = profileRepo.findById(id).orElse(null);
        Map<String, Object> m = new LinkedHashMap<>();
        if (p == null) {
            // 冷启动：无画像不瞎猜——Agent 只信本轮约束
            m.put("coldStart", true);
            m.put("tags", List.of());
            m.put("avgPrice", null);
            m.put("topCategories", List.of());
        } else {
            m.put("coldStart", false);
            m.put("tags", parseJson(p.getTagsJson(), List.of()));
            m.put("avgPrice", p.getAvgPrice());
            m.put("topCategories", parseJson(p.getTopCategories(), List.of()));
        }
        return ApiResponse.ok(m);
    }

    /**
     * 硬过滤检索：复用 GeoService.nearby——位置同源性
     * （Agent 的"附近"与用户地图的"附近"来自同一个实现，推荐和列表永远对得上）。
     */
    @Operation(summary = "硬过滤检索（approved 强制，带距离）")
    @GetMapping("/shops/search")
    public ApiResponse<?> shopSearch(@RequestParam(required = false) Double lat,
                                     @RequestParam(required = false) Double lng,
                                     @RequestParam(defaultValue = "5000") int radius,
                                     @RequestParam(required = false) String category,
                                     @RequestParam(defaultValue = "12") int limit) {
        if (lat == null || lng == null) {
            return ApiResponse.ok(List.of());   // 无位置：Agent 应先澄清，不给候选
        }
        List<Map<String, Object>> nearby = geoService.nearby(lat, lng,
                Math.min(radius, 50000), category);
        if (nearby.size() > limit) nearby = nearby.subList(0, limit);   // 8~12 家，不是全世界
        return ApiResponse.ok(nearby);
    }

    /**
     * 店铺证据：评分聚合 / 销量 / 券 / 正评3 + 差评3（好评差评都要——只喂好评缺点栏就会编套话）。
     * 每条评论带 evidenceId：生成层的引用锚点，护栏按它校验。
     */
    @Operation(summary = "店铺证据（评分/销量/券/正负评，带 evidenceId）")
    @GetMapping("/shops/{id}/evidence")
    public ApiResponse<?> shopEvidence(@PathVariable Long id) {
        Shop s = shopRepo.findById(id).orElse(null);
        if (s == null || !"approved".equals(s.getStatus())) {
            return ApiResponse.ok(Map.of("exists", false));
        }

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("shopId", s.getId());
        m.put("name", s.getName());
        m.put("category", s.getCategory());

        // 销量（SKU 求和）与最低价
        List<Sku> skus = skuRepo.findByShopIdOrderById(id).stream().filter(Sku::isOnSale).toList();
        m.put("sales", skus.stream().mapToLong(Sku::getSales).sum());
        m.put("skuTitles", skus.stream().map(Sku::getTitle).limit(3).toList());
        m.put("minPrice", skus.stream().mapToInt(Sku::getPrice).min().orElse(0));

        // 评分聚合（均分 + 条数）
        List<Review> reviews = reviewRepo.findByShopIdOrderByIdDesc(id);
        double sum = 0;
        int n = 0;
        for (Review r : reviews) {
            Double avg = avgScore(r.getScoresJson());
            if (avg != null) { sum += avg; n++; }
        }
        m.put("rating", n == 0 ? null : Math.round(sum / n * 10) / 10.0);
        m.put("reviewCount", n);

        // 券（在售）
        Coupon c = couponRepo.findByShopIdAndEndAtAfter(id, Instant.now())
                .stream().findFirst().orElse(null);
        m.put("coupon", c == null ? null : Map.of(
                "title", c.getTitle(), "threshold", c.getThreshold(), "amount", c.getAmount()));

        // 正评 3 + 差评 3（按 taste/wait 均分分档；带 evidenceId）
        List<Map<String, Object>> pos = new ArrayList<>();
        List<Map<String, Object>> neg = new ArrayList<>();
        for (Review r : reviews) {
            Double avg = avgScore(r.getScoresJson());
            if (avg == null) continue;
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("evidenceId", "ev-" + s.getId() + "-" + r.getId());
            item.put("score", Math.round(avg * 10) / 10.0);
            item.put("text", r.getContent());
            if (avg >= 3.5) { if (pos.size() < 3) pos.add(item); }
            else { if (neg.size() < 3) neg.add(item); }
            if (pos.size() >= 3 && neg.size() >= 3) break;
        }
        m.put("positiveReviews", pos);
        m.put("negativeReviews", neg);
        return ApiResponse.ok(m);
    }

    // ==================== 评价锚点 + 商家三件套 ====================

    /**
     * 订单事实（评价锚点）：belongToUser 由显式传入的 userId 比对（服务间信任，Python 传值）。
     * canReview = 归属 + REDEEMED + 未评过——评价助手的唯一准入判断。
     */
    @Operation(summary = "订单事实（评价草稿锚点）")
    @GetMapping("/orders/{id}/facts")
    public ApiResponse<?> orderFacts(@PathVariable Long id,
                                     @RequestParam(required = false) Long userId) {
        Order o = orderRepo.findById(id).orElse(null);
        if (o == null) return ApiResponse.ok(Map.of("exists", false));
        boolean belong = userId != null && userId.equals(o.getUserId());
        boolean canReview = belong && Order.REDEEMED.equals(o.getStatus())
                && reviewRepo.findByOrderId(id).isEmpty();
        Shop shop = shopRepo.findById(o.getShopId()).orElse(null);
        Sku sku = skuRepo.findById(o.getSkuId()).orElse(null);

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("exists", true);
        m.put("belongToUser", belong);
        m.put("status", o.getStatus());
        m.put("canReview", canReview);
        m.put("shopId", o.getShopId());
        m.put("shopName", shop == null ? null : shop.getName());
        m.put("skuTitle", sku == null ? null : sku.getTitle());
        m.put("priceYuan", o.getPriceSnapshot() / 100.0);   // 给模型看元，不给分
        m.put("orderedAt", o.getCreatedAt().toString());
        return ApiResponse.ok(m);
    }

    /** 经营指标：新客/复购/券占比/曝光/评分（归因的数字基础） */
    @Operation(summary = "商家经营指标（新客/复购/券/曝光）")
    @GetMapping("/merchant/{shopId}/metrics")
    public ApiResponse<?> merchantMetrics(@PathVariable Long shopId) {
        return ApiResponse.ok(analytics.metrics(shopId));
    }

    /** 评论观点聚类（关键词分桶，带原评引用） */
    @Operation(summary = "评论观点聚类（每桶带原评×2）")
    @GetMapping("/merchant/{shopId}/review-clusters")
    public ApiResponse<?> reviewClusters(@PathVariable Long shopId) {
        return ApiResponse.ok(analytics.clusters(shopId));
    }

    /** 竞品快照：同品类 3km，只用公开信息 */
    @Operation(summary = "同半径同品类竞品（公开信息）")
    @GetMapping("/merchant/{shopId}/competitors")
    public ApiResponse<?> competitors(@PathVariable Long shopId) {
        return ApiResponse.ok(analytics.competitors(shopId));
    }

    // ==================== 私有辅助 ====================

    /** 解析 scores_json 求均分 */
    private Double avgScore(String scoresJson) {
        try {
            Map<?, ?> m = objectMapper.readValue(scoresJson, Map.class);
            if (m.isEmpty()) return null;
            double sum = 0;
            for (Object v : m.values()) sum += ((Number) v).doubleValue();
            return sum / m.size();
        } catch (Exception e) {
            return null;
        }
    }

    private Object parseJson(String json, Object fallback) {
        try {
            return objectMapper.readValue(json, Object.class);
        } catch (Exception e) {
            return fallback;
        }
    }
}
