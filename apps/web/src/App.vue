<script setup>
import { computed, ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import Icon from "./components/Icon.vue";
import {
  session,
  ui,
  logout,
  demoLogin,
  setMode,
  askConfirm,
  toast,
} from "./session.js";
const router = useRouter(),
  route = useRoute();
const mobileMenu = ref(false);
const merchant = computed(
  () =>
    route.path.startsWith("/merchant") ||
    route.path === "/my" ||
    route.path === "/join",
);
const userNav = [
  { path: "/discover", label: "发现好去处", icon: "Compass" },
  { path: "/feed", label: "探店笔记", icon: "BookOpen" },
  { path: "/agent", label: "AI 探店助手", icon: "Sparkles", ai: true },
  { path: "/orders", label: "我的订单", icon: "Ticket" },
];
const merchantNav = [
  { path: "/merchant", label: "经营概览", icon: "LayoutDashboard" },
  { path: "/merchant/orders", label: "订单核销", icon: "Receipt" },
  { path: "/merchant/catalog", label: "套餐与优惠券", icon: "ShoppingBag" },
  { path: "/merchant/reviews", label: "评价管理", icon: "MessageSquare" },
  { path: "/merchant/ai", label: "AI 经营助手", icon: "Sparkles", ai: true },
  { path: "/my", label: "店铺管理", icon: "Store" },
];
const nav = computed(() => (merchant.value ? merchantNav : userNav));
const active = (item) =>
  route.path === item.path ||
  (item.path === "/discover" && route.path.startsWith("/shop/")) ||
  (item.path === "/orders" && route.path.startsWith("/orders/"));
function portal() {
  if (session.mode === "demo") demoLogin(merchant.value ? "USER" : "MERCHANT");
  router.push(
    merchant.value
      ? "/discover"
      : session.role === "MERCHANT"
        ? "/merchant"
        : "/login?as=MERCHANT",
  );
  mobileMenu.value = false;
}
function changeMode() {
  const next = session.mode === "demo" ? "live" : "demo";
  askConfirm({
    title: next === "live" ? "连接真实业务服务？" : "进入本地演示？",
    text:
      next === "live"
        ? "将使用 shop-api 的真实账号和数据。请确认业务服务已启动；切换后需要重新登录。"
        : "使用保存在当前浏览器的示例数据。示例 Agent 不调用实时模型，可以随时重置。",
    confirm: "切换模式",
    action: () => {
      setMode(next);
      if (next === "demo") demoLogin();
      router.push(next === "demo" ? "/discover" : "/login");
      toast("已切换数据模式");
    },
  });
}
async function confirmModal() {
  const modal = ui.modal;
  modal.busy = true;
  try {
    await modal.action();
    ui.modal = null;
  } catch (e) {
    toast(e.message, "error");
    modal.busy = false;
  }
}
</script>
<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ mobileOpen: mobileMenu }">
      <router-link to="/discover" class="brand" @click="mobileMenu = false"
        ><span class="brand-mark"><Icon name="Compass" :size="26" /></span
        ><span
          ><strong
            >探店雷达<span class="brand-en">SCOUTBITE</span></strong
          ></span
        ></router-link
      >
      <p class="sidebar-caption">
        {{ merchant ? "让经营，每一步有依据" : "把好生活，探明白" }}
      </p>
      <div class="nav-group-title">
        {{ merchant ? "商家工作台" : "探索你的城市" }}
      </div>
      <nav class="main-nav" aria-label="主导航">
        <router-link
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          :class="{ active: active(item), 'ai-nav': item.ai }"
          @click="mobileMenu = false"
          ><Icon :name="item.icon" :size="20" /><span>{{ item.label }}</span
          ><span v-if="item.ai" class="tiny-pill">AI</span></router-link
        ><router-link
          v-if="session.role === 'ADMIN'"
          to="/admin"
          :class="{ active: route.path === '/admin' }"
          ><Icon name="ShieldCheck" />店铺审核</router-link
        >
      </nav>
      <div class="sidebar-bottom">
        <div class="sidebar-assistant">
          <span class="assistant-symbol"
            ><Icon name="Sparkles" :size="19" /></span
          ><strong>少一点纠结，多一点发现</strong>
          <p>
            {{
              merchant
                ? "读懂评价，把建议变成行动。"
                : "说出你的想法，好去处交给我。"
            }}
          </p>
          <router-link :to="merchant ? '/merchant/ai' : '/agent'"
            >{{ merchant ? "开始经营分析" : "问问探店助手" }}
            <Icon name="ArrowUpRight" :size="16"
          /></router-link>
        </div>
        <button class="portal-button" @click="portal">
          <Icon :name="merchant ? 'Compass' : 'Store'" :size="18" />{{
            merchant ? "返回用户端" : "进入商家中心"
          }}<Icon name="ArrowRight" :size="15" /></button
        ><router-link to="/demo" class="guide-link"
          ><Icon name="CircleHelp" :size="16" />演示导览</router-link
        >
      </div>
    </aside>
    <button
      v-if="mobileMenu"
      class="menu-backdrop"
      aria-label="关闭菜单"
      @click="mobileMenu = false"
    ></button>
    <div class="workspace">
      <header class="app-header">
        <button
          class="icon-button mobile-menu-button"
          aria-label="打开导航"
          @click="mobileMenu = !mobileMenu"
        >
          <Icon name="Menu" />
        </button>
        <div class="location-label">
          <Icon name="MapPin" :size="17" /><strong>{{
            ui.location.name
          }}</strong
          ><span class="header-divider"></span
          ><span class="header-note">{{
            merchant ? "商家中心" : "生活有趣，附近有你"
          }}</span>
        </div>
        <div class="header-actions">
          <button
            class="mode-button"
            :class="{ live: session.mode === 'live' }"
            @click="changeMode"
          >
            <span class="status-dot"></span
            >{{ session.mode === "demo" ? "本地演示" : "真实服务"
            }}<Icon name="ChevronDown" :size="13" />
          </button>
          <details v-if="session.token" class="account-menu">
            <summary>
              <span class="avatar">{{
                (session.nickname || "用").slice(0, 1)
              }}</span
              ><span class="account-name">{{
                session.nickname || "已登录"
              }}</span
              ><Icon name="ChevronDown" :size="13" />
            </summary>
            <div class="account-dropdown">
              <span class="muted">{{
                session.role === "MERCHANT"
                  ? "商家账号"
                  : session.role === "ADMIN"
                    ? "管理员账号"
                    : "用户账号"
              }}</span
              ><router-link to="/login">切换账号</router-link
              ><button
                @click="
                  logout();
                  router.push('/login');
                "
              >
                <Icon name="LogOut" :size="15" />退出登录
              </button>
            </div>
          </details>
          <router-link v-else to="/login" class="btn primary small"
            >登录 / 注册</router-link
          >
        </div>
      </header>
      <main class="page-content">
        <router-view v-slot="{ Component }"
          ><component
            :is="Component"
            :key="
              session.mode +
              ':' +
              (route.path === '/login'
                ? ''
                : session.role + ':' + session.userId) +
              ':' +
              route.path
            "
        /></router-view>
      </main>
      <footer class="app-footer">
        <span>ScoutBite · 在附近，发现生活的另一面</span
        ><span
          >{{
            session.mode === "demo"
              ? "示例数据保存在当前浏览器"
              : "当前使用真实业务数据"
          }}
          · 店铺配图为展示素材</span
        >
      </footer>
    </div>
    <div class="toast-stack" aria-live="polite">
      <div
        v-for="item in ui.toasts"
        :key="item.id"
        class="toast"
        :class="item.type"
      >
        <Icon
          :name="item.type === 'error' ? 'Info' : 'CheckCircle2'"
          :size="19"
        />{{ item.message }}
      </div>
    </div>
    <Teleport to="body"
      ><div
        v-if="ui.modal"
        class="modal-backdrop"
        @click.self="!ui.modal.busy && (ui.modal = null)"
      >
        <section
          class="modal small-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-title"
        >
          <button
            class="modal-close icon-button"
            aria-label="关闭"
            :disabled="ui.modal.busy"
            @click="ui.modal = null"
          >
            <Icon name="X" />
          </button>
          <div class="modal-symbol"><Icon name="Info" :size="25" /></div>
          <h2 id="confirm-title">{{ ui.modal.title }}</h2>
          <p>{{ ui.modal.text }}</p>
          <div class="modal-actions">
            <button
              class="btn"
              :disabled="ui.modal.busy"
              @click="ui.modal = null"
            >
              取消</button
            ><button
              class="btn"
              :class="ui.modal.danger ? 'danger' : 'primary'"
              :disabled="ui.modal.busy"
              @click="confirmModal"
            >
              {{ ui.modal.busy ? "处理中…" : ui.modal.confirm }}
            </button>
          </div>
        </section>
      </div></Teleport
    >
  </div>
</template>
