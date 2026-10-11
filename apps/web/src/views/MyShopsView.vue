<script setup>
import { onMounted, ref } from "vue";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import { myShops, resubmitShop } from "../api.js";
import { shopImage, categories } from "../domain.js";
import { toast } from "../session.js";
const shops = ref([]),
  loading = ref(true),
  error = ref(""),
  busy = ref(null);
async function load() {
  loading.value = true;
  error.value = "";
  try {
    shops.value = await myShops();
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
async function resubmit(s) {
  busy.value = s.id;
  try {
    await resubmitShop(s.id, {});
    toast("已重新提交审核，请等待平台确认");
    await load();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    busy.value = null;
  }
}
onMounted(load);
</script>
<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow">A PLACE WITH YOUR NAME ON IT</div>
      <h1 style="margin-top: 8px">管理我的小店</h1>
      <p>每一间门店，都承载着一份认真经营。</p>
    </div>
    <router-link to="/join" class="btn primary small"
      ><Icon name="Plus" :size="15" />入驻新门店</router-link
    >
  </div>
  <UiState
    :loading="loading"
    :error="error"
    :empty="!shops.length"
    title="从一间小店，开始好经营"
    text="提交门店资料，通过审核后，就能被附近的人发现。"
    @retry="load"
    ><router-link to="/join" class="btn primary small"
      >提交入驻</router-link
    ></UiState
  ><template v-if="!loading && !error"
    ><article v-for="s in shops" :key="s.id" class="merchant-shop-item">
      <img :src="shopImage(s)" :alt="`${categories[s.category]}展示素材`" />
      <div>
        <h3>{{ s.name }}</h3>
        <p>
          <span
            class="pill"
            :class="
              s.status === 'approved'
                ? 'green'
                : s.status === 'rejected'
                  ? 'red'
                  : 'orange'
            "
            >{{
              {
                approved: "已通过审核",
                pending: "等待审核",
                rejected: "资料已驳回",
              }[s.status]
            }}</span
          >{{ categories[s.category] }}
        </p>
        <p style="margin-top: 7px">
          {{ s.address || s.city || "杭州" }} · 店铺 #{{ s.id }}
        </p>
      </div>
      <router-link
        v-if="s.status === 'approved'"
        :to="`/shop/${s.id}`"
        class="btn small"
        >查看店铺 <Icon name="ArrowUpRight" :size="13" /></router-link
      ><button
        v-else-if="s.status === 'rejected'"
        class="btn small"
        :disabled="busy === s.id"
        @click="resubmit(s)"
      >
        重新提交审核</button
      ><span v-else class="muted">审核通过后，顾客即可看见</span>
    </article></template
  >
</template>
