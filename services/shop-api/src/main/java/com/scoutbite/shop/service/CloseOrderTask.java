package com.scoutbite.shop.service;

import com.scoutbite.shop.repository.OrderRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.Set;

/**
 * 超时关单任务：ZSET 主路径（秒级）+ 扫表兜底（分钟级）。
 *
 * 可靠消费的关键顺序：先 CAS 关单，后 ZREM——
 * 崩溃在两步之间的话，下轮重扫同一条，CAS 返回 0 行（已支付）静默跳过，天然幂等。
 * ZSET 整体丢失（Redis 挂）由扫表兜底补——双保险。
 */
@Component
public class CloseOrderTask {

    private static final Logger log = LoggerFactory.getLogger(CloseOrderTask.class);

    private final StringRedisTemplate redis;
    private final OrderRepository orderRepo;
    private final OrderService orderService;

    public CloseOrderTask(StringRedisTemplate redis,
                          OrderRepository orderRepo,
                          OrderService orderService) {
        this.redis = redis;
        this.orderRepo = orderRepo;
        this.orderService = orderService;
    }

    /** 主路径：每秒扫 ZSET 中到期的订单（score=expireAt 毫秒） */
    @Scheduled(fixedDelay = 1000)
    public void scanZset() {
        Set<String> ids = redis.opsForZSet()
                .rangeByScore(OrderService.DELAY_KEY, 0, System.currentTimeMillis());
        if (ids == null || ids.isEmpty()) return;
        for (String id : ids) {
            try {
                boolean closed = orderService.timeoutClose(Long.valueOf(id));
                if (!closed) {
                    log.debug("订单 {} 未关单（已支付/已取消），跳过", id);
                }
            } catch (Exception e) {
                log.error("关单 {} 异常（下轮重试）：{}", id, e.getMessage());
                continue;   // 异常不移除，下轮重试
            }
            redis.opsForZSet().remove(OrderService.DELAY_KEY, id);   // 成功失败都移除（CAS 幂等）
        }
    }

    /** 兜底：每分钟扫 DB（expire_at 已过但仍是 CREATED）——ZSET 丢消息的第二道防线 */
    @Scheduled(fixedDelay = 60000)
    public void scanDbFallback() {
        var ids = orderRepo.findExpiredCreated(Instant.now());
        if (!ids.isEmpty()) {
            log.warn("兜底扫表发现 {} 条过期 CREATED 订单（ZSET 可能丢消息）：{}", ids.size(), ids);
            for (Long id : ids) {
                orderService.timeoutClose(id);
                redis.opsForZSet().remove(OrderService.DELAY_KEY, String.valueOf(id));
            }
        }
    }
}
