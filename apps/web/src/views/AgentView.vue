<script setup>
// AI 助手页：对话式推荐（PRED 五步 + 护栏 + 诚实降级的可视化）
// - 推荐卡片必带"缺点"和 evidenceIds（护栏三查的产物，用户可见可验证）
// - 冷启动 needClarify：Agent 先问一个问题（不瞎猜）
// - toolCalls 链路展示：这次推荐 Agent 调了哪些工具（透明性）
import { nextTick, onMounted, ref } from 'vue'
import { agentRecommend, isLogged } from '../api'

const messages = ref([])          // {role:'user'|'ai', text, shops?, toolCalls?}
const input = ref('')
const busy = ref(false)
const err = ref('')
const lat = ref(null)
const lng = ref(null)
const sessionId = ref('s-' + Math.random().toString(36).slice(2, 8))
const box = ref(null)

onMounted(() => {
  if (!isLogged()) { location.hash = '#/login'; return }
  messages.value.push({
    role: 'ai',
    text: '你好，我是探店助手。告诉我你的想法，比如「今晚想吃火锅，两个人，人均100」——我会基于真实评价给你推荐 3 家对比（每家都会说缺点）。',
  })
  // 位置与地图页同源：能用浏览器定位就用（Agent 的"附近"才准确）
  navigator.geolocation?.getCurrentPosition(
    (p) => { lat.value = p.coords.latitude; lng.value = p.coords.longitude },
    () => {},
    { timeout: 3000 },
  )
})

/** 发送：调推荐接口，渲染气泡 + 店卡片 */
async function send() {
  const text = input.value.trim()
  if (!text || busy.value) return
  input.value = ''
  messages.value.push({ role: 'user', text })
  busy.value = true
  err.value = ''
  await nextTick(); box.value?.scrollTo({ top: 99999 })
  try {
    // 浏览器未定位成功时 lat/lng 为 null——后端经纬度必填（float），此时走"不带坐标"会让 Python 拒绝。
    // 解决方案：后端缺省用默认坐标（西湖东岸）；这里请求失败且没定位时，用默认坐标兜底重试一次。
    let data
    if (lat.value != null && lng.value != null) {
      data = await agentRecommend(text, lat.value, lng.value, sessionId.value)
    } else {
      data = await agentRecommend(text, 30.24, 120.15, sessionId.value)
    }
    messages.value.push({
      role: 'ai',
      text: data.answer,
      shops: data.shops || [],
      needClarify: data.needClarify,
      toolCalls: data.toolCalls || [],
    })
  } catch (e) {
    // 诚实降级可视化：50000（服务未连通）与 42201（护栏拦截）都原样展示
    messages.value.push({ role: 'ai', text: '⚠ ' + e.message })
  } finally {
    busy.value = false
    await nextTick(); box.value?.scrollTo({ top: 99999 })
  }
}
</script>

<template>
  <div class="chat-wrap">
    <h2>AI 探店助手</h2>
    <p class="sub">基于真实评价的对比推荐 · 每家必说缺点 · 推荐可溯源（引用评价 ID）</p>

    <div class="chat-box" ref="box">
      <template v-for="(m, i) in messages" :key="i">
        <div class="bubble user" v-if="m.role === 'user'">{{ m.text }}</div>
        <div class="bubble ai" v-else>
          <div>{{ m.text }}</div>

          <!-- 推荐卡片：名称/理由/缺点/引用 -->
          <div class="shop-cards" v-if="m.shops?.length">
            <div class="shop-card" v-for="s in m.shops" :key="s.id">
              <div class="name">
                <router-link :to="`/shop/${s.id}`" style="color:inherit">{{ s.name }}</router-link>
              </div>
              <div>{{ s.reason }}</div>
              <div class="cons">⚠ 缺点：{{ s.cons }}</div>
            </div>
          </div>

          <!-- 工具链透明区：这次推荐 Agent 调了哪些内部接口 -->
          <div class="toolchain" v-if="m.toolCalls?.length">
            工具链：{{ m.toolCalls.join(' → ') }}
          </div>
        </div>
      </template>
      <div class="thinking" v-if="busy">AI 正在检索与对比（约 3~5 秒）…</div>
    </div>

    <p class="msg" v-if="err">{{ err }}</p>

    <div class="chat-input">
      <input
        v-model="input"
        placeholder="例如：想和朋友吃顿辣的火锅，人均 120 以内"
        @keyup.enter="send"
        :disabled="busy"
      />
      <button class="teal" @click="send" :disabled="busy || !input.trim()">发送</button>
    </div>
    <p class="hint" style="margin-top:10px">
      AI 只能读店铺与评价数据，不能替你下单或发布任何内容——写操作永远需要你亲自确认。
    </p>
  </div>
</template>
