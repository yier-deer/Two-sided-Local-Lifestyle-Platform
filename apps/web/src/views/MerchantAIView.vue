<script setup>
import { onMounted, ref, watch } from "vue";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import { myShops, agentAnalyze } from "../api.js";
import { session, ui } from "../session.js";
import { chooseMerchantShop } from "../domain.js";
const shops = ref([]),
  selected = ref(null),
  skill = ref("ops"),
  result = ref(null),
  loading = ref(true),
  busy = ref(false),
  error = ref("");
const skills = {
  ops: {
    name: "读懂经营数据",
    text: "观察订单与收入，寻找需要验证的经营假设。",
    icon: "TrendingUp",
  },
  reviews: {
    name: "听见顾客反馈",
    text: "了解评价里的高频意见，找到可改善的体验。",
    icon: "MessageSquare",
  },
  competitors: {
    name: "了解附近同行",
    text: "基于公开店铺资料，查看同类店的差异。",
    icon: "Compass",
  },
};
async function load() {
  loading.value = true;
  error.value = "";
  try {
    shops.value = (await myShops()).filter((s) => s.status === "approved");
    selected.value = chooseMerchantShop(shops.value, ui.merchantShopId);
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
async function analyze() {
  if (!selected.value || busy.value) return;
  const requestedShop = Number(selected.value),
    requestedSkill = skill.value;
  busy.value = true;
  error.value = "";
  result.value = null;
  try {
    const data = await agentAnalyze(requestedShop, requestedSkill);
    if (
      Number(selected.value) === requestedShop &&
      skill.value === requestedSkill
    )
      result.value = data;
  } catch (e) {
    error.value = e.message;
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
      <div class="eyebrow">INSIGHT BEFORE ACTION</div>
      <h1 style="margin-top: 8px">经营里的下一步，有据可循。</h1>
      <p>把观察、假设与建议分开说清楚，决定权留给你。</p>
    </div>
    <span class="pill green">{{
      session.mode === "demo" ? "本地示例 · 未调用模型" : "本店业务数据"
    }}</span>
  </div>
  <UiState
    :loading="loading"
    :empty="!shops.length && !error"
    title="先让你的小店被看见"
    text="入驻并通过审核后，即可使用经营分析。"
    @retry="load"
    ><router-link to="/join" class="btn primary small"
      >提交入驻</router-link
    ></UiState
  ><template v-if="!loading && shops.length"
    ><div class="panel" style="margin-bottom: 22px">
      <label style="font-size: 11px; color: #93a382"
        >选择分析的门店<select
          v-model="selected"
          :disabled="busy"
          class="shop-select"
          style="display: block; margin-top: 10px"
          @change="result = null"
        >
          <option v-for="s in shops" :key="s.id" :value="s.id">
            {{ s.name }}
          </option>
        </select></label
      >
    </div>
    <div class="skill-options">
      <button
        v-for="(s, key) in skills"
        :key="key"
        class="skill-option"
        :class="{ active: skill === key }"
        :disabled="busy"
        @click="
          skill = key;
          result = null;
        "
      >
        <Icon :name="s.icon" :size="23" />
        <h3>{{ s.name }}</h3>
        <p>{{ s.text }}</p>
      </button>
    </div>
    <button class="btn teal" :disabled="busy" @click="analyze">
      <Icon
        :name="busy ? 'LoaderCircle' : 'Sparkles'"
        :class="{ spin: busy }"
        :size="17"
      />{{ busy ? "正在读取数据并核对分析…" : "开始分析这家店" }}</button
    ><UiState :error="error" style="margin-top: 20px" @retry="analyze" />
    <div v-if="result" class="analysis-layers">
      <section class="analysis-layer">
        <span><Icon name="Eye" :size="16" />01 · 观察 · 数据里看到了什么</span>
        <p v-for="(line, i) in result.observations" :key="i">{{ line }}</p>
        <p v-if="!result.observations?.length">
          目前数据不足，暂时无法形成可靠观察。
        </p>
      </section>
      <section class="analysis-layer hypothesis">
        <span
          ><Icon name="CircleHelp" :size="16" />02 · 假设 ·
          可能的原因，仍需验证</span
        >
        <p v-for="(line, i) in result.hypotheses" :key="i">{{ line }}</p>
      </section>
      <section class="analysis-layer suggestion">
        <span
          ><Icon name="CheckCircle2" :size="16" />03 · 建议 ·
          可以尝试的下一步</span
        >
        <p v-for="(line, i) in result.suggestions" :key="i">{{ line }}</p>
        <router-link
          to="/merchant/reviews"
          class="subtle-link"
          style="margin-top: 14px"
          >先去听听顾客的反馈 <Icon name="ArrowRight" :size="14"
        /></router-link>
      </section>
      <details v-if="result.toolCalls?.length" class="trace-details">
        <summary>查看本次使用的数据工具</summary>
        <code v-for="tool in result.toolCalls" :key="tool">{{ tool }}</code>
      </details>
    </div>
    <div v-else-if="!busy && !error" class="alert-note section-gap">
      <Icon name="Info" :size="17" /><span
        >分析只读取你的门店数据与公开竞品资料。建议不会自动改价、发券或发布回复，需要你亲自操作。</span
      >
    </div></template
  ><UiState v-if="error && !shops.length" :error="error" @retry="load" />
</template>
