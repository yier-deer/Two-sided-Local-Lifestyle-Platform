<script setup>
// 商家入驻页：填资料 → 提交审核（pending）
import { ref } from 'vue'
import { createShop, isLogged } from '../api'

const name = ref('')
const category = ref('HOTPOT')
const lat = ref(30.25)
const lng = ref(120.16)
const msg = ref('')
const ok = ref(false)

async function submit() {
  msg.value = ''
  try {
    const r = await createShop({
      name: name.value,
      category: category.value,
      lat: Number(lat.value),
      lng: Number(lng.value),
    })
    ok.value = true
    msg.value = `已提交（店铺ID=${r.id}），等待管理员审核`
  } catch (e) {
    msg.value = e.message
    if (!isLogged()) msg.value = '请先登录商家账号（' + msg.value + '）'
  }
}
</script>

<template>
  <main class="page">
    <h2>商家入驻</h2>
    <p v-if="!isLogged()" class="hint">需要商家账号：<a href="#/login">先登录/注册（选商家角色）</a></p>

    <label>店名 <input v-model="name" placeholder="如：椒麻火锅·湖滨店" /></label>
    <label>品类
      <select v-model="category">
        <option value="HOTPOT">火锅</option>
        <option value="COFFEE">咖啡</option>
        <option value="ENTERTAIN">玩乐</option>
      </select>
    </label>
    <label>纬度 lat <input v-model.number="lat" type="number" step="0.0001" /></label>
    <label>经度 lng <input v-model.number="lng" type="number" step="0.0001" /></label>
    <p class="hint">坐标可先在地图页看大概范围手填（对接级实现；坐标拾取器不做）</p>

    <button class="primary" @click="submit">提交审核</button>
    <p v-if="msg" :class="ok ? 'ok' : 'msg'">{{ msg }}</p>
    <p class="hint"><a href="#/my">去「我的小店」看审核状态</a></p>
  </main>
</template>

<style scoped src="../style.css"></style>
