<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import Icon from "../components/Icon.vue";
import { createShop } from "../api.js";
import { categories } from "../domain.js";
import { toast, ui } from "../session.js";
const router = useRouter();
const form = ref({
  name: "",
  category: "HOTPOT",
  city: "杭州",
  address: "",
  lat: ui.location.lat,
  lng: ui.location.lng,
});
const busy = ref(false),
  error = ref("");
async function submit() {
  busy.value = true;
  error.value = "";
  try {
    await createShop({
      ...form.value,
      name: form.value.name.trim(),
      lat: Number(form.value.lat),
      lng: Number(form.value.lng),
    });
    toast("门店资料已提交，等待平台审核");
    router.push("/my");
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <router-link to="/my" class="back-link"
    ><Icon name="ArrowLeft" :size="14" />返回店铺管理</router-link
  >
  <div class="page-intro">
    <div>
      <div class="eyebrow">LET THE NEIGHBORHOOD FIND YOU</div>
      <h1 style="margin-top: 8px">让附近的人，认识你的小店。</h1>
      <p>填写真实门店资料，审核后即可展示并进入推荐候选。</p>
    </div>
  </div>
  <div class="draft-layout">
    <section class="panel">
      <form @submit.prevent="submit">
        <label class="form-field"
          >门店名称<input
            v-model="form.name"
            aria-label="门店名称"
            placeholder="例如：蜀味里 · 湖滨店"
            required
            maxlength="80"
        /></label>
        <div class="form-grid">
          <label class="form-field"
            >生活品类<select v-model="form.category">
              <option v-for="(name, key) in categories" :key="key" :value="key">
                {{ name }}
              </option>
            </select></label
          ><label class="form-field"
            >所在城市<input v-model="form.city" placeholder="杭州" required
          /></label>
        </div>
        <label class="form-field"
          >到店地址<input
            v-model="form.address"
            aria-label="到店地址"
            placeholder="道路、门牌号及楼层，方便顾客找到你"
            required
            maxlength="200"
        /></label>
        <details class="trace-details" style="margin: 10px 0 22px">
          <summary>设置门店位置 · 当前默认湖滨商圈</summary>
          <div class="form-grid" style="margin-top: 15px">
            <label
              >纬度<input
                v-model.number="form.lat"
                type="number"
                step="0.000001"
                min="-90"
                max="90"
                required /></label
            ><label
              >经度<input
                v-model.number="form.lng"
                type="number"
                step="0.000001"
                min="-180"
                max="180"
                required
            /></label>
          </div>
          <p class="form-help">附近距离由此位置计算；可使用门店实际坐标。</p>
        </details>
        <p
          v-if="error"
          class="error-state"
          role="alert"
          style="font-size: 12px"
        >
          {{ error }}
        </p>
        <button class="btn primary full" type="submit" :disabled="busy">
          {{ busy ? "正在提交资料…" : "提交，等待审核"
          }}<Icon name="ArrowRight" :size="16" />
        </button>
      </form>
    </section>
    <aside>
      <section class="fact-panel">
        <h3><Icon name="ShieldCheck" :size="17" />入驻后会发生什么？</h3>
        <ul class="fact-list">
          <li>
            <Icon
              name="Check"
              :size="14"
            />平台审核门店资料，未通过前顾客不可见。
          </li>
          <li>
            <Icon
              name="Check"
              :size="14"
            />你可以先准备套餐、价格、库存与优惠券。
          </li>
          <li>
            <Icon name="Check" :size="14" />审核通过后出现在附近发现和 Agent
            候选中。
          </li>
          <li>
            <Icon name="Check" :size="14" />顾客消费后评价，你可以公开回复。
          </li>
        </ul>
      </section>
    </aside>
  </div>
</template>
