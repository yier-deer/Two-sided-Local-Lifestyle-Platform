#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
run_eval.py —— 离线评测：一条命令跑完全部黄金集，生成 evals/reports/latest.md。

用法（项目根目录）：
  python evals/run_eval.py --mode full    # 65 条全量（约 5 分钟，约 ¥0.5 token）
  python evals/run_eval.py --mode smoke   # 6 条快速自检
  python evals/run_eval.py --mode broken  # 破坏性试验：搞坏检索工具后重跑品类用例（区分度证明）

设计要点：
  - 进程内跑图（import graph 直调 run_*）：走 HTTP 就没法 monkeypatch tools 做破坏性试验
  - 程序化指标全部免费可回归；judge 抽样 5 条（量规冻结在本文件 JUDGE_RUBRIC）
  - 「是否自动发布」独立指标：跑完评价用例后查库，测试订单 0 新评价（ADR-028 守门员）
"""
import argparse
import base64
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime

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
import tools as agent_tools     # noqa: E402  (命名避开 eval 内的 tools 概念)
from graph import run_recommend                  # noqa: E402
from review_graph import run_review_draft        # noqa: E402
from merchant_graph import run_merchant_analyze  # noqa: E402

SHOP = os.getenv("SCOUTBITE_SHOP_API_URL", "http://localhost:8081")
GUARD = 42201
HZ_LAT, HZ_LNG = 30.24, 120.15
SHOP41_SKUS = [81, 82]          # 店41（测试店）的套餐

http = httpx.Client(timeout=60.0)
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


def login(phone, pwd=None):
    """登录（双密码兜底：test 用户 test123456，预设用户 user123456）"""
    for pw in ([pwd] if pwd else ["test123456", "user123456"]):
        r = http.post(f"{SHOP}/api/auth/login",
                      json={"phone": phone, "password": pw}).json()
        if r["code"] == 0:
            return r["data"]["token"]
    raise AssertionError(f"登录失败 {phone}: {r['message']}")


def user_id_from_token(token: str) -> int:
    """解自家 JWT 的 payload（userId 在 sub claim——与 JwtUtil.issue 一致）"""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    data = json.loads(base64.urlsafe_b64decode(payload))
    uid = int(data.get("sub") or data.get("userId") or 0)
    assert uid > 0, f"JWT 解析失败: {list(data.keys())}"
    return uid


def register_or_login(phone, pwd="test123456", nickname="eval-cold"):
    """评测冷启动用户：不存在则注册，存在则登录"""
    r = http.post(f"{SHOP}/api/auth/register",
                  json={"phone": phone, "password": pwd, "role": "USER",
                        "nickname": nickname}).json()
    if r["code"] == 0 and r.get("data", {}).get("token"):
        return r["data"]["token"]
    return login(phone, pwd)


def get_shop(shop_id):
    if shop_id not in _shop_cache:
        r = http.get(f"{SHOP}/api/shops/{shop_id}").json()
        _shop_cache[shop_id] = r.get("data") or {}
    return _shop_cache[shop_id]


def get_reviews(shop_id):
    if shop_id not in _review_cache:
        r = http.get(f"{SHOP}/api/shops/{shop_id}/reviews").json()
        _review_cache[shop_id] = {x["id"] for x in (r.get("data") or [])}
    return _review_cache[shop_id]


def get_skus(shop_id):
    if shop_id not in _sku_cache:
        r = http.get(f"{SHOP}/api/shops/{shop_id}/skus").json()
        _sku_cache[shop_id] = r.get("data") or []
    return _sku_cache[shop_id]


class CaseResult:
    """单条用例结果：id / 各项检查（True/False/None=不适用）"""
    def __init__(self, cid):
        self.id = cid
        self.checks: dict[str, bool] = {}
        self.latency_ms: int = 0
        self.tool_calls = 0
        self.detail = ""        # 失败原因摘要

    def add(self, name, ok, detail=""):
        self.checks[name] = bool(ok)
        if not ok and detail:
            self.detail = detail


# ==================== 推荐用例 ====================

def run_recommend_case(case, uid_map) -> CaseResult:
    r = CaseResult(case["id"])
    token = uid_map[case["user"]]
    uid = user_id_from_token(token)
    lat = case.get("lat", HZ_LAT)
    lng = case.get("lng", HZ_LNG)

    t0 = time.time()
    out = run_recommend(uid, case["message"], lat, lng, "eval")
    r.latency_ms = int((time.time() - t0) * 1000)

    exp = case.get("expect", {})
    data = out.get("data") if out.get("code") == 0 else None

    if out.get("code") != 0:
        # 诚实降级/护栏错误：直接全挂并记录
        r.add("api_ok", False, f"code={out['code']} {out.get('message','')[:60]}")
        return r
    r.add("api_ok", True)

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
    oid = order_ids[hash(case["id"]) % len(order_ids)]
    t0 = time.time()
    out = run_review_draft(uid, oid, case.get("note") or None, case.get("prefer") or {})
    r.latency_ms = int((time.time() - t0) * 1000)

    if out.get("code") != 0:
        r.add("api_ok", False, f"code={out['code']} {out.get('message','')[:60]}")
        return r
    r.add("api_ok", True)
    d = out["data"]
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
    anchor = any(t and t[:2] in content for t in sku_titles)
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
    out = run_merchant_analyze(uid, case["shopId"], case["skill"])
    r.latency_ms = int((time.time() - t0) * 1000)

    if out.get("code") != 0:
        r.add("api_ok", False, f"code={out['code']} {out.get('message','')[:60]}")
        return r
    r.add("api_ok", True)
    d = out["data"]
    r.tool_calls = len(d.get("toolCalls") or [])
    obs, hyp, sug = d.get("observations") or [], d.get("hypotheses") or [], d.get("suggestions") or []

    # 独立取数复核：观察句的数字必须真的在工具结果里
    try:
        if case["skill"] == "ops":
            data_text = json.dumps(agent_tools.get_metrics(case["shopId"]), ensure_ascii=False)
        elif case["skill"] == "reviews":
            data_text = json.dumps(agent_tools.get_review_clusters(case["shopId"]), ensure_ascii=False)
        else:
            data_text = json.dumps(agent_tools.get_competitors(case["shopId"]), ensure_ascii=False)
    except Exception as e:
        data_text = ""
        r.add("recheck_source", False, f"复核取数失败: {type(e).__name__}")
    if data_text:
        bad_nums = []
        for s in obs:
            for num in re.findall(r"\d+(?:\.\d+)?", str(s)):
                if num not in data_text:
                    bad_nums.append(num)
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


def run_judge(samples):
    """抽样评审：返回每维均分与明细"""
    results = []
    for q, ans in samples:
        try:
            out = llm.chat_json(JUDGE_RUBRIC,
                                f"用户问题：{q}\n回答：{json.dumps(ans, ensure_ascii=False)[:1500]}",
                                max_tokens=100)
            results.append({"q": q[:30], "usefulness": out.get("usefulness"),
                            "comparison": out.get("comparison")})
        except Exception:
            results.append({"q": q[:30], "usefulness": None, "comparison": None})
    return results


# ==================== 主流程 ====================

def pct(values):
    vals = [v for v in values if v is not None]
    return f"{100 * sum(vals) / len(vals):.0f}%" if vals else "—"


def p(values, q):
    if not values:
        return "—"
    s = sorted(values)
    return f"{s[min(len(s) - 1, int(len(s) * q))]}ms"


def setup():
    """准备：登录/注册用户 + 造 3 个 REDEEMED 订单（评价用例的事实锚）"""
    print("== setup ==")
    uid_map = {
        "13700000001": login("13700000001"),                     # test 用户（订单史丰富）
        "13700000002": login("13700000002"),
        "13611110003": login("13611110003"),                     # 预设·咖啡因选手
        "13900000888": register_or_login("13900000888"),         # 评测冷启动用户
    }
    token = uid_map["13700000001"]
    uid = user_id_from_token(token)
    auth = {"Authorization": f"Bearer {token}"}

    order_ids, sku_titles = [], []
    ts = int(time.time())
    for i, sku in enumerate(SHOP41_SKUS + SHOP41_SKUS[:1]):   # 81, 82, 81
        r = http.post(f"{SHOP}/api/orders", json={"skuId": sku},
                      headers={**auth, "Idempotency-Key": f"eval-{ts}-{i}"}).json()
        assert r["code"] == 0, f"下单失败: {r['message']}"
        oid = r["data"]["id"]
        http.post(f"{SHOP}/api/orders/{oid}/pay", json={}, headers=auth)
        pr = http.post(f"{SHOP}/api/orders/{oid}/redeem", json={}, headers=auth).json()
        assert pr["code"] == 0, f"核销失败: {pr['message']}"
        order_ids.append(oid)
        # 套餐名从公开 skus 接口取（订单 DTO 不带 title）
        sku_titles.append(str(next((s["title"] for s in get_skus(41) if s["id"] == sku), "")))
    # 评价用例自动发布检查的基线：这些订单当前都不该有评价
    before = {x["orderId"] for x in http.get(f"{SHOP}/api/shops/41/reviews").json()["data"]}
    return uid_map, uid, order_ids, sku_titles, before


def auto_publish_check(order_ids, before) -> bool:
    """跑完 20 条草稿用例后：测试订单一条新评价都不许出现（ADR-028 守门员）"""
    after = {x["orderId"] for x in http.get(f"{SHOP}/api/shops/41/reviews").json()["data"]}
    leaked = [o for o in order_ids if o in after and o not in before]
    return not leaked


def load_jsonl(name):
    """读数据集（utf-8-sig：兼容 PowerShell 写入带来的 BOM）"""
    path = os.path.join(BASE, "datasets", name)
    return [json.loads(l) for l in open(path, encoding="utf-8-sig") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "smoke", "broken"], default="full")
    ap.add_argument("--only", choices=["recommend", "review", "merchant"],
                    help="只跑某技能（定向回归用）")
    args = ap.parse_args()

    print(f"== 离线评测 mode={args.mode}{' only=' + args.only if args.only else ''} ==")
    llm.reset_usage()
    uid_map, uid, order_ids, sku_titles, review_before = setup()

    rec_cases = load_jsonl("recommend.jsonl")
    rev_cases = load_jsonl("review.jsonl")
    mer_cases = load_jsonl("merchant.jsonl")

    if args.only == "recommend":
        rev_cases, mer_cases = [], []
    elif args.only == "review":
        rec_cases, mer_cases = [], []
    elif args.only == "merchant":
        rec_cases, rev_cases = [], []

    # 破坏性试验：搞坏检索（丢品类过滤+半径放大），只跑带品类约束的用例
    broken = args.mode == "broken"
    if broken:
        _orig = agent_tools.search_shops
        def _broken_search(lat, lng, radius=5000, category=None, limit=12):
            return _orig(lat, lng, radius=50000, category=None, limit=limit)
        agent_tools.search_shops = _broken_search
        rec_cases = [c for c in rec_cases if c.get("expect", {}).get("category")]
        rev_cases, mer_cases = [], []

    if args.mode == "smoke":
        rec_cases = [rec_cases[i] for i in (0, 24, 26)]      # 正常/跨城/澄清
        rev_cases = rev_cases[:3]
        mer_cases = mer_cases[:2]

    rec_results, rev_results, mer_results = [], [], []
    judge_samples = []

    for i, case in enumerate(rec_cases):
        r = run_recommend_case(case, uid_map)
        rec_results.append(r)
        mark = "PASS" if all(r.checks.values()) else "FAIL"
        print(f"  [{i+1}/{len(rec_cases)}] {case['id']} {mark} {r.detail}")
        if (not broken and len(judge_samples) < 5 and r.checks.get("non_empty")
                and (case.get("expect", {}).get("category"))):
            judge_samples.append((case["message"], None))    # 占位，稍后补 data
            judge_samples[-1] = (case["message"], r)

    for i, case in enumerate(rev_cases):
        r = run_review_case(case, order_ids, uid, sku_titles)
        rev_results.append(r)
        mark = "PASS" if all(r.checks.values()) else "FAIL"
        print(f"  [{i+1}/{len(rev_cases)}] {case['id']} {mark} {r.detail}")

    for i, case in enumerate(mer_cases):
        r = run_merchant_case(case, uid)
        mer_results.append(r)
        mark = "PASS" if all(r.checks.values()) else "FAIL"
        print(f"  [{i+1}/{len(mer_cases)}] {case['id']} {mark} {r.detail}")

    # 自动发布检查（ADR 守门员）
    auto_ok = True
    if rev_cases:
        auto_ok = auto_publish_check(order_ids, review_before)
        print(f"  auto_publish_check: {'PASS（0 条新评价）' if auto_ok else 'FAIL!!!'}")

    # Judge 抽样（量规冻结；同族 judge 偏差如实记录）
    judge_out = []
    if judge_samples and not broken:
        print(f"== judge 抽样 {len(judge_samples)} 条 ==")
        samples = [(q, rr) for q, rr in judge_samples]
        # rr 是 CaseResult——judge 需要答案本体：重放一遍？不，保存答案太重。
        # 简化：judge 直接评"回答文本"——从 trace 不可得，这里改为重新轻跑
        judge_out = run_judge_samples(samples, uid_map)

    usage = llm.get_usage()
    write_report(args.mode, rec_results, rev_results, mer_results,
                 auto_ok, judge_out, usage, broken)


def run_judge_samples(samples, uid_map):
    """对抽样用例重放一次拿答案本体，再送 judge（评测期间答案可复现：同一图同一输入）"""
    out = []
    for q, rr in samples:
        case = next((c for c in load_jsonl("recommend.jsonl") if c["message"] == q), None)
        if not case:
            continue
        uid = user_id_from_token(uid_map[case["user"]])
        res = run_recommend(uid, case["message"], case.get("lat", HZ_LAT),
                            case.get("lng", HZ_LNG), "judge")
        ans = res.get("data") or {}
        try:
            j = llm.chat_json(JUDGE_RUBRIC,
                              f"用户问题：{q}\n回答：{json.dumps(ans, ensure_ascii=False)[:1500]}",
                              max_tokens=100)
            out.append({"q": q[:24], "usefulness": j.get("usefulness"),
                        "comparison": j.get("comparison")})
        except Exception:
            out.append({"q": q[:24], "usefulness": None, "comparison": None})
        print(f"  judge: {q[:18]}… usefulness={out[-1]['usefulness']} comparison={out[-1]['comparison']}")
    return out


def write_report(mode, rec, rev, mer, auto_ok, judge, usage, broken):
    all_res = rec + rev + mer
    lines = []
    a = lines.append
    a(f"# 离线评测报告")
    a("")
    a(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    a(f"- 模式：**{mode}**{'（破坏性试验：检索工具已搞坏——丢品类过滤+半径50km）' if broken else ''}")
    a(f"- LLM：{os.getenv('SCOUTBITE_LLM_MODEL', 'deepseek-chat')}（DeepSeek，temperature=0.3）")
    a(f"- 数据集版本：v1.0.1（recommend 30 / review 20 / merchant 15，含 6 负例；v1.0.1 校准记录见 ADR-031）")
    a("")

    # 总览
    a("## 1. 总览")
    a("")
    a("| 技能 | 用例 | 全过 | 通过率 | p50 | p95 | 平均工具调用 |")
    a("|---|---|---|---|---|---|---|")
    for name, rs in (("recommend", rec), ("review-draft", rev), ("merchant", mer)):
        if not rs:
            continue
        passed = sum(1 for r in rs if all(r.checks.values()))
        lat = [r.latency_ms for r in rs]
        tc = statistics.mean([r.tool_calls for r in rs]) if rs else 0
        a(f"| {name} | {len(rs)} | {passed} | {100*passed/len(rs):.0f}% | "
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
        "content_anchor": "正文锚定真实套餐名",
        "no_fabrication": "★编造抓拍：诱饵词未无声明断言（负例，v1.0.1 校准）",
        "numbers_in_source": "★观察数字存在于工具结果（独立复核）",
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
          f"{'100%' if auto_ok else '0%'} | ★跑完 20 条草稿 0 新评价（ADR-028） |")
    a("")

    # Judge
    if judge:
        a("## 3. Judge 抽样（量规冻结，同族偏差如实记录）")
        a("")
        a("| 用例 | usefulness | comparison |")
        a("|---|---|---|")
        for j in judge:
            a(f"| {j['q']} | {j['usefulness']} | {j['comparison']} |")
        us = [j["usefulness"] for j in judge if isinstance(j.get("usefulness"), (int, float))]
        cs = [j["comparison"] for j in judge if isinstance(j.get("comparison"), (int, float))]
        if us:
            a("")
            a(f"均值：usefulness {statistics.mean(us):.1f} / comparison {statistics.mean(cs):.1f}"
              f"（n={len(us)}；judge=DeepSeek 评 DeepSeek，存在同族偏好——第④层人工抽检对齐）")
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
    fails = [r for r in all_res if not all(r.checks.values())]
    a("## 5. 失败用例清单（诚实记录）")
    a("")
    if not fails:
        a("（无——但请勿只看这一行：破坏性试验才是评测的评测）")
    for r in fails:
        bad = [k for k, v in r.checks.items() if not v]
        a(f"- **{r.id}**：{', '.join(bad)} —— {r.detail}")
    a("")
    a("> 知道测不到什么：本评测测不到长期留存与线上分布漂移——那是人工抽检（第④层）与线上实验的事。")

    os.makedirs(os.path.join(BASE, "reports"), exist_ok=True)
    out_name = "broken-search.md" if broken else "latest.md"
    path = os.path.join(BASE, "reports", out_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n===== 报告已生成：{path} =====")
    total_pass = sum(1 for r in all_res if all(r.checks.values()))
    print(f"===== {len(all_res)} 用例：{total_pass} 全过 / {len(all_res)-total_pass} 有失败项 =====")


if __name__ == "__main__":
    main()
