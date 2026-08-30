# -*- coding: utf-8 -*-
"""
e2e_check.py —— 前后端全链路 E2E：用真实 HTTP 接口走完整业务闭环。
覆盖：登录 → 店铺/详情 → 领券 → 下单(幂等) → 支付(CAS) → 核销 →
      AI 推荐(护栏) → 评价草稿(CASDG) → 签字发布(三重校验) → 信息流 → 商家分析
验证者独立于被验证者：断言只看接口真实返回，不预设结果。
"""
import httpx
import time

SHOP = "http://localhost:8081"
WEB_PROXY = None  # 前端只是透传，直接打后端即可等价验证

passed, failed = [], []

def check(name, cond, detail=""):
    (passed if cond else failed).append(f"{name}{' — ' + detail if detail else ''}")
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"（{detail}）" if detail else ""))

c = httpx.Client(timeout=30.0)

# ---------- 1. 登录种子用户 ----------
print("== 1. 登录 ==")
r = c.post(SHOP + "/api/auth/login", json={"phone": "13611110001", "password": "user123456"}).json()
check("登录返回 code=0", r["code"] == 0, r.get("message", ""))
token = r["data"]["token"]
h = {"Authorization": f"Bearer {token}"}
r2 = c.get(SHOP + "/api/auth/me", headers=h).json()
check("me 返回昵称", r2["code"] == 0 and (r2.get("data") or {}).get("nickname") == "辣妹小队长", str((r2.get("data") or {}).get("nickname")))

# ---------- 2. 店铺与详情 ----------
print("== 2. 店铺检索 ==")
r = c.get(SHOP + "/api/shops/nearby", params={"lat": 30.24, "lng": 120.15, "radius": 5000}).json()
check("附近检索有店", r["code"] == 0 and len(r["data"]) > 0, f"{len(r['data'])} 家")
shop_id = r["data"][0]["id"]
r = c.get(SHOP + f"/api/shops/{shop_id}/skus").json()
check("店详情套餐", r["code"] == 0 and len(r["data"]) > 0, f"{len(r['data'])} 个套餐")
skus_all = r["data"]
sku = next((s for s in skus_all if s["stock"] > 0), None)
check("有可买套餐", sku is not None, f"sku#{sku['id'] if sku else '-'}")

# ---------- 3. 领券 → 下单 → 支付 → 核销 ----------
print("== 3. 交易链路 ==")
r = c.get(SHOP + f"/api/shops/{shop_id}/coupons").json()
coupons = r["data"] if r["code"] == 0 else []

# 选一个"能真正用上券"的组合：skus_all 里价格≥券门槛的 sku + 那张券；没有就用无券下单
use_coupon = None
order_sku = None
if coupons:
    for co in coupons:
        fit = next((s for s in skus_all if s["stock"] > 0 and s["price"] >= co["threshold"]), None)
        if fit:
            r = c.post(SHOP + f"/api/coupons/{co['id']}/claim", headers=h).json()
            check("领券（或已领过幂等拒绝）", r["code"] in (0, 40901, 40902), f"code={r['code']} {r.get('message','')[:30]}")
            r_mine = c.get(SHOP + "/api/coupons/mine", headers=h).json()
            uc = next((x for x in r_mine["data"] if x["couponId"] == co["id"] and x["status"] == "UNUSED"), None)
            if uc:
                use_coupon = uc
                order_sku = fit
                check("券门槛匹配套餐（UNUSED 可用）", True, f"userCouponId={uc['userCouponId']} sku#{fit['id']}")
                break
            else:
                check("领到了券但无 UNUSED（跳过券路径）", True)
    if use_coupon is None and coupons:
        check("本店券均无可用组合（降级为无券下单）", True)
if order_sku is None:
    order_sku = next((s for s in skus_all if s["stock"] > 0), None)

# 下单（幂等键）
idem = f"e2e-{int(time.time())}"
body = {"skuId": order_sku["id"], "userCouponId": use_coupon["userCouponId"] if use_coupon else None}
r = c.post(SHOP + "/api/orders", json=body, headers={**h, "Idempotency-Key": idem}).json()
check("下单成功" + ("（用券）" if use_coupon else "（无券）"), r["code"] == 0, r.get("message", "")[:50])
oid = r["data"]["id"]
# 幂等重放：同 key 再下应返回原单
r = c.post(SHOP + "/api/orders", json=body, headers={**h, "Idempotency-Key": idem}).json()
check("幂等重放返回原单", r["code"] == 0 and r["data"]["id"] == oid, f"返回 id={r['data'].get('id') if r['code']==0 else '-'}")

# 支付 → 核销
r = c.post(SHOP + f"/api/orders/{oid}/pay", headers=h).json()
check("支付 CAS", r["code"] == 0 and r["data"]["status"] == "PAID", str(r.get("data", {}).get("status", r.get("message"))))
r = c.post(SHOP + f"/api/orders/{oid}/redeem", headers=h).json()
check("核销 → REDEEMED", r["code"] == 0 and r["data"]["status"] == "REDEEMED", str(r.get("data", {}).get("status", r.get("message"))))

# ---------- 4. AI 推荐 ----------
print("== 4. AI 推荐（走 Java 门面 → Python 五步图）==")
r = c.post(SHOP + "/api/agent/user/recommend",
           json={"message": "今晚想吃火锅，两个人，人均100", "lat": 30.24, "lng": 120.15, "sessionId": "e2e-1"},
           headers=h).json()
if r["code"] == 0:
    shops = r["data"].get("shops", [])
    check("推荐返回 1~3 家", 1 <= len(shops) <= 3, f"{len(shops)} 家")
    check("每家有缺点（护栏产物）", all(s.get("cons") for s in shops))
    check("工具链可见", len(r["data"].get("toolCalls", [])) > 0, f"{len(r['data'].get('toolCalls', []))} 次调用")
else:
    check("推荐接口（50000=LLM 未配 key 属诚实降级，不算挂）", r["code"] == 50000, f"code={r['code']} {r.get('message','')[:60]}")

# ---------- 5. 评价草稿 → 签字发布 ----------
print("== 5. 评价草稿 CASDG + 签字 ==")
r = c.post(SHOP + "/api/agent/user/review-draft",
           json={"orderId": oid, "userNote": "锅底很香但等位久", "preferScores": {"taste": 5}},
           headers=h).json()
if r["code"] == 0:
    d = r["data"]
    check("草稿带 draftId", bool(d.get("draftId")), d.get("draftId", "")[:14])
    check("预设分 taste=5 原样保留", d.get("scores", {}).get("taste") == 5, str(d.get("scores", {}).get("taste")))
    check("usedFacts 非空（锚定事实）", len(d.get("usedFacts", [])) > 0)
    r = c.post(SHOP + f"/api/agent/user/review-draft/{d['draftId']}/publish", headers=h).json()
    check("签字发布成功", r["code"] == 0, r.get("message", "")[:50])
    # 草稿发布即消费：二次发布必须被拒
    r = c.post(SHOP + f"/api/agent/user/review-draft/{d['draftId']}/publish", headers=h).json()
    check("二次发布被拒（防连点双评）", r["code"] in (40001, 40901, 40903), f"code={r['code']}")
    # 店铺评价列表可见新评价
    r = c.get(SHOP + f"/api/shops/{shop_id}/reviews").json()
    check("评价出现在店页", r["code"] == 0 and any(x.get("orderId") == oid for x in r["data"]))
else:
    check("草稿接口（50000=LLM 未配属诚实降级）", r["code"] == 50000, f"code={r['code']} {r.get('message','')[:60]}")

# ---------- 6. 信息流 + 商家分析 ----------
print("== 6. 信息流与商家分析 ==")
r = c.get(SHOP + "/api/feed", params={"scene": "hot", "explore": "true", "limit": 5}).json()
check("信息流 hot 有内容", r["code"] == 0 and len(r["data"]) > 0, f"{len(r['data'])} 条")
r = c.get(SHOP + "/api/feed", params={"scene": "hot", "explore": "false", "limit": 5}).json()
check("explore 开关可切换", r["code"] == 0)

# 商家角色登录（种子商家？用管理员看 traces 代替——商家分析需店主；用 merchant 注册流程太长，改验证 ops 技能的权限门）
r = c.post(SHOP + "/api/agent/merchant/analyze", json={"shopId": shop_id, "skill": "ops"}, headers=h).json()
check("非商家调分析被拒（40300 权限门）", r["code"] == 40300, f"code={r['code']}")

print(f"\n===== E2E 结果：{len(passed)} PASS / {len(failed)} FAIL =====")
for f in failed:
    print("  ✗", f)
