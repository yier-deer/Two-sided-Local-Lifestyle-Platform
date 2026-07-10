package com.scoutbite.shop;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * shop-api 启动入口。
 * @SpringBootApplication = 自动装配 + 组件扫描
 * @EnableScheduling 开定时任务（超时关单）——忘加的话 @Scheduled 一声不响不跑
 */
@SpringBootApplication
@EnableScheduling
public class ShopApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(ShopApiApplication.class, args);
    }
}
