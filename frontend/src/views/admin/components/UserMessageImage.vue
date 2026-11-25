<template>
  <div class="user-image-attachment">
    <el-image
      v-if="source"
      class="user-message-image"
      :src="source"
      :preview-src-list="[source]"
      preview-teleported
      fit="contain"
      alt="图片附件"
    >
      <template #error>
        <span class="image-state" role="img" aria-label="图片无法加载"><el-icon><Picture /></el-icon></span>
      </template>
    </el-image>
    <span v-else class="user-message-image image-state" role="img" :aria-label="failed ? '图片无法加载' : '图片加载中'">
      <el-icon :class="{ 'is-loading': !failed }"><Picture v-if="failed" /><Loading v-else /></el-icon>
    </span>
    <button
      v-if="publicUrl"
      type="button"
      class="image-copy-link"
      aria-label="复制图片链接"
      title="复制图片链接"
      @click.stop.prevent="copyPublicUrl"
    ><el-icon><Connection /></el-icon></button>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Connection, Loading, Picture } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '@/api/request'

const props = defineProps({
  agentId: { type: [Number, String], required: true },
  path: { type: String, required: true },
  previewUrl: { type: String, default: '' },
})
const source = ref('')
const failed = ref(false)
const publicUrl = computed(() => props.path.startsWith('https://') ? props.path : '')

const copyPublicUrl = async () => {
  try {
    await navigator.clipboard.writeText(publicUrl.value)
    ElMessage.success('图片链接已复制')
  } catch {
    ElMessage.error('图片链接复制失败，请重试')
  }
}

watch(() => [props.agentId, props.path, props.previewUrl], async (_, __, onCleanup) => {
  const controller = new AbortController()
  let objectUrl = ''
  onCleanup(() => {
    controller.abort()
    if (objectUrl) URL.revokeObjectURL(objectUrl)
  })
  source.value = publicUrl.value || props.previewUrl
  failed.value = false
  if (source.value) return
  try {
    const blob = await api.get(`/agents/${props.agentId}/files/download`, {
      params: { path: props.path },
      responseType: 'blob',
      signal: controller.signal,
    })
    if (controller.signal.aborted) return
    objectUrl = URL.createObjectURL(blob)
    source.value = objectUrl
  } catch {
    if (!controller.signal.aborted) failed.value = true
  }
}, { immediate: true })
</script>

<style scoped>
.user-image-attachment { position: relative; width: 96px; max-width: 100%; flex: 0 0 96px; }
.image-copy-link {
  position: absolute;
  top: 5px;
  right: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #909399;
  font-size: 16px;
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
}
.user-image-attachment:hover .image-copy-link,
.user-image-attachment:focus-within .image-copy-link { opacity: 1; pointer-events: auto; }
.image-copy-link:hover { color: #303133; }
.image-copy-link:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
@media (hover: none) {
  .image-copy-link { opacity: 1; pointer-events: auto; }
}
.user-message-image {
  display: block;
  width: 96px;
  height: 96px;
  max-width: 100%;
  flex: 0 0 96px;
  box-sizing: border-box;
  border: 1px solid var(--chat-image-border, #e4e7ed);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.image-state {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  min-height: 96px;
  color: #909399;
}
.user-message-image.image-state { width: 96px; height: 96px; }
</style>
