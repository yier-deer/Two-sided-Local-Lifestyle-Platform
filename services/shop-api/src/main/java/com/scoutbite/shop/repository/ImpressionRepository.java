package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.Impression;
import org.springframework.data.jpa.repository.JpaRepository;

/**
 * 曝光日志仓库：append-only，只 save 不 update。
 * 归因查询（按 user+时间窗）走 idx_impressions_user。
 */
public interface ImpressionRepository extends JpaRepository<Impression, Long> {
}
