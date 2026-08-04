<script setup>
// 我的小店：商家看自己名下店铺与审核状态；被驳回可改资料重新提交
import { onMounted, ref } from 'vue'
import { myShops, resubmitShop, isLogged, myRole } from '../api'

const shops = ref([])
const msg = ref('')

onMounted(async () => {
  if (!isLogged()) return
  try {
    shops.value = await myShops()
  } catch (e) {
    msg.value = e.message
  }
})

async function resubmit(s) {
  msg.value = ''
  try {
    await resubmitShop(s.id, {})   // 资料不改，仅重新提交
    msg.value = `店铺「${s.name}」已重新提交待审核`
    shops.value = await myShops()
  } catch (e) {
    msg.value = e.message
  }
}

const statusText = { pending: '待审核', approved: '已过审', rejected: '已驳回' }
</script>

<template>
  <main class="page">
    <h2>我的小店</h2>
    <p v-if="!isLogged()" class="hint">请先<a href="#/login">登录</a>商家账号</p>
    <p v-else-if="myRole() !== 'MERCHANT'" class="hint">当前账号是用户角色，入驻请换商家账号（或重新注册一个）</p>

    <p v-if="msg" class="msg">{{ msg }}</p>

    <table v-if="shops.length">
      <thead><tr><th>ID</th><th>店名</th><th>品类</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="s in shops" :key="s.id">
          <td>{{ s.id }}</td>
          <td>{{ s.name }}</td>
          <td>{{ s.category }}</td>
          <td :class="s.status">{{ statusText[s.status] || s.status }}</td>
          <td>
            <button v-if="s.status === 'rejected'" @click="resubmit(s)">改资料重新提交</button>
            <span v-else class="hint">—</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="isLogged() && myRole() === 'MERCHANT'" class="hint">还没有店，<a href="#/join">去入驻</a></p>
  </main>
</template>

<style scoped src="../style.css"></style>
