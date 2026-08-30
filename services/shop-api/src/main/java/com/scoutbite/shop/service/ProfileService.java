package com.scoutbite.shop.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.scoutbite.shop.entity.Like;
import com.scoutbite.shop.entity.Order;
import com.scoutbite.shop.entity.Review;
import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.entity.User;
import com.scoutbite.shop.entity.UserProfile;
import com.scoutbite.shop.repository.LikeRepository;
import com.scoutbite.shop.repository.OrderRepository;
import com.scoutbite.shop.repository.ReviewRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.repository.UserProfileRepository;
import com.scoutbite.shop.repository.UserRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 画像服务（）：离线刷新（启动时重算），在线只读。
 * 聚合来源：likes(SHOP→品类) + reviews(店→品类) + orders(实付均价)。
 * topCategories 频次 top2；avgPrice 无订单时留 null（冷启动标记）。
 */
@Service
public class ProfileService {

    private static final Logger log = LoggerFactory.getLogger(ProfileService.class);

    private final UserRepository userRepo;
    private final ShopRepository shopRepo;
    private final LikeRepository likeRepo;
    private final ReviewRepository reviewRepo;
    private final OrderRepository orderRepo;
    private final UserProfileRepository profileRepo;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ProfileService(UserRepository userRepo, ShopRepository shopRepo,
                          LikeRepository likeRepo, ReviewRepository reviewRepo,
                          OrderRepository orderRepo, UserProfileRepository profileRepo) {
        this.userRepo = userRepo;
        this.shopRepo = shopRepo;
        this.likeRepo = likeRepo;
        this.reviewRepo = reviewRepo;
        this.orderRepo = orderRepo;
        this.profileRepo = profileRepo;
    }

    /** 全量刷新（覆盖式 upsert）。真实系统是夜间定时任务；本项目启动时跑一次。 */
    public void refreshAll() {
        Map<Long, String> shopCategory = shopRepo.findAll().stream()
                .collect(Collectors.toMap(Shop::getId, Shop::getCategory));

        int count = 0;
        for (User u : userRepo.findAll()) {
            if (!"USER".equals(u.getRole())) continue;   // 画像只服务消费者

            // 品类频次：点赞 + 评价 + 已支付订单
            Map<String, Integer> freq = new LinkedHashMap<>();
            for (Like l : likeRepo.findAll()) {
                if (l.getUserId().equals(u.getId()) && "SHOP".equals(l.getTargetType())) {
                    String cat = shopCategory.get(l.getTargetId());
                    if (cat != null) freq.merge(cat, 1, Integer::sum);
                }
            }
            for (Review r : reviewRepo.findAll()) {
                if (r.getUserId().equals(u.getId())) {
                    String cat = shopCategory.get(r.getShopId());
                    if (cat != null) freq.merge(cat, 2, Integer::sum);   // 评价权重高于点赞
                }
            }
            List<Order> paidOrders = orderRepo.findByUserIdOrderByIdDesc(u.getId()).stream()
                    .filter(o -> !Order.CREATED.equals(o.getStatus())
                            && !Order.CANCELLED_TIMEOUT.equals(o.getStatus())
                            && !Order.CANCELLED_USER.equals(o.getStatus()))
                    .toList();
            for (Order o : paidOrders) {
                String cat = shopCategory.get(o.getShopId());
                if (cat != null) freq.merge(cat, 3, Integer::sum);       // 消费权重最高
            }

            // topCategories：频次 top2
            List<String> top = freq.entrySet().stream()
                    .sorted((a, b) -> b.getValue() - a.getValue())
                    .limit(2)
                    .map(Map.Entry::getKey)
                    .toList();

            // avgPrice：已支付订单均价（分）
            Integer avgPrice = paidOrders.isEmpty() ? null
                    : (int) paidOrders.stream().mapToLong(Order::getPriceSnapshot).average().orElse(0);

            // tags：品类偏好 + 均价档位
            List<String> tags = new ArrayList<>();
            Map<String, String> catLabel = Map.of("HOTPOT", "吃辣党", "COFFEE", "咖啡党", "ENTERTAIN", "玩乐党");
            for (String c : top) tags.add(catLabel.getOrDefault(c, c));
            if (avgPrice != null) {
                tags.add(avgPrice < 8000 ? "经济档" : avgPrice < 20000 ? "中档" : "轻奢档");
            }

            UserProfile p = new UserProfile();
            p.setUserId(u.getId());
            try {
                p.setTagsJson(objectMapper.writeValueAsString(tags));
                p.setTopCategories(objectMapper.writeValueAsString(top));
            } catch (Exception e) {
                log.warn("画像序列化失败 userId={}", u.getId());
                continue;
            }
            p.setAvgPrice(avgPrice);
            p.setRefreshedAt(java.time.Instant.now());
            profileRepo.save(p);   // 主键即 userId：覆盖式刷新
            count++;
        }
        log.info("画像离线刷新完成：{} 个用户", count);
    }
}
