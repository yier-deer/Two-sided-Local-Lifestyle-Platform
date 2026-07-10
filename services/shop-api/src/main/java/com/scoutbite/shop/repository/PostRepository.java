package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.Post;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

/**
 * 帖子仓库：信息流候选集。
 */
public interface PostRepository extends JpaRepository<Post, Long> {

    /** 最近的帖子（信息流候选；量小全捞，上量后按关注/城市裁剪） */
    List<Post> findTop100ByOrderByCreatedAtDesc();

    /** 某店的帖子 */
    List<Post> findByShopIdOrderByIdDesc(Long shopId);
}
