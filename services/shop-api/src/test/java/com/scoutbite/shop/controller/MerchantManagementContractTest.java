package com.scoutbite.shop.controller;

import com.scoutbite.shop.entity.Coupon;
import com.scoutbite.shop.entity.Order;
import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.entity.Sku;
import com.scoutbite.shop.entity.UserCoupon;
import com.scoutbite.shop.repository.*;
import com.scoutbite.shop.service.CouponService;
import com.scoutbite.shop.service.GeoService;
import com.scoutbite.shop.service.OrderService;
import com.scoutbite.shop.service.ReviewService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.CsvSource;
import org.mockito.Answers;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.http.MediaType;
import org.springframework.beans.BeanWrapper;
import org.springframework.beans.BeanWrapperImpl;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class MerchantManagementContractTest {
    private static final long MERCHANT = 5L;
    @Mock ShopRepository shopRepo;
    @Mock SkuRepository skuRepo;
    @Mock UserRepository userRepo;
    @Mock ReviewRepository reviewRepo;
    @Mock OrderService orderService;
    @Mock GeoService geoService;
    @Mock CouponService couponService;
    @Mock ReviewService reviewService;

    private final Order ownOrder = order(1L, 11L, Order.PAID);
    private final Order reviewedOrder = order(2L, 11L, Order.REVIEWED);
    private final Order unreviewedOrder = order(3L, 11L, Order.REDEEMED);
    private final Order otherOrder = order(4L, 99L, Order.PAID);
    private final OrderRepository orderRepo = mock(OrderRepository.class, invocation ->
            invocation.getMethod().getName().equals("findByShopIdInOrderByIdDesc")
                    ? List.of(ownOrder, reviewedOrder, unreviewedOrder)
                    : Answers.RETURNS_DEFAULTS.answer(invocation));
    private final Coupon coupon = coupon();
    private final CouponRepository couponRepo = mock(CouponRepository.class, invocation ->
            invocation.getMethod().getName().equals("findByShopIdOrderByIdDesc")
                    ? List.of(coupon) : Answers.RETURNS_DEFAULTS.answer(invocation));
    private final UserCouponRepository userCouponRepo = mock(UserCouponRepository.class, invocation -> {
        return switch (invocation.getMethod().getName()) {
            case "countByCouponId" -> 3L;
            case "countByCouponIdAndStatus" -> 1L;
            default -> Answers.RETURNS_DEFAULTS.answer(invocation);
        };
    });

    @InjectMocks OrderController orders;
    @InjectMocks SkuController skus;
    @InjectMocks CouponController coupons;
    @InjectMocks ShopController shops;
    @InjectMocks ReviewController reviewController;
    MockMvc mvc;

    @BeforeEach
    void setUp() {
        // Repositories are the isolated persistence boundary; controllers and JSON serialization are real.
        ReflectionTestUtils.setField(orders, "orderRepo", orderRepo);
        ReflectionTestUtils.setField(coupons, "couponRepo", couponRepo);
        ReflectionTestUtils.setField(coupons, "userCouponRepo", userCouponRepo);
        mvc = MockMvcBuilders.standaloneSetup(orders, skus, coupons, shops, reviewController).build();
        Shop owned = shop(11L, MERCHANT, "approved");
        lenient().when(shopRepo.findById(11L)).thenReturn(Optional.of(owned));
        lenient().when(shopRepo.findById(99L)).thenReturn(Optional.of(shop(99L, 8L, "approved")));
        lenient().when(shopRepo.findByOwnerIdOrderByIdDesc(MERCHANT)).thenReturn(List.of(owned));
        lenient().when(reviewRepo.findByOrderId(anyLong())).thenReturn(Optional.empty());
    }

    @Test
    void merchantCanReadOwnOrdersWithBusinessNames() throws Exception {
        mvc.perform(get("/api/merchant/orders").param("shopId", "11")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.length()").value(3))
                .andExpect(jsonPath("$.data[0].shopId").value(11))
                .andExpect(jsonPath("$.data[0].shopName").value("测试门店11"));
    }

    @Test
    void merchantCannotReadAnotherShopsOrders() throws Exception {
        mvc.perform(get("/api/merchant/orders").param("shopId", "99")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40300));
    }

    @Test
    void consumerCannotUseMerchantOrderRead() throws Exception {
        mvc.perform(get("/api/merchant/orders").requestAttr("userId", MERCHANT).requestAttr("role", "USER"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40300));
    }

    @Test
    void merchantCatalogIncludesOfflineSkus() throws Exception {
        Sku offline = new Sku();
        ReflectionTestUtils.setField(offline, "id", 7L);
        offline.setShopId(11L);
        offline.setTitle("暂停售卖的套餐");
        offline.setPrice(12800);
        offline.setStock(8);
        offline.setOnSale(false);
        when(skuRepo.findByShopIdOrderById(11L)).thenReturn(List.of(offline));
        mvc.perform(get("/api/merchant/skus").param("shopId", "11")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data[0].onSale").value(false));
    }

    @Test
    void merchantCatalogRejectsAnotherShop() throws Exception {
        mvc.perform(get("/api/merchant/skus").param("shopId", "99")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40300));
    }

    @Test
    void merchantCouponReadIncludesClaimAndUseCounts() throws Exception {
        mvc.perform(get("/api/merchant/coupons").param("shopId", "11")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data[0].claimedCount").value(3))
                .andExpect(jsonPath("$.data[0].usedCount").value(1))
                .andExpect(jsonPath("$.data[0].remaining").value(7));
    }

    @Test
    void myCouponIncludesTemplateFactsAndPreservesHeldCouponIdentity() throws Exception {
        UserCoupon held = new UserCoupon();
        ReflectionTestUtils.setField(held, "id", 13L);
        held.setUserId(2L);
        held.setCouponId(9L);
        held.setStatus(UserCoupon.UNUSED);
        when(userCouponRepo.findByUserIdOrderByIdDesc(2L)).thenReturn(List.of(held));
        when(couponRepo.findById(9L)).thenReturn(Optional.of(coupon));
        mvc.perform(get("/api/coupons/mine").requestAttr("userId", 2L).requestAttr("role", "USER"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data[0].id").value(13))
                .andExpect(jsonPath("$.data[0].userCouponId").value(13))
                .andExpect(jsonPath("$.data[0].couponId").value(9))
                .andExpect(jsonPath("$.data[0].shopId").value(11))
                .andExpect(jsonPath("$.data[0].title").value("满100减15"))
                .andExpect(jsonPath("$.data[0].threshold").value(10000))
                .andExpect(jsonPath("$.data[0].amount").value(1500))
                .andExpect(jsonPath("$.data[0].perUserLimit").value(1))
                .andExpect(jsonPath("$.data[0].startAt").value(coupon.getStartAt().toString()))
                .andExpect(jsonPath("$.data[0].endAt").value(coupon.getEndAt().toString()));
    }

    @ParameterizedTest
    @ValueSource(strings = {"-1", "1.5", "2147483648"})
    void cannotCreateNegativeFractionalOrOverflowingStock(String stock) throws Exception {
        mvc.perform(post("/api/merchant/skus").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"shopId\":11,\"title\":\"双人套餐\",\"price\":12800,\"stock\":" + stock + "}")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40001));
        verify(skuRepo, never()).save(any());
    }

    @ParameterizedTest
    @ValueSource(strings = {"-1", "1.5", "2147483648"})
    void invalidStockUpdateDoesNotPartiallyChangeManagedSku(String stock) throws Exception {
        Sku existing = catalogSku();
        when(skuRepo.findById(7L)).thenReturn(Optional.of(existing));
        mvc.perform(patch("/api/merchant/skus/7").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"新标题\",\"stock\":" + stock + "}")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40001));
        assertEquals("双人套餐", existing.getTitle());
        assertEquals(8, existing.getStock());
        verify(skuRepo, never()).save(any());
    }

    @ParameterizedTest
    @ValueSource(strings = {"-1", "0", "10000001", "12800.5"})
    void updateRejectsInvalidPriceInCents(String price) throws Exception {
        Sku existing = catalogSku();
        when(skuRepo.findById(7L)).thenReturn(Optional.of(existing));
        mvc.perform(patch("/api/merchant/skus/7").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"price\":" + price + "}")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40001));
        assertEquals(12800, existing.getPrice());
        verify(skuRepo, never()).save(any());
    }

    @Test
    void zeroStockCanBeSavedWithoutChangingPrice() throws Exception {
        Sku existing = catalogSku();
        when(skuRepo.findById(7L)).thenReturn(Optional.of(existing));
        mvc.perform(patch("/api/merchant/skus/7").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"stock\":0,\"onSale\":false}")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.stock").value(0))
                .andExpect(jsonPath("$.data.price").value(12800))
                .andExpect(jsonPath("$.data.onSale").value(false));
    }

    @Test
    void joinPersistsAndReturnsAddressWithoutDroppingOriginalStatusMessage() throws Exception {
        when(shopRepo.save(any())).thenAnswer(inv -> {
            Shop shop = inv.getArgument(0);
            ReflectionTestUtils.setField(shop, "id", 13L);
            return shop;
        });
        mvc.perform(post("/api/merchant/shops").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"湖边小店\",\"category\":\"COFFEE\",\"lat\":30.24,\"lng\":120.15,\"address\":\"杭州上城区湖滨路18号\"}")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.id").value(13))
                .andExpect(jsonPath("$.data.status").value("pending"))
                .andExpect(jsonPath("$.data.message").exists())
                .andExpect(jsonPath("$.data.address").value("杭州上城区湖滨路18号"));
        var saved = org.mockito.ArgumentCaptor.forClass(Shop.class);
        verify(shopRepo).save(saved.capture());
        assertEquals("杭州上城区湖滨路18号", new BeanWrapperImpl(saved.getValue()).getPropertyValue("address"));
    }

    @Test
    void ownedAndAdminShopReadsIncludeAddress() throws Exception {
        Shop shop = shop(11L, MERCHANT, "pending");
        setAddressWhenAvailable(shop, "杭州上城区湖滨路18号");
        when(shopRepo.findByOwnerIdOrderByIdDesc(MERCHANT)).thenReturn(List.of(shop));
        when(shopRepo.findAll()).thenReturn(List.of(shop));
        mvc.perform(get("/api/merchant/shops").requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(jsonPath("$.data[0].address").value("杭州上城区湖滨路18号"));
        mvc.perform(get("/api/admin/shops").requestAttr("userId", 1L).requestAttr("role", "ADMIN"))
                .andExpect(jsonPath("$.data[0].address").value("杭州上城区湖滨路18号"));
    }

    @Test
    void publicDetailIncludesPersistedAddress() throws Exception {
        Shop shop = shop(11L, MERCHANT, "approved");
        setAddressWhenAvailable(shop, "杭州上城区湖滨路18号");
        when(shopRepo.findById(11L)).thenReturn(Optional.of(shop));
        mvc.perform(get("/api/shops/11"))
                .andExpect(jsonPath("$.data.address").value("杭州上城区湖滨路18号"));
    }

    @Test
    void rejectedShopCanResubmitEditedAddress() throws Exception {
        Shop shop = shop(11L, MERCHANT, "rejected");
        setAddressWhenAvailable(shop, "旧地址");
        when(shopRepo.findById(11L)).thenReturn(Optional.of(shop));
        when(shopRepo.casUpdateStatus(11L, "pending", "rejected", null)).thenReturn(1);
        mvc.perform(post("/api/merchant/shops/11/resubmit").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"address\":\"杭州上城区湖滨路28号\"}")
                        .requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.status").value("pending"))
                .andExpect(jsonPath("$.data.address").value("杭州上城区湖滨路28号"));
    }

    @ParameterizedTest
    @CsvSource({"pending,skus", "pending,coupons", "pending,reviews", "rejected,skus", "rejected,coupons", "rejected,reviews"})
    void unapprovedShopCatalogAndReviewsAreHiddenFromPublicEvenForOwner(String state, String resource) throws Exception {
        when(shopRepo.findById(11L)).thenReturn(Optional.of(shop(11L, MERCHANT, state)));
        mvc.perform(get("/api/shops/11/" + resource).requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40001));
        verify(skuRepo, never()).findByShopIdOrderById(anyLong());
        verify(couponRepo, never()).findByShopIdAndEndAtAfter(anyLong(), any());
        verifyNoInteractions(reviewService);
    }

    @Test
    void adminHasPendingQueueButMerchantCannotUseIt() throws Exception {
        when(shopRepo.findAll()).thenReturn(List.of(shop(11L, MERCHANT, "pending"), shop(12L, MERCHANT, "approved")));
        mvc.perform(get("/api/admin/shops").requestAttr("userId", 1L).requestAttr("role", "ADMIN"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.length()").value(1))
                .andExpect(jsonPath("$.data[0].ownerId").value(MERCHANT));
        mvc.perform(get("/api/admin/shops").requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40300));
    }

    @Test
    void unreviewedListContainsOnlyRedeemedUnreviewedOrders() throws Exception {
        when(orderRepo.findByUserIdOrderByIdDesc(2L)).thenReturn(List.of(ownOrder, reviewedOrder, unreviewedOrder, otherOrder));
        mvc.perform(get("/api/orders").param("unreviewed", "true").requestAttr("userId", 2L))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.length()").value(1))
                .andExpect(jsonPath("$.data[0].id").value(3));
    }

    @Test
    void consumerCannotUseMerchantRedeemEntry() throws Exception {
        mvc.perform(post("/api/merchant/orders/1/redeem").requestAttr("userId", 2L).requestAttr("role", "USER"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40300));
        verifyNoInteractions(orderService);
    }

    @Test
    void ownedMerchantRedeemUsesConsumerOrderOwnershipWithoutPayingOrRefunding() throws Exception {
        when(orderRepo.findById(1L)).thenReturn(Optional.of(ownOrder));
        Order redeemed = order(1L, 11L, Order.REDEEMED);
        when(orderService.redeem(1L, 2L)).thenReturn(redeemed);
        mvc.perform(post("/api/merchant/orders/1/redeem").requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.status").value("REDEEMED"));
        verify(orderService).redeem(1L, 2L);
        verify(orderService, never()).pay(anyLong(), anyLong());
        verify(orderService, never()).refund(anyLong(), anyLong());
    }

    @Test
    void merchantCannotRedeemAnotherShopsOrder() throws Exception {
        when(orderRepo.findById(4L)).thenReturn(Optional.of(otherOrder));
        mvc.perform(post("/api/merchant/orders/4/redeem").requestAttr("userId", MERCHANT).requestAttr("role", "MERCHANT"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(40300));
        verifyNoInteractions(orderService);
    }

    private static Shop shop(long id, long owner, String status) {
        Shop shop = new Shop();
        ReflectionTestUtils.setField(shop, "id", id);
        shop.setOwnerId(owner);
        shop.setName("测试门店" + id);
        shop.setCategory("HOTPOT");
        shop.setCity("杭州");
        shop.setStatus(status);
        return shop;
    }

    private static Order order(long id, long shop, String status) {
        Order order = new Order();
        ReflectionTestUtils.setField(order, "id", id);
        order.setUserId(2L);
        order.setShopId(shop);
        order.setSkuId(7L);
        order.setPriceSnapshot(11300);
        order.setStatus(status);
        order.setExpireAt(Instant.now().plusSeconds(900));
        return order;
    }

    private static Coupon coupon() {
        Coupon coupon = new Coupon();
        ReflectionTestUtils.setField(coupon, "id", 9L);
        coupon.setShopId(11L);
        coupon.setTitle("满100减15");
        coupon.setThreshold(10000);
        coupon.setAmount(1500);
        coupon.setTotal(10);
        coupon.setStartAt(Instant.now().minusSeconds(60));
        coupon.setEndAt(Instant.now().plusSeconds(3600));
        return coupon;
    }

    private static Sku catalogSku() {
        Sku sku = new Sku();
        ReflectionTestUtils.setField(sku, "id", 7L);
        sku.setShopId(11L);
        sku.setTitle("双人套餐");
        sku.setPrice(12800);
        sku.setStock(8);
        sku.setOnSale(true);
        return sku;
    }

    private static void setAddressWhenAvailable(Shop shop, String address) {
        BeanWrapper bean = new BeanWrapperImpl(shop);
        if (bean.isWritableProperty("address")) bean.setPropertyValue("address", address);
    }
}
