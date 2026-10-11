import { DEMO_KEY, initialData } from "./data.js";

const clone = (value) =>
  value === undefined ? undefined : structuredClone(value);
const fail = (message) => {
  throw new Error(message);
};

export function createDemoStore({ storage } = {}) {
  let state;
  try {
    state = JSON.parse(storage?.getItem(DEMO_KEY) || "null");
  } catch {
    state = null;
  }
  if (state?.version !== 1) state = initialData();
  const save = () => storage?.setItem(DEMO_KEY, JSON.stringify(state));
  const id = () => ++state.nextId;
  const shop = (shopId) =>
    state.shops.find((s) => s.id === Number(shopId)) || fail("店铺不存在");
  const auth = (session) => session?.userId || fail("请先登录");
  const role = (session, expected) => {
    auth(session);
    if (session.role !== expected)
      fail(expected === "ADMIN" ? "只有管理员可以审核" : "只有商家可以管理");
  };
  const own = (session, shopId) => {
    role(session, "MERCHANT");
    const s = shop(shopId);
    if (s.ownerId !== session.userId) fail("只能管理自己的店铺");
    return s;
  };
  const orderDto = (o) => ({
    ...o,
    shopName: shop(o.shopId).name,
    skuTitle: state.skus.find((s) => s.id === o.skuId)?.title,
    nickname:
      state.accounts.find((a) => a.userId === o.userId)?.nickname || "用户",
  });
  const validScores = (scores) => {
    if (
      !scores ||
      !["taste", "wait", "env"].every(
        (k) => Number.isInteger(scores[k]) && scores[k] >= 1 && scores[k] <= 5,
      )
    )
      fail("请填写 1–5 分的三项评分");
  };
  const visible = () => state.shops.filter((s) => s.status === "approved");
  const couponDto = (c) => {
    const claimed = state.userCoupons.filter((u) => u.couponId === c.id);
    return {
      ...c,
      claimedCount: claimed.length,
      usedCount: claimed.filter((u) => u.status === "USED").length,
      remaining: c.total - claimed.length,
    };
  };
  const release = (o) => {
    state.skus.find((s) => s.id === o.skuId).stock++;
    const c = state.userCoupons.find((c) => c.id === o.couponId);
    if (c) c.status = "UNUSED";
  };
  function expire() {
    for (const o of state.orders)
      if (o.status === "CREATED" && Date.parse(o.expireAt) < Date.now()) {
        o.status = "CANCELLED_TIMEOUT";
        release(o);
      }
  }
  function handle(path, opts, session) {
    const url = new URL(path, "http://demo.local");
    const p = url.pathname;
    const q = url.searchParams;
    const method = opts.method || "GET";
    const b = opts.body || {};
    const parts = p.split("/").filter(Boolean);
    expire();
    if (p === "/api/auth/login" && method === "POST") {
      const a =
        state.accounts.find(
          (a) => a.phone === b.phone && a.password === b.password,
        ) || fail("手机号或密码错误");
      return {
        token: `demo-${a.userId}`,
        userId: a.userId,
        role: a.role,
        nickname: a.nickname,
        phone: a.phone,
      };
    }
    if (p === "/api/auth/register" && method === "POST") {
      if (!/^1\d{10}$/.test(b.phone) || (b.password || "").length < 6)
        fail("请输入正确手机号和至少 6 位密码");
      if (!["USER", "MERCHANT"].includes(b.role)) fail("注册角色无效");
      if (state.accounts.some((a) => a.phone === b.phone)) fail("手机号已注册");
      state.accounts.push({
        userId: id(),
        ...b,
        nickname: b.nickname || "新朋友",
      });
      return { success: true };
    }
    if (p === "/api/auth/me") {
      auth(session);
      const a = state.accounts.find((a) => a.userId === session.userId);
      return {
        userId: a.userId,
        role: a.role,
        nickname: a.nickname,
        phone: a.phone,
      };
    }
    if (p === "/api/shops/nearby") {
      const lat = Number(q.get("lat") || 30.24),
        lng = Number(q.get("lng") || 120.15);
      return visible()
        .map((s) => ({
          ...s,
          distanceMeters: Math.round(
            Math.hypot((s.lat - lat) * 111000, (s.lng - lng) * 96000),
          ),
        }))
        .filter(
          (s) =>
            (!q.get("category") || s.category === q.get("category")) &&
            s.distanceMeters <= Number(q.get("radius") || 5000),
        )
        .sort((a, b) => a.distanceMeters - b.distanceMeters);
    }
    if (p === "/api/merchant/shops") {
      role(session, "MERCHANT");
      if (method === "GET")
        return state.shops.filter((s) => s.ownerId === session.userId);
      if (
        !b.name?.trim() ||
        !["HOTPOT", "COFFEE", "ENTERTAIN"].includes(b.category)
      )
        fail("请输入店名并选择品类");
      const s = {
        ...b,
        id: id(),
        ownerId: session.userId,
        status: "pending",
        rating: null,
        reviewCount: 0,
        distanceMeters: 800,
        image: b.category === "COFFEE" ? "coffee" : "restaurant",
        tags: [],
        approvedAt: null,
      };
      state.shops.push(s);
      return s;
    }
    if (/^\/api\/merchant\/shops\/\d+\/resubmit$/.test(p)) {
      const s = own(session, parts[3]);
      if (s.status !== "rejected") fail("只有被驳回店铺可以重新提交");
      Object.assign(s, b, {
        status: "pending",
        ownerId: session.userId,
        id: s.id,
      });
      return s;
    }
    if (p === "/api/admin/shops") {
      role(session, "ADMIN");
      return state.shops.filter(
        (s) => s.status === (q.get("status") || "pending"),
      );
    }
    if (/^\/api\/admin\/shops\/\d+\/(approve|reject)$/.test(p)) {
      role(session, "ADMIN");
      const s = shop(parts[3]);
      if (s.status !== "pending") fail("店铺当前不在待审核状态");
      s.status = parts[4] === "approve" ? "approved" : "rejected";
      s.approvedAt = parts[4] === "approve" ? new Date().toISOString() : null;
      return s;
    }
    if (/^\/api\/shops\/\d+$/.test(p)) {
      const s = shop(parts[2]);
      if (s.status !== "approved") fail("店铺尚未通过审核");
      return s;
    }
    if (/^\/api\/shops\/\d+\/skus$/.test(p)) {
      if (shop(parts[2]).status !== "approved") fail("店铺尚未通过审核");
      return state.skus.filter(
        (s) => s.shopId === Number(parts[2]) && s.onSale,
      );
    }
    if (
      /^\/api\/shops\/\d+\/(coupons|reviews)$/.test(p) &&
      shop(parts[2]).status !== "approved"
    )
      fail("店铺尚未通过审核");
    if (/^\/api\/shops\/\d+\/coupons$/.test(p))
      return state.coupons
        .filter(
          (c) =>
            c.shopId === Number(parts[2]) && Date.parse(c.endAt) > Date.now(),
        )
        .map(couponDto);
    if (/^\/api\/shops\/\d+\/reviews$/.test(p))
      return state.reviews
        .filter((r) => r.shopId === Number(parts[2]))
        .sort(
          (a, b) =>
            Date.parse(b.createdAt) - Date.parse(a.createdAt) || b.id - a.id,
        );
    if (/^\/api\/coupons\/\d+\/claim$/.test(p)) {
      auth(session);
      const c =
        state.coupons.find((c) => c.id === Number(parts[2])) ||
        fail("优惠券不存在");
      if (
        state.userCoupons.filter(
          (u) => u.couponId === c.id && u.userId === session.userId,
        ).length >= c.perUserLimit
      )
        fail("你已领取过这张优惠券");
      if (couponDto(c).remaining <= 0 || Date.parse(c.endAt) <= Date.now())
        fail("优惠券已领完或过期");
      const u = {
        id: id(),
        userId: session.userId,
        couponId: c.id,
        status: "UNUSED",
      };
      state.userCoupons.push(u);
      return { ...c, ...u };
    }
    if (p === "/api/coupons/mine") {
      auth(session);
      return state.userCoupons
        .filter(
          (u) =>
            u.userId === session.userId &&
            (!q.get("status") || u.status === q.get("status")),
        )
        .map((u) => ({
          ...state.coupons.find((c) => c.id === u.couponId),
          ...u,
        }));
    }
    if (p === "/api/orders" && method === "POST") {
      auth(session);
      const key = opts.headers?.["Idempotency-Key"] || fail("缺少幂等键");
      const fullKey = `${session.userId}:${key}`;
      if (state.idempotency[fullKey])
        return orderDto(
          state.orders.find((o) => o.id === state.idempotency[fullKey]),
        );
      const s = state.skus.find((s) => s.id === b.skuId) || fail("套餐不存在");
      if (!s.onSale || s.stock < 1 || shop(s.shopId).status !== "approved")
        fail("套餐已下架或库存不足");
      let price = s.price,
        uc;
      if (b.userCouponId) {
        uc =
          state.userCoupons.find(
            (c) =>
              c.id === b.userCouponId &&
              c.userId === session.userId &&
              c.status === "UNUSED",
          ) || fail("优惠券不可用");
        const c = state.coupons.find((c) => c.id === uc.couponId);
        if (
          c.shopId !== s.shopId ||
          c.threshold > s.price ||
          Date.parse(c.endAt) < Date.now()
        )
          fail("优惠券不满足使用条件");
        price = Math.max(0, price - c.amount);
      }
      const o = {
        id: id(),
        userId: session.userId,
        shopId: s.shopId,
        skuId: s.id,
        couponId: uc?.id || null,
        priceSnapshot: price,
        status: "CREATED",
        createdAt: new Date().toISOString(),
        expireAt: new Date(Date.now() + 15 * 60000).toISOString(),
      };
      s.stock--;
      if (uc) uc.status = "FROZEN";
      state.orders.unshift(o);
      state.idempotency[fullKey] = o.id;
      return orderDto(o);
    }
    if (p === "/api/orders") {
      auth(session);
      return state.orders
        .filter(
          (o) =>
            o.userId === session.userId &&
            (!q.get("status") || o.status === q.get("status")) &&
            (q.get("unreviewed") !== "true" || o.status === "REDEEMED"),
        )
        .map(orderDto)
        .sort((a, b) => b.id - a.id);
    }
    if (p === "/api/merchant/orders") {
      role(session, "MERCHANT");
      if (q.get("shopId")) own(session, q.get("shopId"));
      return state.orders
        .filter(
          (o) =>
            shop(o.shopId).ownerId === session.userId &&
            (!q.get("shopId") || o.shopId === Number(q.get("shopId"))) &&
            (!q.get("status") || o.status === q.get("status")),
        )
        .map(orderDto)
        .sort((a, b) => b.id - a.id);
    }
    if (
      /^\/api\/(merchant\/)?orders\/\d+\/(pay|redeem|cancel|refund)$/.test(p)
    ) {
      auth(session);
      const merchantPath = parts[1] === "merchant";
      const orderId = Number(parts[merchantPath ? 3 : 2]),
        action = parts.at(-1);
      const o =
        state.orders.find((o) => o.id === orderId) || fail("订单不存在");
      if (merchantPath) {
        own(session, o.shopId);
        if (action !== "redeem") fail("商家只能核销订单");
      } else if (o.userId !== session.userId) fail("只能操作自己的订单");
      const rules = {
        pay: ["CREATED", "PAID"],
        redeem: ["PAID", "REDEEMED"],
        cancel: ["CREATED", "CANCELLED_USER"],
        refund: ["PAID", "REFUNDED"],
      };
      const [before, after] = rules[action];
      if (o.status === after) return orderDto(o);
      if (o.status !== before) fail("订单状态已变化，此操作不可用");
      o.status = after;
      if (action === "cancel" || action === "refund") release(o);
      if (action === "pay") {
        const c = state.userCoupons.find((c) => c.id === o.couponId);
        if (c) c.status = "USED";
      }
      if (action === "redeem") state.skus.find((s) => s.id === o.skuId).sales++;
      return orderDto(o);
    }
    if (p === "/api/merchant/skus") {
      own(session, q.get("shopId") || b.shopId);
      if (method === "GET")
        return state.skus.filter((s) => s.shopId === Number(q.get("shopId")));
      if (
        !b.title?.trim() ||
        !Number.isInteger(b.price) ||
        b.price < 1 ||
        !Number.isInteger(b.stock) ||
        b.stock < 0
      )
        fail("套餐名称、价格或库存无效");
      const s = { ...b, id: id(), onSale: true, sales: 0 };
      state.skus.push(s);
      return s;
    }
    if (/^\/api\/merchant\/skus\/\d+$/.test(p)) {
      const s =
        state.skus.find((s) => s.id === Number(parts[3])) || fail("套餐不存在");
      own(session, s.shopId);
      if (b.price !== undefined && (!Number.isInteger(b.price) || b.price < 1))
        fail("价格必须为正整数分");
      if (b.stock !== undefined && (!Number.isInteger(b.stock) || b.stock < 0))
        fail("库存不能小于 0");
      Object.assign(s, b, { id: s.id, shopId: s.shopId });
      return s;
    }
    if (p === "/api/merchant/coupons") {
      own(session, q.get("shopId") || b.shopId);
      if (method === "GET")
        return state.coupons
          .filter((c) => c.shopId === Number(q.get("shopId")))
          .map(couponDto);
      if (
        !b.title?.trim() ||
        !Number.isInteger(b.amount) ||
        b.amount < 1 ||
        !Number.isInteger(b.threshold) ||
        b.threshold <= 0 ||
        b.amount >= b.threshold ||
        !Number.isInteger(b.total) ||
        b.total < 1
      )
        fail("请填写有效的优惠券规则，减免额须小于门槛");
      const c = {
        ...b,
        id: id(),
        perUserLimit: 1,
        startAt: new Date().toISOString(),
        endAt: new Date(Date.now() + 365 * 86400000).toISOString(),
      };
      state.coupons.push(c);
      return couponDto(c);
    }
    if (/^\/api\/reviews\/\d+\/replies$/.test(p)) {
      const r =
        state.reviews.find((r) => r.id === Number(parts[2])) ||
        fail("评价不存在");
      own(session, r.shopId);
      if (!b.content?.trim() || b.content.length > 300)
        fail("请输入 1–300 字回复");
      const reply = {
        id: id(),
        content: b.content.trim(),
        isMerchant: true,
        nickname:
          state.accounts.find((a) => a.userId === session.userId)?.nickname ||
          "商家",
        createdAt: new Date().toISOString(),
      };
      r.replies.push(reply);
      return reply;
    }
    if (p === "/api/reviews")
      return publishReview(b.orderId, b.content, b.scores, session);
    if (p === "/api/feed") {
      const newShops = visible().filter(
        (s) => Date.parse(s.approvedAt) > Date.now() - 7 * 86400000,
      );
      return visible()
        .filter(
          (s) =>
            q.get("scene") !== "new" || newShops.some((n) => n.id === s.id),
        )
        .map((s, i) => {
          const r = state.reviews.find((r) => r.shopId === s.id);
          return {
            shopId: s.id,
            shopName: s.name,
            contentId: r?.id,
            contentType: "REVIEW",
            isNew: newShops.some((n) => n.id === s.id),
            score: Number(
              (
                (8 - i) *
                (newShops.some((n) => n.id === s.id) &&
                q.get("explore") !== "false"
                  ? 2
                  : 1)
              ).toFixed(2),
            ),
            content: {
              text: r?.content || "新店开业，等你来发现。",
              scores: r?.scores,
            },
            nickname: r?.nickname || "探店雷达",
            image: s.image,
            shop: s,
          };
        })
        .sort((a, b) =>
          q.get("scene") === "nearby"
            ? a.shop.distanceMeters - b.shop.distanceMeters
            : b.score - a.score,
        );
    }
    if (p === "/api/agent/user/recommend") {
      auth(session);
      const message = b.message || "";
      const cat = /咖啡|下午茶|办公/.test(message)
        ? "COFFEE"
        : /电影|玩|约会/.test(message)
          ? "ENTERTAIN"
          : "HOTPOT";
      const candidates = visible()
        .filter((s) => s.category === cat)
        .slice(0, 3);
      return {
        sessionId: b.sessionId,
        answer: `按你的需求，我从示例数据中选了 ${candidates.length} 家${cat === "COFFEE" ? "咖啡店" : cat === "ENTERTAIN" ? "休闲好去处" : "火锅店"}。位置和评论可以逐条核对，预算还需以套餐为准。`,
        shops: candidates.map((s) => ({
          id: s.id,
          name: s.name,
          reason:
            state.reviews.find((r) => r.shopId === s.id)?.content ||
            "新店值得了解。",
          cons:
            cat === "HOTPOT"
              ? s.id === 3
                ? "口味偏清淡，重辣爱好者可能不适合。"
                : "晚餐高峰需要等位，环境较热闹。"
              : "周末热门时段座位可能紧张。",
        })),
        evidenceIds: candidates.flatMap((s) =>
          state.reviews
            .filter((r) => r.shopId === s.id)
            .slice(0, 2)
            .map((r) => r.id),
        ),
        toolCalls: [
          "get_user_profile",
          "search_shops",
          "get_review_evidence",
          "compare_and_guard",
        ],
        demo: true,
        needClarify: false,
      };
    }
    if (p === "/api/agent/user/review-draft") {
      auth(session);
      const o =
        state.orders.find(
          (o) => o.id === b.orderId && o.userId === session.userId,
        ) || fail("订单不存在或不属于你");
      if (o.status !== "REDEEMED") fail("订单需已核销且未评价");
      const s = shop(o.shopId),
        sku = state.skus.find((s) => s.id === o.skuId);
      const d = {
        draftId: `draft-${id()}`,
        userId: session.userId,
        orderId: o.id,
        scores: { taste: 4, wait: 4, env: 4, ...b.preferScores },
        content: `这次到${s.name}，购买的是「${sku.title}」。${b.userNote?.trim() || "具体口味、等位和环境体验，我想再补充一下。"}`,
        usedFacts: [
          `店铺：${s.name}`,
          `套餐：${sku.title}`,
          `实付：${(o.priceSnapshot / 100).toFixed(2)} 元`,
          "订单已核销",
          ...(b.userNote ? [`我的笔记：${b.userNote}`] : []),
        ],
        toolCalls: [
          "get_order_facts",
          "align_user_note",
          "draft",
          "human_confirmation",
        ],
        demo: true,
      };
      validScores(d.scores);
      state.drafts.push(d);
      return d;
    }
    if (/^\/api\/agent\/user\/review-draft\/[^/]+\/publish$/.test(p)) {
      auth(session);
      const d =
        state.drafts.find(
          (d) => d.draftId === parts[4] && d.userId === session.userId,
        ) || fail("草稿不存在或已发布");
      const result = publishReview(
        d.orderId,
        b.content ?? d.content,
        b.scores ?? d.scores,
        session,
      );
      state.drafts = state.drafts.filter((x) => x !== d);
      return result;
    }
    if (p === "/api/agent/merchant/analyze") {
      const s = own(session, b.shopId);
      const orders = state.orders.filter(
        (o) =>
          o.shopId === s.id &&
          ["PAID", "REDEEMED", "REVIEWED"].includes(o.status),
      );
      const reviews = state.reviews.filter((r) => r.shopId === s.id);
      const total = orders.reduce((sum, o) => sum + o.priceSnapshot, 0);
      return {
        skill: b.skill,
        observations:
          b.skill === "reviews"
            ? [
                `当前有 ${reviews.length} 条示例评价。`,
                `其中 ${reviews.filter((r) => /等位|高峰/.test(r.content)).length} 条提到等位或高峰。`,
              ]
            : b.skill === "competitors"
              ? visible()
                  .filter((x) => x.category === s.category && x.id !== s.id)
                  .map(
                    (x) =>
                      `${x.name}：${x.distanceMeters} 米，示例参考人均 ${x.avgPrice} 元。`,
                  )
              : [
                  `当前样本有效订单 ${orders.length} 笔，实付合计 ${(total / 100).toFixed(2)} 元。`,
                  `已核销及已评价 ${orders.filter((o) => ["REDEEMED", "REVIEWED"].includes(o.status)).length} 笔。`,
                ],
        hypotheses: [
          "高峰时段的等位体验可能影响再次到店意愿，需要结合更多时段数据验证。",
        ],
        suggestions: [
          "记录一周高峰时段等位时长，优先确认问题是否持续。",
          "对近期评价逐条回复，说明可执行的改进安排。",
        ],
        toolCalls: [
          b.skill === "reviews"
            ? "cluster_reviews"
            : b.skill === "competitors"
              ? "public_competitor_snapshot"
              : "get_order_summary",
        ],
        demo: true,
      };
    }
    fail("本地演示暂不支持此操作，请切换真实服务或返回上一页");
  }
  function publishReview(orderId, content, scores, session) {
    auth(session);
    const o =
      state.orders.find(
        (o) => o.id === orderId && o.userId === session.userId,
      ) || fail("订单不存在");
    if (o.status !== "REDEEMED") fail("订单需已核销且未评价");
    if (!content?.trim() || content.trim().length > 500)
      fail("评价请输入 1–500 字");
    validScores(scores);
    const r = {
      id: id(),
      orderId,
      shopId: o.shopId,
      userId: session.userId,
      nickname:
        state.accounts.find((a) => a.userId === session.userId)?.nickname ||
        "用户",
      content: content.trim(),
      scores,
      createdAt: new Date().toISOString(),
      replies: [],
    };
    state.reviews.unshift(r);
    o.status = "REVIEWED";
    o.reviewId = r.id;
    return r;
  }
  return {
    async request(path, opts = {}, session) {
      const result = handle(path, opts, session);
      save();
      return clone(result);
    },
    reset() {
      state = initialData();
      save();
    },
  };
}
