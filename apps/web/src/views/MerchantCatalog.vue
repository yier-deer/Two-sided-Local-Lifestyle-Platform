<script setup>
import { onMounted, ref, watch } from "vue";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import {
  myShops,
  merchantSkus,
  merchantCoupons,
  addSku,
  updateSku,
  addCoupon,
} from "../api.js";
import { toast, ui } from "../session.js";
import { money, shopImage, dateTime, chooseMerchantShop } from "../domain.js";
const shops = ref([]),
  selected = ref(null),
  skus = ref([]),
  coupons = ref([]),
  tab = ref("skus"),
  loading = ref(true),
  error = ref(""),
  busy = ref(false),
  modal = ref(null),
  form = ref({}),
  formError = ref("");
async function load() {
  loading.value = true;
  error.value = "";
  try {
    shops.value = await myShops();
    if (!selected.value)
      selected.value = chooseMerchantShop(shops.value, ui.merchantShopId);
    if (selected.value)
      [skus.value, coupons.value] = await Promise.all([
        merchantSkus(selected.value),
        merchantCoupons(selected.value),
      ]);
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
function open(type, sku) {
  modal.value = { type, id: sku?.id };
  formError.value = "";
  form.value = sku
    ? { title: sku.title, price: sku.price / 100, stock: sku.stock }
    : type === "coupon"
      ? { title: "到店满减券", threshold: 100, amount: 20, total: 50 }
      : { title: "", price: 198, stock: 30 };
}
async function save() {
  busy.value = true;
  formError.value = "";
  try {
    const f = form.value,
      shopId = Number(selected.value);
    if (modal.value.type === "coupon") {
      if (Number(f.amount) >= Number(f.threshold))
        throw new Error("减免金额需要小于使用门槛");
      await addCoupon({
        shopId,
        title: f.title.trim(),
        threshold: Math.round(Number(f.threshold) * 100),
        amount: Math.round(Number(f.amount) * 100),
        total: Number(f.total),
      });
    } else {
      const body = {
        shopId,
        title: f.title.trim(),
        price: Math.round(Number(f.price) * 100),
        stock: Number(f.stock),
      };
      if (modal.value.id) await updateSku(modal.value.id, body);
      else await addSku(body);
    }
    modal.value = null;
    toast("已保存，用户端会展示最新供给");
    await load();
  } catch (e) {
    formError.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function toggle(s) {
  busy.value = true;
  try {
    await updateSku(s.id, { onSale: !s.onSale });
    toast(s.onSale ? "套餐已下架，已有订单不受影响" : "套餐已重新上架");
    await load();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    busy.value = false;
  }
}
onMounted(load);
watch(selected, (value) => {
  if (value != null) ui.merchantShopId = Number(value);
});
</script>
<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow">SOMETHING GOOD TO OFFER</div>
      <h1 style="margin-top: 8px">把一份好体验，准备好。</h1>
      <p>套餐、库存与优惠券，让附近的人有理由走进你的小店。</p>
    </div>
    <button
      class="btn primary small"
      :disabled="!selected || busy"
      @click="open(tab === 'coupons' ? 'coupon' : 'sku')"
    >
      <Icon name="Plus" :size="15" />{{
        tab === "coupons" ? "创建优惠券" : "添加套餐"
      }}
    </button>
  </div>
  <section class="panel">
    <div class="section-title">
      <select
        v-model="selected"
        class="shop-select"
        aria-label="供给门店"
        @change="load"
      >
        <option v-for="s in shops" :key="s.id" :value="s.id">
          {{ s.name }}
        </option></select
      ><span class="muted">管理自有门店</span>
    </div>
    <div class="tabs">
      <button :class="{ active: tab === 'skus' }" @click="tab = 'skus'">
        到店套餐 <span class="muted">{{ skus.length }}</span></button
      ><button :class="{ active: tab === 'coupons' }" @click="tab = 'coupons'">
        优惠券 <span class="muted">{{ coupons.length }}</span>
      </button>
    </div>
    <UiState
      :loading="loading"
      :error="error"
      :empty="!shops.length"
      title="先给你的小店一个位置"
      text="提交入驻后，即可准备自己的套餐与优惠。"
      @retry="load"
      ><router-link to="/join" class="btn primary small"
        >入驻开店</router-link
      ></UiState
    ><template v-if="!loading && !error && shops.length"
      ><template v-if="tab === 'skus'"
        ><UiState
          :empty="!skus.length"
          title="第一份好套餐，等你上架"
          text="设置清晰的套餐名称、价格与库存，让顾客安心选择。"
        />
        <div v-for="s in skus" :key="s.id" class="catalog-item">
          <img
            :src="shopImage(shops.find((x) => x.id === Number(selected)))"
            alt="套餐展示素材"
          />
          <div class="catalog-main">
            <h3>
              {{ s.title }}
              <span class="pill" :class="s.onSale ? 'green' : ''">{{
                s.onSale ? "在售" : "已下架"
              }}</span>
            </h3>
            <p>库存 {{ s.stock }} 份 · 已消费 {{ s.sales }} 份</p>
          </div>
          <span class="price">¥{{ money(s.price) }}</span
          ><button class="btn small" :disabled="busy" @click="open('sku', s)">
            编辑</button
          ><button class="btn small" :disabled="busy" @click="toggle(s)">
            {{ s.onSale ? "下架" : "上架" }}
          </button>
        </div></template
      ><template v-else
        ><UiState
          :empty="!coupons.length"
          title="给第一次到店，一份小心意"
          text="设置满减券，领取和使用情况会记录在这里。"
        />
        <div class="coupon-grid">
          <div v-for="c in coupons" :key="c.id" class="coupon-ticket">
            <div class="amount"><small>¥</small>{{ money(c.amount) }}</div>
            <div>
              <strong>{{ c.title }} · 满 {{ money(c.threshold) }}</strong>
              <p>
                已领取 {{ c.claimedCount }} / {{ c.total }} 张 · 已使用
                {{ c.usedCount }} 张
              </p>
              <p>剩余 {{ c.remaining }} 张 · 每人限领 1 张</p>
              <p>有效至 {{ dateTime(c.endAt) }}</p>
            </div>
          </div>
        </div></template
      ></template
    >
  </section>
  <Teleport to="body"
    ><div
      v-if="modal"
      class="modal-backdrop"
      @click.self="!busy && (modal = null)"
    >
      <section
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="catalog-title"
      >
        <button
          class="modal-close icon-button"
          aria-label="关闭供给编辑"
          :disabled="busy"
          @click="modal = null"
        >
          <Icon name="X" />
        </button>
        <h2 id="catalog-title">
          {{
            modal.type === "coupon"
              ? "给到店体验，一份心意。"
              : modal.id
                ? "让这份套餐，更合适。"
                : "准备一份好套餐。"
          }}
        </h2>
        <form @submit.prevent="save">
          <label class="form-field"
            >{{ modal.type === "coupon" ? "优惠券名称" : "套餐名称"
            }}<input
              v-model="form.title"
              aria-label="供给名称"
              placeholder="清晰说明这份到店心意"
              required
              maxlength="80" /></label
          ><template v-if="modal.type === 'coupon'"
            ><div class="form-grid">
              <label class="form-field"
                >使用门槛（元）<input
                  v-model.number="form.threshold"
                  type="number"
                  min="0.01"
                  step="0.01"
                  required /></label
              ><label class="form-field"
                >减免金额（元）<input
                  v-model.number="form.amount"
                  type="number"
                  min="0.01"
                  step="0.01"
                  required
              /></label>
            </div>
            <label class="form-field"
              >发行总量（张）<input
                v-model.number="form.total"
                type="number"
                min="1"
                max="100000"
                step="1"
                required
            /></label>
            <p class="form-help">
              每人限领 1 张，创建时开始生效，有效期 365 天。
            </p></template
          ><template v-else
            ><div class="form-grid">
              <label class="form-field"
                >套餐价格（元）<input
                  v-model.number="form.price"
                  type="number"
                  min="0.01"
                  max="100000"
                  step="0.01"
                  required /></label
              ><label class="form-field"
                >可售库存（份）<input
                  v-model.number="form.stock"
                  type="number"
                  min="0"
                  max="100000"
                  step="1"
                  required
              /></label>
            </div>
            <p class="form-help">
              价格以分精确存储，新套餐保存后自动上架。
            </p></template
          >
          <p
            v-if="formError"
            class="error-state"
            style="margin-top: 15px; font-size: 12px"
          >
            {{ formError }}
          </p>
          <button
            class="btn primary full"
            style="margin-top: 22px"
            :disabled="busy"
            type="submit"
          >
            {{ busy ? "保存中…" : "确认保存" }}
          </button>
        </form>
      </section>
    </div></Teleport
  >
</template>
