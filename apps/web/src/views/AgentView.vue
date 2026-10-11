<script setup>
import { nextTick, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import Icon from "../components/Icon.vue";
import { agentRecommend, shopReviews } from "../api.js";
import { ui, session, toast } from "../session.js";
import { evidenceRef } from "../domain.js";
const route = useRoute();
const messages = ref([]),
  input = ref(route.query.prompt || ""),
  busy = ref(false),
  thread = ref(null),
  evidence = ref(null),
  evidenceBusy = ref(false);
const prompts = [
  {
    icon: "Flame",
    title: "朋友聚餐，热辣一点",
    text: "今晚想吃火锅，两个人，人均100元以内",
  },
  {
    icon: "Coffee",
    title: "找一杯安静的咖啡",
    text: "想找一家可以看书的咖啡店，预算50元",
  },
  {
    icon: "Clapperboard",
    title: "给周末安排一点乐趣",
    text: "周末和朋友想看电影，有哪些附近好去处",
  },
  {
    icon: "Compass",
    title: "第一次来，不知道怎么选",
    text: "湖滨附近有什么适合家庭聚餐的店",
  },
];
const storageKey = `scoutbite-chat-${session.mode}-${session.userId}`;
try {
  messages.value = JSON.parse(sessionStorage.getItem(storageKey) || "[]");
} catch {
  /* Corrupted local chat can be discarded. */
}
const sessionId = "s-" + crypto.randomUUID();
async function scroll() {
  await nextTick();
  if (thread.value) thread.value.scrollTop = thread.value.scrollHeight;
}
async function send(text = input.value) {
  const value = text.trim();
  if (!value || busy.value) return;
  input.value = "";
  messages.value.push({ role: "user", text: value });
  busy.value = true;
  scroll();
  try {
    const data = await agentRecommend(
      value,
      ui.location.lat,
      ui.location.lng,
      sessionId,
    );
    messages.value.push({ role: "assistant", ...data, text: data.answer });
    sessionStorage.setItem(
      storageKey,
      JSON.stringify(messages.value.slice(-16)),
    );
  } catch (e) {
    messages.value.push({ role: "error", text: e.message });
  } finally {
    busy.value = false;
    scroll();
  }
}
async function openEvidence(value, candidates) {
  evidenceBusy.value = true;
  try {
    const ref = evidenceRef(value, candidates[0]?.id);
    let found,
      shopId = ref.shopId;
    if (/^ev-/.test(String(value)))
      found = (await shopReviews(shopId)).find((r) => r.id === ref.reviewId);
    else {
      const results = await Promise.all(
        candidates.map(async (s) => ({
          id: s.id,
          reviews: await shopReviews(s.id),
        })),
      );
      for (const item of results) {
        const r = item.reviews.find((r) => r.id === ref.reviewId);
        if (r) {
          found = r;
          shopId = item.id;
          break;
        }
      }
    }
    if (!found)
      throw new Error("这条引用暂时无法在公开评价中定位，请查看原店铺评价。");
    evidence.value = { ...found, shopId, source: value };
  } catch (e) {
    toast(e.message, "error");
  } finally {
    evidenceBusy.value = false;
  }
}
function clear() {
  messages.value = [];
  sessionStorage.removeItem(storageKey);
}
onMounted(scroll);
</script>
<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow">LESS GUESSING. MORE LIVING.</div>
      <h1 style="margin-top: 8px">好去处，一起选。</h1>
      <p>告诉我你的想法，用店铺资料和消费评价帮你做个对比。</p>
    </div>
    <button class="btn small" :disabled="busy" @click="clear">
      <Icon name="RotateCcw" :size="14" />清空记录
    </button>
  </div>
  <div class="agent-layout">
    <section class="agent-surface">
      <div class="agent-surface-head">
        <span class="agent-mark"><Icon name="Sparkles" :size="21" /></span>
        <div>
          <h3>你的探店搭子</h3>
          <p>每次提问独立检索 · 预算仅作参考</p>
        </div>
        <span class="pill green">{{
          session.mode === "demo" ? "本地示例 · 未调用模型" : "基于业务数据"
        }}</span>
      </div>
      <div ref="thread" class="agent-thread">
        <div v-if="!messages.length" class="agent-welcome">
          <span class="agent-mark"><Icon name="Sparkles" :size="29" /></span>
          <h2>今天，有什么小计划？</h2>
          <p>一顿热辣的聚餐，一杯安静的咖啡，或者一点新的乐趣。</p>
          <div class="prompt-grid">
            <button
              v-for="p in prompts"
              :key="p.title"
              class="prompt-card"
              @click="send(p.text)"
            >
              <span><Icon :name="p.icon" :size="16" />{{ p.title }}</span>
              <p>{{ p.text }}</p>
            </button>
          </div>
        </div>
        <div v-for="(m, i) in messages" :key="i" class="agent-message">
          <div v-if="m.role === 'user'" class="user-message">
            <p>{{ m.text }}</p>
          </div>
          <div v-else-if="m.role === 'error'" class="error-state" role="alert">
            <Icon name="Info" :size="18" />
            <div>
              <strong>这次没有生成推荐</strong>
              <p>{{ m.text }}</p>
              <router-link
                to="/discover"
                class="subtle-link"
                style="margin-top: 10px"
                >继续浏览附近店铺 <Icon name="ArrowRight" :size="13"
              /></router-link>
            </div>
          </div>
          <div v-else class="assistant-message">
            <div class="answer-label">
              <Icon name="Sparkles" :size="15" />探店助手
              <span v-if="m.demo" class="muted">· 示例数据</span>
            </div>
            <p>{{ m.text }}</p>
            <article
              v-for="s in m.shops || []"
              :key="s.id"
              class="agent-shop-card"
            >
              <div class="agent-shop-head">
                <h3>{{ s.name }}</h3>
                <router-link :to="`/shop/${s.id}`"
                  >看看套餐
                  <Icon name="ArrowUpRight" :size="12" style="display: inline"
                /></router-link>
              </div>
              <p>{{ s.reason }}</p>
              <p class="cons">
                留意一点 · {{ s.cons || "具体到店体验需结合时段与个人偏好。" }}
              </p>
            </article>
            <div v-if="m.evidenceIds?.length" class="evidence-buttons">
              <button
                v-for="ev in m.evidenceIds"
                :key="ev"
                :disabled="evidenceBusy"
                @click="openEvidence(ev, m.shops || [])"
              >
                <Icon name="Link" :size="11" />评价
                {{ String(ev).replace(/^ev-/, "#") }}
              </button>
            </div>
            <details v-if="m.toolCalls?.length" class="trace-details">
              <summary>查看本次检索与核对记录</summary>
              <code v-for="tool in m.toolCalls" :key="tool">{{ tool }}</code>
            </details>
          </div>
        </div>
        <div
          v-if="busy"
          class="loading-state"
          style="padding: 20px"
          role="status"
        >
          <Icon
            name="LoaderCircle"
            class="spin"
            :size="18"
          />正在查询资料，核对评论与推荐…
        </div>
      </div>
      <form class="agent-composer" @submit.prevent="send()">
        <div class="composer-row">
          <input
            v-model="input"
            aria-label="向探店助手提问"
            placeholder="说说人数、预算和口味，例如：两人吃火锅，人均100"
            :disabled="busy"
            maxlength="500"
          /><button
            class="btn teal"
            type="submit"
            aria-label="发送问题"
            :disabled="busy || !input.trim()"
          >
            <Icon name="Send" :size="17" />
          </button>
        </div>
        <p class="composer-note">
          {{
            session.mode === "demo"
              ? "本地示例使用确定性输出演示流程，不代表实时模型效果。"
              : "AI 结果供选店参考，请核对评论、套餐与实际到店信息。"
          }}
        </p>
      </form>
    </section>
    <aside>
      <section class="fact-panel">
        <h3><Icon name="ShieldCheck" :size="17" />一个靠谱搭子的坚持</h3>
        <ul class="fact-list">
          <li>
            <Icon name="Check" :size="14" />店铺来自检索，未经审核的店不会推荐。
          </li>
          <li>
            <Icon
              name="Check"
              :size="14"
            />每家都说明优点与限制，让你自己做决定。
          </li>
          <li>
            <Icon name="Check" :size="14" />引用可点开，消费评价可以逐条核对。
          </li>
          <li>
            <Icon
              name="Check"
              :size="14"
            />购买、消费确认和评价发布，始终由你操作。
          </li>
        </ul>
      </section>
      <section class="fact-panel">
        <h3>从想法，到有依据的选择</h3>
        <div class="tool-steps">
          <div
            v-for="(step, i) in [
              '理解本次需求',
              '检索附近已审核店铺',
              '查阅消费评价',
              '对比并核对引用',
            ]"
            :key="step"
            class="tool-step"
          >
            <span class="step-number">0{{ i + 1 }}</span
            >{{ step }}
          </div>
        </div>
        <p style="margin-top: 18px">
          每个问题独立处理。调整偏好时，请在新问题中再次说明人数、预算和口味。
        </p>
      </section>
    </aside>
  </div>
  <Teleport to="body"
    ><div v-if="evidence" class="modal-backdrop" @click.self="evidence = null">
      <section
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-title"
      >
        <button
          class="modal-close icon-button"
          aria-label="关闭评价证据"
          @click="evidence = null"
        >
          <Icon name="X" />
        </button>
        <div class="eyebrow">A RECOMMENDATION YOU CAN CHECK</div>
        <h2 id="evidence-title" style="margin-top: 12px">
          推荐依据，原文在这里。
        </h2>
        <div class="evidence-card">
          <span class="pill green">{{
            evidence.orderId > 0 ? "已消费评价" : "展示样本评价"
          }}</span>
          <p>{{ evidence.content }}</p>
          <span class="muted"
            >{{ evidence.nickname }} · 评价 #{{ evidence.id }}</span
          >
        </div>
        <p class="form-help">
          引用编号
          {{ evidence.source }}。这条评价是个人体验，不能保证每次到店都相同。
        </p>
        <router-link
          :to="`/shop/${evidence.shopId}?review=${evidence.id}`"
          class="btn teal full"
          style="margin-top: 22px"
          @click="evidence = null"
          >查看店铺与完整评价 <Icon name="ArrowUpRight" :size="16"
        /></router-link>
      </section></div
  ></Teleport>
</template>
