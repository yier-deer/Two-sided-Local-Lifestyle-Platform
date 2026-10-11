<script setup>
import { ref, onBeforeUnmount } from "vue";
import { useRoute, useRouter } from "vue-router";
import Icon from "../components/Icon.vue";
import { login, register, me } from "../api.js";
import { session, setIdentity, toast } from "../session.js";
const route = useRoute(),
  router = useRouter();
const mode = ref("login"),
  phone = ref(""),
  password = ref(""),
  role = ref(route.query.as === "MERCHANT" ? "MERCHANT" : "USER"),
  nickname = ref(""),
  busy = ref(false),
  error = ref("");
const seeds = {
  USER: ["13611110001", "user123456"],
  MERCHANT: ["13611110004", "merchant123456"],
  ADMIN: ["13900000000", "admin123456"],
};
let disposed = false;
onBeforeUnmount(() => {
  disposed = true;
});
async function submit() {
  busy.value = true;
  error.value = "";
  try {
    if (mode.value === "register") {
      await register(phone.value, password.value, role.value, nickname.value);
      mode.value = "login";
      toast("注册成功，现在可以登录");
      return;
    }
    const data = await login(phone.value, password.value);
    if (disposed) return;
    setIdentity(data);
    const identityRevision = session.revision;
    try {
      const details = await me();
      if (disposed || session.revision !== identityRevision) return;
      setIdentity(details);
    } catch (e) {
      if (disposed || e.code === "SESSION_CHANGED") return;
      /* JWT login succeeded; nickname may be unavailable. */
    }
    const redirect = route.query.redirect ? String(route.query.redirect) : null;
    const requiredRole = redirect ? router.resolve(redirect).meta.role : null;
    const compatible = !requiredRole || requiredRole === data.role;
    router.push(
      redirect && compatible
        ? redirect
        : data.role === "MERCHANT"
          ? "/merchant"
          : data.role === "ADMIN"
            ? "/admin"
            : "/discover",
    );
    toast("欢迎回来，开始发现好生活");
  } catch (e) {
    if (disposed || e.code === "SESSION_CHANGED") return;
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function quick(key) {
  [phone.value, password.value] = seeds[key];
  mode.value = "login";
  submit();
}
</script>
<template>
  <div class="login-layout">
    <section class="login-story">
      <div class="eyebrow">LIFE IS BETTER AROUND THE CORNER</div>
      <h1>生活的好去处，<br />总有你的一席。</h1>
      <p>
        发现附近的烟火气，让推荐有依据，让体验被听见。下一次出发，从这里开始。
      </p>
      <img src="/images/cafe.jpg" class="login-picture" alt="咖啡馆展示素材" />
    </section>
    <section class="login-card">
      <h2>{{ mode === "login" ? "欢迎回到探店雷达" : "遇见附近的好生活" }}</h2>
      <p>
        {{
          session.mode === "demo"
            ? "当前为本地演示 · 账号与数据保存在浏览器"
            : "当前为真实服务 · 使用业务系统账号"
        }}
      </p>
      <div class="tabs">
        <button :class="{ active: mode === 'login' }" @click="mode = 'login'">
          登录账号</button
        ><button
          :class="{ active: mode === 'register' }"
          @click="mode = 'register'"
        >
          注册新账号
        </button>
      </div>
      <form @submit.prevent="submit">
        <label class="form-field"
          >手机号<input
            v-model="phone"
            aria-label="手机号"
            type="tel"
            autocomplete="username"
            placeholder="请输入 11 位手机号"
            required
            pattern="1[0-9]{10}" /></label
        ><label class="form-field"
          >密码<input
            v-model="password"
            aria-label="密码"
            type="password"
            :autocomplete="
              mode === 'login' ? 'current-password' : 'new-password'
            "
            placeholder="请输入至少 6 位密码"
            required
            minlength="6" /></label
        ><template v-if="mode === 'register'"
          ><label class="form-field"
            >昵称<input
              v-model="nickname"
              placeholder="怎么称呼你？"
              maxlength="24" /></label
          ><label class="form-field"
            >注册身份<select v-model="role">
              <option value="USER">用户 · 发现与体验</option>
              <option value="MERCHANT">商家 · 管理我的小店</option>
            </select></label
          ></template
        >
        <p
          v-if="error"
          class="error-state"
          style="font-size: 11px"
          role="alert"
        >
          {{ error }}
        </p>
        <button type="submit" class="btn primary full" :disabled="busy">
          {{
            busy
              ? "正在处理…"
              : mode === "login"
                ? "登录，开始发现"
                : "注册账号"
          }}<Icon name="ArrowRight" :size="16" />
        </button>
      </form>
      <div class="quick-login">
        <p>答辩快捷账号 · 一键体验完整流程</p>
        <div class="quick-account-row">
          <button :disabled="busy" @click="quick('USER')">
            <Icon name="Compass" :size="13" />体验用户</button
          ><button :disabled="busy" @click="quick('MERCHANT')">
            <Icon name="Store" :size="13" />体验商家</button
          ><button :disabled="busy" @click="quick('ADMIN')">
            <Icon name="ShieldCheck" :size="13" />店铺审核
          </button>
        </div>
        <router-link
          to="/discover"
          class="subtle-link"
          style="margin-top: 19px; font-size: 10px"
          >先去逛逛 <Icon name="ArrowUpRight" :size="12"
        /></router-link>
      </div>
    </section>
  </div>
</template>
