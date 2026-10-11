<script setup>
import { ref } from "vue";
import Icon from "./Icon.vue";
import {
  categories,
  distance,
  shopImage,
  isNewShop,
  money,
} from "../domain.js";
import { session, toast } from "../session.js";
const props = defineProps({ shop: Object });
const key = `scoutbite-saved-${session.mode}`;
const readSaved = () => {
  try {
    return JSON.parse(localStorage.getItem(key) || "[]");
  } catch {
    return [];
  }
};
const saved = ref(readSaved().includes(props.shop.id));
function toggle() {
  saved.value = !saved.value;
  const values = readSaved().filter((id) => id !== props.shop.id);
  if (saved.value) values.push(props.shop.id);
  localStorage.setItem(key, JSON.stringify(values));
  toast(saved.value ? "已收藏这家店" : "已取消收藏");
}
</script>
<template>
  <article class="shop-tile" :data-testid="`shop-card-${shop.id}`">
    <div class="tile-image-wrap">
      <router-link :to="`/shop/${shop.id}`" :aria-label="`查看${shop.name}`"
        ><img
          :src="shopImage(shop)"
          :alt="`${categories[shop.category]}展示配图`"
          class="tile-image"
          loading="lazy" /></router-link
      ><span class="photo-label">{{
        isNewShop(shop) ? "新店发现" : categories[shop.category]
      }}</span
      ><button
        class="save-button"
        :class="{ saved }"
        :aria-label="saved ? '取消收藏' : '收藏店铺'"
        :aria-pressed="saved"
        @click="toggle"
      >
        <Icon name="Heart" :size="17" />
      </button>
    </div>
    <div class="tile-body">
      <router-link :to="`/shop/${shop.id}`" class="tile-title"
        >{{ shop.name }}<Icon name="ArrowUpRight" :size="17"
      /></router-link>
      <div class="tile-rating">
        <span v-if="shop.rating" class="rating"
          ><Icon name="Star" :size="13" />{{ shop.rating }}</span
        ><span v-else class="muted">评分待积累</span
        ><span v-if="shop.reviewCount != null" class="muted"
          >{{ shop.reviewCount }} 条评价</span
        ><span class="tile-distance">{{ distance(shop.distanceMeters) }}</span>
      </div>
      <p class="tile-description">
        {{ shop.description || shop.address || "发现附近值得去的好店" }}
      </p>
      <div class="tags">
        <span
          v-for="tag in (shop.tags || [categories[shop.category]]).slice(0, 3)"
          :key="tag"
          >{{ tag }}</span
        >
      </div>
      <div class="tile-bottom">
        <span v-if="shop.avgPrice != null"
          ><b>¥{{ shop.avgPrice }}</b
          ><small> / 人参考</small></span
        ><span v-else-if="shop.minSkuPrice != null"
          ><b>¥{{ money(shop.minSkuPrice) }}</b
          ><small> 套餐起</small></span
        ><span v-else class="muted">暂无在售套餐</span
        ><router-link :to="`/shop/${shop.id}`" class="subtle-link"
          >去看看 <Icon name="ArrowRight" :size="15"
        /></router-link>
      </div>
    </div>
  </article>
</template>
