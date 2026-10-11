package com.scoutbite.shop.config;

import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.entity.User;
import com.scoutbite.shop.repository.*;
import com.scoutbite.shop.service.CouponService;
import com.scoutbite.shop.service.ProfileService;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class DemoMerchantSeedTest {
    @Test
    void createsUsableMerchantAndBindsOnlyAnonymousSeedShopsAcrossRestarts() {
        Map<String, User> users = new LinkedHashMap<>();
        for (String phone : List.of("13900000000", "13611110001", "13611110002", "13611110003")) {
            User user = user(phone, phone.equals("13900000000") ? "ADMIN" : "USER", users.size() + 1L);
            users.put(phone, user);
        }
        UserRepository userRepo = mock(UserRepository.class);
        when(userRepo.findByPhone(anyString())).thenAnswer(inv -> Optional.ofNullable(users.get(inv.getArgument(0))));
        when(userRepo.save(any())).thenAnswer(inv -> {
            User user = inv.getArgument(0);
            ReflectionTestUtils.setField(user, "id", users.size() + 1L);
            users.put(user.getPhone(), user);
            return user;
        });
        Shop anonymousFirst = shop(1L, 0L, "川味火锅·西湖1号店");
        Shop anonymousSecond = shop(2L, 0L, "潮牛火锅·西湖2号店");
        Shop realOwner = shop(3L, 90L, "码头火锅·西湖3号店");
        Shop newShop = shop(41L, 0L, "新店·围炉小火锅·开业尝鲜");
        List<Shop> shops = new ArrayList<>(List.of(anonymousFirst, anonymousSecond, realOwner, newShop));
        ShopRepository shopRepo = mock(ShopRepository.class);
        when(shopRepo.count()).thenReturn(41L);
        when(shopRepo.findAll()).thenReturn(shops);
        SkuRepository skus = mock(SkuRepository.class);
        when(skus.count()).thenReturn(81L);
        ReviewRepository reviews = mock(ReviewRepository.class);
        when(reviews.count()).thenReturn(500L);
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.opsForValue()).thenReturn(mock(ValueOperations.class));
        DataSeeder seeder = new DataSeeder(userRepo, shopRepo, skus, mock(CouponRepository.class), reviews,
                mock(PostRepository.class), mock(LikeRepository.class), redis, mock(CouponService.class), mock(ProfileService.class));

        seeder.run();

        User merchant = users.get("13611110004");
        assertNotNull(merchant, "双端演示必须拥有可登录的 MERCHANT 种子账号");
        assertEquals("MERCHANT", merchant.getRole());
        assertEquals("蜀味里店长", merchant.getNickname());
        assertTrue(new BCryptPasswordEncoder().matches("merchant123456", merchant.getPasswordHash()));
        assertEquals(merchant.getId(), anonymousFirst.getOwnerId());
        assertEquals(merchant.getId(), newShop.getOwnerId());
        assertEquals(90L, realOwner.getOwnerId());
        assertEquals(0L, anonymousSecond.getOwnerId());

        seeder.run();
        assertEquals(5, users.size());
        assertEquals(0L, anonymousSecond.getOwnerId(), "重启不能逐次接管其他种子门店");
        assertEquals(90L, realOwner.getOwnerId());
    }

    @Test
    void existingPhoneWithOtherRoleIsPreservedAndNeverGetsSeedShops() {
        User existing = user("13611110004", "USER", 23L);
        UserRepository userRepo = mock(UserRepository.class);
        when(userRepo.findByPhone(anyString())).thenReturn(Optional.of(existing));
        Shop shop = shop(1L, 0L, "老灶火锅·西湖1号店");
        ShopRepository shops = mock(ShopRepository.class);
        when(shops.count()).thenReturn(41L);
        when(shops.findAll()).thenReturn(List.of(shop, shop(41L, 0L, "新店·围炉小火锅·开业尝鲜")));
        SkuRepository skus = mock(SkuRepository.class);
        when(skus.count()).thenReturn(81L);
        ReviewRepository reviews = mock(ReviewRepository.class);
        when(reviews.count()).thenReturn(500L);
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.opsForValue()).thenReturn(mock(ValueOperations.class));
        new DataSeeder(userRepo, shops, skus, mock(CouponRepository.class), reviews,
                mock(PostRepository.class), mock(LikeRepository.class), redis, mock(CouponService.class), mock(ProfileService.class)).run();
        assertEquals("USER", existing.getRole());
        assertEquals(0L, shop.getOwnerId());
        verify(userRepo, never()).save(any());
    }

    private static User user(String phone, String role, long id) {
        User user = new User();
        ReflectionTestUtils.setField(user, "id", id);
        user.setPhone(phone);
        user.setRole(role);
        user.setNickname("现存用户");
        return user;
    }

    private static Shop shop(long id, long owner, String name) {
        Shop shop = new Shop();
        ReflectionTestUtils.setField(shop, "id", id);
        shop.setOwnerId(owner);
        shop.setName(name);
        shop.setCategory("HOTPOT");
        shop.setCity("杭州");
        shop.setStatus("approved");
        return shop;
    }
}
