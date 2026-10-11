import test from "node:test";
import assert from "node:assert/strict";
import { createClient } from "../src/client.js";

test("demo requests never send stored credentials to network", async () => {
  let fetched = false;
  const client = createClient({
    mode: () => "demo",
    session: () => ({ token: "secret-real" }),
    demo: { request: async () => ({ demo: true }) },
    fetchImpl: async () => {
      fetched = true;
    },
  });
  assert.deepEqual(await client.request("/api/orders"), { demo: true });
  assert.equal(fetched, false);
});
test("real HTTP failures never fall back to sample success", async () => {
  let demoCalled = false;
  const client = createClient({
    mode: () => "live",
    session: () => ({ token: "real-token" }),
    demo: {
      request: () => {
        demoCalled = true;
      },
    },
    fetchImpl: async () => ({
      ok: false,
      status: 503,
      json: async () => ({
        code: 50000,
        message: "Agent 不可用",
        requestId: "r1",
      }),
    }),
  });
  await assert.rejects(
    client.request("/api/agent/user/recommend"),
    /Agent 不可用/,
  );
  assert.equal(demoCalled, false);
});
test("HTTP request preserves caller idempotency key and request body", async () => {
  let actual;
  const client = createClient({
    mode: () => "live",
    session: () => ({ token: "jwt" }),
    fetchImpl: async (path, opts) => {
      actual = opts;
      return { ok: true, json: async () => ({ code: 0, data: { id: 1 } }) };
    },
  });
  await client.request("/api/orders", {
    method: "POST",
    body: { skuId: 11, userCouponId: 5 },
    headers: { "Idempotency-Key": "reuse-this" },
  });
  assert.equal(actual.headers["Idempotency-Key"], "reuse-this");
  assert.deepEqual(JSON.parse(actual.body), { skuId: 11, userCouponId: 5 });
});

test("late live responses cannot cross into a newer demo session", async () => {
  const state = {
    mode: "live",
    token: "old-jwt",
    userId: 42,
    role: "USER",
    revision: 0,
  };
  let complete;
  const client = createClient({
    mode: () => state.mode,
    session: () => state,
    fetchImpl: () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  });
  const pending = client.request("/api/auth/login");
  Object.assign(state, {
    mode: "demo",
    token: "demo-1",
    userId: 1,
    revision: 1,
  });
  complete({
    ok: true,
    json: async () => ({
      code: 0,
      data: { token: "new-real-jwt", userId: 444 },
    }),
  });
  await assert.rejects(pending, (e) => e.code === "SESSION_CHANGED");
});

test("late unauthorized responses are discarded instead of invalidating the new identity", async () => {
  const state = { mode: "live", token: "old-jwt", userId: 42, revision: 0 };
  let complete;
  const client = createClient({
    mode: () => state.mode,
    session: () => state,
    fetchImpl: () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  });
  const pending = client.request("/api/orders");
  Object.assign(state, { token: "fresh-jwt", userId: 43, revision: 1 });
  complete({
    ok: false,
    json: async () => ({ code: 40100, message: "旧登录已失效" }),
  });
  await assert.rejects(pending, (e) => e.code === "SESSION_CHANGED");
});
