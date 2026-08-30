<script setup>
// 评价草稿页（CASDG 可视化 + 签字权闭环的后半段）：
//   ① 用户补充笔记 + 可选预设分（用户给的维度 AI 必须原样保留）
//   ② 生成草稿：AI 基于订单事实起草（引用的事实 usedFacts 全部展示——不可编造区的可视化）
//   ③ 用户可改正文 → 点击发布 = 签字（Java 门面二次校验后写库）
import { onMounted, ref } from 'vue'
import { agentReviewDraft, agentPublishDraft, myOrders } from '../api'

const props = defineProps({ orderId: String })

const note = ref('')
const prefer = ref({ taste: null, wait: null, env: null })   // 预设分（可空）
const draft = ref(null)      // {draftId, scores, content, usedFacts}
const editing = ref('')      // 用户编辑后的正文
const busy = ref(false)
const err = ref('')
const done = ref(false)

onMounted(async () => {
  // 校验该订单确实可评价（REDEEMED）——不可评的订单在这里就拦住
  try {
    const list = await myOrders({ status: 'REDEEMED' })
    if (!list.some((o) => String(o.id) === String(props.orderId))) {
      err.value = '该订单当前不可评价（需已核销且未评过）'
    }
  } catch (e) {
    err.value = e.message
  }
})

/** 生成草稿（调 Agent：Collect→Align→Draft→Gate 全链路在服务端跑） */
async function gen() {
  busy.value = true; err.value = ''
  try {
    const preferScores = {}
    for (const [k, v] of Object.entries(prefer.value)) if (v != null) preferScores[k] = Number(v)
    const data = await agentReviewDraft(Number(props.orderId), note.value || null, preferScores)
    draft.value = data
    editing.value = data.content
  } catch (e) {
    err.value = e.message   // 42201 护栏 / 50000 服务未连通 / 40903 状态不对——原样展示
  } finally {
    busy.value = false
  }
}

/** 发布 = 用户签字：门面取草稿 → ReviewService 原路二次校验 → 写库 */
async function publish() {
  busy.value = true; err.value = ''
  try {
    await agentPublishDraft(draft.value.draftId)
    done.value = true
  } catch (e) {
    err.value = e.message
  } finally {
    busy.value = false
  }
}

const dims = [['taste', '口味'], ['wait', '等位'], ['env', '环境']]
</script>

<template>
  <div class="page">
    <h2>AI 起草评价 <span class="muted" style="font-size:13px">订单 #{{ orderId }}</span></h2>
    <p class="sub">AI 只基于订单事实起草；发布必须你亲自签字——这是产品原则，不是技术妥协</p>

    <p class="msg" v-if="err">{{ err }}</p>

    <!-- ① 输入区 -->
    <div v-if="!draft && !done">
      <label>
        想补充的体验笔记（可选，主观感受 AI 可以采用）
        <textarea v-model="note" placeholder="例如：周末去的，等了大概20分钟；锅底很香但是环境有点吵"></textarea>
      </label>

      <label class="hint">预设分（可选）——你定的维度 AI 必须原样保留</label>
      <div class="score-row">
        <div class="score-cell" v-for="[k, name] in dims" :key="k">
          <div class="dim-name">{{ name }} {{ k }}</div>
          <select v-model.number="prefer[k]">
            <option :value="null">AI 定</option>
            <option v-for="n in 5" :key="n" :value="n">{{ n }}</option>
          </select>
        </div>
      </div>

      <button class="primary" @click="gen" :disabled="busy">
        {{ busy ? 'AI 起草中…' : '✨ 生成评价草稿' }}
      </button>
    </div>

    <!-- ② 草稿区：三维分 + 事实引用 + 可编辑正文 -->
    <div v-if="draft" class="draft-box">
      <h3>草稿（发布前可修改）</h3>
      <div class="score-row">
        <div class="score-cell" v-for="[k, name] in dims" :key="k">
          <div class="dim-name">{{ name }}</div>
          <div class="v">{{ draft.scores[k] ?? '-' }}</div>
        </div>
      </div>
      <div class="hint" style="margin-bottom:8px">AI 引用的订单事实（不可编造区）：</div>
      <div>
        <span class="fact-chip" v-for="(f, i) in draft.usedFacts" :key="i">{{ f }}</span>
      </div>
      <label style="margin-top:12px">正文（你可以修改）
        <textarea v-model="editing" style="min-height:110px"></textarea>
      </label>
      <button class="primary" @click="publish" :disabled="busy">
        {{ busy ? '发布中…' : '✍ 确认发布（签字）' }}
      </button>
      <p class="hint" style="margin-top:8px">
        点击发布后：服务端会再次校验订单归属与核销状态（纵深防御），草稿即刻消费——无法重复发布。
      </p>
    </div>

    <!-- ③ 完成态 -->
    <div v-if="done" class="card" style="text-align:center;padding:36px">
      <div style="font-size:34px">🎉</div>
      <h3>评价已发布</h3>
      <p class="hint">本次发布由你签字确认；AI 全程只起草、未碰数据库。</p>
      <router-link to="/orders"><button class="teal">返回我的订单</button></router-link>
    </div>
  </div>
</template>
