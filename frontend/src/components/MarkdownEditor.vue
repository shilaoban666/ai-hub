<template>
  <MdEditor v-bind="$attrs" class="hub-markdown-editor" :model-value="modelValue"
    language="zh-CN" :toolbars="toolbars" :preview="wideScreen" show-code-row-number
    @update:model-value="$emit('update:modelValue', $event)" />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { MdEditor } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'

defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: { type: String, default: '' }, mediaTools: Boolean })
defineEmits(['update:modelValue'])
const screenQuery = window.matchMedia('(min-width: 1024px)')
const wideScreen = ref(screenQuery.matches)
const updateScreen = event => { wideScreen.value = event.matches }
onMounted(() => screenQuery.addEventListener('change', updateScreen))
onBeforeUnmount(() => screenQuery.removeEventListener('change', updateScreen))
const toolbars = computed(() => [
  'bold', 'italic', 'title', 'quote', 'unorderedList', 'orderedList', 'task', '-',
  'codeRow', 'code', 'link', ...(props.mediaTools ? ['image'] : []), 'table',
  ...(props.mediaTools ? ['mermaid', 'katex'] : []), '-', 'revoke', 'next', '=',
  'preview', 'fullscreen', 'catalog',
])
</script>

<style scoped>
.hub-markdown-editor { width: 100%; min-width: 0; height: 520px; border: 1px solid var(--el-border-color); border-radius: 6px; --md-bk-color: #fff; --md-color: #303133; }
.hub-markdown-editor :deep(.md-editor-toolbar-wrapper) { padding: 6px 10px; }
.hub-markdown-editor :deep(.md-editor-toolbar-item) { margin: 0 2px; }
.hub-markdown-editor :deep(.md-editor-input-wrapper) { font-size: 14px; line-height: 1.7; }
.hub-markdown-editor :deep(.md-editor-preview) { font-size: 14px; line-height: 1.7; }
.hub-markdown-editor :deep(.md-editor-preview-wrapper) { padding: 20px; }
.hub-markdown-editor :deep(.md-editor-footer) { font-size: 12px; color: #909399; }
</style>
