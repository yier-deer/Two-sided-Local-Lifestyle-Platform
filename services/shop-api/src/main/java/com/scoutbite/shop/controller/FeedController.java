package com.scoutbite.shop.controller;

import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.Like;
import com.scoutbite.shop.entity.Post;
import com.scoutbite.shop.repository.LikeRepository;
import com.scoutbite.shop.repository.PostRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.service.FeedService;
import com.scoutbite.shop.service.OrderService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * Feed 分组（变真）：信息流（推流五因子）+ 发帖 + 点赞。
 * 信息流公开（游客可刷）；发帖点赞需登录。
 */
@RestController
@Tag(name = "Feed", description = "信息流（推流五因子）与发帖点赞")
public class FeedController {

    private final FeedService feedService;
    private final PostRepository postRepo;
    private final LikeRepository likeRepo;
    private final ShopRepository shopRepo;

    public FeedController(FeedService feedService, PostRepository postRepo,
                          LikeRepository likeRepo, ShopRepository shopRepo) {
        this.feedService = feedService;
        this.postRepo = postRepo;
        this.likeRepo = likeRepo;
        this.shopRepo = shopRepo;
    }

    /**
     * 信息流：scene 三队列 + 推流公式 + 同店去重 + 曝光日志。
     * explore 是请求级开关——验收要求「关掉开关后新店几乎消失」的同屏对比演示。
     */
    @Operation(summary = "信息流（scene=nearby|hot|new；explore 开关可对比）")
    @GetMapping("/api/feed")
    public ApiResponse<?> feed(@RequestParam(defaultValue = "nearby") String scene,
                               @RequestParam(required = false) Double lat,
                               @RequestParam(required = false) Double lng,
                               @RequestParam(defaultValue = "true") boolean explore,
                               @RequestParam(defaultValue = "20") int limit,
                               HttpServletRequest request) {
        if (!Set.of("nearby", "hot", "new").contains(scene)) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "scene 只能是 nearby/hot/new");
        }
        Long userId = (Long) request.getAttribute("userId");   // 游客为 null（/api/feed 白名单）
        return ApiResponse.ok(feedService.feed(scene, lat, lng, explore, userId,
                Math.clamp(limit, 1, 50)));
    }

    /** 发帖：可关联店铺（shopId 可空——纯分享） */
    @Operation(summary = "发帖（可关联店铺）")
    @PostMapping("/api/posts")
    public ApiResponse<?> post(@RequestBody Map<String, Object> body, HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");

        String content = (String) body.get("content");
        if (content == null || content.isBlank() || content.length() > 1000) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "正文 1~1000 字");
        }
        Long shopId = body.get("shopId") instanceof Number n ? n.longValue() : null;
        if (shopId != null && shopRepo.findById(shopId).isEmpty()) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "关联店铺不存在");
        }

        Post p = new Post();
        p.setUserId(userId);
        p.setShopId(shopId);
        p.setContent(content);
        postRepo.save(p);

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", p.getId());
        m.put("shopId", p.getShopId());
        m.put("content", p.getContent());
        return ApiResponse.ok(m);
    }

    /** 点赞：body { targetType: POST|REVIEW|SHOP, targetId }；重复点赞 40901 */
    @Operation(summary = "点赞（画像的原料）")
    @PostMapping("/api/likes")
    public ApiResponse<?> like(@RequestBody Map<String, Object> body, HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");

        String targetType = (String) body.get("targetType");
        Long targetId = body.get("targetId") instanceof Number n ? n.longValue() : null;
        if (!Set.of("POST", "REVIEW", "SHOP").contains(targetType) || targetId == null) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "targetType ∈ POST/REVIEW/SHOP，targetId 必填");
        }
        // 幂等预检
        if (likeRepo.existsByUserIdAndTargetTypeAndTargetId(userId, targetType, targetId)) {
            return ApiResponse.fail(ErrorCode.IDEMPOTENT_CONFLICT, "已赞过");
        }
        Like l = new Like();
        l.setUserId(userId);
        l.setTargetType(targetType);
        l.setTargetId(targetId);
        try {
            likeRepo.saveAndFlush(l);
        } catch (DataIntegrityViolationException e) {
            // 联合唯一索引兜底（并发双击）
            return ApiResponse.fail(ErrorCode.IDEMPOTENT_CONFLICT, "已赞过");
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("targetType", targetType);
        m.put("targetId", targetId);
        m.put("likeCount", likeRepo.countByTargetTypeAndTargetId(targetType, targetId));
        return ApiResponse.ok(m);
    }
}
