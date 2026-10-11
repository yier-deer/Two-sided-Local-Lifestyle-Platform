<script setup>
import { onMounted, ref } from "vue";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import { feed } from "../api.js";
import { ui, session } from "../session.js";
import { shopImage } from "../domain.js";
const scene = ref("hot"),
  explore = ref(true),
  items = ref([]),
  loading = ref(true),
  error = ref("");
async function load() {
  loading.value = true;
  error.value = "";
  try {
    items.value = await feed(
      scene.value,
      ui.location.lat,
      ui.location.lng,
      explore.value,
    );
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
function switchScene(value) {
  scene.value = value;
  load();
}
function toggle() {
  explore.value = !explore.value;
  load();
}
onMounted(load);
</script>
<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow">MOMENTS AROUND YOU</div>
      <h1 style="margin-top: 8px">把值得的瞬间，分享出来。</h1>
      <p>来自附近的消费评价，发现下一次出发的理由。</p>
    </div>
    <router-link to="/orders" class="btn small"
      ><Icon name="MessageSquare" :size="15" />分享我的体验</router-link
    >
  </div>
  <div class="feed-top">
    <div class="tabs">
      <button
        v-for="(name, key) in {
          hot: '热门推荐',
          nearby: '附近发现',
          new: '新店尝鲜',
        }"
        :key="key"
        :class="{ active: scene === key }"
        @click="switchScene(key)"
      >
        {{ name }}
      </button>
    </div>
    <div class="explore-setting">
      <button
        class="toggle-button"
        :class="{ on: explore }"
        role="switch"
        :aria-checked="explore"
        aria-label="新店探索"
        @click="toggle"
      ></button
      >发现新店 <span class="muted">{{ explore ? "已开启" : "已关闭" }}</span>
    </div>
  </div>
  <UiState
    :loading="loading"
    :error="error"
    :empty="!items.length"
    title="这一页还在等待新故事"
    text="换个场景，看看附近的其他分享。"
    @retry="load"
  />
  <div v-if="!loading && !error" class="note-grid">
    <article
      v-for="(item, i) in items"
      :key="item.contentId || i"
      class="note-card"
    >
      <component
        :is="item.shopId ? 'router-link' : 'div'"
        :to="item.shopId ? `/shop/${item.shopId}` : undefined"
        ><img
          :src="
            shopImage(
              item.shop || { image: item.image, category: item.category },
            )
          "
          alt="生活方式展示配图"
          loading="lazy"
      /></component>
      <div class="note-content">
        <span v-if="item.isNew" class="pill green" style="margin-bottom: 10px"
          >新店发现</span
        ><component
          :is="item.shopId ? 'router-link' : 'div'"
          :to="item.shopId ? `/shop/${item.shopId}` : undefined"
          ><h3>{{ item.shopName || "社区生活分享" }}</h3></component
        >
        <p>
          {{ item.content?.text || item.content || "一次值得记录的附近发现。" }}
        </p>
        <div class="note-author">
          <span class="avatar teal">{{
            (item.nickname || "探").slice(0, 1)
          }}</span
          >{{ item.nickname || "附近的体验者"
          }}<router-link v-if="item.shopId" :to="`/shop/${item.shopId}`"
            >查看店铺
            <Icon name="ArrowUpRight" :size="11" style="display: inline"
          /></router-link>
        </div>
      </div>
    </article>
  </div>
  <details class="trace-details section-gap">
    <summary>
      了解新店探索机制{{ session.mode === "demo" ? " · 当前是示例对比" : "" }}
    </summary>
    <p>
      开启后，为近期审核通过的新店增加探索权重；同店内容仍会去重。关闭后恢复基础排序，不承诺某家店必然出现。
    </p>
    <code v-for="it in items" :key="it.shopId"
      >{{ it.shopName }} · {{ it.isNew ? "新店" : "常规店" }} · 排序分
      {{ it.score }}</code
    >
  </details>
</template>
