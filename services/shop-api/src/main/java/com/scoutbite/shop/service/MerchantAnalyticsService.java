package com.scoutbite.shop.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.scoutbite.shop.entity.Impression;
import com.scoutbite.shop.entity.Order;
import com.scoutbite.shop.entity.Review;
import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.entity.Sku;
import com.scoutbite.shop.repository.CouponRepository;
import com.scoutbite.shop.repository.ImpressionRepository;
import com.scoutbite.shop.repository.OrderRepository;
import com.scoutbite.shop.repository.ReviewRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.repository.SkuRepository;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 商家分析数据服务（）：metrics / review-clusters / competitors 三个工具的数据出口。
 * 口径诚实原则：所有数字可回溯到库里的行；聚类是关键词分桶（MVP 简化，面试主动说）。
 */
@Service
public class MerchantAnalyticsService {

    /** 有效订单状态（付过钱的；REFUNDED/CANCELLED 不算消费） */
    private static final List<String> VALID_ORDER_STATUS = List.of("PAID", "REDEEMED", "REVIEWED");

    /** 聚类关键词桶（MVP：分桶不是语义聚类——升级路径 embedding，接口形状不变） */
    private static final Map<String, List<String>> TOPIC_KEYWORDS = new LinkedHashMap<>();
    static {
        TOPIC_KEYWORDS.put("排队等位", List.of("排队", "等位", "等了", "久等", "排队久"));
        TOPIC_KEYWORDS.put("服务态度", List.of("服务", "加水", "没人理", "态度", "热情"));
        TOPIC_KEYWORDS.put("口味品质", List.of("味道", "好吃", "难吃", "香", "汤底", "出品"));
        TOPIC_KEYWORDS.put("优惠争议", List.of("券", "优惠", "满减", "折扣", "不参与"));
        TOPIC_KEYWORDS.put("环境位置", List.of("环境", "位置", "装修", "吵", "好找"));
    }

    private final OrderRepository orderRepo;
    private final ReviewRepository reviewRepo;
    private final ImpressionRepository impressionRepo;
    private final ShopRepository shopRepo;
    private final SkuRepository skuRepo;
    private final CouponRepository couponRepo;
    private final GeoService geoService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public MerchantAnalyticsService(OrderRepository orderRepo,
                                    ReviewRepository reviewRepo,
                                    ImpressionRepository impressionRepo,
                                    ShopRepository shopRepo,
                                    SkuRepository skuRepo,
                                    CouponRepository couponRepo,
                                    GeoService geoService) {
        this.orderRepo = orderRepo;
        this.reviewRepo = reviewRepo;
        this.impressionRepo = impressionRepo;
        this.shopRepo = shopRepo;
        this.skuRepo = skuRepo;
        this.couponRepo = couponRepo;
        this.geoService = geoService;
    }

    /** 经营指标：新客（首单落在近7日）/ 复购 / 券占比 / 曝光 / 评分——商家归因的原料 */
    public Map<String, Object> metrics(Long shopId) {
        List<Order> validOrders = orderRepo.findAll().stream()
                .filter(o -> shopId.equals(o.getShopId()) && VALID_ORDER_STATUS.contains(o.getStatus()))
                .toList();

        // 新客口径：该用户【在本店的首单】落在近 7 日（不是"近7日下过单的任何人"）
        Map<Long, Instant> firstOrderAt = new HashMap<>();
        for (Order o : validOrders) {
            firstOrderAt.merge(o.getUserId(), o.getCreatedAt(), (a, b) -> a.isBefore(b) ? a : b);
        }
        Instant weekAgo = Instant.now().minus(7, ChronoUnit.DAYS);
        long newCustomers7d = firstOrderAt.values().stream().filter(t -> t.isAfter(weekAgo)).count();

        // 复购：本店有效订单 ≥2 的用户
        Map<Long, Long> freq = validOrders.stream()
                .collect(Collectors.groupingBy(Order::getUserId, Collectors.counting()));
        long repeatBuyers = freq.values().stream().filter(c -> c >= 2).count();

        // 券单占比（有效订单里用了券的）
        long couponOrders = validOrders.stream().filter(o -> o.getCouponId() != null).count();

        // 曝光（近 7 日，按 scene 分组）——impressions 表第一次被消费
        Map<String, Long> impByScene = impressionRepo.findAll().stream()
                .filter(i -> shopId.equals(i.getShopId()) && i.getTs().isAfter(weekAgo))
                .collect(Collectors.groupingBy(Impression::getScene, Collectors.counting()));

        // 评分
        List<Review> reviews = reviewRepo.findByShopIdOrderByIdDesc(shopId);
        Double avgRating = avgRating(reviews);

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("shopId", shopId);
        m.put("totalValidOrders", validOrders.size());
        m.put("totalCustomers", firstOrderAt.size());
        m.put("newCustomers7d", newCustomers7d);
        m.put("repeatBuyers", repeatBuyers);
        m.put("couponOrderShare", validOrders.isEmpty() ? null
                : Math.round(couponOrders * 1000.0 / validOrders.size()) / 10.0);   // 百分数一位小数
        m.put("impressions7d", impByScene.values().stream().mapToLong(Long::longValue).sum());
        m.put("impressions7dByScene", impByScene);
        m.put("reviewCount", reviews.size());
        m.put("avgRating", avgRating);
        m.put("windowDays", 7);
        return m;
    }

    /** 评论观点聚类（关键词分桶）：每桶 {主题, 条数, 均分, 原评引用×2}——评论诊断的原料 */
    public List<Map<String, Object>> clusters(Long shopId) {
        List<Review> reviews = reviewRepo.findByShopIdOrderByIdDesc(shopId);
        List<Map<String, Object>> result = new ArrayList<>();
        for (Map.Entry<String, List<String>> topic : TOPIC_KEYWORDS.entrySet()) {
            List<Review> hit = reviews.stream()
                    .filter(r -> topic.getValue().stream().anyMatch(k -> r.getContent().contains(k)))
                    .toList();
            if (hit.isEmpty()) continue;
            List<Map<String, Object>> samples = hit.stream().limit(2).map(r -> {
                Map<String, Object> s = new LinkedHashMap<>();
                s.put("reviewId", r.getId());
                s.put("score", avgScoreOf(r));
                s.put("text", r.getContent());
                return s;
            }).collect(Collectors.toList());
            Map<String, Object> bucket = new LinkedHashMap<>();
            bucket.put("topic", topic.getKey());
            bucket.put("count", hit.size());
            bucket.put("avgScore", Math.round(hit.stream()
                    .mapToDouble(this::avgScoreOf).average().orElse(0) * 10) / 10.0);
            bucket.put("samples", samples);
            result.add(bucket);
        }
        // 按条数降序——主要矛盾在前
        result.sort(Comparator.comparingInt(b -> -((Number) b.get("count")).intValue()));
        return result;
    }

    /** 竞品快照：同品类 approved、以本店坐标 3km 半径、只用公开信息（销量/评分/差评主题/券） */
    public List<Map<String, Object>> competitors(Long shopId) {
        Shop self = shopRepo.findById(shopId).orElse(null);
        if (self == null) return List.of();
        List<Map<String, Object>> nearby = geoService.nearby(
                self.getLat(), self.getLng(), 3000, self.getCategory());
        List<Map<String, Object>> result = new ArrayList<>();
        for (Map<String, Object> n : nearby) {
            Long cid = (Long) n.get("id");
            if (cid.equals(shopId)) continue;   // 排除自己
            if (result.size() >= 5) break;
            List<Review> cr = reviewRepo.findByShopIdOrderByIdDesc(cid);
            Map<String, Object> card = new LinkedHashMap<>();
            card.put("shopId", cid);
            card.put("name", n.get("name"));
            card.put("distanceMeters", n.get("distanceMeters"));
            card.put("rating", avgRating(cr));
            card.put("sales", skuRepo.findByShopIdOrderById(cid).stream()
                    .mapToLong(Sku::getSales).sum());
            card.put("hasCoupon", !couponRepo.findByShopIdAndEndAtAfter(cid, Instant.now()).isEmpty());
            card.put("topNegativeTopic", topNegativeTopic(cr));   // 差评主题（公开评论聚合）
            result.add(card);
        }
        return result;
    }

    // ==================== 私有辅助 ====================

    /** 竞品的头号差评主题（负分评论里命中的第一个桶——公开信息聚合） */
    private String topNegativeTopic(List<Review> reviews) {
        for (Map.Entry<String, List<String>> topic : TOPIC_KEYWORDS.entrySet()) {
            boolean hit = reviews.stream()
                    .filter(r -> avgScoreOf(r) < 3.5)
                    .anyMatch(r -> topic.getValue().stream().anyMatch(k -> r.getContent().contains(k)));
            if (hit) return topic.getKey();
        }
        return null;
    }

    private Double avgRating(List<Review> reviews) {
        double sum = 0;
        int n = 0;
        for (Review r : reviews) {
            Double s = avgScoreOf(r);
            if (s != null) { sum += s; n++; }
        }
        return n == 0 ? null : Math.round(sum / n * 10) / 10.0;
    }

    /** 单条评价的均分（解析 scores_json） */
    private double avgScoreOf(Review r) {
        try {
            Map<?, ?> m = objectMapper.readValue(r.getScoresJson(), Map.class);
            if (m.isEmpty()) return 3.0;
            double sum = 0;
            for (Object v : m.values()) sum += ((Number) v).doubleValue();
            return sum / m.size();
        } catch (Exception e) {
            return 3.0;
        }
    }
}
