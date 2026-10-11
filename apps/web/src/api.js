import { createClient } from "./client.js";
import { createDemoStore } from "./demo/store.js";
import { session, logout } from "./session.js";

export const demoStore = createDemoStore({ storage: globalThis.localStorage });
const client = createClient({
  mode: () => session.mode,
  session: () => session,
  demo: demoStore,
});
export async function api(path, opts) {
  try {
    return await client.request(path, opts);
  } catch (e) {
    if (e.code === 40100) logout();
    throw e;
  }
}
const post = (path, body, headers) =>
  api(path, { method: "POST", body, headers });
const query = (params) =>
  new URLSearchParams(
    Object.entries(params).filter(([, v]) => v != null && v !== ""),
  ).toString();
export const register = (phone, password, role, nickname) =>
  post("/api/auth/register", { phone, password, role, nickname });
export const login = (phone, password) =>
  post("/api/auth/login", { phone, password });
export const me = () => api("/api/auth/me");
export const nearby = (lat, lng, radius = 5000, category) =>
  api("/api/shops/nearby?" + query({ lat, lng, radius, category }));
export const shopDetail = (id) => api(`/api/shops/${id}`);
export const shopSkus = (id) => api(`/api/shops/${id}/skus`);
export const shopCoupons = (id) => api(`/api/shops/${id}/coupons`);
export const shopReviews = (id) => api(`/api/shops/${id}/reviews`);
export const createShop = (body) => post("/api/merchant/shops", body);
export const myShops = () => api("/api/merchant/shops");
export const resubmitShop = (id, body) =>
  post(`/api/merchant/shops/${id}/resubmit`, body);
export const adminShops = (status = "pending") =>
  api(`/api/admin/shops?${query({ status })}`);
export const approveShop = (id) => post(`/api/admin/shops/${id}/approve`);
export const rejectShop = (id) => post(`/api/admin/shops/${id}/reject`);
export const claimCoupon = (id) => post(`/api/coupons/${id}/claim`);
export const myCoupons = (status) =>
  api("/api/coupons/mine?" + query({ status }));
export const createOrder = (
  skuId,
  userCouponId = null,
  idempotencyKey = crypto.randomUUID(),
) =>
  post(
    "/api/orders",
    { skuId, userCouponId },
    { "Idempotency-Key": idempotencyKey },
  );
export const myOrders = (params = {}) => api("/api/orders?" + query(params));
export const payOrder = (id) => post(`/api/orders/${id}/pay`);
export const redeemOrder = (id) => post(`/api/orders/${id}/redeem`);
export const cancelOrder = (id) => post(`/api/orders/${id}/cancel`);
export const refundOrder = (id) => post(`/api/orders/${id}/refund`);
export const merchantOrders = (params) =>
  api("/api/merchant/orders?" + query(params || {}));
export const merchantRedeem = (id) => post(`/api/merchant/orders/${id}/redeem`);
export const merchantSkus = (shopId) =>
  api("/api/merchant/skus?" + query({ shopId }));
export const addSku = (body) => post("/api/merchant/skus", body);
export const updateSku = (id, body) =>
  api(`/api/merchant/skus/${id}`, { method: "PATCH", body });
export const merchantCoupons = (shopId) =>
  api("/api/merchant/coupons?" + query({ shopId }));
export const addCoupon = (body) => post("/api/merchant/coupons", body);
export const replyReview = (id, content) =>
  post(`/api/reviews/${id}/replies`, { content });
export const createReview = (body) => post("/api/reviews", body);
export const feed = (
  scene = "hot",
  lat = null,
  lng = null,
  explore = true,
  limit = 20,
) => api("/api/feed?" + query({ scene, lat, lng, explore, limit }));
export const agentRecommend = (message, lat, lng, sessionId) =>
  post("/api/agent/user/recommend", { message, lat, lng, sessionId });
export const agentReviewDraft = (orderId, userNote, preferScores = {}) =>
  post("/api/agent/user/review-draft", { orderId, userNote, preferScores });
export const agentPublishDraft = (draftId, content, scores) =>
  post(`/api/agent/user/review-draft/${draftId}/publish`, { content, scores });
export const agentAnalyze = (shopId, skill = "ops") =>
  post("/api/agent/merchant/analyze", { shopId, skill });
export const agentTraces = () => api("/api/agent/traces");
export const isLogged = () => !!session.token;
export const myRole = () => session.role;
