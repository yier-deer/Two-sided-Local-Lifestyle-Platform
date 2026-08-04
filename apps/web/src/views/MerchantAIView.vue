<script setup>
// 商家 AI 分析页：三技能（经营归因/评论诊断/竞品快照）× 观察/假设/建议三层
// - 归属校验在 Java 门面做（只能分析自己的店），前端只传 shopId
// - 护栏保证：观察句数字来自真实数据、假设必含"可能"、建议 ≤2 条——本页展示这层结构
import { onMounted, ref } from 'vue'
import { myShops, agentAnalyze, isLogged, myRole } from '../api'

const shops = ref([])
const shopId = ref(null)
const skill = ref('ops')
const result = ref(null)      // {observations, hypotheses, suggestions}
const busy = ref(false)
const err = ref('')

onMounted(async () => {
  if (!isLogged() || myRole() !== 'MERCHANT') { location.hash = '#/login'; return }
  try {
    shops.value = (await myShops()).filter((s) => s.status === 'approved')
    if (shops.value.length) shopId.value = shops.value[0].id
  } catch (e) {
    err.value = e.message
  }
})

/** 切店或切技能都重新分析 */
async function analyze() {
  if (!shopId.value) return
  busy.value = true; err.value = ''; result.value = null
  try {
    result.value = await agentAnalyze(shopId.value, skill.value)
  } catch (e) {
    err.value = e.message   // 42201 护栏拦截 / 50000 服务未连通——原样展示
  } finally {
    busy.value = false
  }
}

const skills = { ops: '经营归因', reviews: '评论诊断', competitors: '竞品快照' }
</script>

<template>
  <div class="page wide">
    <h2>AI 经营分析</h2>
    <p class="sub">只陈述数据里有的数字 · 假设必标「可能」· 相关不等于因果</p>

    <div class="toolbar">
      <label>选择店铺
        <select v-model="shopId" @change="result = null">
          <option v-for="s in shops" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </label>
      <div class="tabs" style="margin:0;flex:1">
        <button v-for="(name, k) in skills" :key="k" :class="{ on: skill === k }" @click="skill = k; result = null">
          {{ name }}
        </button>
      </div>
      <button class="teal" @click="analyze" :disabled="busy || !shopId">
        {{ busy ? '分析中…' : '开始分析' }}
      </button>
    </div>

    <p class="msg" v-if="err">{{ err }}</p>
    <div class="empty" v-if="!shops.length">你还没有已过审的店铺</div>

    <!-- 三层结果：观察（蓝）/ 假设（金）/ 建议（绿） -->
    <template v-if="result">
      <div class="layer obs">
        <span class="tag">观察 · OBSERVATION（数字均来自经营数据）</span>
        <div v-for="(o, i) in result.observations" :key="i">· {{ o }}</div>
      </div>
      <div class="layer hyp">
        <span class="tag">假设 · HYPOTHESIS（推测，已标注限定词）</span>
        <div v-for="(h, i) in result.hypotheses" :key="i">· {{ h }}</div>
      </div>
      <div class="layer sug">
        <span class="tag">建议 · SUGGESTION（可执行）</span>
        <div v-for="(s, i) in result.suggestions" :key="i">· {{ s }}</div>
      </div>
    </template>
    <div class="empty" v-else-if="!busy && shops.length">选择技能后点击「开始分析」</div>
  </div>
</template>
