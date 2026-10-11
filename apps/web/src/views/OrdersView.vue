<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import {
  myOrders,
  payOrder,
  redeemOrder,
  cancelOrder,
  refundOrder,
  shopDetail,
} from "../api.js";
import { money, statusText, shopImage, dateTime } from "../domain.js";
import { askConfirm, toast } from "../session.js";
const route = useRoute();
const orders = ref([]),
  shops = ref({}),
  loading = ref(true),
  error = ref(""),
  busy = ref(null),
  tab = ref(route.query.status || "");
const tabs = {
  "": "全部订单",
  CREATED: "待支付",
  PAID: "待核销",
  REDEEMED: "待评价",
  REVIEWED: "已完成",
};
const filtered = computed(() =>
  orders.value.filter((o) => !tab.value || o.status === tab.value),
);
async function load() {
  loading.value = true;
  error.value = "";
  try {
    orders.value = await myOrders();
    const ids = [...new Set(orders.value.map((o) => o.shopId))];
    const results = await Promise.allSettled(ids.map(shopDetail));
    results.forEach((r, i) => {
      if (r.status === "fulfilled") shops.value[ids[i]] = r.value;
    });
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
async function act(o, action) {
  if (busy.value !== null) return;
  busy.value = o.id;
  try {
    await {
      pay: payOrder,
      redeem: redeemOrder,
      cancel: cancelOrder,
      refund: refundOrder,
    }[action](o.id);
    toast(
      {
        pay: "支付成功，出发前可在订单中查看套餐",
        redeem: "核销成功，现在可以分享消费评价",
        cancel: "订单已取消，库存和优惠券已恢复",
        refund: "退单完成，库存和优惠券已恢复",
      }[action],
    );
    await load();
  } catch (e) {
    toast(e.message, "error");
    await load();
  } finally {
    busy.value = null;
  }
}
function confirmAction(o, action) {
  askConfirm({
    title:
      action === "refund"
        ? "确认退掉这份套餐？"
        : action === "cancel"
          ? "取消未支付订单？"
          : "确认完成到店核销？",
    text:
      action === "redeem"
        ? "这是演示用消费确认。核销后代表已到店消费，不能再退单，随后可以评价。商家端也可以核销本店订单。"
        : "确认后会恢复本单占用的套餐库存和优惠券。",
    confirm:
      action === "refund"
        ? "确认退单"
        : action === "cancel"
          ? "取消订单"
          : "确认核销",
    danger: action !== "redeem",
    action: () => act(o, action),
  });
}
onMounted(load);
</script>
<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow">YOUR EVERYDAY PLANS</div>
      <h1 style="margin-top: 8px">我的到店计划</h1>
      <p>从一次心动，到一次认真体验。</p>
    </div>
    <router-link to="/discover" class="btn small"
      ><Icon name="Compass" :size="15" />再发现一家好店</router-link
    >
  </div>
  <div class="order-flow">
    <span><Icon name="ShoppingBag" :size="16" />选套餐</span
    ><Icon name="ChevronRight" :size="13" /><span
      ><Icon name="Ticket" :size="16" />模拟支付</span
    ><Icon name="ChevronRight" :size="13" /><span
      ><Icon name="CheckCircle2" :size="16" />到店核销</span
    ><Icon name="ChevronRight" :size="13" /><span
      ><Icon name="MessageSquare" :size="16" />分享评价</span
    >
  </div>
  <div class="tabs">
    <button
      v-for="(name, key) in tabs"
      :key="key"
      :class="{ active: tab === key }"
      @click="tab = key"
    >
      {{ name }}
      <span v-if="key" class="muted">{{
        orders.filter((o) => o.status === key).length
      }}</span>
    </button>
  </div>
  <UiState
    :loading="loading"
    :error="error"
    :empty="!filtered.length"
    title="这一页还没有到店计划"
    text="找一家喜欢的店，选一份刚刚好的套餐吧。"
    @retry="load"
    ><router-link to="/discover" class="btn primary small"
      >去发现</router-link
    ></UiState
  >
  <div v-if="!loading && !error">
    <article
      v-for="o in filtered"
      :key="o.id"
      class="order-card"
      :data-testid="`order-${o.id}`"
    >
      <router-link :to="`/shop/${o.shopId}`"
        ><img :src="shopImage(shops[o.shopId])" alt="店铺展示素材"
      /></router-link>
      <div class="order-main">
        <div class="order-top">
          <router-link :to="`/shop/${o.shopId}`"
            ><h3>
              {{ o.shopName || shops[o.shopId]?.name || `店铺 #${o.shopId}` }}
            </h3></router-link
          ><span
            class="pill"
            :class="
              ['CREATED', 'REDEEMED'].includes(o.status)
                ? 'orange'
                : ['PAID', 'REVIEWED'].includes(o.status)
                  ? 'green'
                  : ''
            "
            >{{ statusText[o.status] }}</span
          >
        </div>
        <p class="order-subtitle">{{ o.skuTitle || "到店套餐" }}</p>
        <div class="order-details">
          <span>订单 #{{ o.id }}</span
          ><span v-if="o.couponId">已使用优惠券</span
          ><span v-if="o.status === 'CREATED'"
            >支付截止 {{ dateTime(o.expireAt) }}</span
          ><span v-else>电子套餐券 · 单次核销</span>
        </div>
      </div>
      <div class="order-end">
        <div class="price">
          <small>订单实付</small>¥{{ money(o.priceSnapshot) }}
        </div>
        <div class="order-actions">
          <template v-if="o.status === 'CREATED'"
            ><button
              class="btn small"
              :disabled="busy === o.id"
              @click="confirmAction(o, 'cancel')"
            >
              取消订单</button
            ><button
              class="btn primary small"
              :disabled="busy === o.id"
              @click="act(o, 'pay')"
            >
              模拟支付
            </button></template
          ><template v-if="o.status === 'PAID'"
            ><button
              class="btn small"
              :disabled="busy === o.id"
              @click="confirmAction(o, 'refund')"
            >
              未核销退单</button
            ><button
              class="btn teal small"
              :disabled="busy === o.id"
              @click="confirmAction(o, 'redeem')"
            >
              到店核销
            </button></template
          ><router-link
            v-if="o.status === 'REDEEMED'"
            :to="`/orders/${o.id}/review`"
            class="btn teal small"
            ><Icon name="Sparkles" :size="13" />写评价 · AI
            帮我起草</router-link
          ><router-link
            v-if="o.status === 'REVIEWED'"
            :to="`/shop/${o.shopId}?review=${o.reviewId || ''}`"
            class="btn small"
            >查看评价 <Icon name="ArrowUpRight" :size="12" /></router-link
          ><span
            v-if="o.status.startsWith('CANCELLED') || o.status === 'REFUNDED'"
            class="muted"
            >库存与优惠券已恢复</span
          >
        </div>
      </div>
    </article>
  </div>
</template>
