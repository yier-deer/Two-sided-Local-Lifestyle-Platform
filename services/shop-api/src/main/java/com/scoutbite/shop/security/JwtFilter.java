package com.scoutbite.shop.security;

import io.jsonwebtoken.Claims;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * JWT 门卫：每个 /api/** 请求先过这里（注册位置见 WebConfig）。
 * 白名单放行；带票验票，验过把身份塞进 request attribute 传给 Controller；
 * 无票/坏票访问受保护路径 → 统一信封 40100。
 */
@Component
public class JwtFilter extends OncePerRequestFilter {

    private final JwtUtil jwtUtil;

    /**
     * 白名单（前缀匹配）：
     * /api/auth/    办票处本身
     * /swagger-ui、/v3/api-docs  文档站（漏了 Swagger 直接 401）
     * /actuator/    健康检查（运维探活不要票）
     * /internal/    服务间接口：放行，加服务间 token
     * /api/shops/   游客可看附近店、详情、套餐、券、评价
     * /api/feed     游客可刷信息流（）
     */
    private static final List<String> WHITELIST = List.of(
            "/api/auth/",
            "/swagger-ui",
            "/v3/api-docs",
            "/actuator/",
            "/internal/",
            "/api/shops/",
            "/api/feed"
    );

    public JwtFilter(JwtUtil jwtUtil) {
        this.jwtUtil = jwtUtil;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String path = request.getRequestURI();

        // 白名单直接放行；但若带了票仍解析注入（/api/auth/me 在白名单前缀下却需要身份）
        if (WHITELIST.stream().anyMatch(path::startsWith)) {
            String auth = request.getHeader("Authorization");
            if (auth != null && auth.startsWith("Bearer ")) {
                try {
                    Claims claims = jwtUtil.parse(auth.substring(7));
                    request.setAttribute("userId", Long.valueOf(claims.getSubject()));
                    request.setAttribute("role", claims.get("role", String.class));
                } catch (Exception ignored) {
                    // 白名单路径不因坏票拒绝——只是没有身份
                }
            }
            chain.doFilter(request, response);
            return;
        }

        // 无票 → 40100
        String auth = request.getHeader("Authorization");
        if (auth == null || !auth.startsWith("Bearer ")) {
            reject(response);
            return;
        }

        // 验票：通过则把身份传给 Controller（request 就是传话筒）
        try {
            Claims claims = jwtUtil.parse(auth.substring(7));
            request.setAttribute("userId", Long.valueOf(claims.getSubject()));
            request.setAttribute("role", claims.get("role", String.class));
            chain.doFilter(request, response);
        } catch (Exception e) {
            reject(response);   // 过期/篡改/格式错，一视同仁
        }
    }

    /** 统一信封格式的 40100（HTTP 层 200，业务码在 body——项目合同约定） */
    private void reject(HttpServletResponse response) throws IOException {
        response.setStatus(200);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write(
                "{\"code\":40100,\"message\":\"未登录或 token 失效\",\"data\":null,\"requestId\":\"jwt-guard\"}");
    }
}
