<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import Icon from "../components/Icon.vue";
import ShopCard from "../components/ShopCard.vue";
import UiState from "../components/UiState.vue";
import { nearby } from "../api.js";
import { ui, toast } from "../session.js";
import { categories, shopImage, distance } from "../domain.js";
const route = useRoute();
const shops = ref([]),
  loading = ref(true),
  error = ref(""),
  search = ref(""),
  term = ref(""),
  category = ref(""),
  sort = ref("distance"),
  radius = ref(5000);
const view = ref(route.query.view === "map" ? "map" : "list");
const visible = computed(() =>
  shops.value
    .filter(
      (s) =>
        (!category.value || s.category === category.value) &&
        (!term.value ||
          `${s.name} ${s.address || ""} ${(s.tags || []).join(" ")} ${categories[s.category]}`.includes(
            term.value,
          )),
    )
    .sort((a, b) =>
      sort.value === "rating"
        ? (b.rating || 0) - (a.rating || 0)
        : sort.value === "price"
          ? (a.minSkuPrice ??
              (a.avgPrice == null ? Infinity : a.avgPrice * 100)) -
            (b.minSkuPrice ??
              (b.avgPrice == null ? Infinity : b.avgPrice * 100))
          : a.distanceMeters - b.distanceMeters,
    ),
);
const weekends = computed(() =>
  shops.value.filter((s) => s.category === "COFFEE").slice(0, 2),
);
async function load() {
  loading.value = true;
  error.value = "";
  try {
    shops.value = await nearby(ui.location.lat, ui.location.lng, radius.value);
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
function setSearch(text = search.value) {
  search.value = text;
  term.value = text.trim();
}
function locate() {
  if (!navigator.geolocation) {
    toast("当前浏览器不支持定位，已保留湖滨商圈", "error");
    return;
  }
  loading.value = true;
  navigator.geolocation.getCurrentPosition(
    (p) => {
      ui.location = {
        lat: p.coords.latitude,
        lng: p.coords.longitude,
        name: "当前位置 · 附近",
      };
      load();
    },
    () => {
      loading.value = false;
      toast("定位未授权，已保留杭州湖滨商圈，可以继续浏览。", "error");
    },
    { timeout: 5000 },
  );
}
function pinStyle(s, index) {
  const dx = (s.lng - ui.location.lng) * 2600,
    dy = (s.lat - ui.location.lat) * -3800;
  return {
    left: `${Math.max(29, Math.min(86, 54 + (Number.isFinite(dx) ? dx : index * 10)))}%`,
    top: `${Math.max(15, Math.min(85, 53 + (Number.isFinite(dy) ? dy : index * 12)))}%`,
  };
}
onMounted(load);
</script>
<template>
  <section class="discovery-hero">
    <div class="hero-copy">
      <div class="eyebrow">EXPLORE YOUR EVERYDAY</div>
      <h1>探店雷达，<span>杭州。</span></h1>
      <p>寻一锅热辣，遇一杯咖啡。把今天过成值得分享的小日子。</p>
      <form class="hero-search" @submit.prevent="setSearch()">
        <Icon name="Search" :size="19" /><input
          v-model="search"
          aria-label="搜索店铺"
          placeholder="想去哪儿？搜店名、品类或关键词"
        /><button class="btn primary" type="submit">发现</button>
      </form>
      <div class="hero-hints">
        <span>大家都在搜</span
        ><button @click="setSearch('火锅')">朋友聚餐</button
        ><button
          @click="
            category = 'COFFEE';
            setSearch('');
          "
        >
          周末咖啡</button
        ><button
          @click="
            category = 'ENTERTAIN';
            setSearch('');
          "
        >
          约会好去处
        </button>
      </div>
    </div>
    <div class="hero-photo">
      <img
        src="/images/dining.jpg"
        alt="丰盛的一餐，生活方式展示素材"
        fetchpriority="high"
      />
      <div class="hero-photo-tag">
        <Icon name="MapPin" :size="18" /><span
          ><strong>在城市的烟火里</strong>找回生活的松弛感</span
        >
      </div>
    </div>
  </section>
  <div class="category-row">
    <button
      class="category-chip"
      :class="{ active: !category }"
      @click="
        category = '';
        setSearch('');
      "
    >
      <Icon name="Compass" />全部发现</button
    ><button
      v-for="(name, key) in categories"
      :key="key"
      class="category-chip"
      :class="{ active: category === key }"
      @click="
        category = key;
        setSearch('');
      "
    >
      <Icon
        :name="
          key === 'HOTPOT'
            ? 'Flame'
            : key === 'COFFEE'
              ? 'Coffee'
              : 'Clapperboard'
        "
      />{{ name }}
    </button>
  </div>
  <div class="discovery-body">
    <div>
      <div class="discover-toolbar">
        <h2>
          {{ term ? `“${term}”的搜索结果` : "附近值得去"
          }}<span>{{ visible.length }} 家好店，等你发现</span>
        </h2>
        <div class="sort-controls">
          <button
            :class="{ active: sort === 'distance' }"
            @click="sort = 'distance'"
          >
            离我最近</button
          ><button
            :class="{ active: sort === 'rating' }"
            @click="sort = 'rating'"
          >
            口碑优先</button
          ><button
            :class="{ active: sort === 'price' }"
            @click="sort = 'price'"
          >
            价格友好</button
          ><span></span>
          <div class="map-toggle">
            <button
              aria-label="列表视图"
              :class="{ active: view === 'list' }"
              @click="view = 'list'"
            >
              <Icon name="LayoutDashboard" :size="13" /></button
            ><button
              aria-label="附近示意图"
              :class="{ active: view === 'map' }"
              @click="view = 'map'"
            >
              <Icon name="MapPin" :size="13" />
            </button>
          </div>
        </div>
      </div>
      <UiState
        :loading="loading"
        :error="error"
        :empty="!visible.length"
        title="还没找到合适的店"
        text="试试其他关键词、品类，或扩大附近范围。"
        @retry="load"
        ><button
          class="btn small"
          @click="
            category = '';
            setSearch('');
          "
        >
          查看全部
        </button></UiState
      ><template v-if="!loading && !error"
        ><div v-if="view === 'map'" class="coordinate-map">
          <div class="map-lake">西湖</div>
          <span class="map-center"><Icon name="MapPin" :size="15" /></span
          ><router-link
            v-for="(s, i) in visible"
            :key="s.id"
            :to="`/shop/${s.id}`"
            class="map-pin"
            :style="pinStyle(s, i)"
            ><Icon name="MapPin" :size="13" />{{ s.name }} ·
            {{ distance(s.distanceMeters) }}</router-link
          ><span class="map-note">附近坐标示意 · 非街道地图</span>
        </div>
        <div class="shop-grid">
          <ShopCard v-for="shop in visible" :key="shop.id" :shop="shop" /></div
      ></template>
      <div
        class="section-gap muted"
        style="display: flex; gap: 12px; align-items: center"
      >
        <button class="subtle-link" @click="locate">
          <Icon name="MapPin" :size="14" />使用我的位置</button
        ><label
          style="display: flex; align-items: center; gap: 8px; font-size: 10px"
          >范围<select
            v-model.number="radius"
            style="width: 80px; padding: 5px; font-size: 10px; margin: 0"
            @change="load"
          >
            <option :value="1000">1 km</option>
            <option :value="3000">3 km</option>
            <option :value="5000">5 km</option>
          </select></label
        >
      </div>
    </div>
    <aside class="discovery-aside">
      <div class="ai-invite">
        <Icon name="Sparkles" :size="25" />
        <div class="eyebrow">YOUR LOCAL COMPANION</div>
        <h3>今天去哪儿？<br /><span>让灵感来找你。</span></h3>
        <p>
          告诉我人数、预算和口味偏好，帮你对比好店。优点说清楚，缺点不藏着。
        </p>
        <router-link to="/agent" class="btn"
          >和探店助手聊聊 <Icon name="ArrowUpRight" :size="15"
        /></router-link>
        <p class="ai-invite-foot">有据可查的推荐 · 由你决定下一步</p>
      </div>
      <div class="weekend-card">
        <h3>把周末留给自己 <span style="color: #cda775">✦</span></h3>
        <p>咖啡、阳光，和刚刚好的慢节奏</p>
        <router-link
          v-for="s in weekends"
          :key="s.id"
          :to="`/shop/${s.id}`"
          class="mini-place"
          ><img :src="shopImage(s)" alt="咖啡店展示素材" />
          <div>
            <strong>{{ s.name }}</strong>
            <p>
              <span v-if="s.rating" class="rating"
                ><Icon name="Star" :size="10" />{{ s.rating }}</span
              >
              · {{ distance(s.distanceMeters) }}
            </p>
          </div></router-link
        >
      </div>
      <div class="city-note">
        <strong>每一次发现，都有迹可循。</strong
        >消费后评价，让好店被看见；认真听取反馈，让生活更好一点。
      </div>
    </aside>
  </div>
</template>
