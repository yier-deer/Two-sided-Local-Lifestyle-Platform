import test from "node:test";
import assert from "node:assert/strict";
import { createDemoStore } from "../src/demo/store.js";

const user = { userId: 1, role: "USER" };
const merchant = { userId: 4, role: "MERCHANT" };
const admin = { userId: 99, role: "ADMIN" };
const memory = () => {
  const values = new Map();
  return {
    getItem: (k) => values.get(k),
    setItem: (k, v) => values.set(k, v),
    removeItem: (k) => values.delete(k),
  };
};
const setup = () => createDemoStore({ storage: memory() });
const call = (
  store,
  path,
  method = "GET",
  body,
  session = user,
  headers = {},
) => store.request(path, { method, body, headers }, session);

test("claimed coupon uses userCouponId at checkout and duplicate claim is rejected", async () => {
  const store = setup();
  const claimed = await call(store, "/api/coupons/1/claim", "POST");
  await assert.rejects(call(store, "/api/coupons/1/claim", "POST"), /已领取/);
  const order = await call(
    store,
    "/api/orders",
    "POST",
    { skuId: 11, userCouponId: claimed.id },
    user,
    { "Idempotency-Key": "first" },
  );
  assert.equal(order.priceSnapshot, 17800);
  assert.equal((await call(store, "/api/coupons/mine"))[0].status, "FROZEN");
});

test("same idempotency key returns one order and cancelling restores stock and coupon", async () => {
  const store = setup();
  const stock = (await call(store, "/api/shops/1/skus"))[0].stock;
  const claimed = await call(store, "/api/coupons/1/claim", "POST");
  const opts = { skuId: 11, userCouponId: claimed.id };
  const a = await call(store, "/api/orders", "POST", opts, user, {
    "Idempotency-Key": "retry",
  });
  const b = await call(store, "/api/orders", "POST", opts, user, {
    "Idempotency-Key": "retry",
  });
  assert.equal(a.id, b.id);
  assert.equal((await call(store, "/api/shops/1/skus"))[0].stock, stock - 1);
  await call(store, `/api/orders/${a.id}/cancel`, "POST");
  assert.equal((await call(store, "/api/shops/1/skus"))[0].stock, stock);
  assert.equal((await call(store, "/api/coupons/mine"))[0].status, "UNUSED");
});

test("paid orders cannot be reviewed; generation is a draft and edited confirmation is published", async () => {
  const store = setup();
  await assert.rejects(
    call(store, "/api/agent/user/review-draft", "POST", { orderId: 102 }),
    /核销/,
  );
  const before = (await call(store, "/api/shops/1/reviews")).length;
  const draft = await call(store, "/api/agent/user/review-draft", "POST", {
    orderId: 101,
    userNote: "等位十分钟",
    preferScores: { taste: 4 },
  });
  assert.equal((await call(store, "/api/shops/1/reviews")).length, before);
  await call(
    store,
    `/api/agent/user/review-draft/${draft.draftId}/publish`,
    "POST",
    { content: "我确认发布的修改内容", scores: { taste: 4, wait: 3, env: 5 } },
  );
  assert.equal(
    (await call(store, "/api/shops/1/reviews"))[0].content,
    "我确认发布的修改内容",
  );
  assert.equal(
    (await call(store, "/api/orders")).find((x) => x.id === 101).status,
    "REVIEWED",
  );
  await assert.rejects(
    call(
      store,
      `/api/agent/user/review-draft/${draft.draftId}/publish`,
      "POST",
      { content: "重复" },
    ),
    /草稿|评价/,
  );
});

test("merchant reply is visible publicly and foreign shop management is rejected", async () => {
  const store = setup();
  const reviews = await call(store, "/api/shops/1/reviews");
  const first = reviews[0];
  await call(
    store,
    `/api/reviews/${first.id}/replies`,
    "POST",
    { content: "谢谢反馈，我们会改善等位体验" },
    merchant,
  );
  assert.equal(
    (await call(store, "/api/shops/1/reviews"))[0].replies.at(-1).isMerchant,
    true,
  );
  await assert.rejects(
    call(store, "/api/merchant/orders?shopId=6", "GET", undefined, merchant),
    /自己的店/,
  );
  await assert.rejects(
    call(store, "/api/merchant/shops", "GET", undefined, user),
    /商家/,
  );
});

test("pending shops are invisible and approving publishes them to discovery", async () => {
  const store = setup();
  const created = await call(
    store,
    "/api/merchant/shops",
    "POST",
    { name: "待审核示例店", category: "COFFEE", lat: 30.24, lng: 120.15 },
    merchant,
  );
  assert.equal(
    (await call(store, "/api/shops/nearby")).some((x) => x.id === created.id),
    false,
  );
  await assert.rejects(
    call(
      store,
      `/api/admin/shops/${created.id}/approve`,
      "POST",
      undefined,
      merchant,
    ),
    /管理员/,
  );
  await call(
    store,
    `/api/admin/shops/${created.id}/approve`,
    "POST",
    undefined,
    admin,
  );
  assert.equal(
    (await call(store, "/api/shops/nearby")).some((x) => x.id === created.id),
    true,
  );
});

test("browser state survives reload and invalid coupon does not reserve inventory", async () => {
  const storage = memory();
  const store = createDemoStore({ storage });
  const stock = (await call(store, "/api/shops/1/skus"))[0].stock;
  await assert.rejects(
    call(
      store,
      "/api/orders",
      "POST",
      { skuId: 11, userCouponId: 9999 },
      user,
      { "Idempotency-Key": "bad" },
    ),
    /优惠券/,
  );
  assert.equal((await call(store, "/api/shops/1/skus"))[0].stock, stock);
  const order = await call(store, "/api/orders", "POST", { skuId: 11 }, user, {
    "Idempotency-Key": "persist",
  });
  const recovered = createDemoStore({ storage });
  assert.ok(
    (await call(recovered, "/api/orders")).some((x) => x.id === order.id),
  );
});

test("merchant-created coupons use the same one-year defaults and amount limits as the real service", async () => {
  const store = setup();
  const created = await call(
    store,
    "/api/merchant/coupons",
    "POST",
    {
      shopId: 1,
      title: "新增满减券",
      threshold: 10000,
      amount: 1500,
      total: 30,
    },
    merchant,
  );
  assert.ok(Date.parse(created.endAt) > Date.now() + 360 * 86400000);
  assert.equal(
    (await call(store, "/api/shops/1/coupons")).some(
      (c) => c.id === created.id,
    ),
    true,
  );
  await assert.rejects(
    call(
      store,
      "/api/merchant/coupons",
      "POST",
      {
        shopId: 1,
        title: "错误券",
        threshold: 10000,
        amount: 12000,
        total: 30,
      },
      merchant,
    ),
    /优惠券/,
  );
});

test("unapproved shop public child resources are hidden and reply size matches server", async () => {
  const store = setup();
  for (const type of ["skus", "coupons", "reviews"])
    await assert.rejects(call(store, `/api/shops/7/${type}`), /店铺|审核/);
  const reviews = await call(store, "/api/shops/1/reviews");
  await assert.rejects(
    call(
      store,
      `/api/reviews/${reviews[0].id}/replies`,
      "POST",
      { content: "字".repeat(301) },
      merchant,
    ),
    /300/,
  );
});
