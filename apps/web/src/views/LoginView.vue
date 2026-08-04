<script setup>
// 登录/注册合一页：对接级前端，无花活
// 管理员演示账号在页面下方提示（13900000000 / admin123456）
import { ref } from 'vue'
import { login, register } from '../api'

const mode = ref('login')           // login | register
const phone = ref('')
const password = ref('')
const role = ref('USER')
const nickname = ref('')
const msg = ref('')

async function submit() {
  msg.value = ''
  try {
    if (mode.value === 'login') {
      const data = await login(phone.value, password.value)
      localStorage.setItem('token', data.token)
      localStorage.setItem('role', data.role)
      location.hash = data.role === 'MERCHANT' ? '#/my' : '#/map'
    } else {
      await register(phone.value, password.value, role.value, nickname.value)
      msg.value = '注册成功，请登录'
      mode.value = 'login'
    }
  } catch (e) {
    msg.value = e.message
  }
}
</script>

<template>
  <main class="page">
    <h2>{{ mode === 'login' ? '登录 ScoutBite' : '注册账号' }}</h2>

    <div class="tabs">
      <button :class="{ on: mode === 'login' }" @click="mode = 'login'">登录</button>
      <button :class="{ on: mode === 'register' }" @click="mode = 'register'">注册</button>
    </div>

    <label>手机号 <input v-model="phone" placeholder="13800000001" /></label>
    <label>密码 <input v-model="password" type="password" placeholder="至少 6 位" /></label>

    <template v-if="mode === 'register'">
      <label>昵称 <input v-model="nickname" placeholder="选填" /></label>
      <label>角色
        <select v-model="role">
          <option value="USER">用户（逛店下单）</option>
          <option value="MERCHANT">商家（入驻开店）</option>
        </select>
      </label>
    </template>

    <button class="primary" @click="submit">{{ mode === 'login' ? '登录' : '注册' }}</button>
    <p v-if="msg" class="msg">{{ msg }}</p>
    <p class="hint">管理员演示账号：13900000000 / admin123456（仅 Swagger 或本页登录用）</p>
    <p class="hint"><a href="#/map">先逛逛（游客模式）</a></p>
  </main>
</template>

<style scoped src="../style.css"></style>
