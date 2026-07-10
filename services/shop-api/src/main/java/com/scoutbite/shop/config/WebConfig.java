package com.scoutbite.shop.config;

import com.scoutbite.shop.security.JwtFilter;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Web 配置：把 JwtFilter 挂到请求链上。
 * 只拦 /api/*（文档、actuator、internal 不经过门卫，各自有自己的开放策略）。
 */
@Configuration
public class WebConfig {

    @Bean
    public FilterRegistrationBean<JwtFilter> jwtFilterReg(JwtFilter filter) {
        FilterRegistrationBean<JwtFilter> reg = new FilterRegistrationBean<>(filter);
        reg.addUrlPatterns("/api/*");
        reg.setOrder(1);
        return reg;
    }

    /** 服务间门卫挂 /internal/*（与 JWT 门互不干涉——两扇门两把锁） */
    @Bean
    public FilterRegistrationBean<com.scoutbite.shop.security.InternalTokenFilter> internalTokenFilterReg(
            com.scoutbite.shop.security.InternalTokenFilter filter) {
        FilterRegistrationBean<com.scoutbite.shop.security.InternalTokenFilter> reg =
                new FilterRegistrationBean<>(filter);
        reg.addUrlPatterns("/internal/*");
        reg.setOrder(2);
        return reg;
    }
}
