package com.scoutbite.shop.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;

/**
 * JWT 工具：签发（issue）与解析（parse）。
 * 基于 jjwt 0.12 API——注意与网上 0.9 老教程不兼容
 * （老 setSigningKey / parseClaimsJws 已删除，新 verifyWith / parseSignedClaims）。
 */
@Component
public class JwtUtil {

    /** 签名密钥：HS256 要求至少 32 字节（短了启动即抛 WeakKeyException） */
    private final SecretKey key;

    /** 有效期（小时）：演示用 24h；生产应 30 分钟级 + refresh token + 黑名单 */
    private final long expireHours;

    public JwtUtil(@Value("${scoutbite.jwt.secret}") String secret,
                   @Value("${scoutbite.jwt.expire-hours:24}") long expireHours) {
        this.key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        this.expireHours = expireHours;
    }

    /**
     * 签发票据：sub=用户ID，role 走 claim。
     * 注意 payload 只是 Base64 编码，浏览器可读——不放敏感信息。
     */
    public String issue(Long userId, String role) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(String.valueOf(userId))
                .claim("role", role)
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plusSeconds(expireHours * 3600)))
                .signWith(key)                       // 0.12：传 key 即可，算法由密钥类型决定
                .compact();
    }

    /**
     * 解析验票：过期/篡改/格式错误统一抛异常，由调用方（JwtFilter）转 40100。
     */
    public Claims parse(String token) {
        return Jwts.parser()
                .verifyWith(key)                     // 0.12 新 API
                .build()
                .parseSignedClaims(token)            // 0.12 新 API
                .getPayload();
    }
}
