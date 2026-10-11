#!/usr/bin/env python
"""Real ScoutBite concurrency and timeout reconciliation; no model calls.

Creates fresh dedicated coupons/SKUs through authenticated APIs. Reuses only
the explicit concurrency account range; SQL and Redis are read-only. Run the
timeout Java process against the same database/Redis on :8082 with expire=5s.
Example:
  python deploy/verify_concurrency.py --psql E:/PSG/bin/psql.exe
Credentials are inherited through environment variables and never reported.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import importlib.util
import os
from pathlib import Path
import secrets
import sys
import threading
import time


_real_spec = importlib.util.spec_from_file_location("scoutbite_real_verifier", Path(__file__).with_name("verify_real.py"))
real = importlib.util.module_from_spec(_real_spec)
_real_spec.loader.exec_module(real)

USER_COUNT, CLAIM_STOCK, DUPLICATE_REQUESTS = 200, 100, 20


def idem_key(run_id, label, index=0):
    key = f"cc-{run_id}-{label}-{index}"
    real.require(len(key) <= 64, "Idempotency key exceeds 64 characters")
    return key


def concurrent_batch(items, operation, barrier_timeout=30):
    """One thread/HTTP connection per request, all ready before main releases."""
    real.require(items, "Concurrent batch is empty")
    barrier = threading.Barrier(len(items) + 1, timeout=barrier_timeout)
    def worker(index, item):
        try:
            barrier.wait()
            started = time.monotonic()
            response = operation(item)
            real.require(isinstance(response, dict), "Worker returned an invalid envelope")
            return {"index": index, "code": response.get("code"), "data": response.get("data"),
                    "elapsedMs": round((time.monotonic() - started) * 1000)}
        except Exception as error:
            return {"index": index, "error": real.redact(str(error))}
    with ThreadPoolExecutor(max_workers=len(items), thread_name_prefix="scoutbite-claim") as pool:
        futures = [pool.submit(worker, index, item) for index, item in enumerate(items)]
        try:
            barrier.wait()
        except threading.BrokenBarrierError as error:
            raise real.VerificationFailure("All concurrent workers did not become ready before the barrier deadline") from error
        return sorted((future.result() for future in as_completed(futures)), key=lambda item: item["index"])


def summarize_outcomes(outcomes, rejection_codes=(40901, 40902)):
    result = {"requests": len(outcomes), "success": 0, "rejected": 0, "exceptions": 0, "unexpected": 0}
    problems = []
    for item in outcomes:
        if "error" in item:
            result["exceptions"] += 1
            problems.append({"index": item.get("index"), "error": item["error"]})
        elif item.get("code") == 0:
            result["success"] += 1
        elif item.get("code") in rejection_codes:
            result["rejected"] += 1
        else:
            result["unexpected"] += 1
            problems.append({"index": item.get("index"), "code": item.get("code")})
    if problems:
        result["problems"] = problems
    return result


def assert_outcomes(outcomes, expected_success, expected_rejected, rejection_codes=(40901, 40902)):
    result = summarize_outcomes(outcomes, rejection_codes)
    real.equal(result["exceptions"], 0, "concurrency transport exceptions")
    real.equal(result["unexpected"], 0, "unexpected concurrency response codes")
    real.equal(result["success"], expected_success, "concurrency successes")
    real.equal(result["rejected"], expected_rejected, "concurrency business rejections")
    return result


def poll_until_closed(read_status, max_wait, monotonic=time.monotonic, sleep=time.sleep):
    deadline = monotonic() + max_wait
    while True:
        status = read_status()
        if status == "CANCELLED_TIMEOUT":
            return status
        real.equal(status, "CREATED", "unpaid order before timeout closure")
        remaining = deadline - monotonic()
        real.require(remaining > 0, f"Order did not reach CANCELLED_TIMEOUT within {max_wait}s")
        sleep(min(0.5, remaining))


def parser():
    command = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    command.add_argument("--shop-url", default="http://localhost:8081")
    command.add_argument("--output", type=Path, default=real.ROOT / "docs/reports/concurrency-20261010.json")
    command.add_argument("--timeout", type=float, default=60, help="Per-request HTTP timeout; no request retry")
    command.add_argument("--db-mode", choices=("native", "docker"), default="native")
    command.add_argument("--docker", default="docker")
    command.add_argument("--pg-container", default="scoutbite-pg")
    command.add_argument("--psql", default="psql")
    command.add_argument("--pg-host", default="127.0.0.1")
    command.add_argument("--pg-port", type=int, default=5433)
    command.add_argument("--pg-user", default="scoutbite")
    command.add_argument("--pg-database", default="scoutbite")
    command.add_argument("--pg-password-env", default="PGPASSWORD")
    command.add_argument("--redis-mode", choices=("auto", "docker", "native"), default="auto")
    command.add_argument("--redis-container", default="scoutbite-redis")
    command.add_argument("--redis-cli", help="Native redis-cli executable; otherwise use standard-library RESP")
    command.add_argument("--redis-host", default="127.0.0.1")
    command.add_argument("--redis-port", type=int, default=6380)
    command.add_argument("--redis-password-env", default="")
    command.add_argument("--password-env", default="SCOUTBITE_CONCURRENCY_PASSWORD")
    command.add_argument("--merchant-password-env", default="SCOUTBITE_VERIFY_MERCHANT_PASSWORD")
    command.add_argument("--timeout-shop-url", default="http://localhost:8082")
    command.add_argument("--prepare-workers", type=int, default=40)
    command.add_argument("--phone-start", type=int, default=13880000000,
                         help="First phone in the dedicated 200-user range; existing users must share its password")
    command.add_argument("--max-timeout-wait", type=float, default=30)
    return command


class ConcurrencyReporter(real.Reporter):
    def summary(self):
        report = super().summary()
        report["limitations"] = ["These exact isolated local concurrency scenarios do not establish production throughput.",
                                 "Fresh API-created SKU/coupon records are retained; prior data is not reset.",
                                 "The 200-user account range is reused only after role/password checks; tokens never leave memory."]
        return report


class ConcurrencyVerification:
    def __init__(self, args, report):
        self.args, self.report = args, report
        self.sources = real.ReadOnlySources(args)
        self.api = real.Api(args.shop_url, args.timeout)
        self.timeout_api = real.Api(args.timeout_shop_url, args.timeout)
        self.password = os.environ.get(args.password_env, "concurrency123456")
        real.SECRET_VALUES.add(self.password)
        self.users = []
        self.merchant = None
        self.shop_id = None

    def created(self, kind, record):
        self.report.resources.setdefault("created", {}).setdefault(kind, []).append(record)
        self.report.save()

    def login(self, api, phone, password, role):
        real.SECRET_VALUES.add(password)
        login = api.ok("POST", "/api/auth/login", {"phone": phone, "password": password})
        real.equal(login.get("role"), role, "account role")
        real.require(login.get("token") and login.get("userId"), "Login did not return token/userId")
        real.SECRET_VALUES.add(login["token"])
        return login

    def readiness(self):
        for client in (self.api, self.timeout_api):
            real.equal(client.request("GET", "/actuator/health").get("status"), "UP", "Java service readiness")
        real.equal(self.sources.scalar("SELECT 1"), "1", "PostgreSQL readiness")
        real.equal(self.sources.redis("PING"), "PONG", "Redis readiness")
        self.report.resources["timeoutShopUrl"] = self.args.timeout_shop_url
        return {"shop": "UP", "timeoutShop": "UP", "postgres": "SELECT 1", "redis": "PONG"}

    def prepare(self):
        self.merchant = self.login(self.api, "13611110004", os.environ.get(self.args.merchant_password_env, "merchant123456"), "MERCHANT")
        shops = self.api.ok("GET", "/api/merchant/shops", actor=self.merchant)
        approved = [shop for shop in shops if shop.get("status") == "approved"]
        real.require(approved, "Seed merchant needs an approved shop; no implicit admin bypass")
        self.shop_id = approved[0]["id"]
        self.report.resources["shopId"] = self.shop_id
        def prepare_user(index):
            client = real.Api(self.args.shop_url, self.args.timeout)
            phone = str(self.args.phone_start + index)
            response = client.request("POST", "/api/auth/register", {"phone": phone, "password": self.password,
                                                                     "role": "USER", "nickname": f"并发验收专用{index:03d}"})
            real.expect_code(response, {0, 40901}, "prepare dedicated concurrent user")
            actor = self.login(client, phone, self.password, "USER")
            real.require(actor.get("nickname", "").startswith("并发验收专用"), "Reserved test phone belongs to a different account; refusing reuse")
            return {**actor, "phone": phone, "wasCreated": response["code"] == 0}
        failures = []
        with ThreadPoolExecutor(max_workers=self.args.prepare_workers, thread_name_prefix="scoutbite-user") as pool:
            jobs = {pool.submit(prepare_user, index): index for index in range(USER_COUNT)}
            prepared = {}
            for future in as_completed(jobs):
                index = jobs[future]
                try:
                    prepared[index] = future.result()
                except Exception as error:
                    failures.append({"index": index, "phone": str(self.args.phone_start + index), "error": real.redact(str(error))})
        self.report.resources["userPreparation"] = {"expected": USER_COUNT, "prepared": len(prepared), "failures": failures,
                                                    "phoneStart": self.args.phone_start,
                                                    "userIds": [prepared[index]["userId"] for index in sorted(prepared)]}
        self.report.save()
        real.require(not failures, f"User preparation failed: {real.redact(failures)}")
        self.users = [prepared[index] for index in range(USER_COUNT)]
        real.equal(len({user["userId"] for user in self.users}), USER_COUNT, "independent concurrency identities")
        return {"users": USER_COUNT, "createdUsers": sum(user["wasCreated"] for user in self.users),
                "workers": self.args.prepare_workers, "shopId": self.shop_id}

    def coupon(self, label, total):
        result = self.api.ok("POST", "/api/merchant/coupons", {"shopId": self.shop_id, "title": f"并发验收-{label}-{self.report.run_id}",
                                                               "threshold": 10000, "amount": 1500, "total": total}, self.merchant)
        self.created("coupons", {"id": result["id"], "total": total, "label": label})
        real.equal(int(self.sources.redis("GET", f"coupon:{result['id']}:stock")), total, "fresh Redis coupon stock")
        return result

    def sku(self, label, stock):
        result = self.api.ok("POST", "/api/merchant/skus", {"shopId": self.shop_id, "title": f"并发验收-{label}-{self.report.run_id}",
                                                            "price": 12800, "stock": stock}, self.merchant)
        self.created("skus", {"id": result["id"], "stock": stock, "label": label})
        return result

    def stock(self, sku_id):
        return int(self.sources.scalar(f"SELECT stock FROM skus WHERE id={int(sku_id)}"))

    def claims(self):
        coupon = self.coupon("200抢100", CLAIM_STOCK)
        before = int(self.sources.scalar(f"SELECT count(*) FROM user_coupons WHERE coupon_id={coupon['id']}"))
        real.equal(before, 0, "new coupon has no historical claims")
        outcomes = concurrent_batch(self.users, lambda actor: real.Api(self.args.shop_url, self.args.timeout).request(
            "POST", f"/api/coupons/{coupon['id']}/claim", {}, actor))
        stats = summarize_outcomes(outcomes)
        self.report.resources["claim200"] = {"couponId": coupon["id"], "summary": stats, "outcomes": outcomes}
        self.report.save()
        assert_outcomes(outcomes, 100, 100)
        redis_remaining = int(self.sources.redis("GET", f"coupon:{coupon['id']}:stock"))
        redis_users = int(self.sources.redis("SCARD", f"coupon:{coupon['id']}:users"))
        row = self.sources.row(f"SELECT count(*) AS count, count(DISTINCT user_id) AS unique_users FROM user_coupons WHERE coupon_id={coupon['id']}")
        real.equal(redis_remaining, 0, "200 claim Redis stock")
        real.equal(redis_users, 100, "200 claim Redis unique users")
        real.equal(row["count"], 100, "200 claim DB rows")
        real.equal(row["unique_users"], 100, "200 claim DB independent users")
        real.equal(len({outcome["data"]["userCouponId"] for outcome in outcomes if outcome.get("code") == 0}), 100, "200 claim returned unique held IDs")
        return {**stats, "redisRemaining": redis_remaining, "redisUsers": redis_users, "dbUserCoupons": row["count"], "couponId": coupon["id"]}

    def duplicate_claim(self):
        coupon = self.coupon("同人20", 100)
        actor = self.users[0]
        outcomes = concurrent_batch(list(range(DUPLICATE_REQUESTS)), lambda index: real.Api(self.args.shop_url, self.args.timeout).request(
            "POST", f"/api/coupons/{coupon['id']}/claim", {}, actor))
        stats = summarize_outcomes(outcomes)
        self.report.resources["duplicate20"] = {"couponId": coupon["id"], "userId": actor["userId"], "summary": stats, "outcomes": outcomes}
        self.report.save()
        assert_outcomes(outcomes, 1, 19)
        real.equal(int(self.sources.scalar(f"SELECT count(*) FROM user_coupons WHERE coupon_id={coupon['id']}")), 1, "same user DB coupon count")
        real.equal(int(self.sources.redis("GET", f"coupon:{coupon['id']}:stock")), 99, "same user Redis stock")
        real.equal(int(self.sources.redis("SCARD", f"coupon:{coupon['id']}:users")), 1, "same user Redis set")
        return {**stats, "redisRemaining": 99, "dbUserCoupons": 1, "couponId": coupon["id"]}

    def order_race(self):
        sku = self.sku("两人抢一份", 1)
        def create(index):
            return real.Api(self.args.shop_url, self.args.timeout).request("POST", "/api/orders", {"skuId": sku["id"]},
                                                                          self.users[index], idem_key(self.report.run_id, "race", index))
        outcomes = concurrent_batch([0, 1], create)
        self.report.resources["orderRace"] = {"skuId": sku["id"], "outcomes": outcomes}
        self.report.save()
        stats = assert_outcomes(outcomes, 1, 1, rejection_codes=(40902,))
        real.equal(self.stock(sku["id"]), 0, "one-stock race DB stock")
        rows = self.sources.rows(f"SELECT id, user_id, status FROM orders WHERE sku_id={sku['id']}")
        real.equal(len(rows), 1, "loser transaction creates no ghost DB order")
        real.equal(rows[0]["status"], "CREATED", "race winner state")
        winner = next(outcome for outcome in outcomes if outcome.get("code") == 0)
        actor = self.users[winner["index"]]
        real.equal(rows[0]["id"], winner["data"]["id"], "HTTP/DB race winner")
        cancelled = self.api.ok("POST", f"/api/orders/{rows[0]['id']}/cancel", {}, actor)
        real.equal(cancelled["status"], "CANCELLED_USER", "race winner cancelled")
        real.equal(self.stock(sku["id"]), 1, "race cancellation restocks once")
        self.api.reject("POST", f"/api/orders/{rows[0]['id']}/cancel", {40903}, {}, actor)
        real.equal(self.stock(sku["id"]), 1, "repeat race cancellation cannot double restock")
        return {**stats, "orderId": rows[0]["id"], "skuId": sku["id"], "stockAfterCancel": 1}

    def timeouts(self):
        actor = self.users[2]
        free_sku, coupon_sku = self.sku("超时无券", 5), self.sku("超时有券", 5)
        coupon = self.coupon("超时有券", 10)
        held = self.timeout_api.ok("POST", f"/api/coupons/{coupon['id']}/claim", {}, actor)["userCouponId"]
        orders = []
        for label, sku, user_coupon in (("plain", free_sku, None), ("coupon", coupon_sku, held)):
            body = {"skuId": sku["id"]}
            if user_coupon is not None:
                body["userCouponId"] = user_coupon
            order = self.timeout_api.ok("POST", "/api/orders", body, actor, idem_key(self.report.run_id, "timeout-" + label))
            self.created("timeoutOrders", {"id": order["id"], "skuId": sku["id"], "userCouponId": user_coupon, "expireAt": order["expireAt"]})
            real.equal(order["status"], "CREATED", "timeout newly created state")
            expiry = datetime.fromisoformat(order["expireAt"].replace("Z", "+00:00"))
            remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
            real.require(0 < remaining <= self.args.max_timeout_wait - 2,
                         "Order actual expireAt exceeds bounded timeout test; run :8082 with expire-seconds=5")
            real.equal(self.stock(sku["id"]), 4, "timeout initial stock reserved")
            orders.append((order, sku, user_coupon))
        held_before = self.sources.row(f"SELECT status, order_id FROM user_coupons WHERE id={held}")
        real.equal(held_before["status"], "FROZEN", "timeout initial coupon frozen")
        real.equal(held_before["order_id"], orders[1][0]["id"], "timeout frozen coupon binding")
        wait_started = time.monotonic()
        deadline = wait_started + self.args.max_timeout_wait
        evidence = []
        for order, sku, user_coupon in orders:
            remaining = deadline - time.monotonic()
            real.require(remaining > 0, "Combined two-order timeout deadline exceeded")
            status = poll_until_closed(lambda order_id=order["id"]: self.sources.scalar(f"SELECT status FROM orders WHERE id={order_id}"), remaining)
            real.equal(self.stock(sku["id"]), 5, "timeout DB SKU restoration")
            api_orders = self.timeout_api.ok("GET", "/api/orders", actor=actor)
            api_order = next(item for item in api_orders if item["id"] == order["id"])
            real.equal(api_order["status"], status, "timeout HTTP/DB status reconciliation")
            evidence.append({"orderId": order["id"], "skuId": sku["id"], "status": status, "stockRestored": 5,
                             "expireAt": order["expireAt"], "withCoupon": user_coupon is not None})
        held_after = self.sources.row(f"SELECT status, order_id FROM user_coupons WHERE id={held}")
        real.equal(held_after["status"], "UNUSED", "timeout DB coupon restoration")
        real.equal(held_after["order_id"], None, "timeout restored coupon binding cleared")
        real.equal(int(self.sources.redis("GET", f"coupon:{coupon['id']}:stock")), 9, "timeout does not mint coupon claim stock")
        return {"orders": evidence, "couponId": coupon["id"], "userCouponId": held, "couponState": "UNUSED",
                "pollElapsedSeconds": round(time.monotonic() - wait_started, 3), "maxWaitSeconds": self.args.max_timeout_wait}

    def run(self):
        if self.report.check("main and timeout Java with independent PG/Redis readiness", self.readiness) is None:
            self.report.skip("concurrency acceptance", "Required real services are unavailable")
            return
        if self.report.check("prepare 200 dedicated real users with 40 workers", self.prepare) is None:
            self.report.skip("concurrency acceptance", "Dedicated account preparation failed")
            return
        self.report.check("200 barrier-start requests claim 100 fresh coupons", self.claims)
        self.report.check("same user 20 barrier-start requests claim only once", self.duplicate_claim)
        self.report.check("two buyers compete for one SKU then winner cancellation restores once", self.order_race)
        self.report.check("actual expireAt closes unpaid plain/coupon orders and restores three sources", self.timeouts)


def main(argv=None):
    args = parser().parse_args(argv)
    real.require(1 <= args.prepare_workers <= 40, "--prepare-workers must be 1..40")
    real.require(0 < args.max_timeout_wait <= 30, "Timeout polling must be bounded to at most 30 seconds")
    real.require(10_000_000_000 <= args.phone_start <= 99_999_999_999 - USER_COUNT, "Dedicated phone range must contain 200 eleven-digit phones")
    real.require(args.timeout > 0, "HTTP timeout must be positive")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
    report = ConcurrencyReporter(run_id, args.shop_url, args.output)
    report.save()
    try:
        ConcurrencyVerification(args, report).run()
    except Exception as error:
        report.check("unhandled concurrency verifier failure", lambda: (_ for _ in ()).throw(error))
    report.save()
    result = report.summary()
    print(f"Result: {result['status']} {result['counts']}. Report: {args.output}", flush=True)
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
