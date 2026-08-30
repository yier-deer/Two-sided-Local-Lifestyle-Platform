package com.scoutbite.shop.controller;

import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.User;
import com.scoutbite.shop.repository.UserRepository;
import com.scoutbite.shop.security.JwtUtil;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Auth 分组（从骨架变真）：注册 / 登录 / 当前用户。
 * 安全要点：
 *  - 密码 BCrypt 哈希入库，永不明文、永不出库
 *  - 登录失败统一报"手机号或密码错误"（防枚举探测）
 *  - 角色白名单校验：ADMIN 不开放注册（只能从种子进）
 */
@RestController
@RequestMapping("/api/auth")
@Tag(name = "Auth", description = "注册登录与当前用户")
public class AuthController {

    private final UserRepository userRepo;
    private final JwtUtil jwtUtil;

    /** BCrypt：自带随机盐 + 故意慢（demo 用默认 cost 10） */
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();

    public AuthController(UserRepository userRepo, JwtUtil jwtUtil) {
        this.userRepo = userRepo;
        this.jwtUtil = jwtUtil;
    }

    /** 注册：选角色 USER / MERCHANT */
    @Operation(summary = "注册，选角色 USER/MERCHANT")
    @PostMapping("/register")
    public ApiResponse<?> register(@RequestBody Map<String, String> body) {
        String phone = body.get("phone");
        String password = body.get("password");
        String role = body.getOrDefault("role", "USER");
        String nickname = body.get("nickname");

        // 参数校验
        if (phone == null || phone.isBlank() || password == null || password.length() < 6) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "手机号必填，密码至少 6 位");
        }
        // 角色白名单：ADMIN 只能从种子进，不开放注册
        if (!"USER".equals(role) && !"MERCHANT".equals(role)) {
            return ApiResponse.fail(ErrorCode.PARAM_ERROR, "role 只能是 USER 或 MERCHANT");
        }
        // 唯一性：手机号已注册 → 40901（幂等冲突口径）
        if (userRepo.findByPhone(phone).isPresent()) {
            return ApiResponse.fail(ErrorCode.IDEMPOTENT_CONFLICT, "该手机号已注册");
        }

        User u = new User();
        u.setPhone(phone);
        u.setPasswordHash(encoder.encode(password));
        u.setRole(role);
        u.setNickname(nickname == null || nickname.isBlank() ? "用户" + phone.substring(Math.max(0, phone.length() - 4)) : nickname);
        userRepo.save(u);
        return ApiResponse.ok(Map.of("id", u.getId(), "role", u.getRole(), "nickname", u.getNickname()));
    }

    /** 登录：返回 JWT（sub=用户ID，role 走 claim） */
    @Operation(summary = "登录，返回 JWT")
    @PostMapping("/login")
    public ApiResponse<?> login(@RequestBody Map<String, String> body) {
        String phone = body.getOrDefault("phone", "");
        String password = body.getOrDefault("password", "");

        User u = userRepo.findByPhone(phone).orElse(null);
        // 防枚举：用户不存在与密码错误返回同一句话；且不存在时也做一次哈希比对（拉平耗时）
        boolean ok = u != null && encoder.matches(password, u.getPasswordHash());
        if (u == null) {
            encoder.matches(password, DUMMY_HASH);   // 对假哈希算一次，防时序探测
        }
        if (!ok) {
            return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "手机号或密码错误");
        }
        return ApiResponse.ok(Map.of(
                "token", jwtUtil.issue(u.getId(), u.getRole()),
                "role", u.getRole(),
                "nickname", u.getNickname(),
                "userId", u.getId()));
    }

    /** 当前用户：身份来自 JwtFilter 塞进 request 的 attribute */
    @Operation(summary = "当前用户（需带 Authorization: Bearer）")
    @GetMapping("/me")
    public ApiResponse<?> me(HttpServletRequest request) {
        Long userId = (Long) request.getAttribute("userId");
        if (userId == null) {
            return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        }
        return userRepo.findById(userId)
                .map(u -> ApiResponse.ok(Map.of(
                        "id", u.getId(),
                        "phone", u.getPhone(),
                        "role", u.getRole(),
                        "nickname", u.getNickname())))
                .orElseGet(() -> ApiResponse.fail(ErrorCode.UNAUTHORIZED, "用户不存在"));
    }

    /** 假哈希：仅用于登录失败时拉平耗时（防时序探测），非真实账号 */
    private static final String DUMMY_HASH =
            "$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy";
}
