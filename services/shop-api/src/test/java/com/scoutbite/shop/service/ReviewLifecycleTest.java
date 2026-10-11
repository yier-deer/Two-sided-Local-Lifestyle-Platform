package com.scoutbite.shop.service;

import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.Order;
import com.scoutbite.shop.entity.Review;
import com.scoutbite.shop.repository.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ReviewLifecycleTest {
    Order order;
    ReviewRepository reviews;
    OrderRepository orders;
    ReviewService service;

    @BeforeEach
    void setUp() {
        order = new Order();
        ReflectionTestUtils.setField(order, "id", 21L);
        order.setUserId(2L);
        order.setShopId(11L);
        order.setSkuId(7L);
        order.setStatus(Order.REDEEMED);
        reviews = mock(ReviewRepository.class);
        orders = mock(OrderRepository.class);
        when(orders.findById(21L)).thenReturn(Optional.of(order));
        when(reviews.findByOrderId(21L)).thenReturn(Optional.empty());
        when(reviews.saveAndFlush(any())).thenAnswer(inv -> {
            Review review = inv.getArgument(0);
            ReflectionTestUtils.setField(review, "id", 30L);
            ReflectionTestUtils.setField(review, "createdAt", Instant.now());
            return review;
        });
        service = new ReviewService(reviews, mock(ReviewReplyRepository.class), orders, mock(ShopRepository.class), mock(UserRepository.class));
    }

    @Test
    void publishingReviewCompletesOrderLifecycle() {
        Map<String, Object> result = service.create(2L, 21L, Map.of("taste", 5, "wait", 4, "env", 5), "本人的消费评价", null);
        assertEquals(Order.REVIEWED, order.getStatus());
        assertEquals("本人的消费评价", result.get("content"));
        assertEquals(21L, result.get("orderId"));
    }

    @Test
    void completedOrderCannotPublishSecondReview() {
        service.create(2L, 21L, Map.of("taste", 5), "第一次评价", null);
        var error = assertThrows(OrderService.BizException.class, () -> service.create(2L, 21L, Map.of("taste", 5), "第二次评价", null));
        assertEquals(ErrorCode.IDEMPOTENT_CONFLICT, error.code);
        verify(reviews, times(1)).saveAndFlush(any());
    }

    @Test
    void paidButNotRedeemedOrderCannotPublish() {
        order.setStatus(Order.PAID);
        assertThrows(OrderService.BizException.class, () -> service.create(2L, 21L, Map.of("taste", 5), "尚未消费", null));
        verify(reviews, never()).saveAndFlush(any());
    }
}
