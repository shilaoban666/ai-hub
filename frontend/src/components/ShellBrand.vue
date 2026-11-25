<template>
  <router-link to="/home" target="_blank" rel="noopener noreferrer" class="shell-brand" :title="displayName" aria-label="前往 AI Hub 前台（新标签页打开）">
    <strong>{{ displayName }}</strong>
  </router-link>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const displayName = computed(() => route.path.startsWith('/workspace') ? 'AI Hub 工作台' : 'AI Hub 管理后台')
</script>

<style scoped>
.shell-brand { display: flex; align-items: center; min-width: 0; color: #202329; text-decoration: none; }
.shell-brand strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; font-weight: 600; line-height: 20px; }
</style>
