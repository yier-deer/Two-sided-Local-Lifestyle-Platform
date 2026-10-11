<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import Icon from "../components/Icon.vue";
import { demoStore, agentTraces } from "../api.js";
import { session, demoLogin, askConfirm, toast } from "../session.js";
const router = useRouter();
const traces = ref(null),
  error = ref(""),
  busy = ref(false);
function go(role, path) {
  if (session.mode === "demo") {
    demoLogin(role);
    router.push(path);
  } else router.push("/login?as=" + role + "&redirect=" + path);
}
function reset() {
  askConfirm({
    title: "重置当前浏览器的演示数据？",
    text: "示例订单、评价、优惠券、入驻与草稿恢复到初始场景。真实服务数据库不会被修改。",
    confirm: "重置演示空间",
    danger: true,
    action: () => {
      demoStore.reset();
      for (const key of Object.keys(sessionStorage))
        if (key.startsWith("scoutbite-chat-demo-"))
          sessionStorage.removeItem(key);
      demoLogin();
      toast("演示空间已恢复，可以重新走完整流程");
      router.push("/discover");
    },
  });
}
async function loadTraces() {
  busy.value = true;
  error.value = "";
  try {
    traces.value = await agentTraces();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow">SCOUTBITE · DEMO WALKTHROUGH</div>
      <h1 style="margin-top: 8px">三分钟，把这件事讲明白。</h1>
      <p>一条完整消费线，一条商家行动线，让 Agent 的价值看得见。</p>
    </div>
    <span class="pill" :class="session.mode === 'demo' ? 'green' : 'blue'">{{
      session.mode === "demo" ? "当前：本地演示" : "当前：真实服务"
    }}</span>
  </div>
  <div class="demo-steps">
    <section class="demo-step">
      <span>01</span>
      <h3>发现与选择 · 约 60 秒</h3>
      <p>
        浏览附近店铺，向探店助手提问。对比推荐的理由与限制，点开引用评价核对原文。
      </p>
      <button class="btn teal small" @click="go('USER', '/agent')">
        <Icon name="Sparkles" :size="14" />进入用户推荐
      </button>
    </section>
    <section class="demo-step">
      <span>02</span>
      <h3>消费与评价 · 约 60 秒</h3>
      <p>
        领券、结算、模拟支付、到店核销。生成草稿，修改一段话，勾选确认再发布。
      </p>
      <button class="btn teal small" @click="go('USER', '/orders')">
        <Icon name="Ticket" :size="14" />进入消费闭环
      </button>
    </section>
    <section class="demo-step">
      <span>03</span>
      <h3>听见与行动 · 约 60 秒</h3>
      <p>
        切到商家，回复刚才的评价，核对经营指标。用经营助手分别展示观察、假设与建议。
      </p>
      <button class="btn teal small" @click="go('MERCHANT', '/merchant')">
        <Icon name="Store" :size="14" />进入商家工作台
      </button>
    </section>
  </div>
  <div class="mode-description">
    <section class="panel">
      <h3>本地演示 · 随时能走完整流程</h3>
      <p>
        示例数据保存在当前浏览器，不依赖 Docker
        或模型密钥。订单、领券、核销、发布和回复会实际改变示例状态，刷新后保留。Agent
        使用明确标注的固定示例输出，不能用它证明实时模型效果或并发性能。
      </p>
      <button
        class="btn small"
        style="margin-top: 20px"
        :disabled="session.mode !== 'demo'"
        @click="reset"
      >
        <Icon name="RotateCcw" :size="14" />恢复初始演示数据
      </button>
    </section>
    <section class="panel">
      <h3>真实服务 · 展示工程链路</h3>
      <p>
        顶部切换「真实服务」，登录种子账号。业务请求进入 Java 主站；Agent
        经门面读取资料。模型失败会如实报错，生成草稿不会自动发布。Java 与 Python
        服务需同时使用本次更新版本。
      </p>
      <div class="demo-links">
        <a
          href="http://localhost:8081/swagger-ui.html"
          target="_blank"
          rel="noopener noreferrer"
          >业务接口文档 <Icon name="ExternalLink" :size="12" /></a
        ><a
          href="http://localhost:8000/docs"
          target="_blank"
          rel="noopener noreferrer"
          >Agent 文档 <Icon name="ExternalLink" :size="12"
        /></a>
      </div>
    </section>
  </div>
  <section class="panel section-gap">
    <div class="section-title">
      <div>
        <h2>审核可见性，也可以当场验证</h2>
        <p>商家提交门店 → 管理员审核 → 用户发现与 Agent 候选。</p>
      </div>
      <button class="btn small" @click="go('ADMIN', '/admin')">
        <Icon name="ShieldCheck" :size="14" />进入店铺审核
      </button>
    </div>
    <div class="alert-note">
      <Icon name="Info" :size="17" /><span
        >演示使用模拟支付与演示核销，不产生真实资金。图片是展示素材。多轮记忆、跨实例草稿与图片上传属于后续扩展，当前界面不会宣称具备这些能力。</span
      >
    </div>
  </section>
  <section v-if="session.mode === 'live'" class="panel section-gap">
    <div class="section-title">
      <div>
        <h2>实时 Agent 调用记录</h2>
        <p>显示当前账号最近调用的工具、输出与时延。</p>
      </div>
      <button
        class="btn small"
        :disabled="busy || !session.token"
        @click="loadTraces"
      >
        {{ busy ? "读取中…" : "读取我的调用记录" }}
      </button>
    </div>
    <p v-if="error" class="error-state">{{ error }}</p>
    <p v-if="traces?.length === 0" class="muted">
      还没有调用记录。先完成一次真实 Agent 请求。
    </p>
    <details v-for="t in traces || []" :key="t.id" class="trace-details">
      <summary>#{{ t.id }} · {{ t.skill }} · {{ t.latencyMs }} ms</summary>
      <pre
        style="
          font-size: 11px;
          white-space: pre-wrap;
          word-break: break-word;
          line-height: 1.8;
        "
        >{{
          JSON.stringify(
            { input: t.input, tools: t.tools, output: t.output },
            null,
            2,
          )
        }}</pre>
    </details>
  </section>
</template>
