package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

/**
 * 用户仓库：方法名即查询（JPA 派生查询）。
 */
public interface UserRepository extends JpaRepository<User, Long> {

    /** 按手机号找用户（登录用）——自动翻译成 WHERE phone = ? */
    Optional<User> findByPhone(String phone);
}
