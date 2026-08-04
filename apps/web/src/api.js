// api.js —— 全站唯一 HTTP 出口：自动带 token、统一拆信封
// 开发期走 Vite 代理（/api → 8081），无 CORS 问题
const BASE = ''

/**
 * 统一请求函数。
 * @param path 接口路径（如 /api/auth/login）
 * @param opts { method, body, headers }
 * @returns 信封里的 data（code !== 0 时抛 Error，message 可直接展示）
 */
export async function api(path, opts = {}) {
  const token = localStorage.getItem('token')
  const res = await fetch(BASE + path, {
    method: opts.method || 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: 'Bearer ' + token } : {}),
      ...(opts.headers || {}),
    },
    body: opts.body != null ? JSON.stringify(opts.body) : undefined,
  })
  const envelope = await res.json()
  if (envelope.code !== 0) {
    // 40100 统一踢回登录页（token 过期/无效）
    if (envelope.code === 40100) {
      localStorage.removeItem('token')
      localStorage.removeItem('role')
      location.hash = '#/login'
    }
    throw new Error(envelope.message || '请求失败')
  }
  return envelope.data
}

// ---------- Auth ----------
export const register = (phone, password, role, nickname) =>
  api('/api/auth/register', { method: 'POST', body: { phone, password, role, nickname } })

export const login = (phone, password) =>
  api('/api/auth/login', { method: 'POST', body: { phone, password } })

export const me = () => api('/api/auth/me')

// ---------- Shop ----------
export const nearby = (lat, lng, radius = 5000, category = null) =>
  api(`/api/shops/nearby?lat=${lat}&lng=${lng}&radius=${radius}${category ? '&category=' + category : ''}`)

export const shopDetail = (id) => api(`/api/shops/${id}`)

export const createShop = (body) =>
  api('/api/merchant/shops', { method: 'POST', body })

export const myShops = () => api('/api/merchant/shops')

export const approveShop = (id) =>
  api(`/api/admin/shops/${id}/approve`, { method: 'POST' })

export const rejectShop = (id) =>
  api(`/api/admin/shops/${id}/reject`, { method: 'POST' })

export const resubmitShop = (id, body) =>
  api(`/api/merchant/shops/${id}/resubmit`, { method: 'POST', body })

/** 店铺套餐（公开） */
export const shopSkus = (shopId) => api(`/api/shops/${shopId}/skus`)

/** 店铺可用券（公开） */
export const shopCoupons = (shopId) => api(`/api/shops/${shopId}/coupons`)

/** 店铺评价列表（公开，含商家回复） */
export const shopReviews = (shopId) => api(`/api/shops/${shopId}/reviews`)

// ---------- 优惠券 ----------
export const claimCoupon = (couponId) =>
  api(`/api/coupons/${couponId}/claim`, { method: 'POST' })

export const myCoupons = (status = null) =>
  api(`/api/coupons/mine${status ? '?status=' + status : ''}`)

// ---------- 订单 ----------
/** 下单：幂等键由前端生成（UUID），网络重试时带同一个 key */
export const createOrder = (skuId, couponId = null) =>
  api('/api/orders', {
    method: 'POST',
    body: { skuId, couponId },
    headers: { 'Idempotency-Key': 'idem-' + crypto.randomUUID() },
  })

export const myOrders = (params = {}) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null)).toString()
  return api('/api/orders' + (q ? '?' + q : ''))
}

export const payOrder = (id) => api(`/api/orders/${id}/pay`, { method: 'POST' })
export const redeemOrder = (id) => api(`/api/orders/${id}/redeem`, { method: 'POST' })
export const cancelOrder = (id) => api(`/api/orders/${id}/cancel`, { method: 'POST' })
export const refundOrder = (id) => api(`/api/orders/${id}/refund`, { method: 'POST' })

// ---------- 信息流 ----------
export const feed = (scene = 'hot', lat = null, lng = null, explore = true, limit = 20) => {
  const p = new URLSearchParams({ scene, explore, limit })
  if (lat != null && lng != null) { p.set('lat', lat); p.set('lng', lng) }
  return api('/api/feed?' + p.toString())
}

// ---------- Agent（经 Java 门面转发） ----------
/** 对话式推荐（PRED 五步 + 护栏）：返回 {answer, shops, needClarify, evidenceIds, toolCalls} */
export const agentRecommend = (message, lat, lng, sessionId = 's-0') =>
  api('/api/agent/user/recommend', {
    method: 'POST',
    body: { message, lat, lng, sessionId },
  })

/** 生成评价草稿（CASDG）：返回 {draftId, scores, content, usedFacts} */
export const agentReviewDraft = (orderId, userNote = null, preferScores = {}) =>
  api('/api/agent/user/review-draft', {
    method: 'POST',
    body: { orderId, userNote, preferScores },
  })

/** 发布草稿（用户签字）：成功即写库 */
export const agentPublishDraft = (draftId) =>
  api(`/api/agent/user/review-draft/${draftId}/publish`, { method: 'POST' })

/** 商家分析（三技能）：返回 {observations, hypotheses, suggestions} */
export const agentAnalyze = (shopId, skill = 'ops') =>
  api('/api/agent/merchant/analyze', {
    method: 'POST',
    body: { shopId, skill },
  })

/** 登录态快捷判断 */
export const isLogged = () => !!localStorage.getItem('token')
export const myRole = () => localStorage.getItem('role') || ''
