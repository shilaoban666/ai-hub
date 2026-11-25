<template>
  <section
    ref="artifactRef"
    class="html-artifact"
    :class="{ resizing: isResizing }"
    :style="{ '--html-preview-height': `${previewHeight}px` }"
  >
    <header class="artifact-header">
      <span class="artifact-title">
        <el-icon aria-hidden="true"><Monitor /></el-icon>
        HTML 内容
      </span>
      <div class="header-actions">
        <div class="view-switch" aria-label="HTML 显示方式">
          <button
            v-if="!embeddedAssistant"
            type="button"
            :class="{ active: activeView === 'preview' }"
            @click="showPreview"
          >
            <el-icon><View /></el-icon>
            预览
          </button>
          <button
            type="button"
            :class="{ active: activeView === 'source' }"
            @click="activeView = 'source'"
          >
            <el-icon><Document /></el-icon>
            源码
          </button>
        </div>
        <el-tooltip :content="isFullscreen ? '退出全屏' : '全屏'" placement="top">
          <el-button
            class="fullscreen-button"
            :icon="FullScreen"
            circle
            :aria-label="isFullscreen ? '退出全屏' : '全屏显示 HTML 内容'"
            @click="toggleFullscreen"
          />
        </el-tooltip>
      </div>
    </header>
    <div class="artifact-body">
      <iframe
        v-if="activeView === 'preview' && previewLoaded"
        class="html-preview"
        :srcdoc="previewDocument"
        sandbox="allow-scripts allow-same-origin"
        title="智能体返回的 HTML 预览"
      />
      <div
        v-else-if="activeView === 'preview'"
        class="html-preview-placeholder"
        role="status"
        aria-label="HTML 预览等待加载"
      />
      <pre v-else class="html-source"><code>{{ content }}</code></pre>
    </div>
    <div
      v-if="!viewOnly && activeView === 'preview' && !isFullscreen"
      class="preview-resize-handle"
      role="separator"
      aria-orientation="horizontal"
      aria-label="调整 HTML 预览高度"
      :aria-valuemin="MIN_PREVIEW_HEIGHT"
      :aria-valuemax="MAX_PREVIEW_HEIGHT"
      :aria-valuenow="previewHeight"
      tabindex="0"
      title="上下拖动调整预览高度"
      @pointerdown="startResize"
      @pointermove="moveResize"
      @pointerup="endResize"
      @pointercancel="endResize"
      @lostpointercapture="endResize"
      @keydown.up.prevent="resizeBy(-20)"
      @keydown.down.prevent="resizeBy(20)"
      @keydown.home.prevent="previewHeight = DEFAULT_PREVIEW_HEIGHT"
    >
      <span aria-hidden="true"></span>
    </div>
  </section>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Document, FullScreen, Monitor, View } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { buildHtmlPreviewDocument } from '@/utils/html-preview'

const props = defineProps({
  content: { type: String, default: '' },
  viewOnly: { type: Boolean, default: false },
})
const authStore = useAuthStore()
const embeddedAssistant = inject('embeddedAssistant', false)

const DEFAULT_PREVIEW_HEIGHT = 300
const MIN_PREVIEW_HEIGHT = 160
const MAX_PREVIEW_HEIGHT = 1200
const PREVIEW_UPDATE_DELAY_MS = 300
const activeView = ref(embeddedAssistant ? 'source' : 'preview')
const artifactRef = ref(null)
const isFullscreen = ref(false)
const isResizing = ref(false)
const previewLoaded = ref(false)
const previewHeight = ref(DEFAULT_PREVIEW_HEIGHT)
const previewContent = ref(props.content)
let previewObserver = null
let previewUpdateTimer = null
let previewUpdateSequence = 0
let previewLoadPromise = null
let isUnmounted = false
let resizeStartY = 0
let resizeStartHeight = DEFAULT_PREVIEW_HEIGHT

const clampPreviewHeight = height => Math.min(
  MAX_PREVIEW_HEIGHT,
  Math.max(MIN_PREVIEW_HEIGHT, Math.round(height)),
)

const resizeBy = delta => {
  previewHeight.value = clampPreviewHeight(previewHeight.value + delta)
}

const startResize = (event) => {
  isResizing.value = true
  resizeStartY = event.clientY
  resizeStartHeight = previewHeight.value
  event.currentTarget.setPointerCapture(event.pointerId)
}

const moveResize = (event) => {
  if (!isResizing.value) return
  previewHeight.value = clampPreviewHeight(resizeStartHeight + event.clientY - resizeStartY)
}

const endResize = (event) => {
  if (!isResizing.value) return
  isResizing.value = false
  if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
    event.currentTarget.releasePointerCapture(event.pointerId)
  }
}

const syncFullscreenState = () => {
  isFullscreen.value = document.fullscreenElement === artifactRef.value
}

const syncPreviewContent = () => {
  window.clearTimeout(previewUpdateTimer)
  previewUpdateTimer = null
  previewContent.value = props.content
}

const loadPreview = () => {
  if (embeddedAssistant) return Promise.resolve()
  syncPreviewContent()
  if (!isUnmounted) previewLoaded.value = true
  previewObserver?.disconnect()
  previewLoadPromise = null
  return Promise.resolve()
}

const toggleFullscreen = async () => {
  if (document.fullscreenElement === artifactRef.value) {
    await document.exitFullscreen()
    return
  }
  await artifactRef.value?.requestFullscreen()
  await loadPreview()
}

const showPreview = () => {
  activeView.value = 'preview'
  void loadPreview()
}

onMounted(() => {
  document.addEventListener('fullscreenchange', syncFullscreenState)
  if (typeof IntersectionObserver === 'undefined') {
    void loadPreview()
    return
  }
  previewObserver = new IntersectionObserver((entries) => {
    if (!entries.some(entry => entry.isIntersecting)) return
    void loadPreview()
  }, { rootMargin: '600px 0px' })
  previewObserver.observe(artifactRef.value)
})
onBeforeUnmount(() => {
  isUnmounted = true
  document.removeEventListener('fullscreenchange', syncFullscreenState)
  previewObserver?.disconnect()
  window.clearTimeout(previewUpdateTimer)
})

watch(() => props.content, (content) => {
  window.clearTimeout(previewUpdateTimer)
  const updateSequence = ++previewUpdateSequence
  if (!previewLoaded.value) {
    previewContent.value = content
    previewUpdateTimer = null
    return
  }
  previewUpdateTimer = window.setTimeout(async () => {
    previewUpdateTimer = null
    await ensureOnlinePreviewSession(authStore.accessToken)
    if (isUnmounted || updateSequence !== previewUpdateSequence) return
    previewContent.value = content
  }, PREVIEW_UPDATE_DELAY_MS)
})

const previewDocument = computed(() => buildHtmlPreviewDocument(previewContent.value))
</script>

<style scoped>
.html-artifact {
  max-width: 100%;
  margin: 12px 0;
  overflow: hidden;
  border: 1px solid #d8dee4;
  border-radius: 6px;
  background: #fff;
}

.artifact-header {
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 10px 7px 12px;
  border-bottom: 1px solid #dfe3e8;
  background: #f6f8fa;
}

.artifact-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: #3f4b59;
  font-size: 12px;
  font-weight: 650;
  line-height: 20px;
  letter-spacing: 0;
}

.artifact-title :deep(.el-icon) {
  color: #087f5b;
  font-size: 15px;
}

.header-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.view-switch {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  padding: 2px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  background: #eef1f4;
}

.view-switch button {
  height: 24px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  border: 0;
  border-radius: 4px;
  color: #606b78;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  letter-spacing: 0;
}

.view-switch button:hover {
  color: #1f5f99;
}

.view-switch button.active {
  color: #1f5f99;
  background: #fff;
  box-shadow: 0 1px 3px rgba(31, 45, 61, 0.14);
}

.fullscreen-button.el-button {
  width: 30px;
  height: 30px;
  padding: 0;
  flex: 0 0 30px;
}

.artifact-body {
  min-width: 0;
  background: #fff;
}

.html-preview {
  width: 100%;
  height: var(--html-preview-height, 300px);
  display: block;
  border: 0;
  background: #fff;
}

.html-preview-placeholder {
  width: 100%;
  height: var(--html-preview-height, 300px);
  background: linear-gradient(90deg, #fafbfc 25%, #f3f5f7 37%, #fafbfc 63%);
  background-size: 400% 100%;
  animation: preview-placeholder 1.4s ease infinite;
}

@keyframes preview-placeholder {
  from { background-position: 100% 0; }
  to { background-position: 0 0; }
}

@media (prefers-reduced-motion: reduce) {
  .html-preview-placeholder { animation: none; }
}

.preview-resize-handle {
  height: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-top: 1px solid #edf0f2;
  background: #f8fafb;
  cursor: ns-resize;
  touch-action: none;
  outline: none;
}

.preview-resize-handle span {
  width: 34px;
  height: 3px;
  border-radius: 2px;
  background: #c5cbd3;
  transition: background-color 0.15s, width 0.15s;
}

.preview-resize-handle:hover span,
.preview-resize-handle:focus-visible span,
.html-artifact.resizing .preview-resize-handle span {
  width: 42px;
  background: #7b8794;
}

.html-artifact.resizing {
  user-select: none;
}

.html-artifact.resizing .html-preview {
  pointer-events: none;
}

.html-artifact:fullscreen {
  width: 100vw;
  height: 100vh;
  margin: 0;
  display: flex;
  flex-direction: column;
  border: 0;
  border-radius: 0;
}

.html-artifact:fullscreen .artifact-body {
  min-height: 0;
  display: flex;
  flex: 1;
}

.html-artifact:fullscreen .html-preview,
.html-artifact:fullscreen .html-source {
  width: 100%;
  height: 100%;
  max-height: none;
  box-sizing: border-box;
}

.html-source {
  max-height: 55vh;
  margin: 0;
  padding: 14px;
  overflow: auto;
  color: #e6edf3;
  background: #0d1117;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
  font-size: 13px;
  line-height: 1.55;
  white-space: pre;
}

@media (max-width: 640px) {
  .artifact-header {
    align-items: flex-start;
  }
}
</style>
