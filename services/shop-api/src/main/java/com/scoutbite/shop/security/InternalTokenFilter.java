package com.scoutbite.shop.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 服务间门卫（）：校验 X-Internal-Token。
 * /internal/** 是 Agent 专用瘦事实出口——人类走 JwtFilter（JWT 门），
 * 机器走这里（服务门）。密钥由 shop-api 与 agent-api 共享（配置注入，不进代码）。
 * 注意：它挂在 /internal/* 上，与 JwtFilter（/api/*）互不干涉。
 */
@Component
public class InternalTokenFilter extends OncePerRequestFilter {

    private final String expectedToken;

    public InternalTokenFilter(@Value("${scoutbite.internal-token}") String expectedToken) {
        this.expectedToken = expectedToken;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String token = request.getHeader("X-Internal-Token");
        if (token == null || !token.equals(expectedToken)) {
            response.setStatus(200);   // 项目合同：HTTP 层 200，业务码在 body
            response.setContentType("application/json;charset=UTF-8");
            response.getWriter().write(
                    "{\"code\":40300,\"message\":\"服务间 token 无效\",\"data\":null,\"requestId\":\"internal-guard\"}");
            return;
        }
        chain.doFilter(request, response);
    }
}
