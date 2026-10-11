<script setup>
import Icon from "./Icon.vue";
defineProps({
  loading: Boolean,
  error: String,
  empty: Boolean,
  title: { type: String, default: "这里还没有内容" },
  text: String,
});
defineEmits(["retry"]);
</script>
<template>
  <div v-if="loading" class="loading-state" role="status">
    <Icon name="LoaderCircle" class="spin" /> 正在为你准备…
  </div>
  <div v-else-if="error" class="error-state" role="alert">
    <Icon name="Info" />
    <div>
      <strong>暂时没能完成这一步</strong>
      <p>{{ error }}</p>
    </div>
    <button class="btn small" @click="$emit('retry')">重试</button>
  </div>
  <div v-else-if="empty" class="empty-state">
    <div class="empty-symbol"><Icon name="Compass" :size="30" /></div>
    <h3>{{ title }}</h3>
    <p>{{ text }}</p>
    <slot />
  </div>
</template>
