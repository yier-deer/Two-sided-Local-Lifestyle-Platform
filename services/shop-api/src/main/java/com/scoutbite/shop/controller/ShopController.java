package com.scoutbite.shop.controller;

import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.service.GeoService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.transaction.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Shop 分组（变真）：nearby 检索、详情可见性、商家建店、管理员审核。
 * 状态机：pending → approved / rejected；rejected 改资料后可回 pending。
 * 可见性设计：approved 任何人可见；其他状态仅店主人可见（数据问题，不是权限问题）。
 */
@RestController
@Tag(name = "Shop", description = "附近店铺检索、详情与商家入驻审核")
public class ShopController {

    private final ShopRepository shopRepo;
    private final GeoService geoService;
    private final com.scoutbite.shop.repository.SkuRepository skuRepo;

    public ShopController(ShopRepository shopRepo, GeoService geoService,
                          com.scoutbite.shop.repository.SkuRepository skuRepo) {
        this.shopRepo = shopRepo;
        this.geoService = geoService;
        this.skuRepo = skuRepo;
    }

    // ==================== 用户侧：看店（白名单，游客可用） ====================

    /** 附近店铺：盒粗筛 + Haversine 精算 + 距离排序（status=approved 在 SQL 强制） */
    @Operation(summary = "附近店铺，按距离排序")
    @GetMapping("/api/shops/nearby")
    public ApiResponse<?> nearby(@RequestParam double lat,
                                 @RequestParam double lng,
                                 @RequestParam(defaultValue = "3000") int radius,
                                 @RequestParam(required = false) String category) {
        if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "经纬度非法");
        }
        if (radius < 100 || radius > 50000) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "radius 取值 100~50000 米");
        }
        return ApiResponse.ok(geoService.nearby(lat, lng, radius, category));
    }

    /** 店铺详情：approved 公开可见；未过审只对店主人可见 */
    @Operation(summary = "店铺详情（approved 公开；其他状态仅店主人可见）")
    @GetMapping("/api/shops/{id}")
    public ApiResponse<?> detail(@PathVariable Long id, HttpServletRequest request) {
        Shop s = shopRepo.findById(id).orElse(null);
        if (s == null) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "店铺不存在");
        }
        // 白名单路径可能无票：userId 为 null 表示游客
        Long userId = (Long) request.getAttribute("userId");
        boolean owner = userId != null && userId.equals(s.getOwnerId());
        if (!"approved".equals(s.getStatus()) && !owner) {
            // 故意报"不存在"而非"无权限"——对外不可见的店等同于不存在
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "店铺不存在");
        }
        return ApiResponse.ok(toDto(s, owner));
    }

    // ==================== 商家侧：建店与我的店（需登录 + MERCHANT） ====================

    /** 建店：创建即 pending（状态机入口），等管理员审核 */
    @Operation(summary = "商家建店（提交后进入待审核）")
    @PostMapping("/api/merchant/shops")
    public ApiResponse<?> create(@RequestBody Map<String, Object> body, HttpServletRequest request) {
        Long userId = requireUser(request);
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        String role = (String) request.getAttribute("role");
        if (!"MERCHANT".equals(role)) {
            return ApiResponse.fail(ErrorCode.FORBIDDEN, "只有商家角色可以建店");
        }

        String name = (String) body.get("name");
        String category = (String) body.get("category");
        Double lat = toDouble(body.get("lat"));
        Double lng = toDouble(body.get("lng"));
        if (name == null || name.isBlank() || category == null || lat == null || lng == null) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "name/category/lat/lng 必填");
        }
        if (!List.of("HOTPOT", "COFFEE", "ENTERTAIN").contains(category)) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "category 只能是 HOTPOT/COFFEE/ENTERTAIN");
        }

        Shop s = new Shop();
        s.setOwnerId(userId);
        s.setName(name);
        s.setCategory(category);
        s.setCity((String) body.getOrDefault("city", "杭州"));
        s.setLat(lat);
        s.setLng(lng);
        s.setStatus("pending");
        shopRepo.save(s);
        return ApiResponse.ok(Map.of("id", s.getId(), "status", s.getStatus(),
                "message", "已提交，等待管理员审核"));
    }

    /** 我的小店：商家查自己名下店铺（含各状态——商家需要看到审核进展） */
    @Operation(summary = "我的小店（商家查看各状态）")
    @GetMapping("/api/merchant/shops")
    public ApiResponse<?> myShops(HttpServletRequest request) {
        Long userId = requireUser(request);
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        List<Map<String, Object>> list = shopRepo.findByOwnerIdOrderByIdDesc(userId)
                .stream().map(s -> toDto(s, true)).toList();
        return ApiResponse.ok(list);
    }

    /** 改资料重新提交：仅 rejected 店可改回 pending（状态机回环） */
    @Operation(summary = "改资料重新提交（仅 rejected 可回 pending）")
    @PostMapping("/api/merchant/shops/{id}/resubmit")
    @Transactional
    public ApiResponse<?> resubmit(@PathVariable Long id,
                                   @RequestBody Map<String, Object> body,
                                   HttpServletRequest request) {
        Long userId = requireUser(request);
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");

        Shop s = shopRepo.findById(id).orElse(null);
        if (s == null || !s.getOwnerId().equals(userId)) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "店铺不存在");
        }
        // 资料更新（传了才改）
        if (body.containsKey("name")) s.setName((String) body.get("name"));
        if (body.containsKey("category")) s.setCategory((String) body.get("category"));
        Double lat = toDouble(body.get("lat"));
        if (lat != null) s.setLat(lat);
        Double lng = toDouble(body.get("lng"));
        if (lng != null) s.setLng(lng);
        shopRepo.save(s);

        // CAS：只有 rejected 能回 pending
        int rows = shopRepo.casUpdateStatus(id, "pending", "rejected", null);
        if (rows == 0) {
            return ApiResponse.fail(ErrorCode.STATE_CONFLICT, "只有被驳回的店可以重新提交");
        }
        return ApiResponse.ok(Map.of("id", id, "status", "pending"));
    }

    // ==================== 管理员侧：审核（需登录 + ADMIN） ====================

    /** 审核通过：CAS 保证只有 pending 能过（防"已驳回又通过"的并发鬼畜） */
    @Operation(summary = "管理员审核通过")
    @PostMapping("/api/admin/shops/{id}/approve")
    @Transactional
    public ApiResponse<?> approve(@PathVariable Long id, HttpServletRequest request) {
        String err = requireAdmin(request);
        if (err != null) return ApiResponse.fail(ErrorCode.FORBIDDEN, err);

        int rows = shopRepo.casUpdateStatus(id, "approved", "pending", Instant.now());
        if (rows == 0) {
            return ApiResponse.fail(ErrorCode.STATE_CONFLICT, "状态机冲突：该店不在待审核状态");
        }
        return ApiResponse.ok(Map.of("id", id, "status", "approved"));
    }

    /** 审核驳回：同样 CAS */
    @Operation(summary = "管理员审核驳回")
    @PostMapping("/api/admin/shops/{id}/reject")
    @Transactional
    public ApiResponse<?> reject(@PathVariable Long id, HttpServletRequest request) {
        String err = requireAdmin(request);
        if (err != null) return ApiResponse.fail(ErrorCode.FORBIDDEN, err);

        int rows = shopRepo.casUpdateStatus(id, "rejected", "pending", null);
        if (rows == 0) {
            return ApiResponse.fail(ErrorCode.STATE_CONFLICT, "状态机冲突：该店不在待审核状态");
        }
        return ApiResponse.ok(Map.of("id", id, "status", "rejected"));
    }

    /** 店铺的套餐列表（公开，白名单路径 /api/shops/**）：只回上架的 */
    @Operation(summary = "店铺套餐列表（公开）")
    @GetMapping("/api/shops/{shopId}/skus")
    public ApiResponse<?> shopSkus(@PathVariable Long shopId) {
        return ApiResponse.ok(skuRepo.findByShopIdOrderById(shopId).stream()
                .filter(com.scoutbite.shop.entity.Sku::isOnSale)
                .map(this::skuDto).toList());
    }

    /** SKU 简版 DTO（店页展示） */
    private Map<String, Object> skuDto(com.scoutbite.shop.entity.Sku s) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", s.getId());
        m.put("shopId", s.getShopId());
        m.put("title", s.getTitle());
        m.put("price", s.getPrice());      // 分
        m.put("stock", s.getStock());
        m.put("sales", s.getSales());
        return m;
    }

    // ==================== 私有辅助 ====================

    /** 从 request 取用户 ID（JwtFilter 塞的）；无则 null */
    private Long requireUser(HttpServletRequest request) {
        return (Long) request.getAttribute("userId");
    }

    /** 校验管理员角色；返回 null 表示通过，否则返回错误信息 */
    private String requireAdmin(HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        String role = (String) request.getAttribute("role");
        if (userId == null) return "未登录";
        if (!"ADMIN".equals(role)) return "只有管理员可以审核";
        return null;
    }

    /** Map 取 Double（JSON 数字可能是 Integer/Double） */
    private Double toDouble(Object o) {
        return o instanceof Number n ? n.doubleValue() : null;
    }

    /** 实体转输出 DTO（不暴露 ownerId 给非店主人；不暴露任何敏感字段） */
    private Map<String, Object> toDto(Shop s, boolean owner) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", s.getId());
        m.put("name", s.getName());
        m.put("category", s.getCategory());
        m.put("city", s.getCity());
        m.put("lat", s.getLat());
        m.put("lng", s.getLng());
        m.put("status", s.getStatus());
        m.put("approvedAt", s.getApprovedAt() == null ? null : s.getApprovedAt().toString());
        if (owner) m.put("ownerId", s.getOwnerId());
        return m;
    }
}
