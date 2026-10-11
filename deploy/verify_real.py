#!/usr/bin/env python
"""ScoutBite real HTTP + independent PostgreSQL/Redis acceptance.

All writes use public authenticated APIs and new per-run records. No cleanup,
service restart, .env reads, direct SQL mutations, or fabricated model results.

Native example (PGPASSWORD is inherited, never printed):
  python deploy/verify_real.py --db-mode native --psql E:/PSG/bin/psql.exe \
      --redis-port 6380 --skip-agent
Run again without --skip-agent for the real model checks. --prepare-eval requires
SCOUTBITE_EVAL_FIXTURE_PASSWORD and emits only its environment variable name.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
SECRET_VALUES: set[str] = set()
TOPICS = {
    "排队等位": ["排队", "等位", "等了", "久等", "排队久"],
    "服务态度": ["服务", "加水", "没人理", "态度", "热情"],
    "口味品质": ["味道", "好吃", "难吃", "香", "汤底", "出品"],
    "优惠争议": ["券", "优惠", "满减", "折扣", "不参与"],
    "环境位置": ["环境", "位置", "装修", "吵", "好找"],
}


class VerificationFailure(Exception):
    pass


def require(condition, message):
    if not condition:
        raise VerificationFailure(message)


def equal(actual, expected, name):
    require(actual == expected, f"{name}: expected {expected!r}, got {actual!r}")


def instant_nanoseconds(value):
    require(isinstance(value, str), "Timestamp must be an ISO-8601 instant string")
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})", value)
    require(match is not None, "Timestamp must include a timezone and at most nine fractional digits")
    whole, fraction, zone = match.groups()
    try:
        instant = datetime.fromisoformat(whole + ("+00:00" if zone == "Z" else zone))
        elapsed = instant.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    except ValueError as error:
        raise VerificationFailure("Invalid ISO-8601 instant") from error
    return (elapsed.days * 86400 + elapsed.seconds) * 1_000_000_000 + int((fraction or "").ljust(9, "0"))


def equal_instant(actual, expected, name):
    # Java Instant keeps nanoseconds; PostgreSQL TIMESTAMPTZ stores microseconds.
    # Compare exact integer nanoseconds so truncation never hides a >1us mismatch.
    difference = abs(instant_nanoseconds(actual) - instant_nanoseconds(expected))
    require(difference <= 1000, f"{name}: instant mismatch of {difference}ns (allowed at most 1000ns)")


def java_one_decimal(number):
    return math.floor(number * 10 + 0.5) / 10.0


def redact(value):
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if str(key).lower() in {
            "token", "password", "passwordhash", "password_hash", "authorization", "secret", "api_key"
        } else redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for secret in sorted(SECRET_VALUES, key=len, reverse=True):
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"Bearer\s+[^\s,\"']+", "Bearer [REDACTED]", value, flags=re.I)
        value = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED JWT]", value)
    return value


def expect_code(envelope, expected, label):
    require(isinstance(envelope, dict) and isinstance(envelope.get("code"), int), f"{label}: invalid API envelope")
    require(envelope["code"] in expected, f"{label}: code={envelope['code']}, message={envelope.get('message', '')}")
    return envelope.get("data")


class Reporter:
    def __init__(self, run_id, shop_url, output=None):
        self.run_id, self.shop_url, self.output = run_id, shop_url, output
        self.started = datetime.now(timezone.utc).isoformat()
        self.checks = []
        self.resources = {}

    def check(self, name, fn):
        start = time.monotonic()
        try:
            value = fn()
            item = {"name": name, "status": "PASS", "evidence": redact(value)}
        except Exception as error:
            value = None
            item = {"name": name, "status": "FAIL", "error": redact(str(error))}
        item["elapsedMs"] = round((time.monotonic() - start) * 1000)
        self.checks.append(item)
        print(f"[{item['status']}] {name}" + (f": {item['error']}" if item['status'] == "FAIL" else ""), flush=True)
        self.save()
        return value

    def skip(self, name, reason):
        self.checks.append({"name": name, "status": "SKIP", "reason": reason})
        print(f"[SKIP] {name}: {reason}", flush=True)
        self.save()

    def summary(self):
        failed = sum(item["status"] == "FAIL" for item in self.checks)
        skipped = sum(item["status"] == "SKIP" for item in self.checks)
        return {"version": 1, "runId": self.run_id, "shopUrl": self.shop_url,
                "startedAt": self.started, "updatedAt": datetime.now(timezone.utc).isoformat(),
                "status": "FAIL" if failed else "PASS_WITH_SKIPS" if skipped else "PASS",
                "counts": {state: sum(item["status"] == state for item in self.checks) for state in ("PASS", "FAIL", "SKIP")},
                "resources": redact(self.resources), "checks": self.checks,
                "limitations": ["Model checks test observable contracts and referenced records, not universal freedom from hallucinations.",
                                "Per-run API records are intentionally retained. Existing data is never reset."]}

    def save(self):
        if self.output:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps(self.summary(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Api:
    def __init__(self, base, timeout):
        parsed = urlsplit(base)
        require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username,
                "--shop-url must be HTTP(S) without embedded credentials")
        self.base, self.timeout = base.rstrip("/"), timeout

    def request(self, method, path, body=None, actor=None, idem=None):
        headers = {"Accept": "application/json"}
        if actor:
            headers["Authorization"] = "Bearer " + actor["token"]
        if idem:
            headers["Idempotency-Key"] = idem
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(self.base + path, data=payload, headers=headers, method=method), timeout=self.timeout) as response:
                require(200 <= response.status < 300, f"HTTP {response.status} {path}")
                result = json.load(response)
                require(isinstance(result, dict), f"{path}: response is not an object")
                return result
        except HTTPError as error:
            raise VerificationFailure(f"HTTP {error.code} {method} {path}") from error
        except (URLError, TimeoutError, OSError) as error:
            uncertainty = " UNKNOWN: this write may have committed; inspect its run records before replay." if method not in {"GET", "HEAD"} else ""
            raise VerificationFailure(f"Transport error {method} {path}: {type(error).__name__}.{uncertainty}") from error

    def ok(self, method, path, body=None, actor=None, idem=None):
        return expect_code(self.request(method, path, body, actor, idem), {0}, f"{method} {path}")

    def reject(self, method, path, codes, body=None, actor=None, idem=None):
        envelope = self.request(method, path, body, actor, idem)
        expect_code(envelope, set(codes), f"rejection {method} {path}")
        return {"path": path, "code": envelope["code"]}


class ReadOnlySources:
    def __init__(self, args):
        self.args = args

    def sql(self, sql):
        sql = sql.strip()
        require(re.match(r"^SELECT\b", sql, re.I) is not None and ";" not in sql and "--" not in sql and "/*" not in sql,
                "Verifier accepts a single SELECT statement only")
        args = self.args
        env = os.environ.copy()
        env["PGOPTIONS"] = (env.get("PGOPTIONS", "") + " -c default_transaction_read_only=on").strip()
        env["PGCONNECT_TIMEOUT"] = "5"
        env["PGCLIENTENCODING"] = "UTF8"
        if args.pg_password_env in env:
            env["PGPASSWORD"] = env[args.pg_password_env]
            SECRET_VALUES.add(env["PGPASSWORD"])
        psql = ["-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "--no-password", "-U", args.pg_user, "-d", args.pg_database, "-c", sql]
        if args.db_mode == "docker":
            command = [args.docker, "exec", "-i", "-e", "PGOPTIONS=-c default_transaction_read_only=on", args.pg_container, "psql", *psql]
        else:
            command = [args.psql, "-h", args.pg_host, "-p", str(args.pg_port), *psql]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=20)
        require(result.returncode == 0, f"PostgreSQL read failed: {redact(result.stderr.strip()[:500])}")
        return result.stdout.strip()

    def row(self, sql):
        raw = self.sql(f"SELECT row_to_json(record) FROM ({sql}) AS record")
        require(raw, "Expected a PostgreSQL row, found none")
        return json.loads(raw)

    def rows(self, sql):
        raw = self.sql(f"SELECT COALESCE(json_agg(record), '[]'::json) FROM ({sql}) AS record")
        return json.loads(raw)

    def scalar(self, sql):
        value = self.sql(sql)
        require(value and "\n" not in value, "Expected one PostgreSQL scalar")
        return value

    def redis(self, *command):
        require(command and command[0] in {"PING", "GET", "SCARD", "SISMEMBER"}, "Verifier accepts Redis reads only")
        args = self.args
        mode = args.redis_mode if args.redis_mode != "auto" else args.db_mode
        if mode == "docker" or args.redis_cli:
            cli = ["--raw", *map(str, command)]
            invocation = [args.docker, "exec", args.redis_container, "redis-cli", *cli] if mode == "docker" else [
                args.redis_cli, "-h", args.redis_host, "-p", str(args.redis_port), *cli]
            env = os.environ.copy()
            if args.redis_password_env and env.get(args.redis_password_env):
                env["REDISCLI_AUTH"] = env[args.redis_password_env]
                SECRET_VALUES.add(env["REDISCLI_AUTH"])
            result = subprocess.run(invocation, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15)
            require(result.returncode == 0 and not result.stdout.startswith(("ERR", "NOAUTH")),
                    f"Redis read failed: {redact((result.stderr or result.stdout).strip()[:300])}")
            return result.stdout.strip()
        with socket.create_connection((args.redis_host, args.redis_port), timeout=5) as connection:
            stream = connection.makefile("rb")
            def exchange(parts):
                encoded = [str(part).encode("utf-8") for part in parts]
                connection.sendall(b"*" + str(len(encoded)).encode() + b"\r\n" + b"".join(
                    b"$" + str(len(part)).encode() + b"\r\n" + part + b"\r\n" for part in encoded))
                line = stream.readline()
                require(line, "Redis closed the connection")
                prefix, text = line[:1], line[1:-2]
                if prefix == b"-":
                    raise VerificationFailure("Redis error: " + redact(text.decode("utf-8", errors="replace")))
                if prefix == b"$":
                    length = int(text)
                    return None if length < 0 else stream.read(length + 2)[:-2].decode("utf-8")
                require(prefix in {b"+", b":"}, "Unexpected Redis response")
                return text.decode("utf-8")
            password = os.environ.get(args.redis_password_env, "") if args.redis_password_env else ""
            if password:
                SECRET_VALUES.add(password)
                equal(exchange(("AUTH", password)), "OK", "Redis authentication")
            return exchange(command)


def verify_evidence_ids(ids, sources):
    require(isinstance(ids, list) and ids, "Recommendation must declare actual review evidenceIds")
    for evidence in ids:
        matched = re.fullmatch(r"ev-(\d+)-(\d+)", str(evidence))
        require(matched, f"Invalid evidence reference: {evidence}")
        shop_id, review_id = map(int, matched.groups())
        row = sources.row(f"SELECT id, shop_id FROM reviews WHERE id={review_id}")
        equal(row["shop_id"], shop_id, f"{evidence} actual shop")
    return ids


def eval_fixture_entry(user_id, phone, password_env, order_id, shop_id, sku_id):
    return {"userId": user_id, "phone": phone, "passwordEnv": password_env,
            "orderId": order_id, "shopId": shop_id, "skuId": sku_id}


def parser():
    command = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    command.add_argument("--shop-url", default="http://localhost:8081")
    command.add_argument("--skip-agent", action="store_true", help="Explicitly SKIP real model checks; core checks still run")
    command.add_argument("--output", type=Path, default=ROOT / "docs/reports/real-integration-latest.json")
    command.add_argument("--timeout", type=float, default=75)
    command.add_argument("--db-mode", choices=("docker", "native"), default="docker")
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
    command.add_argument("--redis-cli", help="Native redis-cli executable; otherwise use the standard-library RESP reader")
    command.add_argument("--redis-host", default="127.0.0.1")
    command.add_argument("--redis-port", type=int, default=6380)
    command.add_argument("--redis-password-env", default="")
    command.add_argument("--password-env", default="SCOUTBITE_VERIFY_PASSWORD", help="Password for new verification users, generated in memory when unset")
    command.add_argument("--admin-password-env", default="SCOUTBITE_VERIFY_ADMIN_PASSWORD")
    command.add_argument("--merchant-password-env", default="SCOUTBITE_VERIFY_MERCHANT_PASSWORD")
    command.add_argument("--prepare-eval", action="store_true")
    command.add_argument("--eval-fixtures", type=Path, default=ROOT / "deploy/logs/eval-fixtures.json")
    return command


class Verification:
    def __init__(self, args, report):
        self.args, self.report = args, report
        self.api = Api(args.shop_url, args.timeout)
        self.sources = ReadOnlySources(args)
        self.password = os.environ.get(args.password_env) or secrets.token_urlsafe(18)
        SECRET_VALUES.add(self.password)
        self.actors = {}
        self.records = {}
        # Separate phone suffixes per process/run, still valid 11-digit demonstration numbers.
        self.phone_base = int.from_bytes(secrets.token_bytes(4), "big") % 100_000_000
        self.phone_cursor = 0

    def phone(self):
        self.phone_cursor += 1
        return "138" + f"{(self.phone_base + self.phone_cursor) % 100_000_000:08d}"

    def login(self, phone, password, expected_role):
        SECRET_VALUES.add(password)
        login = self.api.ok("POST", "/api/auth/login", {"phone": phone, "password": password})
        require(isinstance(login, dict) and login.get("token"), "Login did not return a token")
        SECRET_VALUES.add(login["token"])
        equal(login["role"], expected_role, "login role")
        actor = {**login, "phone": phone}
        me = self.api.ok("GET", "/api/auth/me", actor=actor)
        equal(me["id"], login["userId"], "JWT current user")
        return actor

    def register(self, role="USER", password=None, nickname="验收用户"):
        phone = self.phone()
        password = password or self.password
        SECRET_VALUES.add(password)
        account = self.api.ok("POST", "/api/auth/register", {"phone": phone, "password": password, "role": role,
                                                    "nickname": nickname + self.report.run_id[-8:]})
        self.created("users", {"id": account["id"], "phone": phone, "role": role})
        return self.login(phone, password, role)

    def created(self, kind, evidence):
        self.report.resources.setdefault("created", {}).setdefault(kind, []).append(evidence)
        self.report.save()

    def order(self, actor, sku_id, label, user_coupon=None):
        body = {"skuId": sku_id}
        if user_coupon is not None:
            body["userCouponId"] = user_coupon
        key = f"vr-{self.report.run_id}-{label}"
        require(len(key) <= 64, "Generated idempotency key exceeds API limit")
        result = self.api.ok("POST", "/api/orders", body, actor, key)
        self.created("orders", {"id": result["id"], "userId": actor["userId"], "skuId": sku_id, "idempotencyKey": key})
        equal(result["status"], "CREATED", "new order status")
        return result, key

    def new_shop(self, merchant, label, approve=False):
        body = {"name": f"验收专用{label}-{self.report.run_id}", "category": "HOTPOT", "city": "杭州",
                "lat": 30.24, "lng": 120.15, "address": "验收测试地址（专用API数据）"}
        shop = self.api.ok("POST", "/api/merchant/shops", body, merchant)
        self.created("shops", {"id": shop["id"], "ownerId": merchant["userId"], "label": label})
        equal(shop["status"], "pending", "new shop review status")
        equal(shop["address"], body["address"], "shop address roundtrip")
        if approve:
            self.api.ok("POST", f"/api/admin/shops/{shop['id']}/approve", {}, self.actors["admin"])
            shop = self.api.ok("GET", f"/api/shops/{shop['id']}", actor=merchant)
            equal(shop["status"], "approved", "admin approval")
        return shop

    def new_sku(self, merchant, shop_id, label, stock=25):
        sku = self.api.ok("POST", "/api/merchant/skus", {"shopId": shop_id, "title": f"验收双人套餐-{label}-{self.report.run_id}",
                                                        "price": 12800, "stock": stock}, merchant)
        self.created("skus", {"id": sku["id"], "shopId": shop_id, "label": label})
        return sku

    def new_coupon(self, merchant, shop_id, label):
        coupon = self.api.ok("POST", "/api/merchant/coupons", {"shopId": shop_id, "title": f"验收满100减15-{label}",
                                                           "threshold": 10000, "amount": 1500, "total": 12}, merchant)
        self.created("coupons", {"id": coupon["id"], "shopId": shop_id, "label": label})
        return coupon

    def stock(self, sku_id):
        return int(self.sources.scalar(f"SELECT stock FROM skus WHERE id={int(sku_id)}"))

    def coupon_record(self, user_coupon):
        return self.sources.row(f"SELECT id, user_id, coupon_id, status, order_id FROM user_coupons WHERE id={int(user_coupon)}")

    def claim(self, coupon, actor):
        before = int(self.sources.redis("GET", f"coupon:{coupon['id']}:stock"))
        claimed = self.api.ok("POST", f"/api/coupons/{coupon['id']}/claim", {}, actor)
        user_coupon = claimed["userCouponId"]
        self.created("userCoupons", {"id": user_coupon, "couponId": coupon["id"], "userId": actor["userId"]})
        equal(claimed["status"], "UNUSED", "claim status")
        equal(int(self.sources.redis("GET", f"coupon:{coupon['id']}:stock")), before - 1, "Redis claim stock")
        equal(self.sources.redis("SISMEMBER", f"coupon:{coupon['id']}:users", actor["userId"]), "1", "Redis claim membership")
        row = self.coupon_record(user_coupon)
        equal(row["user_id"], actor["userId"], "DB coupon owner")
        equal(row["coupon_id"], coupon["id"], "DB coupon template")
        mine = self.api.ok("GET", "/api/coupons/mine?status=UNUSED", actor=actor)
        item = next((item for item in mine if item.get("userCouponId") == user_coupon), None)
        require(item is not None, "Claimed coupon is absent from mine")
        for field in ("shopId", "threshold", "amount", "title", "perUserLimit"):
            equal(item[field], coupon[field], "mine coupon " + field)
        for field in ("startAt", "endAt"):
            equal_instant(item[field], coupon[field], "mine coupon " + field)
        equal(item["id"], user_coupon, "mine held identity")
        self.api.reject("POST", f"/api/coupons/{coupon['id']}/claim", {40901, 40902}, {}, actor)
        equal(int(self.sources.redis("GET", f"coupon:{coupon['id']}:stock")), before - 1, "duplicate claim preserves Redis")
        return user_coupon

    def readiness(self):
        health = self.api.request("GET", "/actuator/health")
        equal(health.get("status"), "UP", "shop health")
        equal(self.sources.scalar("SELECT 1"), "1", "PostgreSQL readiness")
        equal(self.sources.redis("PING"), "PONG", "Redis readiness")
        return {"shop": "UP", "postgres": "SELECT 1", "redis": "PONG", "databaseMode": self.args.db_mode}

    def setup(self):
        self.actors["admin"] = self.login("13900000000", os.environ.get(self.args.admin_password_env, "admin123456"), "ADMIN")
        self.actors["merchant"] = self.login("13611110004", os.environ.get(self.args.merchant_password_env, "merchant123456"), "MERCHANT")
        self.actors["user"] = self.register(nickname="真实验收")
        self.actors["other-user"] = self.register(nickname="越权验收")
        self.actors["other-merchant"] = self.register("MERCHANT", nickname="其他商家验收")
        owned = self.api.ok("GET", "/api/merchant/shops", actor=self.actors["merchant"])
        approved = [shop for shop in owned if shop.get("status") == "approved"]
        approved.sort(key=lambda shop: -(shop.get("reviewCount") or 0))
        shop = approved[0] if approved else self.new_shop(self.actors["merchant"], "审核", approve=True)
        self.records["shop"] = shop
        self.records["sku"] = self.new_sku(self.actors["merchant"], shop["id"], "main")
        self.records["coupon"] = self.new_coupon(self.actors["merchant"], shop["id"], "main")
        self.records["pending-shop"] = self.new_shop(self.actors["merchant"], "待审")
        self.records["pending-sku"] = self.new_sku(self.actors["merchant"], self.records["pending-shop"]["id"], "pending", 5)
        self.records["pending-coupon"] = self.new_coupon(self.actors["merchant"], self.records["pending-shop"]["id"], "pending")
        self.records["foreign-shop"] = self.new_shop(self.actors["other-merchant"], "异店", approve=True)
        self.records["foreign-coupon"] = self.new_coupon(self.actors["other-merchant"], self.records["foreign-shop"]["id"], "foreign")
        self.report.resources.update({"userId": self.actors["user"]["userId"], "otherUserId": self.actors["other-user"]["userId"],
                                      "shopId": shop["id"], "skuId": self.records["sku"]["id"], "couponId": self.records["coupon"]["id"],
                                      "pendingShopId": self.records["pending-shop"]["id"], "foreignShopId": self.records["foreign-shop"]["id"]})
        return dict(self.report.resources)

    def visibility(self):
        merchant, user = self.actors["merchant"], self.actors["user"]
        pending, sku = self.records["pending-shop"], self.records["pending-sku"]
        for resource in ("skus", "coupons", "reviews"):
            self.api.reject("GET", f"/api/shops/{pending['id']}/{resource}", {40001}, actor=user)
        self.api.reject("GET", f"/api/shops/{pending['id']}", {40001}, actor=user)
        before = self.stock(sku["id"])
        self.api.reject("POST", "/api/orders", {40001, 40903}, {"skuId": sku["id"]}, user, f"vr-{self.report.run_id}-pending")
        equal(self.stock(sku["id"]), before, "pending purchase stock unchanged")
        equal(int(self.sources.scalar(f"SELECT count(*) FROM orders WHERE sku_id={sku['id']}")), 0, "pending purchase creates no order")
        queue = self.api.ok("GET", "/api/admin/shops?status=pending", actor=self.actors["admin"])
        require(any(shop["id"] == pending["id"] for shop in queue), "Pending shop absent from admin queue")
        catalog = self.api.ok("GET", f"/api/merchant/skus?shopId={pending['id']}", actor=merchant)
        require(any(item["id"] == sku["id"] for item in catalog), "Merchant cannot prepare pending shop catalog")
        return {"pendingShopId": pending["id"], "publicResources": "rejected", "stock": before}

    def permissions(self):
        shop_id, sku_id = self.records["shop"]["id"], self.records["sku"]["id"]
        user, merchant, other = self.actors["user"], self.actors["merchant"], self.actors["other-merchant"]
        checks = []
        for path in (f"/api/merchant/orders?shopId={shop_id}", f"/api/merchant/skus?shopId={shop_id}", f"/api/merchant/coupons?shopId={shop_id}"):
            checks.append(self.api.reject("GET", path, {40300}, actor=other))
            checks.append(self.api.reject("GET", path, {40300}, actor=user))
        checks.append(self.api.reject("POST", f"/api/admin/shops/{self.records['pending-shop']['id']}/approve", {40300}, {}, merchant))
        checks.append(self.api.reject("PATCH", f"/api/merchant/skus/{sku_id}", {40300}, {"stock": 0}, other))
        before = self.stock(sku_id)
        foreign_held = self.claim(self.records["foreign-coupon"], user)
        checks.append(self.api.reject("POST", "/api/orders", {40001}, {"skuId": sku_id, "userCouponId": foreign_held},
                                      user, f"vr-{self.report.run_id}-foreigncoupon"))
        equal(self.stock(sku_id), before, "foreign coupon order stock unchanged")
        equal(self.coupon_record(foreign_held)["status"], "UNUSED", "foreign coupon not frozen")
        if not self.args.skip_agent:
            checks.append(self.api.reject("POST", "/api/agent/merchant/analyze", {40300}, {"shopId": shop_id, "skill": "ops"}, other))
            checks.append(self.api.reject("POST", "/api/agent/merchant/analyze", {40300}, {"shopId": shop_id, "skill": "ops"}, user))
        return checks

    def checkout(self):
        user, sku, coupon = self.actors["user"], self.records["sku"], self.records["coupon"]
        held = self.claim(coupon, user)
        before = self.stock(sku["id"])
        order, key = self.order(user, sku["id"], "main", held)
        equal(order["priceSnapshot"], sku["price"] - coupon["amount"], "actual payable cents")
        equal(order["couponId"], coupon["id"], "order template anchor")
        repeated = self.api.ok("POST", "/api/orders", {"skuId": sku["id"], "userCouponId": held}, user, key)
        equal(repeated["id"], order["id"], "idempotent order retry")
        equal(self.stock(sku["id"]), before - 1, "one SKU reservation")
        frozen = self.coupon_record(held)
        equal(frozen["status"], "FROZEN", "DB held coupon frozen")
        equal(frozen["order_id"], order["id"], "DB coupon order binding")
        equal(int(self.sources.scalar(f"SELECT count(*) FROM orders WHERE sku_id={sku['id']} AND user_id={user['userId']}")), 1, "one DB order")
        self.api.reject("POST", "/api/orders", {40901}, {"skuId": sku["id"]}, self.actors["other-user"], key)
        self.api.reject("POST", f"/api/orders/{order['id']}/pay", {40001, 40300}, {}, self.actors["other-user"])
        paid = self.api.ok("POST", f"/api/orders/{order['id']}/pay", {}, user)
        equal(paid["status"], "PAID", "paid state")
        equal(self.coupon_record(held)["status"], "USED", "payment uses coupon")
        for action in ("cancel", "refund", "redeem"):
            self.api.reject("POST", f"/api/orders/{order['id']}/{action}", {40001, 40300}, {}, self.actors["other-user"])
        self.api.reject("POST", "/api/reviews", {40903}, {"orderId": order["id"], "scores": {"taste": 5}, "content": "未消费不可评价"}, user)
        self.api.reject("POST", f"/api/merchant/orders/{order['id']}/redeem", {40300}, {}, self.actors["other-merchant"])
        redeemed = self.api.ok("POST", f"/api/merchant/orders/{order['id']}/redeem", {}, self.actors["merchant"])
        equal(redeemed["status"], "REDEEMED", "merchant redeem state")
        repeated = self.api.ok("POST", f"/api/merchant/orders/{order['id']}/redeem", {}, self.actors["merchant"])
        equal(repeated["status"], "REDEEMED", "idempotent merchant redeem")
        sales = int(self.sources.scalar(f"SELECT sales FROM skus WHERE id={sku['id']}"))
        equal(sales, 1, "only one fulfilled sale")
        self.records.update({"order": order, "held": held, "reserved-stock": before - 1})
        self.report.resources.update({"orderId": order["id"], "userCouponId": held})
        return {"orderId": order["id"], "priceSnapshot": paid["priceSnapshot"], "stock": before - 1, "sales": sales, "couponStatus": "USED"}

    def restoration(self, kind):
        user, merchant = self.actors["user"], self.actors["merchant"]
        sku_id = self.records["sku"]["id"]
        coupon = self.new_coupon(merchant, self.records["shop"]["id"], kind)
        held = self.claim(coupon, user)
        before = self.stock(sku_id)
        order, _ = self.order(user, sku_id, kind, held)
        equal(self.stock(sku_id), before - 1, kind + " reserved stock")
        if kind == "refund":
            self.api.ok("POST", f"/api/orders/{order['id']}/pay", {}, user)
            equal(self.coupon_record(held)["status"], "USED", "refund paid coupon")
        result = self.api.ok("POST", f"/api/orders/{order['id']}/{kind}", {}, user)
        equal(result["status"], "REFUNDED" if kind == "refund" else "CANCELLED_USER", kind + " state")
        equal(self.stock(sku_id), before, kind + " stock restored")
        restored = self.coupon_record(held)
        equal(restored["status"], "UNUSED", kind + " coupon restored")
        equal(restored["order_id"], None, kind + " coupon binding cleared")
        self.api.reject("POST", f"/api/orders/{order['id']}/{kind}", {40903}, {}, user)
        equal(self.stock(sku_id), before, kind + " second call cannot restock again")
        equal(int(self.sources.redis("GET", f"coupon:{coupon['id']}:stock")), coupon["total"] - 1, "restoration does not mint claim stock")
        return {"orderId": order["id"], "skuStock": before, "couponStatus": "UNUSED", "repeatRejected": True}

    def trace(self, actor, skill, expected_input, expected_output=None):
        traces = self.api.ok("GET", "/api/agent/traces", actor=actor)
        matched = [trace for trace in traces if trace.get("skill") == skill and all(
            (trace.get("input") or {}).get(key) == value for key, value in expected_input.items())]
        require(matched, f"Missing {skill} trace for this exact run input")
        trace = matched[0]
        equal(trace["userId"], actor["userId"], "trace owner")
        require(isinstance(trace.get("latencyMs"), int) and trace["latencyMs"] >= 0, "Trace latency is invalid")
        tools = trace.get("tools") or {}
        require(isinstance(tools.get("toolCalls"), list) and tools["toolCalls"], "Trace toolCalls must be recorded")
        if expected_output is not None:
            equal(trace["output"], expected_output, skill + " HTTP trace output")
        stored = self.sources.row(f"SELECT id, user_id, skill, input, tools_json, output FROM agent_traces WHERE id={int(trace['id'])}")
        equal(stored["user_id"], actor["userId"], "DB trace owner")
        equal(stored["skill"], skill, "DB trace skill")
        equal(stored["output"], trace["output"], "DB trace output matches HTTP")
        return trace

    def agent_publish(self):
        user, order = self.actors["user"], self.records["order"]
        before = int(self.sources.scalar(f"SELECT count(*) FROM reviews WHERE order_id={order['id']}"))
        note = "味道不错，服务热情，排队等位较久；以下评价由本人确认。"
        draft = self.api.ok("POST", "/api/agent/user/review-draft", {"orderId": order["id"], "userNote": note,
                                                                  "preferScores": {"taste": 4, "wait": 3, "env": 4}}, user)
        require(isinstance(draft.get("draftId"), str) and draft["draftId"], "Draft has no draftId")
        require(draft.get("content") and draft.get("usedFacts"), "Draft has no content/fact references")
        equal(int(self.sources.scalar(f"SELECT count(*) FROM reviews WHERE order_id={order['id']}")), before, "generation never publishes")
        equal(self.sources.scalar(f"SELECT status FROM orders WHERE id={order['id']}"), "REDEEMED", "draft preserves order state")
        shop_name, sku_title = self.records["shop"]["name"], self.records["sku"]["title"]
        expected_facts = {"店铺：" + shop_name, "套餐：" + sku_title, f"实付：约{order['priceSnapshot'] / 100.0}元"}
        ordered_at = self.sources.row(f"SELECT created_at FROM orders WHERE id={order['id']}")["created_at"]
        utc_time = datetime.fromisoformat(ordered_at).astimezone(timezone.utc).isoformat(timespec="seconds")[:19]
        expected_facts.add("下单时间：" + utc_time)
        require(all(fact in expected_facts for fact in draft["usedFacts"]), "Draft usedFacts includes facts not present in the real order")
        draft_trace = self.trace(user, "review-draft", {"orderId": order["id"]}, draft)
        require(f"GET /internal/orders/{order['id']}/facts" in draft_trace["tools"]["toolCalls"], "Draft trace lacks the actual order facts tool")
        path = "/api/agent/user/review-draft/" + quote(draft["draftId"], safe="") + "/publish"
        self.api.reject("POST", path, {40300}, {"content": "越权修改"}, self.actors["other-user"])
        self.api.reject("POST", path, {40001}, {"content": "", "scores": {"taste": 4, "wait": 3, "env": 4}}, user)
        equal(int(self.sources.scalar(f"SELECT count(*) FROM reviews WHERE order_id={order['id']}")), before, "failed confirmation never publishes")
        edited = f"本人修改确认-{self.report.run_id}：味道不错，服务热情，环境整洁，排队等位较久。"
        scores = {"taste": 4, "wait": 3, "env": 5}
        review = self.api.ok("POST", path, {"content": edited, "scores": scores, "orderId": -999}, user)
        equal(review["content"], edited, "edited review content actually published")
        equal(review["scores"], scores, "edited scores actually published")
        equal(review["orderId"], order["id"], "draft original order anchor cannot be overridden")
        self.api.reject("POST", path, {40001, 40901}, {"content": edited, "scores": scores}, user)
        publish_trace = self.trace(user, "review-publish", {"draftId": draft["draftId"]}, review)
        self.records["review"] = review
        self.created("reviews", {"id": review["id"], "orderId": order["id"], "source": "edited Agent confirmation"})
        return {"draftId": draft["draftId"], "reviewId": review["id"], "draftTraceId": draft_trace["id"], "publishTraceId": publish_trace["id"]}

    def manual_publish(self):
        order = self.records["order"]
        content = f"本人手写真实验收-{self.report.run_id}：味道不错，服务热情，环境整洁，排队等位较久。"
        review = self.api.ok("POST", "/api/reviews", {"orderId": order["id"], "scores": {"taste": 4, "wait": 3, "env": 5},
                                                      "content": content}, self.actors["user"])
        self.records["review"] = review
        self.created("reviews", {"id": review["id"], "orderId": order["id"], "source": "manual"})
        return {"reviewId": review["id"], "source": "manual user-authored review; no Agent call"}

    def reply_and_reconcile(self):
        review, user, merchant, order = self.records["review"], self.actors["user"], self.actors["merchant"], self.records["order"]
        reply = self.api.ok("POST", f"/api/reviews/{review['id']}/replies", {"content": "谢谢真实反馈，商家会关注排队与服务体验。"}, merchant)
        self.created("replies", {"id": reply["id"], "reviewId": review["id"]})
        equal(reply["isMerchant"], True, "owned shop merchant badge")
        public = self.api.ok("GET", f"/api/shops/{order['shopId']}/reviews")
        published = next((item for item in public if item["id"] == review["id"]), None)
        require(published and any(item["id"] == reply["id"] and item["isMerchant"] for item in published["replies"]), "Merchant reply is not publicly visible")
        user_orders = self.api.ok("GET", "/api/orders", actor=user)
        actual = next(item for item in user_orders if item["id"] == order["id"])
        equal(actual["status"], "REVIEWED", "HTTP final order state")
        equal(actual["reviewId"], review["id"], "HTTP final review link")
        unreviewed = self.api.ok("GET", "/api/orders?unreviewed=true", actor=user)
        require(not any(item["id"] == order["id"] for item in unreviewed), "Reviewed order remains in unreviewed list")
        self.api.reject("POST", "/api/reviews", {40901}, {"orderId": order["id"], "scores": {"taste": 5}, "content": "重复提交"}, user)
        row = self.sources.row(f"SELECT o.id, o.user_id, o.shop_id, o.sku_id, o.price_snapshot, o.status, r.id AS review_id, r.content, r.scores_json FROM orders o JOIN reviews r ON r.order_id=o.id WHERE o.id={order['id']}")
        equal(row["status"], "REVIEWED", "DB final order state")
        equal(row["review_id"], review["id"], "DB final review link")
        equal(row["content"], review["content"], "DB edited/manual content")
        equal(row["scores_json"], review["scores"], "DB scores")
        equal(row["price_snapshot"], 11300, "DB payable cents")
        equal(int(self.sources.scalar(f"SELECT count(*) FROM reviews WHERE order_id={order['id']}")), 1, "one DB review")
        stored_reply = self.sources.row(f"SELECT id, review_id, user_id, is_merchant FROM review_replies WHERE id={reply['id']}")
        equal(stored_reply["is_merchant"], True, "DB merchant badge")
        equal(self.coupon_record(self.records["held"])["status"], "USED", "DB final coupon")
        self.report.resources["reviewId"] = review["id"]
        return {"orderId": row["id"], "status": row["status"], "reviewId": review["id"], "replyId": reply["id"], "dbMatched": True}

    def recommend(self):
        message = f"{self.report.run_id} 今晚两个人在西湖附近吃火锅，套餐预算300元，有哪些店，告诉我缺点并引用评价。"
        result = self.api.ok("POST", "/api/agent/user/recommend", {"message": message, "lat": 30.24, "lng": 120.15}, self.actors["user"])
        require(result.get("answer") and 1 <= len(result.get("shops", [])) <= 3, "Recommendation is empty or exceeds three shops")
        require(len(result.get("pros", [])) == len(result["shops"]) and len(result.get("cons", [])) == len(result["shops"]), "Recommendation pros/cons mismatch")
        for item in result["shops"]:
            require(item.get("reason") and item.get("cons"), "Each recommended shop needs reason and drawback")
            row = self.sources.row(f"SELECT id, name, category, status FROM shops WHERE id={int(item['id'])}")
            equal(row["status"], "approved", "recommended shop approval")
            equal(row["name"], item["name"], "recommended shop actual name")
        ids = verify_evidence_ids(result.get("evidenceIds"), self.sources)
        trace = self.trace(self.actors["user"], "recommend", {"message": message}, result)
        for evidence in ids:
            shop_id = int(evidence.split("-")[1])
            require(f"GET /internal/shops/{shop_id}/evidence" in trace["tools"]["toolCalls"], "Reference has no corresponding evidence tool call")
        return {"shopIds": [item["id"] for item in result["shops"]], "evidenceIds": ids, "traceId": trace["id"]}

    def merchant_analyze(self, skill):
        shop_id, merchant = self.records["shop"]["id"], self.actors["merchant"]
        result = self.api.ok("POST", "/api/agent/merchant/analyze", {"shopId": shop_id, "skill": skill}, merchant)
        equal(result.get("skill"), skill, "analysis skill")
        for layer in ("observations", "hypotheses", "suggestions"):
            require(isinstance(result.get(layer), list) and result[layer] and all(isinstance(item, str) and item.strip() for item in result[layer]), "Missing analysis layer: " + layer)
        require(1 <= len(result["suggestions"]) <= 2, "Analysis suggestions exceed contract")
        for hypothesis in result["hypotheses"]:
            require(re.search(r"可能|或许|大概|猜测|大概率|一种可能", hypothesis), "Analysis hypothesis lacks uncertainty wording")
            require(not re.search(r"证明了?|肯定是|就是由于|百分百|无疑", hypothesis), "Analysis hypothesis makes a certainty assertion")
        tool = {"ops": "metrics", "reviews": "review-clusters", "competitors": "competitors"}[skill]
        expected_tool = f"GET /internal/merchant/{shop_id}/{tool}"
        require(expected_tool in result.get("toolCalls", []), "Analysis has no actual skill tool reference")
        trace = self.trace(merchant, "analyze-" + skill, {"shopId": shop_id, "skill": skill}, result)
        require(expected_tool in trace["tools"]["toolCalls"], "Analysis trace lacks skill tool")
        # Verify numeric observation references against independently reconstructed tool facts.
        facts = self.analysis_facts(skill, shop_id)
        fact_text = json.dumps(facts, ensure_ascii=False)
        for observation in result["observations"]:
            for number in re.findall(r"\d+(?:\.\d+)?", observation):
                require(number in fact_text, f"Observation number {number} absent from independently read {skill} facts")
        return {"skill": skill, "layers": {key: len(result[key]) for key in ("observations", "hypotheses", "suggestions")}, "traceId": trace["id"]}

    def analysis_facts(self, skill, shop_id):
        reviews = self.sources.rows(f"SELECT id, content, scores_json FROM reviews WHERE shop_id={shop_id} ORDER BY id DESC")
        def mean(review):
            values = review.get("scores_json") or {}
            return sum(values.values()) / len(values) if isinstance(values, dict) and values else 3.0
        if skill == "reviews":
            clusters = []
            for topic, words in TOPICS.items():
                hit = [review for review in reviews if any(word in review["content"] for word in words)]
                if hit:
                    clusters.append({"topic": topic, "count": len(hit), "avgScore": java_one_decimal(sum(map(mean, hit)) / len(hit)),
                                     "samples": [{"reviewId": review["id"], "score": mean(review), "text": review["content"]} for review in hit[:2]]})
            return clusters
        if skill == "ops":
            orders = self.sources.rows(f"SELECT user_id, coupon_id, created_at FROM orders WHERE shop_id={shop_id} AND status IN ('PAID','REDEEMED','REVIEWED')")
            first, frequency = {}, {}
            for order in orders:
                user_id = order["user_id"]
                date = datetime.fromisoformat(order["created_at"])
                first[user_id] = min(first.get(user_id, date), date)
                frequency[user_id] = frequency.get(user_id, 0) + 1
            since = datetime.now(timezone.utc) - timedelta(days=7)
            impressions = self.sources.rows(f"SELECT scene, count(*) AS count FROM impressions WHERE shop_id={shop_id} AND ts > now()-interval '7 days' GROUP BY scene")
            return {"shopId": shop_id, "totalValidOrders": len(orders), "totalCustomers": len(first),
                    "newCustomers7d": sum(date > since for date in first.values()), "repeatBuyers": sum(value >= 2 for value in frequency.values()),
                    "couponOrderShare": java_one_decimal(sum(order["coupon_id"] is not None for order in orders) * 100 / len(orders)) if orders else None,
                    "impressions7d": sum(item["count"] for item in impressions), "impressions7dByScene": {item["scene"]: item["count"] for item in impressions},
                    "reviewCount": len(reviews), "avgRating": java_one_decimal(sum(map(mean, reviews)) / len(reviews)) if reviews else None, "windowDays": 7}
        self_shop = self.sources.row(f"SELECT id, category, lat, lng FROM shops WHERE id={shop_id}")
        candidates = self.api.ok("GET", "/api/shops/nearby?" + urlencode({"lat": self_shop["lat"], "lng": self_shop["lng"], "radius": 3000, "category": self_shop["category"]}))
        facts = []
        for item in [item for item in candidates if item["id"] != shop_id][:5]:
            cid = int(item["id"])
            review_rows = self.sources.rows(f"SELECT id, content, scores_json FROM reviews WHERE shop_id={cid}")
            negative = next((topic for topic, words in TOPICS.items() if any(mean(review) < 3.5 and any(word in review["content"] for word in words) for review in review_rows)), None)
            facts.append({"shopId": cid, "name": item["name"], "distanceMeters": item["distanceMeters"],
                          "rating": java_one_decimal(sum(map(mean, review_rows)) / len(review_rows)) if review_rows else None,
                          "sales": int(self.sources.scalar(f"SELECT COALESCE(sum(sales),0) FROM skus WHERE shop_id={cid}")),
                          "hasCoupon": int(self.sources.scalar(f"SELECT count(*) FROM coupons WHERE shop_id={cid} AND end_at > now()")) > 0,
                          "topNegativeTopic": negative})
        return facts

    def prepare_eval(self):
        env_name = "SCOUTBITE_EVAL_FIXTURE_PASSWORD"
        password = os.environ.get(env_name)
        require(password and len(password) >= 6, "--prepare-eval requires SCOUTBITE_EVAL_FIXTURE_PASSWORD (value never written)")
        owner = self.register(password=password, nickname="评测订单主人")
        cold = self.register(password=password, nickname="评测冷启动")
        sku = self.new_sku(self.actors["merchant"], self.records["shop"]["id"], "eval", 10)
        order_ids = []
        entries = []
        for index in range(3):
            order, _ = self.order(owner, sku["id"], f"eval{index}")
            self.api.ok("POST", f"/api/orders/{order['id']}/pay", {}, owner)
            self.api.ok("POST", f"/api/merchant/orders/{order['id']}/redeem", {}, self.actors["merchant"])
            equal(self.sources.scalar(f"SELECT status FROM orders WHERE id={order['id']}"), "REDEEMED", "eval order is actually redeemed")
            equal(int(self.sources.scalar(f"SELECT count(*) FROM reviews WHERE order_id={order['id']}")), 0, "eval order remains unreviewed")
            order_ids.append(order["id"])
            entries.append(eval_fixture_entry(owner["userId"], owner["phone"], env_name, order["id"], sku["shopId"], sku["id"]))
        equal(int(self.sources.scalar(f"SELECT count(*) FROM user_profiles WHERE user_id={cold['userId']}")), 0, "eval cold user has no fabricated profile")
        mappings = {alias: {"phone": phone, "passwordEnv": "SCOUTBITE_EVAL_USER_PASSWORD"} for alias, phone in
                    {"13700000001": "13611110001", "13700000002": "13611110002", "13611110003": "13611110003"}.items()}
        mappings["13900000888"] = {"phone": cold["phone"], "passwordEnv": env_name}
        fixture = {"version": 1, "runId": self.report.run_id, "users": mappings,
                   "review": {"account": {"phone": owner["phone"], "passwordEnv": env_name}, "orderIds": order_ids},
                   "merchant": {"account": {"phone": "13611110004", "passwordEnv": "SCOUTBITE_EVAL_MERCHANT_PASSWORD"},
                                "shopIds": {str(alias): sku["shopId"] for alias in (41, 1, 11, 10, 5)}},
                   "createdRecords": entries,
                   "projectionNote": "Five merchant dataset aliases map to one actual owned reviewed shop; they are not five independent shop samples."}
        self.args.eval_fixtures.parent.mkdir(parents=True, exist_ok=True)
        self.args.eval_fixtures.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"fixturePath": str(self.args.eval_fixtures), "orderIds": order_ids, "coldUserId": cold["userId"], "shopId": sku["shopId"]}

    def run(self):
        if self.report.check("real service and independent read readiness", self.readiness) is None:
            self.report.skip("business and Agent checks", "Required HTTP/PostgreSQL/Redis dependency is unavailable")
            return
        if self.report.check("seed accounts and dedicated per-run API records", self.setup) is None:
            self.report.skip("remaining checks", "Account/record setup failed; inspect run records before retry")
            return
        self.report.check("pending shop public visibility and checkout gate", self.visibility)
        self.report.check("cross-role, cross-shop, cross-user coupon permissions", self.permissions)
        core = self.report.check("claim, coupon amount, idempotency, payment gate and merchant redeem", self.checkout)
        self.report.check("unpaid cancel restores stock and frozen coupon only once", lambda: self.restoration("cancel"))
        self.report.check("paid refund restores stock and used coupon only once", lambda: self.restoration("refund"))
        if core is None:
            self.report.skip("review confirmation and reply", "Main checkout failed")
        elif self.args.skip_agent:
            self.report.skip("real review draft, edited confirmation and draft traces", "--skip-agent explicitly selected")
            if self.report.check("manual user review through the real API", self.manual_publish) is not None:
                self.report.check("merchant reply and final HTTP/DB reconciliation", self.reply_and_reconcile)
        else:
            if self.report.check("real review draft, edited confirmation and draft traces", self.agent_publish) is not None:
                self.report.check("merchant reply and final HTTP/DB reconciliation", self.reply_and_reconcile)
            else:
                self.report.skip("merchant reply and final reviewed reconciliation", "Agent confirmation failed; no fabricated manual substitution")
        if self.args.skip_agent:
            self.report.skip("real recommendation and evidence/trace references", "--skip-agent explicitly selected")
            for skill in ("ops", "reviews", "competitors"):
                self.report.skip("real merchant " + skill + " three-layer analysis", "--skip-agent explicitly selected")
        else:
            self.report.check("real recommendation and evidence/trace references", self.recommend)
            for skill in ("ops", "reviews", "competitors"):
                self.report.check("real merchant " + skill + " three-layer analysis", lambda skill=skill: self.merchant_analyze(skill))
        if self.args.prepare_eval:
            self.report.check("prepare dedicated real API evaluation fixtures", self.prepare_eval)


def main(argv=None):
    args = parser().parse_args(argv)
    require(args.timeout > 0, "--timeout must be positive")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
    report = Reporter(run_id, args.shop_url, args.output)
    report.save()
    try:
        runner = Verification(args, report)
        runner.run()
    except Exception as error:
        report.check("verifier initialization or unhandled failure", lambda: (_ for _ in ()).throw(error))
    report.save()
    result = report.summary()
    print(f"Result: {result['status']} {result['counts']}. Report: {args.output}", flush=True)
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
