package com.scoutbite.shop.config;

import com.scoutbite.shop.entity.Coupon;
import com.scoutbite.shop.entity.Like;
import com.scoutbite.shop.entity.Post;
import com.scoutbite.shop.entity.Review;
import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.entity.Sku;
import com.scoutbite.shop.entity.User;
import com.scoutbite.shop.repository.CouponRepository;
import com.scoutbite.shop.repository.LikeRepository;
import com.scoutbite.shop.repository.PostRepository;
import com.scoutbite.shop.repository.ReviewRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.repository.SkuRepository;
import com.scoutbite.shop.repository.UserRepository;
import com.scoutbite.shop.service.CouponService;
import org.springframework.boot.CommandLineRunner;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.List;
import java.util.Random;

/**
 * 种子数据（扩充版）：管理员 + 40 店 + 每店 2 SKU + 每店 1 券。
 * 工程要点：
 *  - 固定随机种子(42)：每次重灌结果完全一致（评测依赖可复现）
 *  - 幂等：已有数据就跳过，重启不重复灌
 *  - 券余量镜像到 Redis（coupon:{id}:stock），并写一条心跳键——
 *    lettuce 是懒连接，配置错 6380/6379 时启动不报错，心跳键让问题立刻暴露
 */
@Component
public class DataSeeder implements CommandLineRunner {

    private final UserRepository userRepo;
    private final ShopRepository shopRepo;
    private final SkuRepository skuRepo;
    private final CouponRepository couponRepo;
    private final ReviewRepository reviewRepo;
    private final PostRepository postRepo;
    private final LikeRepository likeRepo;
    private final StringRedisTemplate redis;
    private final CouponService couponService;
    private final com.scoutbite.shop.service.ProfileService profileService;
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();

    private static final String[] HOTPOT_WORDS = {"老灶", "川味", "潮牛", "椒麻", "码头", "围炉"};
    private static final String[] COFFEE_WORDS = {"山野", "慢船", "分子", "街角", "屋顶", "岛屿"};
    private static final String[] PLAY_WORDS = {"城市记忆", "手作", "光影", "迷宫", "潮玩", "艺术仓库"};

    public DataSeeder(UserRepository userRepo, ShopRepository shopRepo,
                      SkuRepository skuRepo, CouponRepository couponRepo,
                      ReviewRepository reviewRepo, PostRepository postRepo,
                      LikeRepository likeRepo,
                      StringRedisTemplate redis, CouponService couponService,
                      com.scoutbite.shop.service.ProfileService profileService) {
        this.userRepo = userRepo;
        this.shopRepo = shopRepo;
        this.skuRepo = skuRepo;
        this.couponRepo = couponRepo;
        this.reviewRepo = reviewRepo;
        this.postRepo = postRepo;
        this.likeRepo = likeRepo;
        this.redis = redis;
        this.couponService = couponService;
        this.profileService = profileService;
    }

    @Override
    public void run(String... args) {
        // Redis 心跳：懒连接陷阱的探针——连不上这里就炸，启动日志立刻暴露（而不是等到第一次领券）
        redis.opsForValue().set("scoutbite:heartbeat", Instant.now().toString());

        seedAdmin();
        seedShops();       // 40 家店
        seedSkusCoupons(); // 每店 2 SKU + 1 券
        seedPresetUsers(); // 3 个预设用户（评价作者 + 画像原料）
        seedNewShop();     // 1 家新店（exploreBoost 演示主角）
        seedContent();     // 每店 8~20 条评价（掺差评）+ 帖子 + 点赞
        profileService.refreshAll();   // 画像离线刷新（模拟夜间任务）
    }

    /** 管理员：不开放注册的角色，只能从种子进 */
    private void seedAdmin() {
        if (userRepo.findByPhone("13900000000").isPresent()) return;
        User admin = new User();
        admin.setPhone("13900000000");
        admin.setPasswordHash(encoder.encode("admin123456"));
        admin.setRole("ADMIN");
        admin.setNickname("管理员");
        userRepo.save(admin);
    }

    /** 40 家店：火锅12 / 咖啡14 / 玩乐14，西湖东岸为心，300m~4km 散布，默认已过审 */
    private void seedShops() {
        if (shopRepo.count() >= 40) return;   // 幂等

        Random rnd = new Random(42);          // 固定种子 = 可复现
        seedCategory(rnd, "HOTPOT", "火锅", 12, HOTPOT_WORDS);
        seedCategory(rnd, "COFFEE", "咖啡", 14, COFFEE_WORDS);
        seedCategory(rnd, "ENTERTAIN", "玩乐", 14, PLAY_WORDS);
    }

    private void seedCategory(Random rnd, String category, String label, int count, String[] words) {
        for (int i = 1; i <= count; i++) {
            Shop s = new Shop();
            s.setOwnerId(0L);
            s.setName(words[rnd.nextInt(words.length)] + label + "·西湖" + i + "号店");
            s.setCategory(category);
            s.setCity("杭州");
            double angle = rnd.nextDouble() * 2 * Math.PI;
            double distM = 300 + rnd.nextDouble() * 3700;
            s.setLat(30.240 + distM / 111000.0 * Math.sin(angle));
            s.setLng(120.150 + distM / (111000.0 * Math.cos(Math.toRadians(30.24))) * Math.cos(angle));
            s.setStatus("approved");
            shopRepo.save(s);
        }
    }

    /** 每店 2 个套餐 + 1 张满减券（余量镜像 Redis） */
    private void seedSkusCoupons() {
        if (skuRepo.count() >= 80) return;    // 幂等：已有 40店×2

        Random rnd = new Random(42);
        Instant now = Instant.now();
        for (Shop shop : shopRepo.findAll()) {
            // 套餐 A：正常价；套餐 B：贵一档
            int basePrice = 3000 + rnd.nextInt(17000);   // 30~200 元（分）
            for (int k = 0; k < 2; k++) {
                Sku s = new Sku();
                s.setShopId(shop.getId());
                s.setTitle(shop.getCategory().equals("HOTPOT") ? (k == 0 ? "双人套餐" : "四人欢聚套餐")
                        : shop.getCategory().equals("COFFEE") ? (k == 0 ? "拿铁+甜点套餐" : "手冲品鉴套餐")
                        : (k == 0 ? "单人体验票" : "双人通票"));
                s.setPrice(k == 0 ? basePrice : basePrice + 2000 + rnd.nextInt(5000));
                s.setStock(50 + rnd.nextInt(150));
                s.setSales(rnd.nextInt(200));   // 历史销量（展示用；真实销量在核销 +1）
                s.setOnSale(true);
                skuRepo.save(s);
            }
            // 每店一张满减券：满 100 减 15 档位，总量 100
            Coupon c = new Coupon();
            c.setShopId(shop.getId());
            c.setTitle("满100减15");
            c.setThreshold(10000);
            c.setAmount(1500);
            c.setTotal(100);
            c.setPerUserLimit(1);
            c.setStartAt(now);
            c.setEndAt(now.plusSeconds(365L * 24 * 3600));
            couponRepo.save(c);
            couponService.initMirror(c.getId(), 100);   // Redis 余量镜像
        }
    }

    /** 3 个预设用户（接口实现种子规格：吃辣党/亲子党/咖啡党——画像与推荐的原料） */
    private void seedPresetUsers() {
        String[][] users = {
                {"13611110001", "辣妹小队长", "USER"},
                {"13611110002", "奶爸阿伦", "USER"},
                {"13611110003", "咖啡因选手", "USER"},
        };
        for (String[] u : users) {
            if (userRepo.findByPhone(u[0]).isPresent()) continue;
            User user = new User();
            user.setPhone(u[0]);
            user.setPasswordHash(encoder.encode("user123456"));
            user.setRole(u[2]);
            user.setNickname(u[1]);
            userRepo.save(user);
        }
    }

    /** 1 家「新店」（approvedAt=now，7 日窗口内）——exploreBoost 与冷启动演示的主角 */
    private void seedNewShop() {
        boolean exists = shopRepo.findAll().stream()
                .anyMatch(s -> s.getName().startsWith("新店·"));
        if (exists) return;
        Shop s = new Shop();
        s.setOwnerId(0L);
        s.setName("新店·围炉小火锅·开业尝鲜");
        s.setCategory("HOTPOT");
        s.setCity("杭州");
        s.setLat(30.245);
        s.setLng(120.158);
        s.setStatus("approved");
        s.setApprovedAt(Instant.now());   // 关键：过审时间在 7 日窗口内 → isNew=true
        shopRepo.save(s);
        // 新店也给 1 SKU（无评价无点赞——就是要演示「冷启动」）
        Sku sku = new Sku();
        sku.setShopId(s.getId());
        sku.setTitle("开业双人套餐");
        sku.setPrice(9900);
        sku.setStock(100);
        sku.setSales(0);
        sku.setOnSale(true);
        skuRepo.save(sku);
    }

    /** 每店 8~20 条评价（80% 好评 20% 差评掺「排队久/服务差/假优惠」）+ 帖子 + 点赞 */
    private void seedContent() {
        if (reviewRepo.count() >= 300) return;   // 幂等

        Random rnd = new Random(42);
        List<Shop> shops = shopRepo.findAll();
        List<Long> authorIds = userRepo.findAll().stream()
                .filter(u -> "USER".equals(u.getRole()))
                .map(User::getId).toList();       // 3 个预设用户 + 测试注册的用户
        long fakeOrderId = -1;                    // 负数合成 orderId：不与真实订单（正数）冲突

        String[] goodTexts = {
                "环境不错，套餐分量实在，会回购。",
                "味道很正，服务热情，性价比高。",
                "和朋友吃得很开心，推荐双人套餐。",
                "位置好找，出品稳定，值得二刷。",
                "上菜快，汤底香，体验超出预期。",
        };
        String[] badTexts = {
                "周五晚上排队超过一小时，建议错峰。",
                "服务一般，喊加水没人理，体验打折。",
                "券说是满100减15，结账才发现套餐不算，有点失望。",
                "味道可以但等位太久，性价比一般。",
        };

        for (Shop shop : shops) {
            if (shop.getName().startsWith("新店·")) continue;   // 新店零评价（冷启动演示）
            int n = 8 + rnd.nextInt(13);        // 8~20 条
            for (int i = 0; i < n; i++) {
                boolean bad = rnd.nextInt(100) < 20;   // 20% 差评
                int taste = bad ? 2 + rnd.nextInt(2) : 4 + rnd.nextInt(2);
                int wait = bad ? 1 + rnd.nextInt(2) : 3 + rnd.nextInt(3);
                int env = 3 + rnd.nextInt(3);
                Review r = new Review();
                r.setOrderId(fakeOrderId--);    // 合成 orderId（负数）
                r.setShopId(shop.getId());
                r.setUserId(authorIds.get(rnd.nextInt(authorIds.size())));
                r.setScoresJson(String.format(
                        "{\"taste\":%d,\"wait\":%d,\"env\":%d}", taste, wait, env));
                String[] pool = bad ? badTexts : goodTexts;
                r.setContent(pool[rnd.nextInt(pool.length)]);
                reviewRepo.save(r);
            }
            // 店的点赞（quality 的互动项）：0~30 个
            int likeN = rnd.nextInt(31);
            for (int i = 0; i < likeN; i++) {
                Like l = new Like();
                l.setUserId(authorIds.get(rnd.nextInt(authorIds.size())));
                l.setTargetType("SHOP");
                l.setTargetId(shop.getId());
                try {
                    likeRepo.save(l);   // 联合唯一可能撞（同人同店），撞了就跳过
                } catch (Exception ignore) {}
            }
        }

        // 帖子：每品类各来几条 + 2 条无店纯分享
        String[] postTexts = {
                "西湖边暴走两万步，收下这份citywalk补给地图。",
                "雨天和火锅更配，这家汤底绝了。",
                "周末带娃好去处，互动展览大人也玩得开心。",
                "打工人续命咖啡测评第三弹，这家的手冲值得一试。",
                "今天天气真好呀。",
                "有没有人一起去逛展的？",
        };
        for (int i = 0; i < postTexts.length; i++) {
            Post p = new Post();
            p.setUserId(authorIds.get(i % authorIds.size()));
            if (i < 4) {
                Shop target = shops.get(rnd.nextInt(shops.size()));
                p.setShopId(target.getId());
            }                               // 后两条纯分享（无店）
            p.setContent(postTexts[i]);
            postRepo.save(p);
        }
    }
}
