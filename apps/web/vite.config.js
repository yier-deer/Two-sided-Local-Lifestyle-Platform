import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vite 配置：开发服务器 5173，/api 与 /internal 统一代理到主站 8081
// 前端永远不直连 agent-api(8000)——AI 请求走主站门面，这是架构铁律
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8081',
    },
  },
})
