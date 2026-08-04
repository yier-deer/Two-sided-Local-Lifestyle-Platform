// 前端入口：挂载 Vue 应用 + 路由
import { createApp } from 'vue'
import App from './App.vue'
import router from './router.js'

createApp(App).use(router).mount('#app')
