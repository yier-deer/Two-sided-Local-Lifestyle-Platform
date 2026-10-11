<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import {
  myOrders,
  agentReviewDraft,
  agentPublishDraft,
  createReview,
} from "../api.js";
import { session, toast } from "../session.js";
import { money } from "../domain.js";
const props = defineProps({ orderId: String });
const router = useRouter();
const order = ref(null),
  loading = ref(true),
  error = ref(""),
  generationError = ref(""),
  note = ref(""),
  scores = ref({ taste: 4, wait: 4, env: 4 }),
  draft = ref(null),
  content = ref(""),
  busy = ref(false),
  confirmed = ref(false),
  done = ref(false),
  reviewId = ref(null);
const dims = { taste: "口味体验", wait: "等位体验", env: "环境体验" };
const facts = computed(
  () =>
    draft.value?.usedFacts ||
    (order.value
      ? [
          `店铺：${order.value.shopName || "#" + order.value.shopId}`,
          `套餐：${order.value.skuTitle || "#" + order.value.skuId}`,
          `实付：${money(order.value.priceSnapshot)} 元`,
          "订单已核销",
        ]
      : []),
);
async function load() {
  loading.value = true;
  error.value = "";
  try {
    const rows = await myOrders({ unreviewed: true });
    order.value = rows.find((o) => String(o.id) === props.orderId);
    if (!order.value)
      error.value =
        "这份订单尚未核销，或已经评价过。请返回订单页确认当前状态。";
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
async function gen() {
  if (!order.value) return;
  busy.value = true;
  generationError.value = "";
  try {
    const d = await agentReviewDraft(
      Number(props.orderId),
      note.value.trim() || null,
      { ...scores.value },
    );
    draft.value = d;
    content.value = d.content;
    scores.value = { ...d.scores };
    confirmed.value = false;
  } catch (e) {
    generationError.value = e.message;
  } finally {
    busy.value = false;
  }
}
function manual() {
  draft.value = {
    manual: true,
    usedFacts: facts.value,
    scores: { ...scores.value },
  };
  content.value = note.value;
  confirmed.value = false;
  generationError.value = "";
}
async function publish() {
  if (!confirmed.value || !content.value.trim() || busy.value) return;
  busy.value = true;
  generationError.value = "";
  try {
    const data = draft.value.manual
      ? await createReview({
          orderId: Number(props.orderId),
          content: content.value.trim(),
          scores: { ...scores.value },
        })
      : await agentPublishDraft(draft.value.draftId, content.value.trim(), {
          ...scores.value,
        });
    done.value = true;
    reviewId.value = data?.id;
    toast("你的评价已发布，感谢分享认真体验");
  } catch (e) {
    generationError.value = e.message;
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <router-link to="/orders" class="back-link"
    ><Icon name="ArrowLeft" :size="14" />返回我的订单</router-link
  >
  <div class="page-intro">
    <div>
      <div class="eyebrow">YOUR EXPERIENCE. YOUR WORDS.</div>
      <h1 style="margin-top: 8px">让真实体验，被认真听见。</h1>
      <p>AI 可以帮你起草，评分与发布始终由你决定。</p>
    </div>
    <span class="pill green">{{
      session.mode === "demo" ? "本地示例 · 未调用模型" : "消费后评价"
    }}</span>
  </div>
  <UiState :loading="loading" :error="error" @retry="load" />
  <section v-if="done" class="panel success-panel">
    <span class="modal-symbol"><Icon name="CheckCircle2" :size="32" /></span>
    <h2>谢谢你，认真分享这一次。</h2>
    <p>你确认的正文和评分已发布，订单也已完成。</p>
    <div
      style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap"
    >
      <router-link
        :to="`/shop/${order.shopId}?review=${reviewId || ''}`"
        class="btn teal"
        >查看我的评价 <Icon name="ArrowUpRight" :size="15" /></router-link
      ><router-link to="/orders" class="btn">返回订单</router-link>
    </div>
  </section>
  <div v-else-if="order && !loading && !error" class="draft-layout">
    <section class="panel">
      <div class="draft-title-line">
        <Icon name="MessageSquare" :size="19" style="color: #74945d" />
        <h3>{{ order.shopName || "我的到店体验" }}</h3>
        <span class="muted">订单 #{{ orderId }}</span>
      </div>
      <div class="draft-steps">
        <span :class="{ active: !draft }"
          ><span class="step-number">01</span>补充体验</span
        ><Icon name="ChevronRight" :size="12" /><span :class="{ active: draft }"
          ><span class="step-number">02</span>核对与修改</span
        ><Icon name="ChevronRight" :size="12" /><span
          ><span class="step-number">03</span>确认发布</span
        >
      </div>
      <template v-if="!draft"
        ><label
          >这次体验，有什么想说的？<textarea
            v-model="note"
            aria-label="体验笔记"
            placeholder="例如：等位大约10分钟；套餐份量合适；环境比想象中热闹。只写你实际体验到的。"
            maxlength="500"
          ></textarea>
        </label>
        <p class="form-help">
          没有提到的体验，助手不应自行补充。你可以在草稿里删改任何一句。
        </p></template
      >
      <div class="score-row">
        <div v-for="(name, key) in dims" :key="key" class="score-cell">
          <label :for="`score-${key}`">{{ name }}</label
          ><select
            :id="`score-${key}`"
            v-model.number="scores[key]"
            :aria-label="name"
            :disabled="busy"
          >
            <option v-for="n in 5" :key="n" :value="n">
              {{ n }} 分{{ n === 5 ? " · 很满意" : n === 1 ? " · 待改善" : "" }}
            </option>
          </select>
        </div>
      </div>
      <p class="score-note">评分由你亲自设定；AI 起草时会保留你给出的分数。</p>
      <p
        v-if="generationError"
        class="error-state"
        style="margin-top: 18px; font-size: 12px"
        role="alert"
      >
        {{ generationError }}
      </p>
      <div v-if="!draft" class="stack" style="margin-top: 23px">
        <button class="btn teal full" :disabled="busy" @click="gen">
          <Icon
            :name="busy ? 'LoaderCircle' : 'Sparkles'"
            :size="16"
            :class="{ spin: busy }"
          />{{ busy ? "正在整理消费事实…" : "帮我整理成评价草稿" }}</button
        ><button class="btn ghost full" :disabled="busy" @click="manual">
          自己写，同样值得被看见
        </button>
      </div>
      <template v-else
        ><div class="divider"></div>
        <div class="section-title">
          <h3>{{ draft.manual ? "我的评价" : "先核对，再说出你的体验" }}</h3>
          <span class="pill orange">尚未发布</span>
        </div>
        <label
          >评价正文<textarea
            v-model="content"
            aria-label="评价正文"
            style="min-height: 180px"
            maxlength="500"
            :disabled="busy"
          ></textarea>
        </label>
        <p class="form-help" style="text-align: right">
          {{ content.length }} / 500 字
        </p>
        <label class="confirm-checkbox"
          ><input
            v-model="confirmed"
            aria-label="确认评价真实"
            type="checkbox"
            :disabled="busy"
          />我已核对正文与评分，确认这是我的真实体验，并同意公开发布。</label
        ><button
          class="btn primary full"
          :disabled="busy || !confirmed || !content.trim()"
          @click="publish"
        >
          <Icon name="CheckCircle2" :size="16" />{{
            busy ? "正在发布…" : "确认，发布我的评价"
          }}
        </button>
        <p class="form-help" style="text-align: center; margin-top: 12px">
          生成草稿不会发布评价；只有点击本按钮才会提交。
        </p></template
      >
    </section>
    <aside>
      <section class="fact-panel">
        <h3><Icon name="ShieldCheck" :size="17" />这次评价的事实依据</h3>
        <ul class="fact-list">
          <li v-for="fact in facts" :key="fact">
            <Icon name="Check" :size="13" />{{ fact }}
          </li>
        </ul>
        <p style="margin-top: 13px">
          事实来自本次消费记录与体验笔记，不借用他人的评价当作你的经历。
        </p>
      </section>
    </aside>
  </div>
</template>
