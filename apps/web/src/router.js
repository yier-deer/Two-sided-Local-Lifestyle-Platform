// router.js —— 路由表：地图 / 信息流 / AI 助手 / 订单 / 评价草稿 / 店铺详情 / 商家
import { createRouter, createWebHashHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import MapView from './views/MapView.vue'
import JoinView from './views/JoinView.vue'
import MyShopsView from './views/MyShopsView.vue'
import FeedView from './views/FeedView.vue'
import AgentView from './views/AgentView.vue'
import OrdersView from './views/OrdersView.vue'
import ReviewDraftView from './views/ReviewDraftView.vue'
import ShopDetailView from './views/ShopDetailView.vue'
import MerchantAIView from './views/MerchantAIView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/map' },
    { path: '/login', component: LoginView },
    { path: '/map', component: MapView },
    { path: '/feed', component: FeedView },
    { path: '/agent', component: AgentView },
    { path: '/orders', component: OrdersView },
    { path: '/orders/:orderId/review', component: ReviewDraftView, props: true },
    { path: '/shop/:id', component: ShopDetailView, props: true },
    { path: '/join', component: JoinView },
    { path: '/my', component: MyShopsView },
    { path: '/merchant/ai', component: MerchantAIView },
  ],
})

export default router
