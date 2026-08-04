<script setup>
// App 外壳：顶部导航（登录态 + 角色感知）+ 路由出口
// 登录态读 localStorage（非响应式），用 tick 强制在路由切换时重算
import { ref } from 'vue'
import { isLogged, myRole } from './api'

const tick = ref(0)
window.addEventListener('hashchange', () => tick.value++)

/** 退出登录：清凭证回登录页 */
function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('role')
  location.hash = '#/login'
  tick.value++
}
</script>

<template>
  <nav class="topbar" :key="tick">
    <b>探店雷达 ScoutBite</b>
    <router-link to="/map">地图</router-link>
    <router-link to="/feed">信息流</router-link>
    <router-link v-if="isLogged()" to="/agent">AI 助手</router-link>
    <router-link v-if="isLogged()" to="/orders">我的订单</router-link>
    <router-link v-if="isLogged() && myRole() === 'MERCHANT'" to="/join">入驻</router-link>
    <router-link v-if="isLogged() && myRole() === 'MERCHANT'" to="/my">我的小店</router-link>
    <router-link v-if="isLogged() && myRole() === 'MERCHANT'" to="/merchant/ai">AI 经营分析</router-link>
    <a v-if="!isLogged()" href="#/login">登录</a>
    <a v-else href="#" @click.prevent="logout">退出（{{ myRole() }}）</a>
  </nav>
  <router-view />
</template>
