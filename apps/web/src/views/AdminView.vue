<script setup>
import { onMounted, ref } from "vue";
import Icon from "../components/Icon.vue";
import UiState from "../components/UiState.vue";
import { adminShops, approveShop, rejectShop } from "../api.js";
import { askConfirm, toast } from "../session.js";
import { categories, shopImage } from "../domain.js";
const shops = ref([]),
  status = ref("pending"),
  loading = ref(true),
  error = ref("");
async function load() {
  loading.value = true;
  error.value = "";
  try {
    shops.value = await adminShops(status.value);
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
function review(s, approved) {
  askConfirm({
    title: approved
      ? `通过「${s.name}」的入驻申请？`
      : `驳回「${s.name}」的入驻申请？`,
    text: approved
      ? "通过后，这家店会出现在附近发现与推荐候选中。请核对店铺资料后确认。"
      : "驳回后，店铺将继续对顾客隐藏。商家可以重新提交资料。",
    confirm: approved ? "通过审核" : "确认驳回",
    danger: !approved,
    action: async () => {
      await (approved ? approveShop : rejectShop)(s.id);
      toast(approved ? "审核通过，门店已公开可见" : "已驳回，门店继续保持隐藏");
      await load();
    },
  });
}
onMounted(load);
</script>
<template>
  <div class="page-intro">
    <div>
      <div class="eyebrow">A TRUSTED NEIGHBORHOOD</div>
      <h1 style="margin-top: 8px">让靠谱的门店，被看见。</h1>
      <p>入驻审核只对管理员开放；顾客与 Agent 只能发现已通过审核的店。</p>
    </div>
    <span class="pill green"><Icon name="ShieldCheck" :size="13" />管理员</span>
  </div>
  <div class="tabs">
    <button
      v-for="(name, key) in {
        pending: '等待审核',
        approved: '已通过',
        rejected: '已驳回',
      }"
      :key="key"
      :class="{ active: status === key }"
      @click="
        status = key;
        load();
      "
    >
      {{ name }}
    </button>
  </div>
  <UiState
    :loading="loading"
    :error="error"
    :empty="!shops.length"
    title="当前队列已处理完毕"
    text="新的入驻资料会在这里等待审核。"
    @retry="load"
  /><template v-if="!loading && !error"
    ><article v-for="s in shops" :key="s.id" class="merchant-shop-item">
      <img :src="shopImage(s)" alt="门店展示配图" />
      <div>
        <h3>{{ s.name }}</h3>
        <p>
          {{ categories[s.category] }} · {{ s.city || "杭州" }} · 店铺 #{{
            s.id
          }}
        </p>
        <p style="margin-top: 7px">
          {{ s.address || "地址未填写" }} · 商家 #{{ s.ownerId }}
        </p>
      </div>
      <div v-if="s.status === 'pending'" class="table-actions">
        <button class="btn small" @click="review(s, false)">驳回</button
        ><button class="btn teal small" @click="review(s, true)">
          通过审核
        </button>
      </div>
      <router-link
        v-else-if="s.status === 'approved'"
        :to="`/shop/${s.id}`"
        class="btn small"
        >查看店铺</router-link
      >
    </article></template
  >
</template>
