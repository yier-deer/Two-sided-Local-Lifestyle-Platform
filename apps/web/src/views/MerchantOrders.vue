<script setup>
import { computed, onMounted, ref } from "vue";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import { myShops, merchantOrders, merchantRedeem } from "../api.js";
import { money, statusText, dateTime } from "../domain.js";
import { askConfirm, toast } from "../session.js";
const shops = ref([]),
  orders = ref([]),
  selected = ref(""),
  tab = ref(""),
  search = ref(""),
  loading = ref(true),
  error = ref(""),
  busy = ref(null);
const filtered = computed(() =>
  orders.value.filter(
    (o) =>
      (!selected.value || o.shopId === Number(selected.value)) &&
      (!tab.value || o.status === tab.value) &&
      (!search.value.trim() ||
        `${o.id} ${o.nickname} ${o.skuTitle}`.includes(search.value.trim())),
  ),
);
async function load() {
  loading.value = true;
  error.value = "";
  try {
    [shops.value, orders.value] = await Promise.all([
      myShops(),
      merchantOrders(),
    ]);
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
function redeem(o) {
  askConfirm({
    title: "确认顾客已到店消费？",
    text: `${o.nickname || "顾客"}的「${o.skuTitle}」，订单 #${o.id}。核销后将记入消费销量，顾客可评价，不能再退款。`,
    confirm: "确认核销",
    action: async () => {
      busy.value = o.id;
      try {
        await merchantRedeem(o.id);
        toast("核销完成，欢迎顾客分享消费评价");
        await load();
      } finally {
        busy.value = null;
      }
    },
  });
}
onMounted(load);
</script>
<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow">EVERY VISIT COUNTS</div>
      <h1 style="margin-top: 8px">接待每一份到店计划</h1>
      <p>核对订单，确认到店消费。只有自有门店的已支付订单可以核销。</p>
    </div>
    <button class="btn small" @click="load">
      <Icon name="RotateCcw" :size="14" />刷新
    </button>
  </div>
  <section class="panel">
    <div class="section-title" style="flex-wrap: wrap">
      <select v-model="selected" class="shop-select" aria-label="订单门店">
        <option value="">全部自有门店</option>
        <option v-for="s in shops" :key="s.id" :value="s.id">
          {{ s.name }}
        </option>
      </select>
      <div style="position: relative; width: 235px; max-width: 100%">
        <input
          v-model="search"
          aria-label="搜索订单"
          placeholder="搜索订单号、顾客或套餐"
          style="font-size: 11px; padding: 9px 12px"
        />
      </div>
    </div>
    <div class="tabs">
      <button
        v-for="(name, key) in {
          '': '全部订单',
          PAID: '待核销',
          REDEEMED: '已核销',
          REVIEWED: '已评价',
          REFUNDED: '已退款',
        }"
        :key="key"
        :class="{ active: tab === key }"
        @click="tab = key"
      >
        {{ name }}
      </button>
    </div>
    <UiState
      :loading="loading"
      :error="error"
      :empty="!filtered.length"
      title="这里暂时没有订单"
      text="换个门店或订单状态，也可以邀请用户体验一份到店套餐。"
      @retry="load"
    />
    <div v-if="!loading && !error && filtered.length" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>订单 / 套餐</th>
            <th>到店顾客</th>
            <th>实付</th>
            <th>状态</th>
            <th>接待操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in filtered" :key="o.id">
            <td>
              <strong>{{ o.skuTitle }}</strong>
              <div class="table-secondary">{{ o.shopName }} · #{{ o.id }}</div>
              <div class="table-secondary">{{ dateTime(o.createdAt) }}</div>
            </td>
            <td>{{ o.nickname || `用户 #${o.userId}` }}</td>
            <td style="color: #b9824f; font-weight: 600">
              ¥{{ money(o.priceSnapshot) }}
            </td>
            <td>
              <span
                class="pill"
                :class="o.status === 'PAID' ? 'orange' : 'green'"
                >{{ statusText[o.status] }}</span
              >
            </td>
            <td>
              <button
                v-if="o.status === 'PAID'"
                class="btn teal small"
                :disabled="busy === o.id"
                @click="redeem(o)"
              >
                <Icon name="CheckCircle2" :size="13" />确认核销</button
              ><router-link
                v-else-if="o.status === 'REVIEWED'"
                :to="`/shop/${o.shopId}?review=${o.reviewId}`"
                class="subtle-link"
                >查看评价 <Icon name="ArrowUpRight" :size="12" /></router-link
              ><span v-else class="muted">{{
                o.status === "REDEEMED" ? "等待顾客评价" : "无需核销"
              }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
