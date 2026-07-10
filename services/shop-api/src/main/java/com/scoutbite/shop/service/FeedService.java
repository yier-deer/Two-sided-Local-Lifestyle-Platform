package com.scoutbite.shop.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.scoutbite.shop.entity.Impression;
import com.scoutbite.shop.entity.Post;
import com.scoutbite.shop.entity.Review;
import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.repository.ImpressionRepository;
import com.scoutbite.shop.repository.LikeRepository;
import com.scoutbite.shop.repository.PostRepository;
import com.scoutbite.shop.repository.ReviewRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.repository.SkuRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 信息流服务：推流公式五因子的最小可用实现。
 *
 * score = quality × freshness^λ × proximity × exploreBoost × diversityPenalty
 *  - quality   评分（平滑防零）× 互动 × 销量代理 —— 防低质
 *  - freshness 1/(1+小时数)^λ（λ=0.5）        —— 防老帖永占
 *  - proximity exp(-距离/3000m)，无位置时 1    —— 防本地变全国
 *  - explore   新店（7日内过审）×2，请求可开关 —— 防新店冷启动死局
 *  - diversity 输出阶段同店只留最高分一条      —— 防爆款霸屏
 *
 * scene 三队列：nearby（距离主导）/ hot（质量主导）/ new（只留新店）。
 * 每次输出写 impressions（归因 + 已读降权的原料）。
 */
@Service
public class FeedService {

    private static final Logger log = LoggerFactory.getLogger(FeedService.class);

    /** freshness 的 λ 旋钮：调大更看重新鲜。产品参数而非技术参数 */
    private static final double LAMBDA = 0.5;
    /** 探索半径（米）：proximity 的衰减尺度 */
    private static final double PROXIMITY_DECAY_M = 3000.0;
    /** 新店窗口：过审 7 日内算新店 */
    private static final Duration NEW_SHOP_WINDOW = Duration.ofDays(7);
    /** 评分平滑底数：无评价时给中位数 3.0 而不是 0（否则 quality=0 会把 exploreBoost 也乘没） */
    private static final double RATING_PRIOR = 3.0;
    private static final double RATING_PRIOR_WEIGHT = 2.0;

    private final ShopRepository shopRepo;
    private final ReviewRepository reviewRepo;
    private final PostRepository postRepo;
    private final LikeRepository likeRepo;
    private final SkuRepository skuRepo;
    private final ImpressionRepository impressionRepo;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public FeedService(ShopRepository shopRepo, ReviewRepository reviewRepo,
                       PostRepository postRepo, LikeRepository likeRepo,
                       SkuRepository skuRepo, ImpressionRepository impressionRepo) {
        this.shopRepo = shopRepo;
        this.reviewRepo = reviewRepo;
        this.postRepo = postRepo;
        this.likeRepo = likeRepo;
        this.skuRepo = skuRepo;
        this.impressionRepo = impressionRepo;
    }

    /**
     * 信息流。
     * @param scene   nearby / hot / new
     * @param lat,lng 用户位置（可空：无位置则 proximity=1）
     * @param explore 探索开关（请求级——验收要同屏对比开关效果）
     * @param userId  当前用户（可空：游客；用于曝光日志归属）
     * @param limit   返回条数
     */
    public List<Map<String, Object>> feed(String scene, Double lat, Double lng,
                                          boolean explore, Long userId, int limit) {
        Instant now = Instant.now();

        // ===== 候选集：approved 店 ×（最新一条评价或帖子作为内容） + 无店帖子 =====
        List<Shop> shops = shopRepo.findAll().stream()
                .filter(s -> "approved".equals(s.getStatus())).toList();
        List<Post> recentPosts = postRepo.findTop100ByOrderByCreatedAtDesc();

        // 每店的聚合数据（评分/点赞/销量）——40 家店量级，Java 内存聚合够用
        Map<Long, double[]> shopStats = new HashMap<>();   // [平滑评分, 评价数]
        Map<Long, Long> shopLikes = new HashMap<>();
        Map<Long, Long> shopSales = new HashMap<>();
        Map<Long, Instant> shopLatestContent = new HashMap<>();
        for (Shop s : shops) {
            List<Review> reviews = reviewRepo.findByShopIdOrderByIdDesc(s.getId());
            double ratingSum = 0;
            int ratingCount = 0;
            for (Review r : reviews) {
                Double avg = avgScore(r.getScoresJson());
                if (avg != null) { ratingSum += avg; ratingCount++; }
                shopLatestContent.merge(s.getId(), r.getCreatedAt(),
                        (a, b) -> a.isAfter(b) ? a : b);
            }
            // 平滑：(sum + 3.0×2) / (count + 2) —— 新店无评分时 3.0（中位数），不是 0
            double smoothed = (ratingSum + RATING_PRIOR * RATING_PRIOR_WEIGHT)
                    / (ratingCount + RATING_PRIOR_WEIGHT);
            shopStats.put(s.getId(), new double[]{smoothed, ratingCount});
            shopLikes.put(s.getId(), likeRepo.countByTargetTypeAndTargetId("SHOP", s.getId()));
            shopSales.put(s.getId(), (long) skuRepo.findByShopIdOrderById(s.getId())
                    .stream().mapToLong(sku -> sku.getSales()).sum());
        }
        // 帖子时间也参与 freshness 的「最新内容时间」
        for (Shop s : shops) {
            List<Post> posts = postRepo.findByShopIdOrderByIdDesc(s.getId());
            if (!posts.isEmpty()) {
                Instant latest = posts.get(0).getCreatedAt();
                shopLatestContent.merge(s.getId(), latest,
                        (a, b) -> a.isAfter(b) ? a : b);
            }
        }

        // ===== 逐候计算 =====
        List<Candidate> candidates = new ArrayList<>();
        for (Shop s : shops) {
            boolean isNew = isNewShop(s, now);
            // scene=new：只留新店（冷启动专属队列）
            if ("new".equals(scene) && !isNew) continue;

            // quality：平滑评分(归一化) × 互动 × 销量代理
            double[] stats = shopStats.get(s.getId());
            double normRating = stats[0] / 5.0;
            long likes = shopLikes.getOrDefault(s.getId(), 0L);
            long sales = shopSales.getOrDefault(s.getId(), 0L);
            double quality = normRating
                    * (1 + Math.log10(1 + likes))
                    * (1 + Math.log10(1 + sales) / 2.0);

            // freshness：以该店最新内容时间算
            Instant contentAt = shopLatestContent.getOrDefault(s.getId(), s.getCreatedAt());
            double hours = Math.max(0, Duration.between(contentAt, now).toMinutes() / 60.0);
            double freshness = 1.0 / Math.pow(1 + hours, LAMBDA);

            // proximity
            double proximity = 1.0;
            if (lat != null && lng != null) {
                double d = GeoService.haversine(lat, lng, s.getLat(), s.getLng());
                proximity = Math.exp(-d / PROXIMITY_DECAY_M);
            }

            // explore：新店 ×2（scene=new 不再乘——它们全是新的）
            double exploreBoost = (explore && isNew && !"new".equals(scene)) ? 2.0 : 1.0;

            // scene 加权（三队列）
            double score = quality * freshness * proximity * exploreBoost;
            if ("nearby".equals(scene)) score *= Math.pow(proximity, 2);
            if ("hot".equals(scene)) score *= Math.pow(quality, 2);

            // 内容：该店最新一条评价或帖子
            Object content = latestContent(s.getId(), recentPosts);
            candidates.add(new Candidate(s, content, score, isNew));
        }
        // 无店帖子（自由内容，不参与店铺去重）
        for (Post p : recentPosts) {
            if (p.getShopId() == null) {
                double hours = Math.max(0, Duration.between(p.getCreatedAt(), now).toMinutes() / 60.0);
                double freshness = 1.0 / Math.pow(1 + hours, LAMBDA);
                long likes = likeRepo.countByTargetTypeAndTargetId("POST", p.getId());
                double quality = 0.6 * (1 + Math.log10(1 + likes));
                candidates.add(new Candidate(null, p, quality * freshness, false));
            }
        }

        // ===== 排序 → 多样性去重（同店只留最高分）→ 探索配额 → 输出 =====
        candidates.sort(Comparator.comparingDouble((Candidate c) -> c.score).reversed());

        List<Candidate> output = new ArrayList<>();
        Set<Long> seenShops = new HashSet<>();
        for (Candidate c : candidates) {
            if (output.size() >= limit) break;
            if (c.shop != null) {
                if (seenShops.contains(c.shop.getId())) continue;   // diversityPenalty：同店一屏一条
                seenShops.add(c.shop.getId());
            }
            output.add(c);
        }

        // 探索位配额（nearby/hot 流）：前 3 位若无新店且开关开，把最高分新店插到第 2 位
        if (explore && !"new".equals(scene) && output.size() > 2) {
            boolean hasNewInTop3 = output.subList(0, Math.min(3, output.size())).stream()
                    .anyMatch(c -> c.isNew);
            if (!hasNewInTop3) {
                output.stream().filter(c -> c.isNew).findFirst().ifPresent(newC -> {
                    output.remove(newC);
                    output.add(1, newC);
                });
            }
        }

        // ===== 输出 + 曝光日志 =====
        List<Map<String, Object>> result = new ArrayList<>();
        int pos = 0;
        for (Candidate c : output) {
            Map<String, Object> m = new HashMap<>();
            if (c.shop != null) {
                m.put("shopId", c.shop.getId());
                m.put("shopName", c.shop.getName());
                m.put("category", c.shop.getCategory());
                m.put("isNew", c.isNew);
                m.put("distanceMeters", (lat != null && lng != null)
                        ? Math.round(GeoService.haversine(lat, lng, c.shop.getLat(), c.shop.getLng()))
                        : null);
                // 曝光日志（append-only）：归因 + 已读降权的原料
                Impression imp = new Impression();
                imp.setUserId(userId);
                imp.setShopId(c.shop.getId());
                imp.setScene(scene);
                imp.setPosition(pos);
                impressionRepo.save(imp);
            }
            m.put("contentType", c.content instanceof Post ? "POST" : "REVIEW");
            m.put("content", contentBrief(c.content));
            m.put("score", Math.round(c.score * 10000.0) / 10000.0);
            result.add(m);
            pos++;
        }
        log.info("feed scene={} explore={} 候选{} 输出{}（含新店{}）",
                scene, explore, candidates.size(), output.size(),
                output.stream().filter(c -> c.isNew).count());
        return result;
    }

    /** 该店最新内容：帖子优先比时间，简化为取最新评价或帖子中更新者 */
    private Object latestContent(Long shopId, List<Post> recentPosts) {
        Post latestPost = recentPosts.stream()
                .filter(p -> shopId.equals(p.getShopId()))
                .findFirst().orElse(null);
        List<Review> reviews = reviewRepo.findByShopIdOrderByIdDesc(shopId);
        Review latestReview = reviews.isEmpty() ? null : reviews.get(0);
        if (latestPost != null && (latestReview == null ||
                latestPost.getCreatedAt().isAfter(latestReview.getCreatedAt()))) {
            return latestPost;
        }
        return latestReview != null ? latestReview : null;
    }

    /** 内容摘要（评价带分数，帖子带正文头） */
    private Map<String, Object> contentBrief(Object content) {
        Map<String, Object> m = new HashMap<>();
        if (content instanceof Post p) {
            m.put("id", p.getId());
            m.put("text", p.getContent().length() > 60
                    ? p.getContent().substring(0, 60) + "…" : p.getContent());
        } else if (content instanceof Review r) {
            m.put("id", r.getId());
            try {
                m.put("scores", objectMapper.readValue(r.getScoresJson(), Map.class));
            } catch (Exception e) {
                m.put("scores", Map.of());
            }
            m.put("text", r.getContent().length() > 60
                    ? r.getContent().substring(0, 60) + "…" : r.getContent());
        }
        return m;
    }

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

    private boolean isNewShop(Shop s, Instant now) {
        return s.getApprovedAt() != null
                && Duration.between(s.getApprovedAt(), now).compareTo(NEW_SHOP_WINDOW) < 0;
    }

    /** 内部候选结构 */
    private record Candidate(Shop shop, Object content, double score, boolean isNew) {}
}
