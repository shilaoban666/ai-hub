<template>
  <nav class="product-mode-switch" :class="{ 'product-mode-switch--compact': compact }" aria-label="产品模式切换">
    <el-tooltip content="工作台" :placement="compact ? 'right' : 'bottom'" :enterable="false" :trigger-keys="[]">
      <router-link
        to="/workspace/chat"
        class="product-mode-switch__item"
        :class="{ 'is-active': isWorkspace }"
        :aria-current="isWorkspace ? 'page' : undefined"
        aria-label="进入工作台"
        @click="$emit('navigate')"
      >
        <el-icon aria-hidden="true"><Monitor /></el-icon>
      </router-link>
    </el-tooltip>
    <span v-if="!compact" class="product-mode-switch__divider" aria-hidden="true" />
    <el-tooltip content="管理后台" :placement="compact ? 'right' : 'bottom'" :enterable="false" :trigger-keys="[]">
      <router-link
        to="/admin"
        class="product-mode-switch__item"
        :class="{ 'is-active': isAdmin }"
        :aria-current="isAdmin ? 'page' : undefined"
        aria-label="进入管理后台"
        @click="$emit('navigate')"
      >
        <el-icon aria-hidden="true"><Setting /></el-icon>
      </router-link>
    </el-tooltip>
  </nav>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Monitor, Setting } from '@element-plus/icons-vue'

defineProps({ compact: Boolean })
defineEmits(['navigate'])
const route = useRoute()
const isWorkspace = computed(() => route.path.startsWith('/workspace'))
const isAdmin = computed(() => route.path.startsWith('/admin'))
</script>

<style scoped>
.product-mode-switch { display: flex; align-items: center; flex: 0 0 auto; gap: 2px; }
.product-mode-switch__divider { flex: 0 0 1px; width: 1px; height: 12px; background: #b8bdc5; }
.product-mode-switch__item { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 6px; color: #96999d; text-decoration: none; transition: background .15s, color .15s; }
.product-mode-switch__item:hover { color: #555a61; background: #eceef1; }
.product-mode-switch__item:focus-visible { outline: 2px solid #409EFF; outline-offset: 1px; }
.product-mode-switch__item.is-active { color: #409EFF; }
.product-mode-switch__item.is-active :deep(svg) { stroke: currentColor; stroke-width: 24; stroke-linejoin: round; }
.product-mode-switch__item .el-icon { font-size: 16px; }
.product-mode-switch--compact { flex-direction: column; padding: 8px 0 10px; }
.product-mode-switch--compact .product-mode-switch__item { width: 42px; height: 38px; }
@media (prefers-reduced-motion: reduce) { .product-mode-switch__item { transition: none; } }
</style>
