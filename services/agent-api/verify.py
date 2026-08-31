# verify.py —— 全链路验证脚本（Python 侧跑，UTF-8 安全）：覆盖错误路径与越权，防止「只测了正常流程」。
#
# ============================ 这个脚本是干什么的 ============================
# 一个可重复执行的验收脚本：启动双服务后跑一遍，逐项断言，末尾打印 PASS/FAIL 统计。
# 覆盖 7 组用例（A~G）：
#   A 未核销单起草 → 应 40903（状态机拦截）
#   B 核销后起草   → 应成功（正常路径）
#   C 他人抢发草稿 → 应 40300（越权拦截）
#   D 本人发布     → 应成功且店页可见；重复发布应 40001（幂等）
#   E 商家三技能   → ops/reviews/competitors 都该跑通
#   F 越权调用     → 普通用户调商家分析 40300；商家分析他人店铺 40300
#   G 护栏直测     → 直接 import gate 函数，构造违规数据验证拦截（不花 LLM 钱、毫秒级）
#
# 为什么 G 组最有价值：护栏是「确定性代码」，可以脱离网络和模型单独测——
# 这也是「护栏用代码不用模型」的好处之一（可单测）。
#
# ============================ 用法 ============================
#   先启动 shop-api(:8081) 与 agent-api(:8000)，然后：
#   .\.venv\Scripts\python.exe verify.py
#
# ============================ 本文件涉及的 Python 语法速览（Java 背景看这里） ============================
#   PASS, FAIL = [], []                → 一次给两个变量赋空列表（Python 的元组解包）
#   (PASS if cond else FAIL).append(x) → 三元表达式选列表，再 append
#   f"  [{'PASS' if cond else 'FAIL'}]" → f-string 里嵌套表达式（含引号，注意外层用双引号）
#   def check(name, cond, detail="")   → 带默认参数的函数
#   dict(headers or {})                → 复制字典；or {} 是 None 兜底
#   next((o for o in 列表 if 条件), None) → 找第一个满足条件的元素，找不到给 None（≈ stream().filter().findFirst()）
#   __import__('time').time()          → 动态 import（这里为了不额外加一行 import 语句）
#   sys.exit(1)                        → 退出进程并返回状态码 1（CI/脚本用）
import json
import sys

import httpx

H = "http://localhost:8081"        # 主站地址（所有请求都打主站，由门面转发给 Python）
c = httpx.Client(timeout=60.0)     # 共享 HTTP 客户端（60s 超时：LLM 可能慢）
PASS, FAIL = [], []                # 两个「记分牌」：通过项 / 失败项


def check(name, cond, detail=""):
    """断言一条用例：cond 为真记 PASS，否则记 FAIL 并打印详情。

    参数：name 用例名；cond 断言结果（布尔）；detail 失败时附加的信息
    """
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not cond else ""))


def post(path, body, token=None, headers=None):
    """发 POST 请求并返回响应 JSON。

    参数：path 路径；body 请求体（会被转成 JSON）；token 可选，自动加 Authorization 头；headers 额外头
    返回：响应 JSON（已解析成 dict）
    """
    h = dict(headers or {})                       # 复制一份额外头（不修改调用方传进来的对象）
    if token:
        h["Authorization"] = f"Bearer {token}"    # 有 token 就自动加鉴权头
    r = c.post(H + path, json=body, headers=h)
    return r.json()


def login(phone, pwd="test123456"):
    """登录并返回 token（默认密码 test123456，可用第二参数覆盖）。"""
    return post("/api/auth/login", {"phone": phone, "password": pwd})["data"]["token"]


print("== 0. 服务健康 ==")
try:
    # 两个服务都要活着才继续，否则后面全都会失败
    check("shop-api UP", c.get(H + "/actuator/health").json()["status"] == "UP")
    check("agent-api UP", c.get("http://localhost:8000/health").json()["status"] == "UP")
except Exception as e:
    print("服务未就绪：", e)
    sys.exit(1)     # 直接退出，不浪费时间跑后面的用例

# 三个测试账号：ta/tb 普通用户（用来测越权），tm 商家（店 41 的主人）
ta = login("13700000001")
tb = login("13700000002")
tm = login("13811112222", "shop123456")   # 商家（店41主人）

print("== A. 未核销单起草（PAID 订单，应 40903）==")
orders = c.get(H + "/api/orders", headers={"Authorization": f"Bearer {ta}"}).json()["data"]
# 找一个「已支付未核销」的单；next(生成器, None) = 找到第一个就返回，没有就 None
paid_unredeemed = next((o for o in orders if o["status"] == "PAID"), None)
if not paid_unredeemed:
    # 幂等造一个 PAID 未核销单（幂等键带时间戳，脚本可重复跑）
    key = f"d7-verify-paid-{int(__import__('time').time())}"
    o = post("/api/orders", {"skuId": 81}, token=ta, headers={"Idempotency-Key": key})
    post(f"/api/orders/{o['data']['id']}/pay", {}, token=ta)   # 支付但不核销
    paid_unredeemed = o["data"]
r = post("/api/agent/user/review-draft", {"orderId": paid_unredeemed["id"], "userNote": "测试"},
         token=ta)
check("PAID 单起草被拒 40903", r["code"] == 40903, f"code={r['code']} {r.get('message')}")

print("== B. A 核销新单并起草（准备越权测试）==")
key = f"d7-verify-owner-{int(__import__('time').time())}"
o = post("/api/orders", {"skuId": 81}, token=ta, headers={"Idempotency-Key": key})
oid = o["data"]["id"]
post(f"/api/orders/{oid}/pay", {}, token=ta)      # 支付
post(f"/api/orders/{oid}/redeem", {}, token=ta)   # 核销（到店消费确认）
r = post("/api/agent/user/review-draft", {"orderId": oid, "userNote": "微辣锅底很香，周末人多"},
         token=ta)
check("A 起草成功", r["code"] == 0 and r.get("data"), f"code={r['code']} {r.get('message')}")
did = r["data"]["draftId"] if r["code"] == 0 and r.get("data") else None   # 记下草稿 ID 供后面用
if did:
    check("预设分被尊重", r["code"] == 0)
    # 打印草稿内容，人眼可核对（ensure_ascii=False 让中文正常显示）
    print("    scores:", json.dumps(r["data"]["scores"], ensure_ascii=False))
    print("    content:", r["data"]["content"])
    print("    usedFacts:", " | ".join(r["data"]["usedFacts"]))

if did:
    print("== C. B 抢发 A 的草稿（应 40300）==")
    # 用另一个用户的 token 去发布 A 的草稿 → 必须被拒（草稿有归属校验）
    r = post(f"/api/agent/user/review-draft/{did}/publish", {}, token=tb)
    check("他人草稿被拒 40300", r["code"] == 40300, f"code={r['code']} {r.get('message')}")

    print("== D. A 自己发布（应成功且店页可见）==")
    r = post(f"/api/agent/user/review-draft/{did}/publish", {}, token=ta)
    check("A 发布成功", r["code"] == 0, f"code={r['code']} {r.get('message')}")
    reviews = c.get(H + "/api/shops/41/reviews").json()["data"]
    check("店页出现该评价", any(x["orderId"] == oid for x in reviews))   # any = 列表里有任一满足即可
    r2 = post(f"/api/agent/user/review-draft/{did}/publish", {}, token=ta)
    check("重复发布 40001（已消费）", r2["code"] == 40001, f"code={r2['code']}")

print("== E. 商家三技能（店41，主人 13811112222）==")
for skill in ("ops", "reviews", "competitors"):
    r = post("/api/agent/merchant/analyze", {"shopId": 41, "skill": skill}, token=tm)
    ok = r["code"] == 0
    check(f"analyze {skill}", ok, f"code={r['code']} {r.get('message')}")
    if ok:
        d = r["data"]
        # 打印三层结果，人眼核对结构是否齐全
        print(f"    观察: {d['observations']}")
        print(f"    假设: {d['hypotheses']}")
        print(f"    建议: {d['suggestions']}")

print("== F. 越权（应 40300）==")
r = post("/api/agent/merchant/analyze", {"shopId": 41, "skill": "ops"}, token=ta)
check("用户角色调 analyze 拒 40300", r["code"] == 40300, f"code={r['code']}")
r = post("/api/agent/merchant/analyze", {"shopId": 1, "skill": "ops"}, token=tm)
check("商家分析他人店铺拒 40300", r["code"] == 40300, f"code={r['code']}")

print("== G. 商家护栏直测（构造违规输出）==")
# 关键：直接 import 护栏函数本地调用——不发请求、不花 LLM 钱、毫秒级出结果
from merchant_graph import gate

# 合法样本：数字来自 data_text，假设带「可能」
good = {"data_text": '{"newCustomers7d": 3, "couponShare": 50.0}',
        "observations": ["近7日新客3人"], "hypotheses": ["可能因券活动，或周末客流"],
        "suggestions": ["继续投放满减券"]}
check("合法输出放行", gate(good) == {})
# 违规①：观察句编了个数字 99（数据里没有）
bad_num = dict(good, observations=["近7日新客99人"])
check("编造数字拦截 42201", gate(bad_num).get("error_code") == 42201)
# 违规②：假设是无限制的因果断言（没有「可能」）
no_hedge = dict(good, hypotheses=["因为投了券所以新客涨"])
check("无限定词因果断言拦截 42201", gate(no_hedge).get("error_code") == 42201)
# 合规③：带「可能」的因果表述应该放行（这就是当初修正的那条规则）
hedged_causal = dict(good, hypotheses=["可能因为券活动，导致新客上升，也可能是周末客流"])
check("带『可能』限定的因果表述放行", gate(hedged_causal) == {})
# 违规④：确定性断言「证明了」
certain = dict(good, hypotheses=["券活动证明了新客增长"])
check("确定性断言拦截 42201", gate(certain).get("error_code") == 42201)
# 违规⑤：建议超过 2 条
bad_many = dict(good, suggestions=["建议1", "建议2", "建议3"])
check("建议超量拦截 42201", gate(bad_many).get("error_code") == 42201)

print()
print(f"===== 结果：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
if FAIL:
    print("失败项：", FAIL)
    sys.exit(1)   # 有失败就以非 0 退出（便于 CI/脚本判断）
