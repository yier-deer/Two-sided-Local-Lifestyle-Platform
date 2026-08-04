<script setup>
// 我的订单页：状态机全流程可视化（下单→支付→核销→评价）
// - 每个状态的合法操作按钮由状态机决定（CREATED 可支付/取消；PAID 可核销/退单；REDEEMED 可评价）
// - REDEEMED 的订单带"AI 起草评价"入口 → 签字权闭环的前半段
import { onMounted, ref } from 'vue'
import { myOrders, payOrder, redeemOrder, cancelOrder, refundOrder, isLogged } from '../api'

const orders = ref([])
const loading = ref(false)
const err = ref('')
const okMsg = ref('')

onMounted(load)

/** 拉我的订单 */
async function load() {
  if (!isLogged()) { location.hash = '#/login'; return }
  loading.value = true
  try {
    orders.value = await myOrders()
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

/** 通用动作执行器：成功后刷新列表（CAS 的 40903 会以 message 展示） */
async function act(name, fn) {
  err.value = ''; okMsg.value = ''
  try {
    await fn()
    okMsg.value = name + '成功'
    await load()
  } catch (e) {
    err.value = e.message
    await load()   // 冲突（40903）后刷新看最新状态
  }
}

const statusText = {
  CREATED: '待支付', PAID: '已支付·待核销', REDEEMED: '已核销·可评价',
  REVIEWED: '已评价', CANCELLED_TIMEOUT: '超时取消', CANCELLED_USER: '已取消', REFUNDED: '已退款',
}
const fen = (v) => (v == null ? '-' : (v / 100).toFixed(2))
</script>

<template>
  <div class="page wide">
    <h2>我的订单</h2>
    <p class="sub">电子套餐券模型：支付只是买了券，到店核销才算消费，核销后才能评价</p>

    <p class="msg" v-if="err">{{ err }}</p>
    <p class="ok" v-if="okMsg">{{ okMsg }}</p>
    <p class="hint" v-if="loading">加载中…</p>
    <div class="empty" v-if="!loading && !orders.length">
      还没有订单——去 <router-link to="/map">地图</router-link> 或 <router-link to="/agent">AI 助手</router-link> 逛逛
    </div>

    <div class="card order-item" v-for="o in orders" :key="o.id" :class="{ dim: o.status.startsWith('CANCELLED') || o.status === 'REFUNDED' }">
      <div class="row1">
        <b>#{{ o.id }} · 店铺 {{ o.shopId }} · 套餐 {{ o.skuTitle || o.skuId }}</b>
        <span class="badge" :class="o.status">{{ statusText[o.status] || o.status }}</span>
      </div>
      <div class="muted">
        实付 <span class="price">¥{{ fen(o.priceSnapshot) }}</span>
        <span v-if="o.couponId"> · 已用满减券</span>
        · 下单时间 {{ (o.createdAt || '').slice(0, 19).replace('T', ' ') }}
      </div>

      <div class="actions">
        <button class="small primary" style="width:auto;margin:0" v-if="o.status === 'CREATED'" @click="act('支付', () => payOrder(o.id))">模拟支付</button>
        <button class="small" v-if="o.status === 'CREATED'" @click="act('取消', () => cancelOrder(o.id))">取消</button>
        <button class="small teal" v-if="o.status === 'PAID'" @click="act('核销', () => redeemOrder(o.id))">到店核销</button>
        <button class="small" v-if="o.status === 'PAID'" @click="act('退单', () => refundOrder(o.id))">退单</button>
        <router-link v-if="o.status === 'REDEEMED'" :to="`/orders/${o.id}/review`">
          <button class="small teal">✍ AI 起草评价</button>
        </router-link>
        <span class="muted" v-if="o.status === 'REVIEWED'">已发布评价 ✓</span>
      </div>
    </div>
  </div>
</template>
