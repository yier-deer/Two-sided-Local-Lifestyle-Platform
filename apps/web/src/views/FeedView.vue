<script setup>
// 信息流页：scene 三队列（nearby/hot/new）+ explore 探索开关同屏对比
// - explore 开关是请求级参数：新店（7日内过审）×2 加成——关掉后新店下沉
// - 每条内容带 score：开关切换时分数变化肉眼可见（演示"探索位"的效果）
import { onMounted, ref } from 'vue'
import { feed } from '../api'

const scene = ref('hot')
const explore = ref(true)
const items = ref([])
const loading = ref(false)
const err = ref('')

onMounted(load)

/** 拉信息流（游客可看） */
async function load() {
  loading.value = true
  err.value = ''
  try {
    items.value = await feed(scene.value, null, null, explore.value, 20)
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

function switchScene(s) { scene.value = s; load() }
function toggleExplore() { explore.value = !explore.value; load() }

const sceneName = { nearby: '附近', hot: '热门', new: '新店' }
</script>

<template>
  <div class="page wide">
    <h2>信息流</h2>
    <p class="sub">三队列 × 探索开关 —— 开启探索后新店获得曝光加成（score ×2）</p>

    <div class="tabs">
      <button v-for="(name, s) in sceneName" :key="s" :class="{ on: scene === s }" @click="switchScene(s)">
        {{ name }}
      </button>
    </div>

    <label class="explore-toggle" style="margin:6px 0 14px">
      <input type="checkbox" :checked="explore" @change="toggleExplore" />
      探索模式（新店加成）{{ explore ? '· 开' : '· 关' }}
    </label>

    <p class="msg" v-if="err">{{ err }}</p>
    <p class="hint" v-if="loading">加载中…</p>
    <div class="empty" v-if="!loading && !items.length">这个队列暂时没有内容</div>

    <div class="card feed-item" v-for="(it, i) in items" :key="i">
      <div class="head">
        <router-link v-if="it.shopId" :to="`/shop/${it.shopId}`" style="font-weight:700;font-size:14.5px">
          {{ it.shopName }}
        </router-link>
        <span v-else style="font-weight:700">社区分享</span>
        <span class="cat" v-if="it.isNew">新店</span>
        <span class="muted" style="flex:1"></span>
        <span class="score" v-if="it.score != null">score {{ it.score }}</span>
      </div>
      <div class="content">
        <span v-if="it.contentType === 'REVIEW' && it.content?.scores">
          口味{{ it.content.scores.taste ?? '-' }} / 等位{{ it.content.scores.wait ?? '-' }} / 环境{{ it.content.scores.env ?? '-' }} ·
        </span>
        {{ it.content?.text }}
      </div>
    </div>
  </div>
</template>
