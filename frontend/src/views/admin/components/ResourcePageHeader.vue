<template>
  <header class="resource-page-header">
    <div>
      <h1>{{ title }}</h1>
      <p v-if="description">{{ description }}</p>
    </div>
    <slot name="actions" />
  </header>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<style scoped>
.resource-page-header { min-height: 44px; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid #eceef1; }
.resource-page-header h1 { margin: 0 0 4px; color: #202328; font-size: 20px; font-weight: 650; letter-spacing: 0; }
.resource-page-header p { margin: 0; color: #747b86; font-size: 14px; }
</style>
