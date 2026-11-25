<template>
  <section v-if="files.length" class="chat-artifacts" aria-label="产物">
    <header class="artifact-heading"><el-icon><Files /></el-icon><span>产物</span><span>{{ files.length }} 个</span></header>
    <ul class="artifact-list">
      <li v-for="file in visibleFiles" :key="file.path" class="artifact-row">
        <el-icon class="artifact-file-icon"><Document /></el-icon>
        <span class="artifact-path" :title="file.path">{{ file.path }}</span>
        <div class="artifact-actions">
          <el-tooltip :content="previewLabel(file)" placement="top">
            <span class="artifact-action-trigger">
              <el-button text circle :icon="View" :disabled="!canAccess || !file.is_previewable"
                :aria-label="`预览 ${file.name}`" @click="previewFile(file)" />
            </span>
          </el-tooltip>
          <el-tooltip :content="canAccess ? '下载文件' : '请在原对话中下载文件'" placement="top">
            <span class="artifact-action-trigger">
              <el-button text circle :icon="Download" :disabled="!canAccess" :loading="downloading.has(file.path)"
                :aria-label="`下载 ${file.name}`" @click="downloadFile(file)" />
            </span>
          </el-tooltip>
        </div>
      </li>
    </ul>
    <button v-if="files.length > COLLAPSED_FILE_COUNT" type="button" class="artifact-toggle"
      :aria-expanded="expanded" @click="expanded = !expanded">
      <span>{{ expanded ? '收起' : `展开全部（还有 ${files.length - COLLAPSED_FILE_COUNT} 个）` }}</span>
      <el-icon><ArrowUp v-if="expanded" /><ArrowDown v-else /></el-icon>
    </button>
    <el-dialog v-model="previewVisible" :title="previewName" width="min(900px, calc(100vw - 32px))"
      append-to-body destroy-on-close @closed="clearPreview">
      <div class="artifact-preview" v-loading="previewLoading">
        <img v-if="previewUrl && previewType === 'image'" class="artifact-image" :src="previewUrl" :alt="previewName" />
        <iframe v-else-if="previewUrl && previewType === 'pdf'" class="artifact-frame" :src="previewUrl" :title="previewName" />
        <iframe v-else-if="previewType === 'html' && !previewLoading" class="artifact-frame" :srcdoc="htmlDocument" sandbox="allow-scripts" :title="previewName" />
        <MessageContent v-else-if="previewType === 'markdown' && !previewLoading" :content="previewContent" :html-preview-enabled="false" view-only />
        <pre v-else-if="!previewLoading" class="artifact-source"><code>{{ previewContent }}</code></pre>
      </div>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Document, Download, Files, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '@/api/request'
import { useAuthStore } from '@/stores/auth'
import { buildHtmlPreviewDocument } from '@/utils/html-preview'
import MessageContent from './MessageContent.vue'

const props = defineProps({
  files: { type: Array, default: () => [] },
  agentId: { type: [Number, String], default: '' },
  viewOnly: { type: Boolean, default: false },
})
const auth = useAuthStore()
const COLLAPSED_FILE_COUNT = 5
const expanded = ref(false)
const visibleFiles = computed(() => expanded.value ? props.files : props.files.slice(0, COLLAPSED_FILE_COUNT))
const canAccess = computed(() => !props.viewOnly && Number(props.agentId) > 0)
const downloading = ref(new Set())
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewName = ref('文件预览')
const previewType = ref('text')
const previewContent = ref('')
const previewUrl = ref('')
const htmlDocument = computed(() => buildHtmlPreviewDocument(previewContent.value))
const controllers = new Set()
let previewController
const previewLabel = file => !canAccess.value ? '请在原对话中预览文件'
  : file.is_previewable ? '预览文件' : '此格式暂不支持预览，可下载查看'
const errorMessage = async (error, fallback) => {
  let data = error.response?.data
  if (data instanceof Blob) {
    try { data = JSON.parse(await data.text()) } catch { data = null }
  }
  return typeof data?.detail === 'string' ? data.detail : fallback
}
const clearPreview = () => {
  previewController?.abort()
  previewController = null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  previewContent.value = ''
  previewLoading.value = false
}
const previewFile = async file => {
  if (!canAccess.value || !file.is_previewable) return
  clearPreview()
  const controller = new AbortController()
  previewController = controller
  previewName.value = file.name
  previewVisible.value = true
  previewLoading.value = true
  const extension = file.path.split('.').at(-1).toLowerCase()
  const imageTypes = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp' }
  previewType.value = imageTypes[extension] ? 'image' : extension === 'pdf' ? 'pdf'
    : ['html', 'htm'].includes(extension) ? 'html' : ['md', 'markdown'].includes(extension) ? 'markdown' : 'text'
  try {
    if (['image', 'pdf'].includes(previewType.value)) {
      const blob = await api.get(`/agents/${props.agentId}/files/download`, {
        params: { path: file.path }, responseType: 'blob', signal: controller.signal,
      })
      if (controller.signal.aborted) return
      previewUrl.value = URL.createObjectURL(new Blob([blob], { type: imageTypes[extension] || 'application/pdf' }))
    } else {
      const result = await api.get(`/agents/${props.agentId}/files/preview`, {
        params: { path: file.path }, signal: controller.signal,
      })
      if (controller.signal.aborted) return
      previewContent.value = result.content || ''
    }
  } catch (error) {
    if (!controller.signal.aborted) {
      previewVisible.value = false
      ElMessage.error(await errorMessage(error, '文件预览失败'))
    }
  } finally {
    if (!controller.signal.aborted) previewLoading.value = false
  }
}
const downloadFile = async file => {
  if (!canAccess.value || downloading.value.has(file.path)) return
  const controller = new AbortController()
  controllers.add(controller)
  downloading.value.add(file.path)
  try {
    const blob = await api.get(`/agents/${props.agentId}/files/download`, {
      params: { path: file.path }, responseType: 'blob', signal: controller.signal,
    })
    if (controller.signal.aborted) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.name
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    if (!controller.signal.aborted) ElMessage.error(await errorMessage(error, '文件下载失败'))
  } finally {
    controllers.delete(controller)
    downloading.value.delete(file.path)
  }
}
const dispose = () => {
  expanded.value = false
  previewVisible.value = false
  clearPreview()
  controllers.forEach(controller => controller.abort())
  controllers.clear()
  downloading.value.clear()
}
watch(() => props.agentId, dispose)
onBeforeUnmount(dispose)
</script>

<style scoped>
.chat-artifacts { min-width: 0; margin: 16px 0 4px; border: 1px solid #e3e6eb; border-radius: 12px; overflow: hidden; background: #fff; }
.artifact-heading { display: flex; align-items: center; gap: 8px; padding: 12px 14px; background: #f8f9fa; color: #41464e; font-size: calc(13px + var(--workspace-font-size-offset, 0px)); }
.artifact-heading > .el-icon { color: #737b87; font-size: 17px; }
.artifact-heading > span { color: #818894; }
.artifact-list { margin: 0; padding: 4px 0; list-style: none; }
.artifact-row { display: flex; align-items: center; gap: 9px; min-width: 0; padding: 7px 12px 7px 14px; }
.artifact-row + .artifact-row { border-top: 1px solid #f0f1f3; }
.artifact-file-icon { flex-shrink: 0; color: #858d98; font-size: 16px; }
.artifact-path { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #515761; font-size: calc(13px + var(--workspace-font-size-offset, 0px)); }
.artifact-actions { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
.artifact-action-trigger { display: inline-flex; }
.artifact-actions :deep(.el-button) { width: 30px; height: 30px; color: #687282; }
.artifact-actions :deep(.el-button.is-disabled) { color: #bcc1c9; }
.artifact-toggle { display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; padding: 10px 14px; border: 0; border-top: 1px solid #f0f1f3; background: #f8f9fa; color: #687282; font: inherit; font-size: calc(13px + var(--workspace-font-size-offset, 0px)); cursor: pointer; }
.artifact-toggle:hover { background: #f0f1f3; color: #41464e; }
.artifact-toggle:focus-visible { outline: 2px solid #687282; outline-offset: -2px; }
.artifact-preview { min-height: 160px; max-height: 70vh; overflow: auto; }
.artifact-image { display: block; max-width: 100%; max-height: 65vh; margin: auto; object-fit: contain; }
.artifact-frame { display: block; width: 100%; height: 65vh; border: 1px solid #e3e6eb; border-radius: 6px; background: white; box-sizing: border-box; }
.artifact-source { margin: 0; padding: 14px; white-space: pre-wrap; overflow-wrap: anywhere; color: #34383f; background: #f8f9fa; border-radius: 6px; font-size: calc(13px + var(--workspace-font-size-offset, 0px)); line-height: 1.6; }
</style>
