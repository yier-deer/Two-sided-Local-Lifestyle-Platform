<script setup>
import { computed, nextTick, onMounted, ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import {
  shopDetail,
  shopSkus,
  shopCoupons,
  shopReviews,
  myCoupons,
  claimCoupon,
  createOrder,
  isLogged,
} from "../api.js";
import { toast, ui } from "../session.js";
import {
  categories,
  money,
  shopImage,
  averageScore,
  dateTime,
} from "../domain.js";
const props = defineProps({ id: String });
const router = useRouter(),
  route = useRoute();
const shop = ref(null),
  skus = ref([]),
  coupons = ref([]),
  reviews = ref([]),
  mine = ref([]),
  loading = ref(true),
  error = ref(""),
  busy = ref(false);
const checkout = ref(null),
  selectedCoupon = ref(""),
  checkoutError = ref("");
let checkoutKey = "";
const eligibleCoupons = computed(() =>
  mine.value.filter(
    (c) =>
      Number(c.shopId) === Number(props.id) &&
      c.status === "UNUSED" &&
      Number(c.threshold) <= (checkout.value?.price || 0),
  ),
);
const applied = computed(() =>
  eligibleCoupons.value.find(
    (c) => String(c.id) === String(selectedCoupon.value),
  ),
);
const due = computed(() =>
  Math.max(0, (checkout.value?.price || 0) - (applied.value?.amount || 0)),
);
const rating = computed(() => averageScore(reviews.value));
async function load() {
  loading.value = true;
  error.value = "";
  try {
    [shop.value, skus.value, coupons.value, reviews.value] = await Promise.all([
      shopDetail(props.id),
      shopSkus(props.id),
      shopCoupons(props.id),
      shopReviews(props.id),
    ]);
    ui.merchantShopId = Number(props.id);
    if (isLogged()) {
      try {
        mine.value = await myCoupons();
      } catch {
        mine.value = [];
      }
    }
    await nextTick();
    if (route.query.review)
      document
        .getElementById(`review-${route.query.review}`)
        ?.scrollIntoView({ block: "center" });
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
async function claim(c) {
  if (!isLogged()) return router.push(`/login?redirect=/shop/${props.id}`);
  busy.value = true;
  try {
    await claimCoupon(c.id);
    mine.value = await myCoupons();
    coupons.value = await shopCoupons(props.id);
    toast("优惠券已放入你的券包，结算时可选择");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    busy.value = false;
  }
}
async function openCheckout(s) {
  if (!isLogged()) return router.push(`/login?redirect=/shop/${props.id}`);
  checkout.value = s;
  selectedCoupon.value = "";
  checkoutError.value = "";
  checkoutKey = crypto.randomUUID();
  try {
    mine.value = await myCoupons("UNUSED");
  } catch (e) {
    checkoutError.value = e.message;
  }
}
function couponChange() {
  checkoutKey = crypto.randomUUID();
}
async function submit() {
  if (!checkout.value || busy.value) return;
  busy.value = true;
  checkoutError.value = "";
  try {
    await createOrder(
      checkout.value.id,
      applied.value?.id || null,
      checkoutKey,
    );
    checkout.value = null;
    toast("订单已创建，请完成模拟支付");
    router.push("/orders?status=CREATED");
  } catch (e) {
    checkoutError.value = e.message;
  } finally {
    busy.value = false;
  }
}
function claimed(c) {
  return mine.value.some((u) => u.couponId === c.id);
}
onMounted(load);
</script>
<template>
  <router-link to="/discover" class="back-link"
    ><Icon name="ArrowLeft" :size="14" />返回附近发现</router-link
  ><UiState :loading="loading" :error="error" @retry="load" /><template
    v-if="shop && !loading && !error"
    ><div class="detail-gallery">
      <img
        :src="shopImage(shop)"
        :alt="`${categories[shop.category]}展示配图`"
        fetchpriority="high"
      />
      <div class="detail-secondary-photo">
        <img src="/images/restaurant.jpg" alt="餐厅环境展示素材" /><span
          >生活方式展示配图</span
        >
      </div>
    </div>
    <div class="detail-top">
      <div>
        <div class="eyebrow">A GOOD PLACE TO BE</div>
        <h1 style="margin-top: 8px">{{ shop.name }}</h1>
        <div class="detail-meta">
          <span v-if="rating" class="rating"
            ><Icon name="Star" :size="14" />{{ rating }}</span
          ><span>{{ reviews.length }} 条消费评价</span
          ><span>{{ categories[shop.category] }}</span
          ><span v-if="shop.avgPrice != null"
            >参考人均 ¥{{ shop.avgPrice }}</span
          ><span class="pill green">审核通过</span>
        </div>
        <p class="detail-description">
          {{ shop.description || "每一次到店，都值得认真体验。" }}
        </p>
        <div class="tags">
          <span v-for="tag in shop.tags || []" :key="tag">{{ tag }}</span>
        </div>
      </div>
      <router-link
        :to="`/agent?prompt=${encodeURIComponent('帮我对比' + shop.name + '附近的同类店')}`"
        class="btn teal small"
        ><Icon name="Sparkles" :size="16" />请 AI 帮我选</router-link
      >
    </div>
    <div class="detail-layout">
      <div>
        <section class="panel">
          <div class="section-title">
            <div>
              <h2>到店好套餐</h2>
              <p>先购买，到店核销后享用；未核销可申请退单。</p>
            </div>
            <span class="muted">{{ skus.length }} 个可选套餐</span>
          </div>
          <UiState
            :empty="!skus.length"
            title="套餐正在准备中"
            text="可以先看看评价，再来选一份合适的。"
          />
          <article v-for="s in skus" :key="s.id" class="sku-item">
            <img :src="shopImage(shop)" alt="套餐展示素材" />
            <div class="sku-info">
              <h3>{{ s.title }}</h3>
              <p class="muted">
                已消费 {{ s.sales }} 份 · 剩余 {{ s.stock }} 份
              </p>
              <div class="sku-price-row">
                <span class="price"><small>¥</small>{{ money(s.price) }}</span
                ><span class="pill orange">到店套餐</span>
              </div>
            </div>
            <button
              class="btn primary"
              :disabled="s.stock <= 0 || busy"
              @click="openCheckout(s)"
            >
              {{ s.stock > 0 ? "立即购买" : "已售罄" }}
            </button>
          </article>
        </section>
        <section id="reviews" class="panel section-gap">
          <div class="section-title">
            <div>
              <h2>认真体验，真实反馈</h2>
              <p>评价来自已核销消费，每一条都值得被听见。</p>
            </div>
            <span v-if="rating" class="rating"
              ><Icon name="Star" :size="14" />{{ rating }}</span
            >
          </div>
          <UiState
            :empty="!reviews.length"
            title="还没有消费评价"
            text="到店核销后，来分享你的第一手体验吧。"
          />
          <article
            v-for="r in reviews"
            :id="`review-${r.id}`"
            :key="r.id"
            class="review-item"
            :class="{
              'review-highlight': String(route.query.review) === String(r.id),
            }"
          >
            <div class="review-head">
              <span class="avatar teal">{{
                (r.nickname || "用").slice(0, 1)
              }}</span
              ><strong>{{ r.nickname || "到店用户" }}</strong
              ><span class="pill green">{{
                r.orderId > 0 ? "已消费" : "展示样本"
              }}</span
              ><span class="muted">{{ dateTime(r.createdAt) }}</span>
            </div>
            <p class="review-content">{{ r.content }}</p>
            <div class="review-score-row">
              <span>口味 {{ r.scores?.taste }} / 5</span
              ><span>等位 {{ r.scores?.wait }} / 5</span
              ><span>环境 {{ r.scores?.env }} / 5</span>
            </div>
            <div
              v-for="reply in r.replies || []"
              :key="reply.id"
              class="merchant-reply"
            >
              <span class="pill orange" v-if="reply.isMerchant">商家</span
              >{{ reply.nickname || "店铺回复" }}：{{ reply.content }}
            </div>
          </article>
        </section>
      </div>
      <aside>
        <section class="panel" style="align-self: start">
          <div class="section-title">
            <h3>领一份到店心意</h3>
            <Icon name="Ticket" :size="19" style="color: #cfa376" />
          </div>
          <p v-if="!coupons.length" class="muted">暂时没有可领优惠券</p>
          <div v-for="c in coupons" :key="c.id" class="coupon-ticket">
            <div class="amount"><small>¥</small>{{ money(c.amount) }}</div>
            <div>
              <strong>{{ c.title }}</strong>
              <p>满 {{ money(c.threshold) }} 元可用</p>
              <p>每人限 {{ c.perUserLimit || 1 }} 张</p>
            </div>
            <button
              class="btn small"
              :disabled="busy || claimed(c) || c.remaining === 0"
              @click="claim(c)"
            >
              {{
                claimed(c) ? "已领取" : c.remaining === 0 ? "领完了" : "领取"
              }}
            </button>
          </div>
        </section>
        <section
          class="panel section-gap detail-facts"
          style="align-self: start"
        >
          <h3 style="font-size: 14px; color: #648159">出发前，了解一点</h3>
          <div>
            <Icon name="MapPin" :size="16" /><span>{{
              shop.address || shop.city || "杭州 · 具体地址请与店铺确认"
            }}</span>
          </div>
          <div>
            <Icon name="Ticket" :size="16" /><span
              >电子套餐券<br />购买后在「我的订单」中核销</span
            >
          </div>
          <div>
            <Icon name="ShieldCheck" :size="16" /><span
              >未核销可退<br />已核销后，可分享消费评价</span
            >
          </div>
        </section>
      </aside>
    </div></template
  >
  <Teleport to="body"
    ><div
      v-if="checkout"
      class="modal-backdrop"
      @click.self="!busy && (checkout = null)"
    >
      <section
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="checkout-title"
      >
        <button
          class="modal-close icon-button"
          aria-label="关闭结算"
          :disabled="busy"
          @click="checkout = null"
        >
          <Icon name="X" />
        </button>
        <div class="eyebrow">A LITTLE PLAN FOR A GOOD DAY</div>
        <h2 id="checkout-title" style="margin-top: 10px">确认这份到店计划</h2>
        <div class="checkout-sku">
          <img :src="shopImage(shop)" alt="店铺展示素材" />
          <div>
            <h3>{{ checkout.title }}</h3>
            <p>{{ shop.name }}</p>
          </div>
        </div>
        <label
          >使用优惠券<select
            v-model="selectedCoupon"
            aria-label="使用优惠券"
            @change="couponChange"
          >
            <option value="">不使用优惠券</option>
            <option
              v-for="c in eligibleCoupons"
              :key="c.id"
              :value="String(c.id)"
            >
              {{ c.title }} · 满 {{ money(c.threshold) }} 减
              {{ money(c.amount) }}
            </option>
          </select></label
        >
        <p class="form-help">
          {{
            eligibleCoupons.length
              ? "只展示属于本店且满足门槛的可用券。"
              : "暂无满足本套餐门槛的券，可先关闭结算领取。"
          }}
        </p>
        <div class="checkout-summary">
          <div>
            <span>套餐金额</span><span>¥{{ money(checkout.price) }}</span>
          </div>
          <div>
            <span>优惠券抵扣</span
            ><span>− ¥{{ money(applied?.amount || 0) }}</span>
          </div>
          <div>
            <strong>待支付合计</strong
            ><span class="price"><small>¥</small>{{ money(due) }}</span>
          </div>
        </div>
        <div class="consumption-flow">
          创建订单<Icon name="ChevronRight" :size="12" />模拟支付<Icon
            name="ChevronRight"
            :size="12"
          />到店核销<Icon name="ChevronRight" :size="12" />评价
        </div>
        <p
          v-if="checkoutError"
          class="error-state"
          style="font-size: 12px; margin-top: 14px"
        >
          {{ checkoutError }}
        </p>
        <button
          class="btn primary full"
          style="margin-top: 20px"
          :disabled="busy"
          @click="submit"
        >
          {{ busy ? "正在创建订单…" : "提交订单"
          }}<Icon name="ArrowRight" :size="16" />
        </button>
        <p class="form-help" style="text-align: center; margin-top: 12px">
          本项目使用模拟支付，不产生真实资金交易。
        </p>
      </section>
    </div></Teleport
  >
</template>
