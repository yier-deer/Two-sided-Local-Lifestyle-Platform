# _verify.py —— 全链路验证脚本（UTF-8 安全，Python 侧跑）
# 覆盖：错误路径 40903 / 越权 40300 / 商家三技能 / 归属校验 / 护栏直测
# 用法：.\.venv\Scripts\python.exe _verify.py
import json
import sys

import httpx

H = "http://localhost:8081"
c = httpx.Client(timeout=60.0)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not cond else ""))


def post(path, body, token=None, headers=None):
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = c.post(H + path, json=body, headers=h)
    return r.json()


def login(phone, pwd="test123456"):
    return post("/api/auth/login", {"phone": phone, "password": pwd})["data"]["token"]


print("== 0. 服务健康 ==")
try:
    check("shop-api UP", c.get(H + "/actuator/health").json()["status"] == "UP")
    check("agent-api UP", c.get("http://localhost:8000/health").json()["status"] == "UP")
except Exception as e:
    print("服务未就绪：", e)
    sys.exit(1)

ta = login("13700000001")
tb = login("13700000002")
tm = login("13811112222", "shop123456")   # 商家（店41主人）

print("== A. 未核销单起草（PAID 订单，应 40903）==")
orders = c.get(H + "/api/orders", headers={"Authorization": f"Bearer {ta}"}).json()["data"]
paid_unredeemed = next((o for o in orders if o["status"] == "PAID"), None)
if not paid_unredeemed:
    # 幂等造一个 PAID 未核销单（时间戳键，可重复跑）
    key = f"d7-verify-paid-{int(__import__('time').time())}"
    o = post("/api/orders", {"skuId": 81}, token=ta, headers={"Idempotency-Key": key})
    post(f"/api/orders/{o['data']['id']}/pay", {}, token=ta)
    paid_unredeemed = o["data"]
r = post("/api/agent/user/review-draft", {"orderId": paid_unredeemed["id"], "userNote": "测试"},
         token=ta)
check("PAID 单起草被拒 40903", r["code"] == 40903, f"code={r['code']} {r.get('message')}")

print("== B. A 核销新单并起草（准备越权测试）==")
key = f"d7-verify-owner-{int(__import__('time').time())}"
o = post("/api/orders", {"skuId": 81}, token=ta, headers={"Idempotency-Key": key})
oid = o["data"]["id"]
post(f"/api/orders/{oid}/pay", {}, token=ta)
post(f"/api/orders/{oid}/redeem", {}, token=ta)
r = post("/api/agent/user/review-draft", {"orderId": oid, "userNote": "微辣锅底很香，周末人多"},
         token=ta)
check("A 起草成功", r["code"] == 0 and r.get("data"), f"code={r['code']} {r.get('message')}")
did = r["data"]["draftId"] if r["code"] == 0 and r.get("data") else None
if did:
    check("预设分被尊重", r["code"] == 0)
    print("    scores:", json.dumps(r["data"]["scores"], ensure_ascii=False))
    print("    content:", r["data"]["content"])
    print("    usedFacts:", " | ".join(r["data"]["usedFacts"]))

if did:
    print("== C. B 抢发 A 的草稿（应 40300）==")
    r = post(f"/api/agent/user/review-draft/{did}/publish", {}, token=tb)
    check("他人草稿被拒 40300", r["code"] == 40300, f"code={r['code']} {r.get('message')}")

    print("== D. A 自己发布（应成功且店页可见）==")
    r = post(f"/api/agent/user/review-draft/{did}/publish", {}, token=ta)
    check("A 发布成功", r["code"] == 0, f"code={r['code']} {r.get('message')}")
    reviews = c.get(H + "/api/shops/41/reviews").json()["data"]
    check("店页出现该评价", any(x["orderId"] == oid for x in reviews))
    r2 = post(f"/api/agent/user/review-draft/{did}/publish", {}, token=ta)
    check("重复发布 40001（已消费）", r2["code"] == 40001, f"code={r2['code']}")

print("== E. 商家三技能（店41，主人 13811112222）==")
for skill in ("ops", "reviews", "competitors"):
    r = post("/api/agent/merchant/analyze", {"shopId": 41, "skill": skill}, token=tm)
    ok = r["code"] == 0
    check(f"analyze {skill}", ok, f"code={r['code']} {r.get('message')}")
    if ok:
        d = r["data"]
        print(f"    观察: {d['observations']}")
        print(f"    假设: {d['hypotheses']}")
        print(f"    建议: {d['suggestions']}")

print("== F. 越权（应 40300）==")
r = post("/api/agent/merchant/analyze", {"shopId": 41, "skill": "ops"}, token=ta)
check("用户角色调 analyze 拒 40300", r["code"] == 40300, f"code={r['code']}")
r = post("/api/agent/merchant/analyze", {"shopId": 1, "skill": "ops"}, token=tm)
check("商家分析他人店铺拒 40300", r["code"] == 40300, f"code={r['code']}")

print("== G. 商家护栏直测（构造违规输出）==")
from merchant_graph import gate
good = {"data_text": '{"newCustomers7d": 3, "couponShare": 50.0}',
        "observations": ["近7日新客3人"], "hypotheses": ["可能因券活动，或周末客流"],
        "suggestions": ["继续投放满减券"]}
check("合法输出放行", gate(good) == {})
bad_num = dict(good, observations=["近7日新客99人"])
check("编造数字拦截 42201", gate(bad_num).get("error_code") == 42201)
no_hedge = dict(good, hypotheses=["因为投了券所以新客涨"])
check("无限定词因果断言拦截 42201", gate(no_hedge).get("error_code") == 42201)
hedged_causal = dict(good, hypotheses=["可能因为券活动，导致新客上升，也可能是周末客流"])
check("带『可能』限定的因果表述放行", gate(hedged_causal) == {})
certain = dict(good, hypotheses=["券活动证明了新客增长"])
check("确定性断言拦截 42201", gate(certain).get("error_code") == 42201)
bad_many = dict(good, suggestions=["建议1", "建议2", "建议3"])
check("建议超量拦截 42201", gate(bad_many).get("error_code") == 42201)

print()
print(f"===== 结果：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
if FAIL:
    print("失败项：", FAIL)
    sys.exit(1)
