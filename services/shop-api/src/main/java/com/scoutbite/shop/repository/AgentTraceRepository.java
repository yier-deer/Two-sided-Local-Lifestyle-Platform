package com.scoutbite.shop.repository;

import com.scoutbite.shop.entity.AgentTrace;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

/**
 * Agent 轨迹仓库：append-only。评测按用户+时间窗捞取。
 */
public interface AgentTraceRepository extends JpaRepository<AgentTrace, Long> {

    /** 某用户最近的轨迹（演示/答辩现场可查） */
    List<AgentTrace> findTop20ByUserIdOrderByIdDesc(Long userId);

    /** 全站最近轨迹（replay 页：ADMIN 视角） */
    List<AgentTrace> findTop50ByOrderByIdDesc();
}
