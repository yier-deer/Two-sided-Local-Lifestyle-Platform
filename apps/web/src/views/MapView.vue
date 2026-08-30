<script setup>
// 地图页（主页）：定位 → Leaflet 打点 → 附近列表按距离排
// center 是全站"我在哪"的唯一来源（Agent 复用——位置同源性）
import { onMounted, ref } from 'vue'
import { nearby, isLogged, myRole } from '../api'

const shops = ref([])
const center = ref([30.24, 120.15])     // 默认西湖东岸；浏览器定位成功则覆盖
const radius = ref(5000)
const category = ref('')
const loading = ref(false)
const err = ref('')
let map = null
let markers = []

onMounted(() => {
  initMap()
  // 浏览器定位：失败/拒绝/超时就用默认（别让定位失败卡死页面——手动选点是兜底）
  navigator.geolocation?.getCurrentPosition(
    (p) => { center.value = [p.coords.latitude, p.coords.longitude]; load() },
    () => load(),
    { timeout: 3000 },
  )
})

/** 初始化 Leaflet：OSM 免费图层，中心=默认坐标 */
function initMap() {
  map = L.map('map').setView(center.value, 13)
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap',
  }).addTo(map)
}

/** 拉取附近店并重绘打点 */
async function load() {
  loading.value = true
  err.value = ''
  try {
    shops.value = await nearby(center.value[0], center.value[1], radius.value, category.value || null)
    map.setView(center.value, 14)
    redraw()
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

/** 重绘全部打点：红圈=我，蓝点=店 */
function redraw() {
  markers.forEach((m) => map.removeLayer(m))
  markers = []
  const me = L.circleMarker(center.value, { radius: 8, color: '#d63a12', fillOpacity: 0.9 })
    .bindPopup('我在这里').addTo(map)
  markers.push(me)
  for (const s of shops.value) {
    const m = L.circleMarker([s.lat, s.lng], { radius: 6, color: '#17685a', fillOpacity: 0.8 })
      .bindPopup(`<b>${s.name}</b><br/>距离 ${s.distanceMeters} m`)
      .addTo(map)
    markers.push(m)
  }
}
</script>

<template>
  <main class="page wide">
    <h2>附近店铺</h2>

    <div class="toolbar">
      <label>半径
        <select v-model.number="radius" @change="load">
          <option :value="500">500m</option>
          <option :value="1000">1km</option>
          <option :value="3000">3km</option>
          <option :value="5000">5km</option>
        </select>
      </label>
      <label>品类
        <select v-model="category" @change="load">
          <option value="">全部</option>
          <option value="HOTPOT">火锅</option>
          <option value="COFFEE">咖啡</option>
          <option value="ENTERTAIN">玩乐</option>
        </select>
      </label>
      <button @click="load">刷新</button>
      <span class="hint">{{ loading ? '加载中…' : `共 ${shops.length} 家` }}</span>
      <span v-if="err" class="msg">{{ err }}</span>
    </div>

    <div id="map"></div>

    <ol class="shop-list">
      <li v-for="s in shops" :key="s.id">
        <b @click="$router.push(`/shop/${s.id}`)">{{ s.name }} ↗</b>
        <span class="cat">{{ { HOTPOT: '火锅', COFFEE: '咖啡', ENTERTAIN: '玩乐' }[s.category] || s.category }}</span>
        <span class="dist">{{ s.distanceMeters >= 1000 ? (s.distanceMeters / 1000).toFixed(1) + ' km' : s.distanceMeters + ' m' }}</span>
      </li>
      <li v-if="!loading && !shops.length" class="hint">这个半径内没有已过审的店，试试调大半径</li>
    </ol>

    <p class="hint" style="text-align:center;margin-top:16px">
      找店纠结？问问 <router-link to="/agent">AI 助手</router-link>——基于真实评价的对比推荐
    </p>
  </main>
</template>

<style scoped src="../style.css"></style>
