#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
run_eval.py —— 使用现有真实事实评测 Agent，生成独立报告，保留历史结果。

用法（项目根目录）：
  python evals/run_eval.py --check --fixtures deploy/logs/eval-fixtures.json
  python evals/run_eval.py --mode full --fixtures deploy/logs/eval-fixtures.json --skip-judge
  python evals/run_eval.py --mode smoke --only review --fixtures deploy/logs/eval-fixtures.json
  python evals/run_eval.py --judge-only evals/reports/full-<run>.json --report evals/reports/judge-<run>.md

设计要点：
  - 进程内跑图（import graph 直调 run_*）：走 HTTP 就没法 monkeypatch tools 做破坏性试验
  - --check 不需要 LLM key，不生成内容、不注册/下单/核销；评测本身仍调用真实模型
  - fixtures 显式映射账号、已有未评核销单、真实商家门店；密码仅引用环境变量名
  - judge 抽样 5 条（量规冻结），只评本轮答案；--skip-judge 节省额外调用
  - 「是否自动发布」独立指标：跑完评价用例后查库，测试订单 0 新评价（ADR-028 守门员）
"""
import argparse
import base64
import hashlib
import json
import os
import re
import statistics
import sys
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from datetime import datetime
from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))          # evals/
ROOT = os.path.dirname(BASE)
AGENT = os.path.join(ROOT, "services", "agent-api")
sys.path.insert(0, AGENT)

# 关键：必须在 import llm/tools 之前显式加载 agent-api/.env
# （从项目根跑时模块内的 load_dotenv() 找的是 cwd，找不到）
from dotenv import load_dotenv
load_dotenv(os.path.join(AGENT, ".env"))

import httpx                    # noqa: E402
import llm                      # noqa: E402
import graph as recommend_module # noqa: E402
import review_graph as review_module # noqa: E402
import merchant_graph as merchant_module # noqa: E402
import tools as agent_tools     # noqa: E402  (命名避开 eval 内的 tools 概念)
from graph import run_recommend                  # noqa: E402
from review_graph import run_review_draft        # noqa: E402
from merchant_graph import run_merchant_analyze  # noqa: E402

SHOP = os.getenv("SCOUTBITE_SHOP_API_URL", "http://localhost:8081")
GUARD = 42201
HZ_LAT, HZ_LNG = 30.24, 120.15

http = httpx.Client(timeout=httpx.Timeout(10.0, connect=3.0))
_shop_cache: dict = {}          # 店详情缓存（品类/坐标校验用）
_review_cache: dict = {}        # 店评价缓存（引用存在校验用）
_sku_cache: dict = {}           # 店套餐缓存（预算校验用）


# ==================== 基础设施 ====================

def haversine(lat1, lng1, lat2, lng2):
    """球面距离（米）——与主站 GeoService 同公式"""
    from math import asin, cos, sin, sqrt
    r = 6371000.0
    rad = 3.141592653589793 / 180
    dlat = (lat2 - lat1) * rad
    dlng = (lng2 - lng1) * rad
    a = sin(dlat / 2) ** 2 + cos(lat1 * rad) * cos(lat2 * rad) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(a))


class FixtureError(ValueError):
    """Existing facts are not ready for the selected evaluation; never synthesize them."""


def response_data(response, path):
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get("code") != 0:
        code = body.get("code") if isinstance(body, dict) else "invalid-envelope"
        raise FixtureError(f"{path} 返回业务错误 code={code}")
    return body.get("data")


def read_api(path, headers=None):
    return response_data(http.get(SHOP + path, headers=headers), path)


def login(account):
    """Log in to an existing account with an environment-sourced password."""
    password = os.getenv(account["passwordEnv"], "")
    if not password:
        raise FixtureError(f"缺少密码环境变量 {account['passwordEnv']}")
    data = response_data(http.post(f"{SHOP}/api/auth/login", json={
        "phone": account["phone"], "password": password,
    }), "/api/auth/login")
    if not isinstance(data, dict) or not data.get("token"):
        raise FixtureError("/api/auth/login 未返回有效登录凭证")
    return data


def user_id_from_token(token: str) -> int:
    """解自家 JWT 的 payload（userId 在 sub claim——与 JwtUtil.issue 一致）"""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    data = json.loads(base64.urlsafe_b64decode(payload))
    uid = int(data.get("sub") or data.get("userId") or 0)
    assert uid > 0, f"JWT 解析失败: {list(data.keys())}"
    return uid


def get_shop(shop_id):
    if shop_id not in _shop_cache:
        _shop_cache[shop_id] = read_api(f"/api/shops/{shop_id}") or {}
    return _shop_cache[shop_id]


def get_reviews(shop_id):
    if shop_id not in _review_cache:
        reviews = read_api(f"/api/shops/{shop_id}/reviews") or []
        _review_cache[shop_id] = {x["id"] for x in reviews}
    return _review_cache[shop_id]


def get_skus(shop_id):
    if shop_id not in _sku_cache:
        _sku_cache[shop_id] = read_api(f"/api/shops/{shop_id}/skus") or []
    return _sku_cache[shop_id]


class CaseResult:
    """单条用例结果：id / 各项检查（True/False/None=不适用）"""
    def __init__(self, cid):
        self.id = cid
        self.checks: dict[str, bool] = {}
        self.latency_ms: int = 0
        self.tool_calls = 0
        self.detail = ""        # 失败原因摘要
        self.answer: dict | None = None
        self.evidence: list = []
        self.model_outputs: list = []

    def add(self, name, ok, detail=""):
        self.checks[name] = bool(ok)
        if not ok and detail:
            self.detail = detail


@contextmanager
def capture_calls(owner, name, outputs):
    """Save actual model/tool results, including those hidden by a rejected envelope."""
    original = getattr(owner, name)
    def observed(*args, **kwargs):
        value = original(*args, **kwargs)
        outputs.append(deepcopy(value))
        return value
    setattr(owner, name, observed)
    try:
        yield
    finally:
        setattr(owner, name, original)


def numeric_values(source):
    """Independent exact-value recheck; decimal spelling never changes a value."""
    if isinstance(source, bool) or source is None:
        return set()
    if isinstance(source, (int, float)):
        return {Decimal(str(source))}
    if isinstance(source, dict):
        items = source.values()
    elif isinstance(source, list):
        items = source
    elif isinstance(source, str):
        return {Decimal(value) for value in re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])", source)}
    else:
        return set()
    values = set()
    for item in items:
        values.update(numeric_values(item))
    return values


# ==================== 推荐用例 ====================

def run_recommend_case(case, uid_map) -> CaseResult:
    r = CaseResult(case["id"])
    token = uid_map[case["user"]]
    uid = user_id_from_token(token)
    lat = case.get("lat", HZ_LAT)
    lng = case.get("lng", HZ_LNG)

    t0 = time.time()
    original_evidence = agent_tools.get_evidence
    original_chat = recommend_module.chat_json
    model_errors = []
    def capture_evidence(shop_id):
        evidence = original_evidence(shop_id)
        r.evidence.append(evidence)
        return evidence
    def capture_chat(*args, **kwargs):
        try:
            output = original_chat(*args, **kwargs)
            r.model_outputs.append(deepcopy(output))
            return output
        except Exception as error:
            model_errors.append(type(error).__name__)
            raise
    agent_tools.get_evidence = capture_evidence
    recommend_module.chat_json = capture_chat
    try:
        out = run_recommend(uid, case["message"], lat, lng, "eval")
    finally:
        agent_tools.get_evidence = original_evidence
        recommend_module.chat_json = original_chat
    r.latency_ms = int((time.time() - t0) * 1000)

    exp = case.get("expect", {})
    data = out.get("data") if out.get("code") == 0 else None

    if out.get("code") != 0:
        # 诚实降级/护栏错误：直接全挂并记录
        r.add("api_ok", False, f"code={out['code']} {out.get('message','')[:60]}")
        return r
    r.add("api_ok", True)
    r.answer = data
    if model_errors:
        r.add("llm_ok", False, f"LLM 调用失败：{', '.join(model_errors)}；冷启动/画像降级不能冒充模型评测通过")
        return r

    shops = data.get("shops") or []
    r.tool_calls = len(data.get("toolCalls") or [])

    # 期望空结果（跨城）：应诚实回答没有，而不是硬推
    if exp.get("expectEmpty"):
        r.add("honest_empty", len(shops) == 0 and bool(data.get("answer")),
              f"shops={len(shops)}")
        return r
    # 期望澄清（冷启动+模糊）
    if exp.get("expectClarify"):
        r.add("clarify", data.get("needClarify") is True, f"needClarify={data.get('needClarify')}")
        return r

    # 非空用例的通用检查
    if exp.get("nonEmpty") or exp.get("category") or exp.get("budget"):
        r.add("non_empty", len(shops) >= 1, f"shops={len(shops)}")
    if shops:
        r.add("shop_cap_3", len(shops) <= 3, f"shops={len(shops)}")
        schema_ok = all(s.get("id") and s.get("name") and s.get("reason")
                        and s.get("cons") and str(s.get("cons")).strip()
                        for s in shops)
        r.add("schema", schema_ok)

        # 品类约束（独立反查店详情——不信 Agent 的话，信库）
        if exp.get("category"):
            bad = [s["name"] for s in shops
                   if (get_shop(s["id"]).get("category") or "?") != exp["category"]]
            r.add("constraint_category", not bad, f"混入: {bad}")

        # 预算约束：至少 1 家有 ≤预算×1.15 的在售套餐（"人均100左右"类表述给 15% 容差）
        # 注：公开 skus 接口只回在售项且无 onSale 字段——不过滤
        if exp.get("budget"):
            cap = exp["budget"] * 1.15
            mins = [min([sku.get("price", 10**9) / 100 for sku in get_skus(s["id"])]
                        or [10**9]) for s in shops]
            r.add("constraint_budget", any(m <= cap for m in mins),
                  f"各店最低价(元): {[round(m) for m in mins]} 预算{exp['budget']}")

        # 距离（检索半径 5km + 容差）
        if case.get("lat") is not None or case.get("lng") is not None:
            far = [s["name"] for s in shops
                   if haversine(lat, lng,
                                float(get_shop(s["id"]).get("lat", 0)),
                                float(get_shop(s["id"]).get("lng", 0))) > 5500]
            r.add("constraint_distance", not far, f"超距: {far}")

    # 引用存在率（独立反查评价接口）
    eids = data.get("evidenceIds") or []
    if eids:
        ok_ids, bad_ids = [], []
        for e in eids:
            m = re.fullmatch(r"ev-(\d+)-(\d+)", str(e))
            if not m:
                bad_ids.append(e)
                continue
            sid, rid = int(m.group(1)), int(m.group(2))
            (ok_ids if rid in get_reviews(sid) else bad_ids).append(e)
        r.add("citation_existence", not bad_ids, f"坏引用: {bad_ids[:3]}")
    elif shops:
        r.add("citation_existence", False, "有推荐但 0 引用")
    return r


# ==================== 评价用例 ====================

def run_review_case(case, order_ids, uid, sku_titles) -> CaseResult:
    r = CaseResult(case["id"])
    # Python hash() changes across processes; assign the same fact anchor reproducibly.
    index = int.from_bytes(hashlib.sha256(case["id"].encode()).digest()[:8], "big") % len(order_ids)
    oid = order_ids[index]
    t0 = time.time()
    with capture_calls(agent_tools, "get_order_facts", r.evidence), \
         capture_calls(review_module, "chat_json", r.model_outputs):
        out = run_review_draft(uid, oid, case.get("note") or None, case.get("prefer") or {})
    r.latency_ms = int((time.time() - t0) * 1000)
    r.tool_calls = len(r.evidence)

    if out.get("code") != 0:
        r.add("api_ok", False, f"code={out['code']} {out.get('message','')[:60]}")
        return r
    r.add("api_ok", True)
    d = out["data"]
    r.answer = d
    r.tool_calls = len(d.get("toolCalls") or [])

    scores = d.get("scores") or {}
    r.add("scores_complete",
          all(isinstance(scores.get(k), (int, float)) and 1 <= scores[k] <= 5
              for k in ("taste", "wait", "env")))
    for k, v in (case.get("prefer") or {}).items():
        r.add(f"prefer_{k}", scores.get(k) == v, f"{k}={scores.get(k)} 期望{v}")
    r.add("used_facts", bool(d.get("usedFacts")))
    content = d.get("content") or ""
    # 内容锚定：正文应包含真实套餐名前缀（前 2 字——模型可能缩写"四人欢聚套餐"为"四人套餐"）
    title = sku_titles[oid]
    anchor = bool(title and title[:2] in content)
    r.add("content_anchor", anchor, content[:50])
    # 编造抓拍（负例）：诱饵词不得【无声明地断言】——
    # 提示词防线生效后，合法行为是"提及但免责"（"用户提到X，清单未包含，不评价"）；
    # 出现且 ±25 字内无免责标记 → 判编造（v1.0.1 校准，见执行报告）
    DISCLAIM = re.compile(r"未包含|未核实|不评价|无法核实|无法确认|未经证实|清单.{0,4}未|不在.{0,6}清单|未提供|未证实|未达到|需自行判断|不下结论")
    for w in case.get("mustNotContain") or []:
        if w not in content:
            r.add("no_fabrication", True)
            continue
        idx = content.find(w)
        window = content[max(0, idx - 25): idx + len(w) + 15]
        r.add("no_fabrication", bool(DISCLAIM.search(window)),
              f"'{w}' 出现且无免责上下文: …{window}…")
    r.add("schema", bool(content) and len(content) <= 200)
    return r


# ==================== 商家用例 ====================

HEDGE = re.compile(r"可能|或许|大概|猜测|大概率|一种可能")
CERTAIN = re.compile(r"证明了?|肯定是|就是由于|百分百|无疑")


def run_merchant_case(case, uid) -> CaseResult:
    r = CaseResult(case["id"])
    t0 = time.time()
    tool = {"ops": "get_metrics", "reviews": "get_review_clusters", "competitors": "get_competitors"}[case["skill"]]
    with capture_calls(agent_tools, tool, r.evidence), \
         capture_calls(merchant_module, "chat_json", r.model_outputs):
        out = run_merchant_analyze(uid, case["shopId"], case["skill"])
    r.latency_ms = int((time.time() - t0) * 1000)
    r.tool_calls = len(r.evidence)

    if out.get("code") != 0:
        r.add("api_ok", False, f"code={out['code']} {out.get('message','')[:60]}")
        return r
    r.add("api_ok", True)
    d = out["data"]
    r.answer = d
    r.tool_calls = len(d.get("toolCalls") or [])
    obs, hyp, sug = d.get("observations") or [], d.get("hypotheses") or [], d.get("suggestions") or []

    # 独立取数复核：观察句的数字必须真的在工具结果里
    try:
        if case["skill"] == "ops":
            data = agent_tools.get_metrics(case["shopId"])
        elif case["skill"] == "reviews":
            data = agent_tools.get_review_clusters(case["shopId"])
        else:
            data = agent_tools.get_competitors(case["shopId"])
    except Exception as e:
        data = None
        r.add("recheck_source", False, f"复核取数失败: {type(e).__name__}")
    if data is not None:
        source_values = numeric_values(data)
        bad_nums = []
        for s in obs:
            # Use identical token rules for source text and observation text.
            # Dates/run IDs contain '-' separators; signed Decimal tokens must
            # stay consistent on both sides rather than lose their sign here.
            for num in numeric_values(str(s)):
                if num not in source_values:
                    bad_nums.append(format(num, "f"))
        r.add("numbers_in_source", not bad_nums, f"编造数字: {bad_nums[:3]}")
    r.add("hypotheses_hedged", bool(hyp) and all(HEDGE.search(str(h)) for h in hyp))
    r.add("no_certain_assert", not any(CERTAIN.search(str(h)) for h in hyp))
    r.add("suggestions_cap", 1 <= len(sug) <= 2, f"建议{len(sug)}条")
    r.add("three_layers", bool(obs) and bool(hyp) and bool(sug))
    return r


# ==================== Judge（量规冻结） ====================

JUDGE_RUBRIC = """你是评审员，按冻结量规给推荐回答打分。只看【用户问题】【候选证据】【回答】三样，1-5 分两个维度：

有用性 usefulness：
5 = 直接回应诉求，3 家各有理由且提及价格/评分/距离等具体事实，用户可直接决策
3 = 方向对但泛泛（理由空洞如"口碑好"），或只推 1 家
1 = 答非所问、编造、或全是套话

对比质量 comparison：
5 = 店与店之间有真实权衡（谁适合什么场景/预算差异说清），每家有可信缺点
3 = 罗列式介绍，缺少对比；或缺点敷衍
1 = 广告式全夸/无缺点/缺点与店无关

长度惩罚条款：冗长罗列、复读证据原文的长回答，两维各降 1 分。
只输出 json：{"usefulness": n, "comparison": n}"""


# ==================== 主流程 ====================

def pct(values):
    vals = [v for v in values if v is not None]
    return f"{100 * sum(vals) / len(vals):.0f}%" if vals else "—"


def p(values, q):
    if not values:
        return "—"
    s = sorted(values)
    return f"{s[min(len(s) - 1, int(len(s) * q))]}ms"


def fixture_account(value, label):
    if not isinstance(value, dict) or not isinstance(value.get("phone"), str) or not value["phone"]:
        raise FixtureError(f"{label} 需要现有账号 phone")
    name = value.get("passwordEnv")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise FixtureError(f"{label} 需要 passwordEnv 环境变量名")
    if "password" in value or "token" in value:
        raise FixtureError(f"{label} 禁止保存密码或 token；仅填写 passwordEnv")
    if not os.getenv(name):
        raise FixtureError(f"缺少密码环境变量 {name}")
    return {"phone": value["phone"], "passwordEnv": name}


def positive_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FixtureError(f"{label} 需要真实正整数 ID")
    return value


def setup(fixture_path, rec_cases, rev_cases, mer_cases):
    """Read existing fixtures. Login is the only POST; never mutate business data."""
    print("== 现有事实预检（不注册、不下单、不支付、不核销、不发布） ==")
    try:
        with open(fixture_path, encoding="utf-8-sig") as source:
            fixture = json.load(source)
    except (OSError, ValueError) as error:
        raise FixtureError(f"fixtures 无法读取：{type(error).__name__}") from None
    if not isinstance(fixture, dict) or fixture.get("version") != 1:
        raise FixtureError("fixtures.version 必须为 1")

    # Validate all passwords and mappings before the first HTTP request.
    users = fixture.get("users") or {}
    accounts = {}
    for alias in sorted({case["user"] for case in rec_cases}):
        accounts[alias] = fixture_account(users.get(alias), f"users.{alias}")
    review = fixture.get("review") or {}
    order_ids = []
    if rev_cases:
        accounts["review"] = fixture_account(review.get("account"), "review.account")
        raw_ids = review.get("orderIds")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise FixtureError("review.orderIds 需要已有 REDEEMED 且未评价的订单 ID 列表")
        order_ids = list(dict.fromkeys(positive_id(value, "review.orderIds") for value in raw_ids))
    merchant = fixture.get("merchant") or {}
    mapped_shops = {}
    if mer_cases:
        accounts["merchant"] = fixture_account(merchant.get("account"), "merchant.account")
        raw_shops = merchant.get("shopIds") or {}
        for sid in sorted({case["shopId"] for case in mer_cases}):
            mapped_shops[sid] = positive_id(raw_shops.get(str(sid)), f"merchant.shopIds.{sid}")

    health = http.get(SHOP + "/actuator/health")
    health.raise_for_status()
    if health.json().get("status") != "UP":
        raise FixtureError("shop-api 健康检查不是 UP")

    runtime = {"user_tokens": {}, "review_uid": None, "review_order_ids": order_ids,
               "review_titles": {}, "review_shops": {}, "review_before": set(),
               "merchant_uid": None, "merchant_shops": mapped_shops,
               "metadata": {"fixtureRunId": fixture.get("runId"), "reviewOrderIds": order_ids,
                            "merchantShopMapping": mapped_shops,
                            "uniqueMerchantShops": len(set(mapped_shops.values())),
                            "executionBoundary": "in-process graphs; existing facts only; Java facade/auth E2E is separate"}}
    logged_in = {}
    for alias, account in accounts.items():
        key = (account["phone"], account["passwordEnv"])
        if key not in logged_in:
            logged_in[key] = login(account)
        identity = logged_in[key]
        uid = user_id_from_token(identity["token"])
        expected_role = "MERCHANT" if alias == "merchant" else "USER"
        if identity.get("role") != expected_role:
            raise FixtureError(f"{alias} 角色必须为 {expected_role}")
        if alias == "review":
            runtime["review_uid"] = uid
        elif alias == "merchant":
            runtime["merchant_uid"] = uid
        else:
            runtime["user_tokens"][alias] = identity["token"]

    # API tools enforce the actual internal token. No secret is printed.
    for alias, user_token in runtime["user_tokens"].items():
        uid = user_id_from_token(user_token)
        profile = agent_tools.get_profile(uid)
        ambiguous = [case for case in rec_cases if case["user"] == alias
                     and case.get("expect", {}).get("nonEmpty")]
        needs_cold = any(case["user"] == alias and case.get("expect", {}).get("expectClarify")
                         for case in rec_cases)
        if needs_cold and profile.get("coldStart") is not True:
            raise FixtureError(f"users.{alias} 需无历史偏好的真实冷启动账号")
        if ambiguous and (profile.get("coldStart") or not profile.get("topCategories")):
            raise FixtureError(f"users.{alias} 的模糊请求用例需已刷新的真实偏好画像")

    # Check all required nearby categories using the same internal data boundary.
    for category in sorted({case.get("expect", {}).get("category") for case in rec_cases}
                           - {None}):
        if not agent_tools.search_shops(HZ_LAT, HZ_LNG, category=category):
            raise FixtureError(f"杭州 5km 内缺少 {category} 的已过审真实门店")

    for oid in order_ids:
        facts = agent_tools.get_order_facts(oid, runtime["review_uid"])
        if not (facts.get("exists") and facts.get("belongToUser") and facts.get("canReview")
                and facts.get("status") == "REDEEMED"):
            raise FixtureError(f"订单 {oid} 必须属于 review.account，状态 REDEEMED 且尚未评价")
        title = facts.get("skuTitle")
        if not title:
            raise FixtureError(f"订单 {oid} 缺少真实套餐名称")
        runtime["review_titles"][oid] = str(title)
        runtime["review_shops"][oid] = positive_id(facts.get("shopId"), f"订单 {oid}.shopId")
    for shop_id in set(runtime["review_shops"].values()):
        existing = read_api(f"/api/shops/{shop_id}/reviews") or []
        runtime["review_before"].update(item["orderId"] for item in existing)
    if set(order_ids) & runtime["review_before"]:
        raise FixtureError("评价 fixture 订单已有公开评价，不能复用")

    if mapped_shops:
        account = accounts["merchant"]
        identity = logged_in[(account["phone"], account["passwordEnv"])]
        owned = read_api("/api/merchant/shops", {"Authorization": "Bearer " + identity["token"]}) or []
        owned_ids = {shop["id"] for shop in owned if shop.get("ownerId") == runtime["merchant_uid"]}
        if not set(mapped_shops.values()).issubset(owned_ids):
            raise FixtureError("merchant.shopIds 必须全部属于 merchant.account 的真实门店")
        checked = set()
        collectors = {"ops": agent_tools.get_metrics, "reviews": agent_tools.get_review_clusters,
                      "competitors": agent_tools.get_competitors}
        for case in mer_cases:
            sid = mapped_shops[case["shopId"]]
            key = (sid, case["skill"])
            if key in checked:
                continue
            if not collectors[case["skill"]](sid):
                raise FixtureError(f"门店 {sid} 暂无 {case['skill']} 的真实可分析数据")
            checked.add(key)
    print(f"预检通过：推荐账号 {len(runtime['user_tokens'])}，复用核销单 {len(order_ids)}，"
          f"商家真实门店 {len(set(mapped_shops.values()))}")
    return runtime


def auto_publish_check(order_ids, before, order_shops) -> bool:
    """Read every fixture shop and ensure evaluation drafts created no new reviews."""
    after = set()
    for shop_id in set(order_shops.values()):
        after.update(item["orderId"] for item in read_api(f"/api/shops/{shop_id}/reviews") or [])
    return not [oid for oid in order_ids if oid in after and oid not in before]


def load_jsonl(name):
    """读数据集（utf-8-sig：兼容 PowerShell 写入带来的 BOM）"""
    path = os.path.join(BASE, "datasets", name)
    with open(path, encoding="utf-8-sig") as source:
        return [json.loads(line) for line in source if line.strip()]


def select_cases(mode, only):
    rec = load_jsonl("recommend.jsonl")
    rev = load_jsonl("review.jsonl")
    mer = load_jsonl("merchant.jsonl")
    if mode == "smoke":
        rec = [case for case in rec if case["id"] in {"rec-001", "rec-025", "rec-027"}]
        rev, mer = rev[:3], mer[:2]
    elif mode == "broken":
        rec = [case for case in rec if case.get("expect", {}).get("category")]
        rev, mer = [], []
    if only == "recommend":
        rev, mer = [], []
    elif only == "review":
        rec, mer = [], []
    elif only == "merchant":
        rec, rev = [], []
    return rec, rev, mer


def passed(result):
    return bool(result.checks) and all(result.checks.values())


def safe_case(case, runner, *args):
    try:
        return runner(case, *args)
    except Exception as error:
        result = CaseResult(case["id"])
        result.add("api_ok", False, f"评测异常：{type(error).__name__}")
        return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="现有真实数据的 Agent 评测；--check 免费预检，评测不造订单")
    ap.add_argument("--mode", choices=["full", "smoke", "broken"], default="full")
    ap.add_argument("--full", dest="mode", action="store_const", const="full", help="--mode full 的兼容别名")
    ap.add_argument("--only", choices=["recommend", "review", "merchant"],
                    help="只跑某技能（定向回归用）")
    ap.add_argument("--fixtures", default=os.getenv("SCOUTBITE_EVAL_FIXTURES"), help="version=1 的现有事实 JSON")
    ap.add_argument("--check", action="store_true", help="仅登录/只读预检；无 LLM 调用、无业务写入")
    ap.add_argument("--skip-judge", action="store_true", help="跳过额外 judge 付费调用")
    ap.add_argument("--report", type=Path, help="独立报告路径；已有文件一律不覆盖")
    ap.add_argument("--judge-only", type=Path, help="只评已有报告 JSON 中的答案/证据，不重跑推荐或业务预检")
    args = ap.parse_args(argv)

    display_mode = "judge" if args.judge_only else args.mode
    print(f"== 离线评测 mode={display_mode}{' only=' + args.only if args.only else ''} ==")
    print(f"LLM key 已配置：{llm.llm_available()}；internal token 已配置：{bool(agent_tools.INTERNAL_TOKEN)}")
    if args.judge_only:
        if args.check or args.skip_judge:
            print("准备失败：--judge-only 不可与 --check/--skip-judge 同时使用")
            return 2
        return judge_snapshot(args.judge_only, args.report)
    if not args.fixtures:
        print("准备失败：请提供 --fixtures；评测不会自动注册或创建订单")
        return 2
    if not args.check and not llm.llm_available():
        print("准备失败：未配置 LLM API key；未调用模型、未生成任何内容")
        return 2
    if args.report and (args.report.exists() or args.report.with_suffix(".json").exists()):
        print("准备失败：报告文件已存在；请选择新文件以保留历史证据")
        return 2
    try:
        rec_cases, rev_cases, mer_cases = select_cases(args.mode, args.only)
        if not (rec_cases or rev_cases or mer_cases):
            raise FixtureError("所选 mode/only 没有适用用例")
        runtime = setup(args.fixtures, rec_cases, rev_cases, mer_cases)
    except Exception as error:
        detail = str(error) if isinstance(error, FixtureError) else type(error).__name__
        print(f"准备失败：{detail}；未生成内容、未写入业务数据")
        return 2
    if args.check:
        print("CHECK PASS（免费事实预检；未验证模型可用性）")
        return 0
    llm.reset_usage()

    # 破坏性试验：搞坏检索（丢品类过滤+半径放大），只跑带品类约束的用例
    broken = args.mode == "broken"
    original_search = agent_tools.search_shops
    if broken:
        def _broken_search(lat, lng, radius=5000, category=None, limit=12):
            return original_search(lat, lng, radius=50000, category=None, limit=limit)
        agent_tools.search_shops = _broken_search

    rec_results, rev_results, mer_results = [], [], []
    judge_samples = []

    for i, case in enumerate(rec_cases):
        r = safe_case(case, run_recommend_case, runtime["user_tokens"])
        rec_results.append(r)
        mark = "PASS" if passed(r) else "FAIL"
        print(f"  [{i+1}/{len(rec_cases)}] {case['id']} {mark} {r.detail}")
        if (not broken and len(judge_samples) < 5 and r.checks.get("non_empty")
                and (case.get("expect", {}).get("category"))):
            judge_samples.append((case["message"], r))

    for i, case in enumerate(rev_cases):
        r = safe_case(case, run_review_case, runtime["review_order_ids"],
                      runtime["review_uid"], runtime["review_titles"])
        rev_results.append(r)
        mark = "PASS" if passed(r) else "FAIL"
        print(f"  [{i+1}/{len(rev_cases)}] {case['id']} {mark} {r.detail}")

    for i, case in enumerate(mer_cases):
        mapped_case = {**case, "shopId": runtime["merchant_shops"][case["shopId"]]}
        r = safe_case(mapped_case, run_merchant_case, runtime["merchant_uid"])
        mer_results.append(r)
        mark = "PASS" if passed(r) else "FAIL"
        print(f"  [{i+1}/{len(mer_cases)}] {case['id']} {mark} {r.detail}")

    # 自动发布检查（ADR 守门员）
    auto_ok = True
    if rev_cases:
        try:
            auto_ok = auto_publish_check(runtime["review_order_ids"], runtime["review_before"], runtime["review_shops"])
        except Exception as error:
            auto_ok = False
            print(f"  自动发布复核失败：{type(error).__name__}")
        print(f"  auto_publish_check: {'PASS（0 条新评价）' if auto_ok else 'FAIL!!!'}")

    # Judge 抽样（量规冻结；同族 judge 偏差如实记录）
    judge_out = []
    if judge_samples and not broken and not args.skip_judge:
        print(f"== judge 抽样 {len(judge_samples)} 条 ==")
        judge_out = run_judge_samples(judge_samples)

    usage = llm.get_usage()
    agent_tools.search_shops = original_search
    runtime["metadata"]["judgeSkipped"] = args.skip_judge
    try:
        write_report(args.mode, rec_results, rev_results, mer_results,
                     auto_ok, judge_out, usage, broken, report_path=args.report,
                     metadata=runtime["metadata"], judge_samples=judge_samples)
    except (OSError, ValueError) as error:
        print(f"报告保存失败：{type(error).__name__}；历史报告未覆盖")
        return 2
    success = all(passed(result) for result in rec_results + rev_results + mer_results)
    success = success and auto_ok and all(item.get("status") == "PASSED" for item in judge_out)
    return 0 if success else 1


def run_judge_samples(samples, uid_map=None):
    """Judge the recorded answer plus real evidence; never generate a different answer."""
    out = []
    for q, rr in samples:
        try:
            ans = rr.answer
            if not ans:
                raise ValueError("recorded answer missing")
            evidence = rr.evidence or [agent_tools.get_evidence(shop["id"]) for shop in ans.get("shops", [])]
            j = llm.chat_json(JUDGE_RUBRIC,
                              f"用户问题：{q}\n候选证据：{json.dumps(evidence, ensure_ascii=False)}"
                              f"\n本轮已评回答：{json.dumps(ans, ensure_ascii=False)}",
                              max_tokens=100)
            valid = all(isinstance(j.get(name), (int, float)) and not isinstance(j[name], bool)
                        and 1 <= j[name] <= 5 for name in ("usefulness", "comparison"))
            if not valid:
                raise ValueError("judge score outside 1-5")
            out.append({"q": q[:24], "usefulness": j.get("usefulness"),
                        "comparison": j.get("comparison"), "status": "PASSED"})
        except Exception as error:
            out.append({"q": q[:24], "usefulness": None, "comparison": None,
                        "status": "FAILED", "error": type(error).__name__})
        print(f"  judge: {q[:18]}… usefulness={out[-1]['usefulness']} comparison={out[-1]['comparison']}")
    return out


def judge_snapshot(snapshot_path, report_path=None):
    """Judge a saved sample exactly once; no account, data service or graph calls."""
    if not llm.llm_available():
        print("准备失败：未配置 LLM API key，无法评审既有答案")
        return 2
    if report_path and (report_path.exists() or report_path.with_suffix(".json").exists()):
        print("准备失败：报告文件已存在，请另存新文件")
        return 2
    try:
        with Path(snapshot_path).open(encoding="utf-8") as source:
            snapshot = json.load(source)
        recorded = snapshot.get("judgeSamples")
        if snapshot.get("version") != 1 or not isinstance(recorded, list) or not recorded:
            raise FixtureError("快照需要 version=1 与非空 judgeSamples")
        samples = []
        for item in recorded:
            if not isinstance(item.get("answer"), dict) or not isinstance(item.get("evidence"), list) or not item["evidence"]:
                raise FixtureError("快照样本缺少本轮原答案/证据，禁止再生成答案冒充")
            result = CaseResult(item["id"])
            result.answer = item["answer"]
            result.evidence = item["evidence"]
            samples.append((item["question"], result))
    except (OSError, ValueError, KeyError, AttributeError) as error:
        detail = str(error) if isinstance(error, FixtureError) else type(error).__name__
        print(f"准备失败：{detail}")
        return 2
    llm.reset_usage()
    judge = run_judge_samples(samples)
    try:
        write_report("judge", [], [], [], True, judge, llm.get_usage(), False,
                     report_path=report_path, metadata={"fixtureRunId": snapshot.get("metadata", {}).get("fixtureRunId"),
                                                       "judgeSource": Path(snapshot_path).name},
                     judge_samples=samples)
    except (OSError, ValueError) as error:
        print(f"报告保存失败：{type(error).__name__}")
        return 2
    return 0 if all(item["status"] == "PASSED" for item in judge) else 1


def write_report(mode, rec, rev, mer, auto_ok, judge, usage, broken, report_path=None, metadata=None, judge_samples=None):
    all_res = rec + rev + mer
    lines = []
    a = lines.append
    a(f"# 离线评测报告")
    a("")
    a(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    a(f"- 模式：**{mode}**{'（破坏性试验：检索工具已搞坏——丢品类过滤+半径50km）' if broken else ''}")
    a(f"- LLM：{llm.MODEL}（temperature=0.3；成本按项目 DeepSeek 单价粗估）")
    a(f"- 数据集版本：v1.0.1（recommend 30 / review 20 / merchant 15，含 6 负例；v1.0.1 校准记录见 ADR-031）")
    a("- 执行边界：进程内执行真实 Agent 图；取数通过真实 shop-api。未测试 Java 门面鉴权/trace，请另跑真实 E2E。")
    a("- 业务副作用：复用既有已核销未评订单；未注册、下单、支付、核销或发布评价。草稿仅在评测进程内暂存。")
    a("- 预算指标：至少一家最低套餐价 ≤ 预算 × 1.15；此结果不证明所有推荐满足硬预算。")
    if metadata:
        a(f"- Fixture run：{metadata.get('fixtureRunId') or '未命名'}；复用订单：{metadata.get('reviewOrderIds', [])}")
        a(f"- 商家映射：{json.dumps(metadata.get('merchantShopMapping', {}), ensure_ascii=False)}；"
          f"**{metadata.get('uniqueMerchantShops', 0)} 家独立真实门店**（重复映射不算独立店样本）")
        a(f"- Judge：{'主动跳过（未付费评审）' if metadata.get('judgeSkipped') else '使用本轮已生成答案与真实证据，不重跑推荐'}")
        if metadata.get("judgeSource"):
            a(f"- Judge 原快照：{metadata['judgeSource']}；本次不读取业务服务、不重跑图。")
    a("")

    # 总览
    a("## 1. 总览")
    a("")
    a("| 技能 | 用例 | 全过 | 通过率 | p50 | p95 | 平均工具调用 |")
    a("|---|---|---|---|---|---|---|")
    for name, rs in (("recommend", rec), ("review-draft", rev), ("merchant", mer)):
        if not rs:
            continue
        passed_count = sum(1 for r in rs if passed(r))
        lat = [r.latency_ms for r in rs]
        tc = statistics.mean([r.tool_calls for r in rs]) if rs else 0
        a(f"| {name} | {len(rs)} | {passed_count} | {100*passed_count/len(rs):.0f}% | "
          f"{p(lat, 0.5)} | {p(lat, 0.95)} | {tc:.1f} |")
    a("")

    # 程序化指标明细
    a("## 2. 程序化指标明细")
    a("")
    metric_names = []
    for r in all_res:
        for k in r.checks:
            if k not in metric_names:
                metric_names.append(k)
    a("| 指标 | 适用用例 | 通过 | 通过率 | 说明 |")
    a("|---|---|---|---|---|")
    notes = {
        "api_ok": "接口正常返回（非 50000/42201）",
        "llm_ok": "LLM 调用无故障，冷启动/画像降级不能冒充模型评测通过",
        "non_empty": "有候选时至少推 1 家",
        "shop_cap_3": "推荐数 ≤ 3（对比式约束）",
        "schema": "结构完整（id/名称/理由/缺点非空）",
        "constraint_category": "★品类约束：独立反查店详情",
        "constraint_budget": "★预算约束：≥1 家最低价 SKU ≤ 预算×1.15",
        "constraint_distance": "距离 ≤ 5.5km（检索半径+容差）",
        "citation_existence": "★引用存在率：evidenceId 反查评价表",
        "honest_empty": "跨城坐标诚实回答无店（负例）",
        "clarify": "冷启动+模糊先问一个问题（负例）",
        "scores_complete": "三维分齐全且 1~5",
        "prefer_taste": "预设分 taste 原样保留",
        "prefer_wait": "预设分 wait 原样保留",
        "prefer_env": "预设分 env 原样保留",
        "used_facts": "草稿引用了事实清单",
        "content_anchor": "正文锚定该真实订单的套餐名",
        "no_fabrication": "★编造抓拍：诱饵词未无声明断言（负例，v1.0.1 校准）",
        "numbers_in_source": "★观察数字与工具值精确等价（独立 Decimal 复核，非子串）",
        "hypotheses_hedged": "假设含『可能』类限定",
        "no_certain_assert": "无确定性因果断言",
        "suggestions_cap": "建议 1~2 条",
        "three_layers": "观察/假设/建议三层齐全",
        "recheck_source": "复核取数通道正常",
    }
    for mn in metric_names:
        vals = [r.checks.get(mn) for r in all_res if mn in r.checks]
        if not vals:
            continue
        a(f"| {mn} | {len(vals)} | {sum(vals)} | {pct(vals)} | {notes.get(mn, '')} |")
    if rev:
        a(f"| auto_publish_check | 1 | {1 if auto_ok else 0} | "
          f"{'100%' if auto_ok else '0%'} | ★跑完 {len(rev)} 条草稿 0 新评价（ADR-028） |")
    a("")

    # Judge
    if judge:
        a("## 3. Judge 抽样（量规冻结，同族偏差如实记录）")
        a("")
        a("| 用例 | usefulness | comparison | 状态 |")
        a("|---|---|---|---|")
        for j in judge:
            a(f"| {j['q']} | {j['usefulness']} | {j['comparison']} | {j.get('status')} {j.get('error', '')} |")
        us = [j["usefulness"] for j in judge if isinstance(j.get("usefulness"), (int, float))]
        cs = [j["comparison"] for j in judge if isinstance(j.get("comparison"), (int, float))]
        if us and cs:
            a("")
            a(f"均值：usefulness {statistics.mean(us):.1f} / comparison {statistics.mean(cs):.1f}"
              f"（n={len(us)}；judge 与生成使用同一配置模型，存在同族偏好）")
        a("")

    # 系统
    a("## 4. 系统指标")
    a("")
    a(f"- LLM 调用：{usage['calls']} 次；token：输入 {usage['prompt_tokens']} + "
      f"输出 {usage['completion_tokens']}；成本约 ¥{usage['cost_yuan']}")
    if broken:
        a("- ⚠ 破坏性试验模式：constraint_category 应显著低于正常跑——这就是区分度")
    a("")

    # 失败清单
    fails = [r for r in all_res if not passed(r)]
    a("## 5. 失败用例清单（诚实记录）")
    a("")
    if not fails:
        a("（无——但请勿只看这一行：破坏性试验才是评测的评测）")
    for r in fails:
        bad = [k for k, v in r.checks.items() if not v]
        a(f"- **{r.id}**：{', '.join(bad)} —— {r.detail}")
    if not auto_ok:
        a("- **auto_publish_check**：复核失败或发现未授权自动发布，不能算通过。")
    for item in judge:
        if item.get("status") == "FAILED":
            a(f"- **judge**：{item['q']} —— {item.get('error', '未知失败')}")
    a("")
    a("> 知道测不到什么：本评测测不到长期留存与线上分布漂移——那是人工抽检（第④层）与线上实验的事。")

    if report_path is None:
        out_name = f"{mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.md"
        path = Path(BASE) / "reports" / out_name
    else:
        path = Path(report_path)
    snapshot_path = path.with_suffix(".json")
    if path == snapshot_path:
        raise ValueError("Markdown report must use a distinct filename from its JSON snapshot")
    if path.exists() or snapshot_path.exists():
        raise FileExistsError("Existing evidence must not be overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        f.write("\n".join(lines))
    snapshot = {
        "version": 1, "mode": mode, "model": llm.MODEL, "metadata": metadata or {}, "usage": usage,
        "autoPublishCheck": auto_ok,
        "cases": [{"id": result.id, "checks": result.checks, "detail": result.detail,
                   "latencyMs": result.latency_ms, "toolCalls": result.tool_calls,
                   "answer": result.answer, "evidence": result.evidence,
                   "modelOutputs": result.model_outputs} for result in all_res],
        "judge": judge,
        "judgeSamples": [{"id": result.id, "question": question, "answer": result.answer,
                          "evidence": result.evidence} for question, result in judge_samples or []],
    }
    with snapshot_path.open("x", encoding="utf-8") as output:
        json.dump(snapshot, output, ensure_ascii=False, indent=2)
    print(f"\n===== 报告已生成：{path} =====")
    total_pass = sum(1 for r in all_res if passed(r))
    print(f"===== {len(all_res)} 用例：{total_pass} 全过 / {len(all_res)-total_pass} 有失败项 =====")
    if judge:
        judge_pass = sum(item.get("status") == "PASSED" for item in judge)
        print(f"===== Judge：{judge_pass} 通过 / {len(judge) - judge_pass} 失败 =====")
    return path


if __name__ == "__main__":
    sys.exit(main())
