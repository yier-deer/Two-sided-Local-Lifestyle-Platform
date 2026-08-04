<script setup>
// 店铺详情页：套餐（下单入口）+ 优惠券（领取入口）+ 评价列表（含商家回复）
// - 下单/领券后跳"我的订单"完成支付→核销→评价闭环
// - 领券是 Redis Lua 原子扣减（每人限一张），重复领取会收到业务性拒绝提示
import { onMounted, ref } from 'vue'
import { shopDetail, shopSkus, shopCoupons, shopReviews, claimCoupon, createOrder, isLogged } from '../api'

const props = defineProps({ id: String })

const shop = ref(null)
const skus = ref([])
const coupons = ref([])
const reviews = ref([])
const err = ref('')
const okMsg = ref('')
const busy = ref(false)

onMounted(load)

async function load() {
  err.value = ''
  try {
    ;[shop.value, skus.value, coupons.value, reviews.value] = await Promise.all([
      shopDetail(props.id), shopSkus(props.id), shopCoupons(props.id), shopReviews(props.id),
    ])
  } catch (e) {
    err.value = e.message
  }
}

/** 领券：Lua 原子扣减，每人限领一张 */
async function claim(c) {
  if (!isLogged()) { location.hash = '#/login'; return }
  busy.value = true; err.value = ''; okMsg.value = ''
  try {
    await claimCoupon(c.id)
    okMsg.value = `已领取「${c.title}」——下单满 ${(c.threshold / 100).toFixed(0)} 元可用`
  } catch (e) {
    err.value = e.message   // 40902 抢完 / 已领过——业务性拒绝如实展示
  } finally {
    busy.value = false
  }
}

/** 下单：幂等键自动生成；成功跳订单页支付 */
async function order(sku) {
  if (!isLogged()) { location.hash = '#/login'; return }
  busy.value = true; err.value = ''; okMsg.value = ''
  try {
    await createOrder(sku.id)
    location.hash = '#/orders'
  } catch (e) {
    err.value = e.message
  } finally {
    busy.value = false
  }
}

const fen = (v) => (v == null ? '-' : (v / 100).toFixed(2))
const catName = { HOTPOT: '火锅', COFFEE: '咖啡', ENTERTAIN: '玩乐' }
</script>

<template>
  <div class="page wide">
    <p class="msg" v-if="err">{{ err }}</p>
    <p class="ok" v-if="okMsg">{{ okMsg }}</p>

    <template v-if="shop">
      <h2>{{ shop.name }}</h2>
      <p class="sub">
        <span class="cat">{{ catName[shop.category] || shop.category }}</span>
        <span v-if="shop.distanceMeters != null"> · 距离 {{ shop.distanceMeters }} m</span>
        · {{ shop.city }}
      </p>

      <h3>套餐</h3>
      <div class="card" v-for="s in skus" :key="s.id" style="display:flex;align-items:center;gap:12px">
        <div style="flex:1">
          <b>{{ s.title }}</b>
          <div class="muted">已售 {{ s.sales }} · 余 {{ s.stock }} 份</div>
        </div>
        <span class="price">¥{{ fen(s.price) }}</span>
        <button class="small primary" style="width:auto;margin:0" :disabled="busy || s.stock <= 0" @click="order(s)">
          {{ s.stock > 0 ? '下单' : '售罄' }}
        </button>
      </div>

      <h3>优惠券</h3>
      <div class="empty" v-if="!coupons.length">本店暂无可领的券</div>
      <div class="card" v-for="c in coupons" :key="c.id" style="display:flex;align-items:center;gap:12px">
        <div style="flex:1">
          <b style="color:#d63a12">{{ c.title }}</b>
          <div class="muted">满 {{ fen(c.threshold) }} 减 {{ fen(c.amount) }} · 余量 {{ c.stock ?? '-' }}</div>
        </div>
        <button class="small teal" :disabled="busy" @click="claim(c)">领取</button>
      </div>

      <h3>评价（{{ reviews.length }}）</h3>
      <div class="empty" v-if="!reviews.length">还没有评价——到店核销消费后可以来写第一条</div>
      <div class="card">
        <div class="review-item" v-for="r in reviews" :key="r.id">
          <div>
            <b style="font-size:13.5px">{{ r.nickname }}</b>
            <span class="scores">
              <span v-if="r.scores?.taste">口味{{ r.scores.taste }}</span>
              <span v-if="r.scores?.wait">等位{{ r.scores.wait }}</span>
              <span v-if="r.scores?.env">环境{{ r.scores.env }}</span>
            </span>
            <span class="muted">{{ (r.createdAt || '').slice(0, 10) }}</span>
          </div>
          <div style="font-size:13.5px;margin:4px 0">{{ r.content }}</div>
          <div v-for="rp in r.replies || []" :key="rp.id" style="font-size:12.5px;background:#f8f5ef;border-radius:8px;padding:5px 10px;margin-top:4px">
            <span v-if="rp.isMerchant" class="reply-tag">商家</span><b>{{ rp.nickname }}</b>：{{ rp.content }}
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
