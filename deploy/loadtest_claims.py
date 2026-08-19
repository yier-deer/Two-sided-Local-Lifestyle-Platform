#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
loadtest_claims.py —— 压测：200 并发抢 100 张券，断言绝不超卖。

行程验收原话：「券库存 100，200 并发领取/核销，断言成功数 ≤ 100」。
工具决策：Python ThreadPoolExecutor 受控并发（k6/JMeter 未装；本项目要的是
正确性断言而非吞吐曲线——详见 学习指南/文档-讲解.html 第 1.4 节）。

三查断言（全部独立读取，不信服务端自报）：
  ① success ≤ 100（超卖 = FAIL）
  ② Redis 余量 == 100 - success
  ③ DB user_coupons 新增行数 == success
附带：同人并发双击幂等（同用户 20 线程只许成功 1 次）。

用法：python deploy/loadtest_claims.py
"""
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

SHOP = "http://localhost:8081"
COUPON_ID = 3          # 店3 的"满100减15"，total=100（券1已被首轮压测耗尽——那轮已验证无超卖）
TOTAL = 100
N_USERS = 200
BASE_PHONE = 13900000100   # 压测专用用户段（避开演示/评测账号）


def post(client, path, body, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(SHOP + path, json=body, headers=headers).json()


def ensure_user(client, phone):
    """注册压测用户（已存在则登录）——幂等，可重复跑"""
    r = post(client, "/api/auth/register",
             {"phone": phone, "password": "test123456", "role": "USER",
              "nickname": f"压测{phone[-4:]}"})
    if r["code"] == 0 and r.get("data", {}).get("token"):
        return r["data"]["token"]
    r = post(client, "/api/auth/login", {"phone": phone, "password": "test123456"})
    assert r["code"] == 0, f"用户 {phone} 准备失败: {r['message']}"
    return r["data"]["token"]


def db_count(sql):
    """独立读 PG（对账的验证者必须独立于被验证者）"""
    out = subprocess.run(
        ["docker", "exec", "scoutbite-pg", "psql", "-U", "scoutbite", "-d",
         "scoutbite", "-t", "-c", sql],
        capture_output=True, text=True, encoding="utf-8")
    return int(out.stdout.strip() or 0)


def redis_stock():
    """独立读 Redis 余量键（与 CouponService.stockKey 同名：coupon:{id}:stock）"""
    out = subprocess.run(
        ["docker", "exec", "scoutbite-redis", "redis-cli", "GET",
         f"coupon:{COUPON_ID}:stock"],
        capture_output=True, text=True, encoding="utf-8")
    v = out.stdout.strip()
    return int(v) if v.isdigit() else None


def main():
    print(f"== 压测：{N_USERS} 并发抢 {TOTAL} 张券（券{COUPON_ID}·店1）==")
    reg = httpx.Client(timeout=15.0)

    # ---- 阶段1：准备 200 个独立用户（per_user_limit=1，复用用户测不出竞争）----
    t0 = time.time()
    tokens = []
    with ThreadPoolExecutor(50) as ex:
        for tok in ex.map(lambda i: ensure_user(reg, f"{BASE_PHONE + i}"), range(N_USERS)):
            tokens.append(tok)
    print(f"  阶段1 用户就绪：{len(tokens)} 个（{time.time()-t0:.1f}s，注册即预热连接池）")

    # ---- 阶段2：基线（独立读 DB/Redis）----
    db_before = db_count(f"SELECT count(*) FROM user_coupons WHERE coupon_id={COUPON_ID}")
    r_before = redis_stock()
    print(f"  阶段2 基线：DB={db_before} Redis余量={r_before}")
    if r_before is None or r_before <= 0:
        print("  [SKIP] 券余量非正数（可能已被历史测试耗尽）——请复原数据后重跑")
        sys.exit(1)

    # ---- 阶段3：200 并发抢券 ----
    results = {"success": 0, "rejected": 0, "failed": 0}

    def claim(token):
        c = httpx.Client(timeout=20.0)   # 每线程独立连接（真并发，不共享池排队）
        try:
            r = post(c, f"/api/coupons/{COUPON_ID}/claim", {}, token)
            if r["code"] == 0:
                return "success"
            if r["code"] in (40901, 40902):
                return "rejected"      # 40901 已领过 / 40902 已抢完——业务性拒绝（预期内）
            return "failed"
        except Exception:
            return "failed"
        finally:
            c.close()

    t0 = time.time()
    with ThreadPoolExecutor(N_USERS) as ex:
        for outcome in ex.map(claim, tokens):
            results[outcome] += 1
    elapsed = time.time() - t0
    print(f"  阶段3 抢券完成（{elapsed:.1f}s）：成功={results['success']} "
          f"拒绝={results['rejected']} 异常={results['failed']}")

    # ---- 阶段4：三查断言（等 1s 让 DB 提交可见）----
    time.sleep(1)
    db_after = db_count(f"SELECT count(*) FROM user_coupons WHERE coupon_id={COUPON_ID}")
    r_after = redis_stock()
    success = results["success"]

    checks = [
        ("① 不超卖：success ≤ 100", success <= TOTAL, f"success={success}"),
        ("② Redis 一致：余量 == 100-success",
         r_after == TOTAL - success + (TOTAL - r_before if r_before < TOTAL else 0)
         if r_before == TOTAL else r_after == r_before - success,
         f"余量={r_after} 期望={r_before - success}"),
        ("③ DB 一致：新增 == success",
         db_after - db_before == success, f"新增={db_after - db_before}"),
    ]
    print("  阶段4 三查：")
    all_ok = True
    for name, ok, detail in checks:
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}（{detail}）")
        all_ok &= ok

    # ---- 附带：同人并发双击幂等（用券4——券1/3已被压测抢光，幂等要在有余量处测）----
    dup_phone = f"{BASE_PHONE + 998}"
    dup_token = ensure_user(reg, dup_phone)
    dup_results = []
    with ThreadPoolExecutor(20) as ex:
        for r in ex.map(lambda _: post(reg, "/api/coupons/4/claim", {}, dup_token), range(20)):
            dup_results.append(r["code"] == 0)
    dup_ok = sum(dup_results) == 1
    print(f"    [{'PASS' if dup_ok else 'FAIL'}] ④ 同人 20 并发只成功 1 次（券4，成功={sum(dup_results)}）")
    all_ok &= dup_ok

    print(f"\n===== 压测结果：{'PASS' if all_ok else 'FAIL'} "
          f"（{success}/{TOTAL} 张被抢走，{results['rejected']} 人被拒，{elapsed:.1f}s）=====")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
