package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.Like;
import org.springframework.data.jpa.repository.JpaRepository;

/**
 * 点赞仓库：联合唯一约束防重复（exists 预检 + 撞约束兜底）。
 */
public interface LikeRepository extends JpaRepository<Like, Long> {

    /** 是否已赞（点赞幂等预检） */
    boolean existsByUserIdAndTargetTypeAndTargetId(Long userId, String targetType, Long targetId);

    /** 某目标的点赞数（推流 quality 的互动项） */
    long countByTargetTypeAndTargetId(String targetType, Long targetId);
}
