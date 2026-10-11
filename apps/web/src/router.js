import { createRouter, createWebHashHistory } from "vue-router";
import { session } from "./session.js";
import MapView from "./views/MapView.vue";
import LoginView from "./views/LoginView.vue";
import FeedView from "./views/FeedView.vue";
import AgentView from "./views/AgentView.vue";
import OrdersView from "./views/OrdersView.vue";
import ShopDetailView from "./views/ShopDetailView.vue";
import ReviewDraftView from "./views/ReviewDraftView.vue";
import MerchantDashboard from "./views/MerchantDashboard.vue";
import MerchantOrders from "./views/MerchantOrders.vue";
import MerchantCatalog from "./views/MerchantCatalog.vue";
import MerchantReviews from "./views/MerchantReviews.vue";
import MerchantAIView from "./views/MerchantAIView.vue";
import MyShopsView from "./views/MyShopsView.vue";
import JoinView from "./views/JoinView.vue";
import AdminView from "./views/AdminView.vue";
import DemoView from "./views/DemoView.vue";
const router = createRouter({
  history: createWebHashHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: "/", redirect: "/discover" },
    { path: "/map", redirect: "/discover?view=map" },
    { path: "/discover", component: MapView },
    { path: "/feed", component: FeedView },
    { path: "/login", component: LoginView },
    { path: "/shop/:id", component: ShopDetailView, props: true },
    { path: "/agent", component: AgentView, meta: { auth: true } },
    { path: "/orders", component: OrdersView, meta: { auth: true } },
    {
      path: "/orders/:orderId/review",
      component: ReviewDraftView,
      props: true,
      meta: { auth: true },
    },
    {
      path: "/merchant",
      component: MerchantDashboard,
      meta: { role: "MERCHANT" },
    },
    {
      path: "/merchant/orders",
      component: MerchantOrders,
      meta: { role: "MERCHANT" },
    },
    {
      path: "/merchant/catalog",
      component: MerchantCatalog,
      meta: { role: "MERCHANT" },
    },
    {
      path: "/merchant/reviews",
      component: MerchantReviews,
      meta: { role: "MERCHANT" },
    },
    {
      path: "/merchant/ai",
      component: MerchantAIView,
      meta: { role: "MERCHANT" },
    },
    { path: "/my", component: MyShopsView, meta: { role: "MERCHANT" } },
    { path: "/join", component: JoinView, meta: { role: "MERCHANT" } },
    { path: "/admin", component: AdminView, meta: { role: "ADMIN" } },
    { path: "/demo", component: DemoView },
    { path: "/:pathMatch(.*)*", redirect: "/discover" },
  ],
});
router.beforeEach((to) => {
  if ((to.meta.auth || to.meta.role) && !session.token)
    return {
      path: "/login",
      query: { redirect: to.fullPath, as: to.meta.role },
    };
  if (to.meta.role && session.role !== to.meta.role)
    return {
      path: "/login",
      query: { redirect: to.fullPath, as: to.meta.role },
    };
});
export default router;
