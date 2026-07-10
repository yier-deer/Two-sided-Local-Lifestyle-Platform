package com.scoutbite.shop.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.Order;
import com.scoutbite.shop.entity.Review;
import com.scoutbite.shop.entity.ReviewReply;
import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.repository.OrderRepository;
import com.scoutbite.shop.repository.ReviewReplyRepository;
import com.scoutbite.shop.repository.ReviewRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.repository.UserRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 评价服务：发布（四道校验）与回复（is_merchant 服务端判定）。
 *
 * 反刷评三道闸：
 *  ① 订单属于当前用户（越权防护）
 *  ② status == REDEEMED（付了钱没消费不能评——反「好评返现式刷评」）
 *  ③ order_id 唯一索引（一单一评，撞索引转 40901）
 */
@Service
public class ReviewService {

    private static final Logger log = LoggerFactory.getLogger(ReviewService.class);

    private final ReviewRepository reviewRepo;
    private final ReviewReplyRepository replyRepo;
    private final OrderRepository orderRepo;
    private final ShopRepository shopRepo;
    private final UserRepository userRepo;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ReviewService(ReviewRepository reviewRepo,
                         ReviewReplyRepository replyRepo,
                         OrderRepository orderRepo,
                         ShopRepository shopRepo,
                         UserRepository userRepo) {
        this.reviewRepo = reviewRepo;
        this.replyRepo = replyRepo;
        this.orderRepo = orderRepo;
        this.shopRepo = shopRepo;
        this.userRepo = userRepo;
    }

    /**
     * 发布评价。四道校验顺序：归属 → REDEEMED → 分数/正文格式 → 唯一索引。
     * @param scores 多维分数（如 {taste:5, wait:3, env:4}），每维 1~5
     */
    public Map<String, Object> create(Long userId, Long orderId,
                                      Map<String, Integer> scores,
                                      String content, String imageKeysCsv) {
        // ① 归属校验
        Order order = orderRepo.findById(orderId).orElse(null);
        if (order == null || !order.getUserId().equals(userId)) {
            throw new OrderService.BizException(ErrorCode.PARAM_ERROR, "订单不存在");
        }
        // ② 状态校验：只有核销过（真实消费）才能评
        if (!Order.REDEEMED.equals(order.getStatus())) {
            throw new OrderService.BizException(ErrorCode.STATE_CONFLICT,
                    "只有已核销订单可以评价（当前状态 " + order.getStatus() + "）");
        }
        // ③ 格式校验
        if (scores == null || scores.isEmpty()) {
            throw new OrderService.BizException(ErrorCode.PARAM_ERROR, "scores 至少一个维度（如 taste/wait/env）");
        }
        for (Map.Entry<String, Integer> e : scores.entrySet()) {
            if (e.getValue() == null || e.getValue() < 1 || e.getValue() > 5) {
                throw new OrderService.BizException(ErrorCode.PARAM_ERROR,
                        "分数维度 " + e.getKey() + " 必须在 1~5");
            }
        }
        if (content == null || content.isBlank() || content.length() > 500) {
            throw new OrderService.BizException(ErrorCode.PARAM_ERROR, "正文 1~500 字");
        }
        // 预检：已评过直接 40901（幂等友好路径）
        if (reviewRepo.findByOrderId(orderId).isPresent()) {
            throw new OrderService.BizException(ErrorCode.IDEMPOTENT_CONFLICT, "该订单已评价过");
        }

        Review r = new Review();
        r.setOrderId(orderId);
        r.setShopId(order.getShopId());
        r.setUserId(userId);
        try {
            r.setScoresJson(objectMapper.writeValueAsString(scores));
        } catch (Exception e) {
            throw new OrderService.BizException(ErrorCode.PARAM_ERROR, "scores 序列化失败");
        }
        r.setContent(content);
        r.setImages(imageKeysCsv);
        try {
            reviewRepo.saveAndFlush(r);   // flush 让唯一索引立刻触发（好 catch）
        } catch (DataIntegrityViolationException e) {
            // ③ 并发双评撞 uq_reviews_order → 40901（唯一索引兜底）
            log.info("订单 {} 并发重复评价，被唯一索引拦截", orderId);
            throw new OrderService.BizException(ErrorCode.IDEMPOTENT_CONFLICT, "该订单已评价过");
        }
        log.info("订单 {} 评价发布成功（review={}）", orderId, r.getId());
        return toDto(r, null);
    }

    /**
     * 回复评价：is_merchant 由服务端判定（token role=MERCHANT 且是该店 owner），
     * 请求体里的任何身份字段一概不采信。普通用户也能回复，只是没有商家标。
     */
    public Map<String, Object> reply(Long userId, String role, Long reviewId, String content) {
        if (content == null || content.isBlank() || content.length() > 300) {
            throw new OrderService.BizException(ErrorCode.PARAM_ERROR, "回复内容 1~300 字");
        }
        Review review = reviewRepo.findById(reviewId).orElse(null);
        if (review == null) {
            throw new OrderService.BizException(ErrorCode.PARAM_ERROR, "评价不存在");
        }
        // 商家判定链：角色 → 店铺归属
        boolean isMerchant = false;
        if ("MERCHANT".equals(role)) {
            Shop shop = shopRepo.findById(review.getShopId()).orElse(null);
            isMerchant = shop != null && shop.getOwnerId().equals(userId);
        }

        ReviewReply rp = new ReviewReply();
        rp.setReviewId(reviewId);
        rp.setUserId(userId);
        rp.setContent(content);
        rp.setMerchant(isMerchant);
        replyRepo.save(rp);
        return toReplyDto(rp);
    }

    /** 店页评价列表（公开）：带每条的回复（含商家标） */
    public List<Map<String, Object>> listByShop(Long shopId) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (Review r : reviewRepo.findByShopIdOrderByIdDesc(shopId)) {
            List<Map<String, Object>> replies = replyRepo.findByReviewIdOrderById(r.getId())
                    .stream().map(this::toReplyDto).toList();
            result.add(toDto(r, replies));
        }
        return result;
    }

    private Map<String, Object> toDto(Review r, List<Map<String, Object>> replies) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", r.getId());
        m.put("orderId", r.getOrderId());
        m.put("shopId", r.getShopId());
        m.put("userId", r.getUserId());
        m.put("nickname", userRepo.findById(r.getUserId())
                .map(u -> u.getNickname()).orElse("匿名用户"));
        try {
            m.put("scores", objectMapper.readValue(r.getScoresJson(), Map.class));
        } catch (Exception e) {
            m.put("scores", Map.of());
        }
        m.put("content", r.getContent());
        m.put("createdAt", r.getCreatedAt().toString());
        if (replies != null) m.put("replies", replies);
        return m;
    }

    private Map<String, Object> toReplyDto(ReviewReply rp) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", rp.getId());
        m.put("reviewId", rp.getReviewId());
        m.put("userId", rp.getUserId());
        m.put("nickname", userRepo.findById(rp.getUserId())
                .map(u -> u.getNickname()).orElse("匿名用户"));
        m.put("content", rp.getContent());
        m.put("isMerchant", rp.isMerchant());   // 服务端判定的商家标
        m.put("createdAt", rp.getCreatedAt().toString());
        return m;
    }
}
