package com.scoutbite.shop.service;

import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.Order;
import com.scoutbite.shop.entity.Sku;
import com.scoutbite.shop.repository.OrderRepository;
import com.scoutbite.shop.repository.SkuRepository;
import com.scoutbite.shop.repository.UserCouponRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Instant;
import java.util.Optional;

/**
 * 订单服务：交易主链路（下单/支付/取消/退单/关单）。
 *
 * 事务边界设计（为什么用 TransactionTemplate 而不是类上 @Transactional）：
 *  - DB 原子段（冻券+扣库存+INSERT）必须一个事务
 *  - ZADD 入延迟队列必须在【事务提交之后】——Redis 不参与 Spring 事务回滚，
 *    放事务里会在回滚时留下"幽灵订单"（脏但无害），正确顺序是提交后入队
 *  - 所以编排方法不能整体 @Transactional，用编程式事务精确圈定边界
 */
@Service
public class OrderService {

    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    /** 延迟关单的 ZSET：score=expireAt 毫秒，member=orderId */
    public static final String DELAY_KEY = "delay:orders";

    private final OrderRepository orderRepo;
    private final SkuRepository skuRepo;
    private final UserCouponRepository userCouponRepo;
    private final com.scoutbite.shop.repository.CouponRepository couponRepo;
    private final StringRedisTemplate redis;
    private final TransactionTemplate tx;
    private final long expireSeconds;

    public OrderService(OrderRepository orderRepo,
                        SkuRepository skuRepo,
                        UserCouponRepository userCouponRepo,
                        com.scoutbite.shop.repository.CouponRepository couponRepo,
                        StringRedisTemplate redis,
                        TransactionTemplate tx,
                        @Value("${scoutbite.order.expire-seconds:900}") long expireSeconds) {
        this.orderRepo = orderRepo;
        this.skuRepo = skuRepo;
        this.userCouponRepo = userCouponRepo;
        this.couponRepo = couponRepo;
        this.redis = redis;
        this.tx = tx;
        this.expireSeconds = expireSeconds;
    }

    // ==================== 下单 ====================

    /**
     * 下单：幂等查 → [事务：冻券(CAS)+扣库存(CAS)+INSERT] → ZADD。
     * 幂等两层：先按 key 查（挡重试）；撞唯一索引再查（挡并发）。
     */
    public Order create(Long userId, Long skuId, Long userCouponId, String idemKey) {
        // 第一层幂等：见过的 key 直接返回原单
        if (idemKey != null && !idemKey.isBlank()) {
            Optional<Order> exist = orderRepo.findByIdempotencyKey(idemKey);
            if (exist.isPresent()) return exist.get();
        }

        // 校验 SKU
        Sku sku = skuRepo.findById(skuId).orElse(null);
        if (sku == null || !sku.isOnSale()) {
            throw new BizException(ErrorCode.PARAM_ERROR, "套餐不存在或已下架");
        }

        Instant expireAt = Instant.now().plusSeconds(expireSeconds);

        // DB 原子段（编程式事务）
        Order order;
        try {
            order = tx.execute(status -> {
                // ② 若用券：先校验归属与状态，拿到券 ID 存进订单
                Long couponId = null;
                if (userCouponId != null) {
                    var uc = userCouponRepo.findById(userCouponId)
                            .filter(c -> c.getUserId().equals(userId))
                            .orElseThrow(() -> new BizException(ErrorCode.PARAM_ERROR, "券不存在"));
                    if (!uc.getStatus().equals(com.scoutbite.shop.entity.UserCoupon.UNUSED)) {
                        throw new BizException(ErrorCode.STOCK_SHORTAGE, "券不可用（已冻结或已使用）");
                    }
                    // 遗留修复（S8）：满减门槛校验——订单金额须达到券的 threshold
                    var coupon = couponRepo.findById(uc.getCouponId())
                            .orElseThrow(() -> new BizException(ErrorCode.PARAM_ERROR, "券模板不存在"));
                    if (sku.getPrice() < coupon.getThreshold()) {
                        throw new BizException(ErrorCode.PARAM_ERROR,
                                "未到用券门槛（需满 " + coupon.getThreshold() + " 分）");
                    }
                    couponId = uc.getCouponId();
                }

                // ④ INSERT 订单（先拿 id，券冻结要绑定 orderId）
                Order o = new Order();
                o.setUserId(userId);
                o.setShopId(sku.getShopId());
                o.setSkuId(skuId);
                o.setCouponId(couponId);
                o.setPriceSnapshot(sku.getPrice());  // 价格快照：之后改价不影响本单
                o.setStatus(Order.CREATED);
                o.setExpireAt(expireAt);
                o.setIdempotencyKey(idemKey);
                orderRepo.save(o);

                // ②' 冻券（CAS 只认自己的 UNUSED 券）：失败抛异常 → 整个事务回滚
                if (userCouponId != null) {
                    int fz = userCouponRepo.freeze(userCouponId, userId, o.getId());
                    if (fz == 0) {
                        throw new BizException(ErrorCode.STOCK_SHORTAGE, "券被并发占用");
                    }
                }

                // ③ 扣库存（CAS）：0 行抛异常 → 事务回滚（INSERT 和冻券一并回滚）
                int deducted = skuRepo.tryDeductStock(skuId);
                if (deducted == 0) {
                    throw new BizException(ErrorCode.STOCK_SHORTAGE, "库存不足");
                }
                return o;
            });
        } catch (DataIntegrityViolationException e) {
            // 第二层幂等：并发同 key 撞唯一索引 → 查出原单返回
            Order exist = orderRepo.findByIdempotencyKey(idemKey).orElse(null);
            if (exist != null) return exist;
            throw new BizException(ErrorCode.IDEMPOTENT_CONFLICT, "下单冲突，请重试");
        }

        // ⑤ 事务已提交：入延迟队列（崩溃丢消息由兜底扫表补）
        redis.opsForZSet().add(DELAY_KEY, String.valueOf(order.getId()),
                expireAt.toEpochMilli());
        log.info("订单 {} 创建成功，{} 到期", order.getId(), expireAt);
        return order;
    }

    // ==================== 支付 ====================

    /**
     * 支付（模拟）：CAS CREATED→PAID，赢家在同事务内核销券。
     * 与关单赛跑：谁先 UPDATE 成功谁赢；输家拿到 0 行返回 40903。
     * 幂等回调：重复支付（已 PAID）返回成功不报错。
     */
    public Order pay(Long orderId, Long userId) {
        Integer rows = tx.execute(status -> {
            int r = orderRepo.payCas(orderId, userId);
            if (r > 0) {
                // 赢家副作用：券 FROZEN→USED（核销）。不加销量——核销时 +1（ADR-011 规则5）
                userCouponRepo.use(orderId);
            }
            return r;
        });

        if (rows != null && rows > 0) {
            log.info("订单 {} 支付成功（CAS 赢得竞态）", orderId);
            return orderRepo.findById(orderId).orElseThrow();
        }
        // 0 行：判断原因
        Order o = orderRepo.findById(orderId).orElse(null);
        if (o == null || !o.getUserId().equals(userId)) {
            throw new BizException(ErrorCode.PARAM_ERROR, "订单不存在");
        }
        if (Order.PAID.equals(o.getStatus())) {
            return o;   // 幂等：重复支付回调直接成功
        }
        throw new BizException(ErrorCode.STATE_CONFLICT,
                "状态机冲突：当前状态 " + o.getStatus() + " 不能支付（可能已被关单）");
    }

    // ==================== 核销（履约段的入口） ====================

    /**
     * 核销：PAID → REDEEMED（CAS），赢家同事务内销量 +1。
     * 这是「钱」段到「履约」段的桥——评价的唯一入口（ADR-011 规则2）。
     * 幂等：重复核销（已 REDEEMED）返回成功；REFUNDED/CANCELLED 核不动 → 40903。
     */
    public Order redeem(Long orderId, Long userId) {
        Integer rows = tx.execute(status -> {
            int r = orderRepo.redeemCas(orderId, userId);
            if (r > 0) {
                Order o = orderRepo.findById(orderId).orElseThrow();
                skuRepo.incSales(o.getSkuId());   // 核销才算销量（规则5）
            }
            return r;
        });
        if (rows != null && rows > 0) {
            log.info("订单 {} 核销成功（REDEEMED，销量+1）", orderId);
            return orderRepo.findById(orderId).orElseThrow();
        }
        Order o = orderRepo.findById(orderId).orElse(null);
        if (o == null || !o.getUserId().equals(userId)) {
            throw new BizException(ErrorCode.PARAM_ERROR, "订单不存在");
        }
        if (Order.REDEEMED.equals(o.getStatus())) {
            return o;   // 幂等：重复核销直接成功
        }
        throw new BizException(ErrorCode.STATE_CONFLICT,
                "状态机冲突：当前状态 " + o.getStatus() + " 不能核销（需已支付未核销）");
    }

    // ==================== 取消 / 退单 ====================

    /**
     * 用户取消：CREATED → CANCELLED_USER，赢家回补库存+释放券（同事务）。
     */
    public Order cancel(Long orderId, Long userId) {
        Integer rows = tx.execute(status -> {
            int r = orderRepo.cancelCas(orderId, userId);
            if (r > 0) compensate(orderId);
            return r;
        });
        return finishCancel(orderId, userId, rows, "取消");
    }

    /**
     * 退单：PAID → REFUNDED（未核销可退，ADR-011 规则3），回补库存+释放券。
     */
    public Order refund(Long orderId, Long userId) {
        Integer rows = tx.execute(status -> {
            int r = orderRepo.refundCas(orderId, userId);
            if (r > 0) compensate(orderId);
            return r;
        });
        return finishCancel(orderId, userId, rows, "退单");
    }

    /** 回补副作用：库存 +1、券 FROZEN→UNUSED（必须在状态 CAS 成功之后才执行） */
    private void compensate(Long orderId) {
        Order o = orderRepo.findById(orderId).orElseThrow();
        skuRepo.restock(o.getSkuId());
        userCouponRepo.release(orderId);
    }

    /** 取消/退单的收尾：0 行时区分原因 */
    private Order finishCancel(Long orderId, Long userId, Integer rows, String action) {
        if (rows != null && rows > 0) {
            log.info("订单 {} {}成功，已回补库存与券", orderId, action);
            return orderRepo.findById(orderId).orElseThrow();
        }
        Order o = orderRepo.findById(orderId).orElse(null);
        if (o == null || !o.getUserId().equals(userId)) {
            throw new BizException(ErrorCode.PARAM_ERROR, "订单不存在");
        }
        throw new BizException(ErrorCode.STATE_CONFLICT,
                "状态机冲突：当前状态 " + o.getStatus() + " 不能" + action);
    }

    // ==================== 超时关单（供定时任务调用） ====================

    /**
     * 关单（CAS 只认 CREATED）：与支付赛跑的仲裁。
     * @return true=关单成功（已回补）；false=关单失败（已支付/已取消，静默跳过）
     */
    public boolean timeoutClose(Long orderId) {
        Integer rows = tx.execute(status -> {
            int r = orderRepo.timeoutCloseCas(orderId);
            if (r > 0) compensate(orderId);   // 赢家才回补
            return r;
        });
        boolean won = rows != null && rows > 0;
        if (won) log.info("订单 {} 超时关单成功，已回补库存与券", orderId);
        return won;
    }

    // ==================== 业务异常（携带错误码，Controller 统一转信封） ====================

    /** 业务异常：带 ErrorCode，由 GlobalExceptionHandler 或 Controller 转 ApiResponse */
    public static class BizException extends RuntimeException {
        public final ErrorCode code;
        public BizException(ErrorCode code, String message) {
            super(message);
            this.code = code;
        }
    }
}
