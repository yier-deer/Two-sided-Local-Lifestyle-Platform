<script setup>
import { computed, onMounted, ref, watch } from "vue";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import { myShops, shopReviews, replyReview } from "../api.js";
import { toast, ui } from "../session.js";
import { dateTime, chooseMerchantShop } from "../domain.js";
const shops = ref([]),
  selected = ref(null),
  reviews = ref([]),
  loading = ref(true),
  error = ref(""),
  tab = ref("all"),
  replies = ref({}),
  busy = ref(null);
const pending = computed(() =>
  reviews.value.filter((r) => !(r.replies || []).some((p) => p.isMerchant)),
);
const visible = computed(() =>
  tab.value === "pending" ? pending.value : reviews.value,
);
async function load() {
  loading.value = true;
  error.value = "";
  try {
    shops.value = (await myShops()).filter((s) => s.status === "approved");
    if (!selected.value)
      selected.value = chooseMerchantShop(shops.value, ui.merchantShopId);
    if (selected.value) reviews.value = await shopReviews(selected.value);
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
async function reply(r) {
  if (busy.value !== null) return;
  const text = replies.value[r.id]?.trim();
  if (!text) return;
  busy.value = r.id;
  try {
    await replyReview(r.id, text);
    replies.value[r.id] = "";
    reviews.value = await shopReviews(selected.value);
    toast("回复已发布，顾客可以在店铺评价中看到");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    busy.value = null;
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
      <div class="eyebrow">LISTEN. RESPOND. IMPROVE.</div>
      <h1 style="margin-top: 8px">每一句反馈，都值得回应。</h1>
      <p>认真听见顾客体验，商家回复会在店铺评价中公开展示。</p>
    </div>
    <router-link to="/merchant/ai" class="btn teal small"
      ><Icon name="Sparkles" :size="15" />分析高频意见</router-link
    >
  </div>
  <section class="panel">
    <div class="section-title">
      <select
        v-model="selected"
        class="shop-select"
        aria-label="评价门店"
        :disabled="busy !== null"
        @change="load"
      >
        <option v-for="s in shops" :key="s.id" :value="s.id">
          {{ s.name }}
        </option></select
      ><router-link
        v-if="selected"
        :to="`/shop/${selected}`"
        class="subtle-link"
        >查看用户端店页 <Icon name="ArrowUpRight" :size="13"
      /></router-link>
    </div>
    <div class="tabs">
      <button :class="{ active: tab === 'all' }" @click="tab = 'all'">
        全部评价 {{ reviews.length }}</button
      ><button :class="{ active: tab === 'pending' }" @click="tab = 'pending'">
        等待回复 {{ pending.length }}
      </button>
    </div>
    <UiState
      :loading="loading"
      :error="error"
      :empty="!visible.length"
      title="这一页，暂时没有反馈"
      text="顾客消费后，评价会出现在这里。"
      @retry="load"
    /><template v-if="!loading && !error"
      ><article
        v-for="r in visible"
        :key="r.id"
        class="review-item"
        :data-testid="`merchant-review-${r.id}`"
      >
        <div class="review-head">
          <span class="avatar teal">{{ (r.nickname || "顾").slice(0, 1) }}</span
          ><strong>{{ r.nickname }}</strong
          ><span class="pill green">{{
            r.orderId > 0 ? "已消费" : "展示样本"
          }}</span
          ><span class="muted">{{ dateTime(r.createdAt) }} · #{{ r.id }}</span>
        </div>
        <p class="review-content">{{ r.content }}</p>
        <div class="review-score-row">
          <span>口味 {{ r.scores?.taste }} / 5</span
          ><span>等位 {{ r.scores?.wait }} / 5</span
          ><span>环境 {{ r.scores?.env }} / 5</span>
        </div>
        <div v-for="p in r.replies || []" :key="p.id" class="merchant-reply">
          <span class="pill orange" v-if="p.isMerchant">商家</span
          >{{ p.nickname }}：{{ p.content }}
        </div>
        <form class="reply-editor" @submit.prevent="reply(r)">
          <textarea
            v-model="replies[r.id]"
            :aria-label="`回复评价${r.id}`"
            placeholder="感谢真实反馈，说明具体可以改进的地方…"
            maxlength="300"
            :disabled="busy === r.id"
          ></textarea
          ><button
            type="submit"
            class="btn teal small"
            :disabled="busy !== null || !replies[r.id]?.trim()"
          >
            {{ busy === r.id ? "发布中…" : "发布商家回复" }}
          </button>
        </form>
      </article></template
    >
  </section>
</template>
