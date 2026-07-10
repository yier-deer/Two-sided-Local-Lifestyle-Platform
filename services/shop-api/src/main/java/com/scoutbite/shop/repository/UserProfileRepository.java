package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.UserProfile;
import org.springframework.data.jpa.repository.JpaRepository;

/**
 * 画像仓库：覆盖式刷新（save 即 upsert——主键就是 user_id）。
 */
public interface UserProfileRepository extends JpaRepository<UserProfile, Long> {
}
