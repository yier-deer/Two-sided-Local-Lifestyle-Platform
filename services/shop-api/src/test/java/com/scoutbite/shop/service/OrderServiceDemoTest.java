package com.scoutbite.shop.service;

import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.*;
import com.scoutbite.shop.repository.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class OrderServiceDemoTest {
    private static final long USER = 2L;
    final Map<Long, Order> persisted = new HashMap<>();
    OrderRepository orderRepo;
    SkuRepository skuRepo;
    UserCouponRepository userCouponRepo;
    CouponRepository couponRepo;
    ShopRepository shopRepo;
    StringRedisTemplate redis;
    OrderService service;
    Sku sku;
    UserCoupon userCoupon;
    Coupon coupon;

    @BeforeEach
    void setUp() {
        orderRepo = mock(OrderRepository.class);
        skuRepo = mock(SkuRepository.class);
        couponRepo = mock(CouponRepository.class);
        shopRepo = mock(ShopRepository.class);
        Shop shop = new Shop();
        ReflectionTestUtils.setField(shop, "id", 11L);
        shop.setOwnerId(5L);
        shop.setStatus("approved");
        when(shopRepo.findById(11L)).thenReturn(Optional.of(shop));
        redis = mock(StringRedisTemplate.class);
        when(redis.opsForZSet()).thenReturn(mock(ZSetOperations.class));
        sku = new Sku();
        ReflectionTestUtils.setField(sku, "id", 7L);
        sku.setShopId(11L);
        sku.setTitle("双人套餐");
        sku.setPrice(12800);
        sku.setStock(10);
        sku.setOnSale(true);
        coupon = new Coupon();
        ReflectionTestUtils.setField(coupon, "id", 9L);
        coupon.setShopId(11L);
        coupon.setThreshold(10000);
        coupon.setAmount(1500);
        coupon.setStartAt(Instant.now().minusSeconds(60));
        coupon.setEndAt(Instant.now().plusSeconds(3600));
        userCoupon = new UserCoupon();
        ReflectionTestUtils.setField(userCoupon, "id", 13L);
        userCoupon.setUserId(USER);
        userCoupon.setCouponId(9L);
        userCoupon.setStatus(UserCoupon.UNUSED);
        // The fake persistence boundary models both existing freeze/release and the requested refund restoration.
        userCouponRepo = mock(UserCouponRepository.class, invocation -> {
            return switch (invocation.getMethod().getName()) {
                case "releaseAfterRefund" -> {
                    if (java.util.Objects.equals(userCoupon.getOrderId(), invocation.getArgument(0))
                            && (UserCoupon.FROZEN.equals(userCoupon.getStatus()) || UserCoupon.USED.equals(userCoupon.getStatus()))) {
                        userCoupon.setStatus(UserCoupon.UNUSED);
                        userCoupon.setOrderId(null);
                        yield 1;
                    }
                    yield 0;
                }
                default -> org.mockito.Answers.RETURNS_DEFAULTS.answer(invocation);
            };
        });
        when(skuRepo.findById(7L)).thenReturn(Optional.of(sku));
        when(couponRepo.findById(9L)).thenReturn(Optional.of(coupon));
        when(userCouponRepo.findById(13L)).thenReturn(Optional.of(userCoupon));
        when(orderRepo.findById(anyLong())).thenAnswer(inv -> Optional.ofNullable(persisted.get(inv.getArgument(0))));
        when(orderRepo.findByIdempotencyKey(anyString())).thenAnswer(inv -> persisted.values().stream()
                .filter(o -> o.getIdempotencyKey().equals(inv.getArgument(0))).findFirst());
        when(orderRepo.save(any(Order.class))).thenAnswer(inv -> {
            Order order = inv.getArgument(0);
            ReflectionTestUtils.setField(order, "id", 1L);
            persisted.put(1L, order);
            return order;
        });
        when(skuRepo.tryDeductStock(7L)).thenAnswer(inv -> {
            if (sku.getStock() <= 0) return 0;
            sku.setStock(sku.getStock() - 1);
            return 1;
        });
        when(skuRepo.restock(7L)).thenAnswer(inv -> { sku.setStock(sku.getStock() + 1); return 1; });
        when(userCouponRepo.freeze(eq(13L), eq(USER), anyLong())).thenAnswer(inv -> {
            if (!UserCoupon.UNUSED.equals(userCoupon.getStatus())) return 0;
            userCoupon.setStatus(UserCoupon.FROZEN);
            userCoupon.setOrderId(inv.getArgument(2));
            return 1;
        });
        when(userCouponRepo.use(anyLong())).thenAnswer(inv -> {
            if (!UserCoupon.FROZEN.equals(userCoupon.getStatus())) return 0;
            userCoupon.setStatus(UserCoupon.USED);
            return 1;
        });
        when(userCouponRepo.release(anyLong())).thenAnswer(inv -> {
            if (!UserCoupon.FROZEN.equals(userCoupon.getStatus())) return 0;
            userCoupon.setStatus(UserCoupon.UNUSED);
            userCoupon.setOrderId(null);
            return 1;
        });
        when(orderRepo.payCas(anyLong(), anyLong())).thenAnswer(inv -> changeState(inv.getArgument(0), inv.getArgument(1), Order.CREATED, Order.PAID));
        when(orderRepo.refundCas(anyLong(), anyLong())).thenAnswer(inv -> changeState(inv.getArgument(0), inv.getArgument(1), Order.PAID, Order.REFUNDED));
        when(orderRepo.cancelCas(anyLong(), anyLong())).thenAnswer(inv -> changeState(inv.getArgument(0), inv.getArgument(1), Order.CREATED, Order.CANCELLED_USER));
        when(orderRepo.redeemCas(anyLong(), anyLong())).thenAnswer(inv -> changeState(inv.getArgument(0), inv.getArgument(1), Order.PAID, Order.REDEEMED));
        TransactionTemplate tx = new TransactionTemplate(new PlatformTransactionManager() {
            public TransactionStatus getTransaction(TransactionDefinition definition) { return new SimpleTransactionStatus(); }
            public void commit(TransactionStatus status) { }
            public void rollback(TransactionStatus status) { }
        });
        service = new OrderService(orderRepo, skuRepo, shopRepo, userCouponRepo, couponRepo, redis, tx, 900);
    }

    @Test
    void qualifyingCouponReducesAmountInCentsAndFreezesOnlyThatCoupon() {
        Order order = service.create(USER, 7L, 13L, "checkout-1");
        assertEquals(11300, order.getPriceSnapshot());
        assertEquals(9L, order.getCouponId());
        assertEquals(UserCoupon.FROZEN, userCoupon.getStatus());
        assertEquals(9, sku.getStock());
    }

    @Test
    void differentShopCouponIsRejectedBeforeCreatingOrderOrDeductingStock() {
        coupon.setShopId(99L);
        var error = assertThrows(OrderService.BizException.class, () -> service.create(USER, 7L, 13L, "wrong-shop"));
        assertEquals(ErrorCode.PARAM_ERROR, error.code);
        assertEquals(10, sku.getStock());
        assertEquals(UserCoupon.UNUSED, userCoupon.getStatus());
        assertTrue(persisted.isEmpty());
    }

    @Test
    void expiredCouponCannotBeFrozenAtCheckout() {
        coupon.setEndAt(Instant.now().minusSeconds(1));
        assertThrows(OrderService.BizException.class, () -> service.create(USER, 7L, 13L, "expired"));
        assertTrue(persisted.isEmpty());
        assertEquals(UserCoupon.UNUSED, userCoupon.getStatus());
    }

    @Test
    void repeatCheckoutReturnsSameOrderWithoutMoreStockOrCouponDeductions() {
        Order first = service.create(USER, 7L, 13L, "retry-1");
        Order repeated = service.create(USER, 7L, 13L, "retry-1");
        assertSame(first, repeated);
        assertEquals(9, sku.getStock());
        assertEquals(1, persisted.size());
    }

    @Test
    void idempotencyKeyDoesNotExposeAnotherUsersOrder() {
        service.create(USER, 7L, null, "private-key");
        assertThrows(OrderService.BizException.class, () -> service.create(8L, 7L, null, "private-key"));
    }

    @Test
    void paidRefundRestoresUsedCouponAndStockExactlyOnce() {
        Order order = service.create(USER, 7L, 13L, "refund-1");
        service.pay(order.getId(), USER);
        assertEquals(UserCoupon.USED, userCoupon.getStatus());
        service.refund(order.getId(), USER);
        assertEquals(Order.REFUNDED, order.getStatus());
        assertEquals(UserCoupon.UNUSED, userCoupon.getStatus());
        assertNull(userCoupon.getOrderId());
        assertEquals(10, sku.getStock());
        assertThrows(OrderService.BizException.class, () -> service.refund(order.getId(), USER));
        assertEquals(10, sku.getStock());
    }

    @Test
    void unpaidCancellationRestoresFrozenCouponAndStockExactlyOnce() {
        Order order = service.create(USER, 7L, 13L, "cancel-1");
        service.cancel(order.getId(), USER);
        assertEquals(UserCoupon.UNUSED, userCoupon.getStatus());
        assertEquals(10, sku.getStock());
        assertThrows(OrderService.BizException.class, () -> service.cancel(order.getId(), USER));
        assertEquals(10, sku.getStock());
    }

    @Test
    void pendingShopCannotSellPreparedSkuOrFreezeUserCoupon() {
        Shop pending = new Shop();
        pending.setStatus("pending");
        when(shopRepo.findById(11L)).thenReturn(Optional.of(pending));
        assertThrows(OrderService.BizException.class, () -> service.create(USER, 7L, 13L, "pending-checkout"));
        assertTrue(persisted.isEmpty());
        assertEquals(10, sku.getStock());
        assertEquals(UserCoupon.UNUSED, userCoupon.getStatus());
    }

    private int changeState(Long id, Long user, String from, String to) {
        Order order = persisted.get(id);
        if (order == null || !order.getUserId().equals(user) || !from.equals(order.getStatus())) return 0;
        order.setStatus(to);
        return 1;
    }
}
