#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
close_order_check.py —— 关单对账：未支付单超时后，三个资源必须全部归位。

行程验收原话：「制造未支付单，等到超时，库存和券都回来」。
用例A（无券）：下单不支付 → 超时 → 订单 CANCELLED_TIMEOUT + 库存回补 +1
用例B（用券）：领券→下单用券（FROZEN）→ 不支付 → 超时 → 券回 UNUSED + 库存回补
对账原则：独立读三个源（订单表/SKU 表/券表）互相印证——验证者独立于被验证者。

用法：python deploy/close_order_check.py（全程约 80 秒，含两轮真实超时等待）
"""
import subprocess
import sys
import time

import httpx

SHOP = "http://localhost:8081"
WAIT_SECONDS = 35          # expire-seconds=30（演示值），+5s 缓冲
RECON_PHONE = "13900000777"   # 对账专用账号（独立于压测/演示/评测用户）


def api(client, method, path, body=None, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.request(method, SHOP + path, json=body, headers=headers)
    return r.json()


def db_one(sql):
    """独立读 PG 单值"""
    out = subprocess.run(
        ["docker", "exec", "scoutbite-pg", "psql", "-U", "scoutbite", "-d",
         "scoutbite", "-t", "-c", sql],
        capture_output=True, text=True, encoding="utf-8")
    return out.stdout.strip()


def db_stock(sku_id):
    return int(db_one(f"SELECT stock FROM skus WHERE id={sku_id}"))


def db_coupon_status(coupon_id, user_id):
    return db_one(
        f"SELECT status FROM user_coupons WHERE coupon_id={coupon_id} "
        f"AND user_id={user_id}")


def setup_user(client):
    """对账账号（幂等）"""
    r = api(client, "POST", "/api/auth/register",
            {"phone": RECON_PHONE, "password": "test123456", "role": "USER",
             "nickname": "对账员"})
    if not (r["code"] == 0 and r.get("data", {}).get("token")):
        r = api(client, "POST", "/api/auth/login",
                {"phone": RECON_PHONE, "password": "test123456"})
    return r["data"]["token"]


def main():
    print("== 关单对账（含两轮真实超时等待，约 80s）==")
    c = httpx.Client(timeout=15.0)
    token = setup_user(c)
    print("  账号就绪")

    # ---------- 用例A：无券超时 ----------
    print("  [A] 无券：下单→不支付→等超时")
    stock_before = int(db_one("SELECT stock FROM skus WHERE id=5"))
    r = httpx.post(SHOP + "/api/orders", json={"skuId": 5},
                   headers={"Authorization": f"Bearer {token}",
                            "Idempotency-Key": f"recon-a-{int(time.time())}"}).json()
    oid_a = r["data"]["id"]
    print(f"      订单{oid_a} 已建（SKU5 库存 {stock_before}→{stock_before - 1} 逻辑占用）")

    # ---------- 用例B：用券超时（先领券5：店5 券，避开压测券）----------
    print("  [B] 用券：领券→下单（券 FROZEN）→不支付→等超时")
    coupon_id = 5
    r = api(c, "POST", f"/api/coupons/{coupon_id}/claim", {}, token)
    assert r["code"] == 0, f"领券失败: {r['message']}"
    print("      券5 已领（UNUSED→将冻结）")
    stock_b_before = int(db_one("SELECT stock FROM skus WHERE id=6"))
    r = httpx.post(SHOP + "/api/orders", json={"skuId": 6, "couponId": coupon_id},
                   headers={"Authorization": f"Bearer {token}",
                            "Idempotency-Key": f"recon-b-{int(time.time())}"}).json()
    assert r["code"] == 0, f"下单失败: {r['message']}"
    oid_b = r["data"]["id"]
    frozen = db_one(f"SELECT status FROM user_coupons WHERE coupon_id={coupon_id}")
    print(f"      订单{oid_b} 已建（券状态={frozen}，SKU6 库存 {stock_b_before}）")

    # ---------- 等真实超时 ----------
    print(f"      等待 {WAIT_SECONDS}s（真实超时，非造数）…")
    time.sleep(WAIT_SECONDS)

    # ---------- 对账 ----------
    print("  对账（独立读三源）：")
    ok = True

    st_a = db_one(f"SELECT status FROM orders WHERE id={oid_a}")
    stock_a_after = db_stock(5)
    a_ok = st_a == "CANCELLED_TIMEOUT" and stock_a_after == stock_before
    print(f"    [{'PASS' if a_ok else 'FAIL'}] A 订单={st_a} 库存 {stock_before}→{stock_a_after}"
          f"（期望 CANCELLED_TIMEOUT / 回补 {stock_before}）")
    ok &= a_ok

    st_b = db_one(f"SELECT status FROM orders WHERE id={oid_b}")
    stock_b_after = db_stock(6)
    cp_b = db_coupon_status(coupon_id, 0) or db_one(
        f"SELECT status FROM user_coupons WHERE coupon_id={coupon_id}")
    b_ok = (st_b == "CANCELLED_TIMEOUT" and stock_b_after == stock_b_before
            and cp_b == "UNUSED")
    print(f"    [{'PASS' if b_ok else 'FAIL'}] B 订单={st_b} 库存 {stock_b_before}→{stock_b_after}"
          f" 券={cp_b}（期望 CANCELLED_TIMEOUT / 回补 / UNUSED）")
    ok &= b_ok

    print(f"\n===== 对账结果：{'PASS（世界是平的）' if ok else 'FAIL'}=====")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
