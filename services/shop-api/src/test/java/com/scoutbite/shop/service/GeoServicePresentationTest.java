package com.scoutbite.shop.service;

import com.scoutbite.shop.entity.Review;
import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.entity.Sku;
import com.scoutbite.shop.repository.ReviewRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.repository.SkuRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class GeoServicePresentationTest {
    @Mock ShopRepository shops;
    @Mock ReviewRepository reviews;
    @Mock SkuRepository skus;
    @InjectMocks GeoService service;

    @BeforeEach
    void setUp() {
        Shop shop = new Shop();
        ReflectionTestUtils.setField(shop, "id", 11L);
        shop.setName("真实样本门店");
        shop.setCategory("HOTPOT");
        shop.setCity("杭州");
        shop.setLat(30.24);
        shop.setLng(120.15);
        shop.setStatus("approved");
        when(shops.findInBox(anyDouble(), anyDouble(), anyDouble(), anyDouble(), isNull())).thenReturn(List.of(shop));
    }

    @Test
    void nearbyRatingComesFromValidReviewScoresAndLowestOnSaleSku() {
        when(reviews.findByShopIdOrderByIdDesc(11L)).thenReturn(List.of(
                review("{\"taste\":5,\"wait\":3,\"env\":4}"),
                review("{\"taste\":2,\"wait\":3,\"env\":4}"),
                review("not-json")));
        when(skus.findByShopIdOrderById(11L)).thenReturn(List.of(sku(1000, false), sku(12800, true), sku(9900, true)));
        Map<String, Object> result = nearby();
        assertEquals(3, result.get("reviewCount"));
        assertEquals(3.5, result.get("rating"));
        assertEquals(9900, result.get("minSkuPrice"));
        assertFalse(result.containsKey("avgPrice"), "未知用餐人数时不能把套餐价格标成人均");
    }

    @Test
    void noReviewsOrOnSaleSkusReturnNullFactsInsteadOfInventedDefaults() {
        when(reviews.findByShopIdOrderByIdDesc(11L)).thenReturn(List.of());
        when(skus.findByShopIdOrderById(11L)).thenReturn(List.of(sku(9000, false)));
        Map<String, Object> result = nearby();
        assertEquals(0, result.get("reviewCount"));
        assertTrue(result.containsKey("rating"));
        assertNull(result.get("rating"));
        assertTrue(result.containsKey("minSkuPrice"));
        assertNull(result.get("minSkuPrice"));
    }

    @Test
    void stringsOutOfRangeAndMalformedScoresCannotProduceRating() {
        when(reviews.findByShopIdOrderByIdDesc(11L)).thenReturn(List.of(
                review("{\"taste\":\"5\",\"wait\":0,\"env\":7}"),
                review("[]"), review("{}"), review(null)));
        Map<String, Object> result = nearby();
        assertEquals(4, result.get("reviewCount"));
        assertTrue(result.containsKey("rating"));
        assertNull(result.get("rating"));
    }

    @Test
    void averagesEachReviewBeforeComputingOverallRating() {
        when(reviews.findByShopIdOrderByIdDesc(11L)).thenReturn(List.of(
                review("{\"taste\":5}"), review("{\"taste\":1,\"wait\":1,\"env\":1}")));
        assertEquals(3.0, nearby().get("rating"));
    }

    private Map<String, Object> nearby() {
        return service.nearby(30.24, 120.15, 3000, null).getFirst();
    }

    private static Review review(String scoresJson) {
        Review review = new Review();
        review.setShopId(11L);
        review.setScoresJson(scoresJson);
        return review;
    }

    private static Sku sku(int price, boolean onSale) {
        Sku sku = new Sku();
        sku.setShopId(11L);
        sku.setPrice(price);
        sku.setOnSale(onSale);
        return sku;
    }
}
