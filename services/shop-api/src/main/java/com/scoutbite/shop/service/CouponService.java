package com.scoutbite.shop.service;

import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.Coupon;
import com.scoutbite.shop.entity.UserCoupon;
import com.scoutbite.shop.repository.CouponRepository;
import com.scoutbite.shop.repository.UserCouponRepository;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;

/**
 * 领券服务：Redis Lua 原子扣减（余量/限领两判断一步完成）+ DB 记 user_coupons。
 *
 * 为什么 Lua：判断「还有余量吗」「这用户领过没」和「扣减」必须是同一个原子步骤——
 * 多条独立命令之间的缝隙会让两人同时抢到最后一张券。Redis 单线程执行脚本期间
 * 不插入其他命令，缝隙被焊死。
 */
@Service
public class CouponService {

    /** 券余量的 Redis 键：coupon:{id}:stock */
    public static String stockKey(Long couponId) { return "coupon:" + couponId + ":stock"; }

    /** 已领用户集合的键：coupon:{id}:users（每人限领的判断依据） */
    public static String usersKey(Long couponId) { return "coupon:" + couponId + ":users"; }

    /**
     * 领券 Lua 脚本：三判断 + 扣减，一个原子步骤。
     * 返回：1=成功；0=无余量；-1=已领过（限领）
     */
    private static final DefaultRedisScript<Long> CLAIM_LUA = new DefaultRedisScript<>("""
            if redis.call('SISMEMBER', KEYS[2], ARGV[1]) == 1 then
                return -1
            end
            local stock = tonumber(redis.call('GET', KEYS[1]) or '-1')
            if stock <= 0 then
                return 0
            end
            redis.call('DECR', KEYS[1])
            redis.call('SADD', KEYS[2], ARGV[1])
            return 1
            """, Long.class);

    private final StringRedisTemplate redis;
    private final CouponRepository couponRepo;
    private final UserCouponRepository userCouponRepo;

    public CouponService(StringRedisTemplate redis,
                         CouponRepository couponRepo,
                         UserCouponRepository userCouponRepo) {
        this.redis = redis;
        this.couponRepo = couponRepo;
        this.userCouponRepo = userCouponRepo;
    }

    /**
     * 领券。失败时抛出带错误码的异常语义（这里用返回 null + message 由 Controller 转）——
     * 为保持简洁，直接返回失败信息字符串，成功返回实体。
     */
    public ClaimResult claim(Long userId, Long couponId) {
        Coupon c = couponRepo.findById(couponId).orElse(null);
        if (c == null) return ClaimResult.fail(ErrorCode.PARAM_ERROR, "券不存在");

        // 活动窗口判断（DB 侧做，Lua 里只管余量+限领）
        Instant now = Instant.now();
        if (now.isBefore(c.getStartAt()) || now.isAfter(c.getEndAt())) {
            return ClaimResult.fail(ErrorCode.PARAM_ERROR, "不在领取时间内");
        }

        // Lua 原子扣减
        Long r = redis.execute(CLAIM_LUA,
                List.of(stockKey(couponId), usersKey(couponId)),
                String.valueOf(userId));
        if (r == null) return ClaimResult.fail(ErrorCode.STOCK_SHORTAGE, "领券失败");
        if (r == -1) return ClaimResult.fail(ErrorCode.STOCK_SHORTAGE, "每人限领一张");
        if (r == 0) return ClaimResult.fail(ErrorCode.STOCK_SHORTAGE, "券已抢完");

        // 成功：DB 记一张 UNUSED 券
        UserCoupon uc = new UserCoupon();
        uc.setUserId(userId);
        uc.setCouponId(couponId);
        uc.setStatus(UserCoupon.UNUSED);
        userCouponRepo.save(uc);
        return ClaimResult.ok(uc);
    }

    /** 领券结果封装（成功=实体；失败=错误码+消息） */
    public record ClaimResult(UserCoupon coupon, ErrorCode code, String message) {
        static ClaimResult ok(UserCoupon uc) { return new ClaimResult(uc, null, null); }
        static ClaimResult fail(ErrorCode code, String msg) { return new ClaimResult(null, code, msg); }
    }

    /** 初始化某券的 Redis 镜像（种子/建券时调用） */
    public void initMirror(Long couponId, int total) {
        redis.opsForValue().set(stockKey(couponId), String.valueOf(total));
        redis.delete(usersKey(couponId));
    }
}
