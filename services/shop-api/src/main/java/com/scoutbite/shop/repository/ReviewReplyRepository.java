package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.ReviewReply;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

/**
 * 评价回复仓库。
 */
public interface ReviewReplyRepository extends JpaRepository<ReviewReply, Long> {

    /** 某条评价下的回复（含商家标） */
    List<ReviewReply> findByReviewIdOrderById(Long reviewId);
}
