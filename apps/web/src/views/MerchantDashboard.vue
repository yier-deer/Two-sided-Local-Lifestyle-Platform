<script setup>
import { computed, onMounted, ref } from "vue";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import { myShops, merchantOrders, shopReviews } from "../api.js";
import { session } from "../session.js";
import { money, statusText } from "../domain.js";
const shops = ref([]),
  orders = ref([]),
  reviews = ref([]),
  loading = ref(true),
  error = ref("");
const valid = computed(() =>
  orders.value.filter((o) =>
    ["PAID", "REDEEMED", "REVIEWED"].includes(o.status),
  ),
);
const revenue = computed(() =>
  valid.value.reduce((sum, o) => sum + o.priceSnapshot, 0),
);
const waiting = computed(
  () => orders.value.filter((o) => o.status === "PAID").length,
);
const unanswered = computed(
  () =>
    reviews.value.filter((r) => !(r.replies || []).some((p) => p.isMerchant))
      .length,
);
const recent = computed(() => orders.value.slice(0, 5));
async function load() {
  loading.value = true;
  error.value = "";
  try {
    [shops.value, orders.value] = await Promise.all([
      myShops(),
      merchantOrders(),
    ]);
    const result = await Promise.all(
      shops.value
        .filter((s) => s.status === "approved")
        .map((s) => shopReviews(s.id)),
    );
    reviews.value = result.flat();
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>
<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow">WELCOME TO YOUR LITTLE BUSINESS</div>
      <h1 style="margin-top: 8px">你好，{{ session.nickname || "店长" }}。</h1>
      <p>认真做好每一次体验，也把经营的下一步看得更清楚。</p>
    </div>
    <select class="shop-select" disabled>
      <option>全部自有门店 · {{ shops.length }} 家</option>
    </select>
  </div>
  <UiState :loading="loading" :error="error" @retry="load" /><template
    v-if="!loading && !error"
    ><section class="merchant-banner">
      <div>
        <h2>好经营，从听见真实反馈开始。</h2>
        <p>
          还有 {{ unanswered }} 条消费评价等待回复，{{
            waiting
          }}
          笔订单等待到店核销。
        </p>
      </div>
      <router-link to="/merchant/ai" class="btn teal"
        ><Icon name="Sparkles" :size="16" />让 AI 帮我读懂经营</router-link
      >
    </section>
    <div class="metric-grid">
      <article class="metric-card">
        <div>
          <span>有效订单实付</span
          ><span class="metric-icon"
            ><Icon name="TrendingUp" :size="17"
          /></span>
        </div>
        <div class="metric-value">¥{{ money(revenue) }}</div>
        <p>已支付 / 已核销 / 已完成订单合计</p>
      </article>
      <article class="metric-card">
        <div>
          <span>有效订单</span
          ><span class="metric-icon"><Icon name="Receipt" :size="17" /></span>
        </div>
        <div class="metric-value">{{ valid.length }}<small>笔</small></div>
        <p>取消和退款订单不计入</p>
      </article>
      <article class="metric-card">
        <div>
          <span>等待到店核销</span
          ><span class="metric-icon"><Icon name="Ticket" :size="17" /></span>
        </div>
        <div class="metric-value">{{ waiting }}<small>笔</small></div>
        <p>顾客已支付，尚未完成消费</p>
      </article>
      <article class="metric-card">
        <div>
          <span>待回复评价</span
          ><span class="metric-icon"
            ><Icon name="MessageSquare" :size="17"
          /></span>
        </div>
        <div class="metric-value">{{ unanswered }}<small>条</small></div>
        <p>自有已审核门店的消费反馈</p>
      </article>
    </div>
    <div class="dashboard-grid">
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>最近的到店计划</h2>
            <p>掌握订单状态，做好每一次接待。</p>
          </div>
          <router-link to="/merchant/orders" class="subtle-link"
            >全部订单 <Icon name="ArrowRight" :size="13"
          /></router-link>
        </div>
        <UiState
          :empty="!recent.length"
          title="第一位顾客，正在路上"
          text="先准备好套餐与优惠券，让附近的人发现你。"
        />
        <div v-for="o in recent" :key="o.id" class="recent-order">
          <span class="avatar">{{ (o.nickname || "顾").slice(0, 1) }}</span>
          <div>
            <h4>{{ o.shopName }} · {{ o.skuTitle }}</h4>
            <p>
              {{ o.nickname || "到店顾客" }} · 订单 #{{ o.id }} · 实付 ¥{{
                money(o.priceSnapshot)
              }}
            </p>
          </div>
          <span
            class="pill"
            :class="o.status === 'PAID' ? 'orange' : 'green'"
            >{{ statusText[o.status] }}</span
          >
        </div>
      </section>
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>今天，可以做一点</h2>
            <p>从一个小动作开始，让体验更好。</p>
          </div>
        </div>
        <div class="quick-actions">
          <router-link to="/merchant/orders" class="quick-action"
            ><Icon name="Ticket" :size="21" />
            <h4>接待与核销</h4>
            <p>{{ waiting }} 笔订单待处理</p></router-link
          ><router-link to="/merchant/reviews" class="quick-action"
            ><Icon name="MessageSquare" :size="21" />
            <h4>回应顾客</h4>
            <p>{{ unanswered }} 条评价待回复</p></router-link
          ><router-link to="/merchant/catalog" class="quick-action"
            ><Icon name="ShoppingBag" :size="21" />
            <h4>准备一份好套餐</h4>
            <p>管理套餐与到店优惠</p></router-link
          ><router-link to="/merchant/ai" class="quick-action"
            ><Icon name="Sparkles" :size="21" />
            <h4>看看经营建议</h4>
            <p>让下一步更有依据</p></router-link
          >
        </div>
      </section>
    </div>
    <div class="alert-note section-gap">
      <Icon name="Info" :size="17" /><span
        >{{
          session.mode === "demo"
            ? "当前指标由浏览器内的示例订单与评价计算，操作后会更新。"
            : "当前指标由自有门店订单和公开评价计算，为累计口径。"
        }}你可以在订单与评价管理页逐条核对。</span
      >
    </div>
    <UiState
      v-if="!shops.length"
      :empty="true"
      title="让附近的人，认识你的小店"
      text="提交入驻资料，通过审核后就能出现在附近发现。"
      ><router-link to="/join" class="btn primary small"
        >提交入驻</router-link
      ></UiState
    ></template
  >
</template>
