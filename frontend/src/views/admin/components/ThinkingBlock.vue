<template>
  <div class="thinking-block" :class="{ collapsed: !expanded && isDone, running: !isDone }">
    <div
      class="thinking-header"
      role="button"
      tabindex="0"
      :aria-expanded="expanded"
      @click="toggle"
      @keydown.enter.prevent="toggle"
      @keydown.space.prevent="toggle"
    >
      <div class="thinking-left">
        <el-icon v-if="!isDone" class="thinking-spinner"><Loading /></el-icon>
        <el-icon v-else class="thinking-icon"><Opportunity /></el-icon>
        <span class="thinking-label">{{ isDone ? '深度思考' : '正在思考' }}</span>
        <span class="thinking-preview" v-if="!expanded && isDone && lastLine">
          {{ lastLine.slice(0, 80) }}
        </span>
      </div>
      <div class="thinking-right">
        <span v-if="durationText" class="thinking-duration">{{ durationText }}</span>
        <el-icon class="expand-icon" :class="{ rotated: expanded }">
          <ArrowDown />
        </el-icon>
      </div>
    </div>
    <div class="thinking-content" v-show="expanded">
      <div class="thinking-text">{{ content }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Loading, ArrowDown, Opportunity } from '@element-plus/icons-vue'

const props = defineProps({
  content: { type: String, default: '' },
  startTime: { type: Number, default: null },
  endTime: { type: Number, default: null },
  durationMs: { type: Number, default: null },
})

const expanded = ref(!props.endTime)
const manuallyToggled = ref(false)

const isDone = computed(() => !!props.endTime)
const durationText = computed(() => {
  const ms = Number.isFinite(props.durationMs)
    ? Math.max(0, props.durationMs)
    : (props.startTime && props.endTime
        ? Math.max(0, props.endTime - props.startTime)
        : null)
  if (ms === null) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
})
const lastLine = computed(() => {
  const lines = props.content.split('\n').filter(l => l.trim())
  return lines[lines.length - 1] || ''
})

watch(isDone, (done, wasDone) => {
  if (done && !wasDone && !manuallyToggled.value) expanded.value = false
})

const toggle = () => {
  manuallyToggled.value = true
  expanded.value = !expanded.value
}
</script>

<style scoped>
.thinking-block {
  margin: 0;
}

.thinking-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 30px;
  padding: 3px 5px;
  border-radius: 5px;
  cursor: pointer;
  user-select: none;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
}
.thinking-header:hover {
  background: #f5f6f4;
}
.thinking-header:focus-visible {
  outline: 2px solid #aeb3b8;
  outline-offset: -2px;
}
.thinking-left,
.thinking-right {
  display: flex;
  align-items: center;
  gap: 6px;
}
.thinking-left {
  min-width: 0;
  flex: 1;
}
.thinking-right {
  flex-shrink: 0;
}

.thinking-spinner {
  flex-shrink: 0;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
}
.thinking-spinner {
  animation: spin 1.5s linear infinite;
  color: #7b8794;
}
.thinking-icon {
  flex-shrink: 0;
  color: #8b9096;
  font-size: 14px;
}
.thinking-label {
  color: #777d84;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  font-weight: 400;
  flex-shrink: 0;
  white-space: nowrap;
}
.thinking-preview {
  color: #909399;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.thinking-duration {
  color: #a3aab3;
  font-family: 'SF Mono', Consolas, monospace;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  font-variant-numeric: tabular-nums;
}
.expand-icon {
  color: #c0c4cc;
  font-size: 12px;
  transition: transform 0.2s;
}
.expand-icon.rotated {
  transform: rotate(180deg);
}

.thinking-content {
  padding: 2px 6px 9px 25px;
}
.thinking-text {
  color: #5e646b;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
  padding: 4px 0;
  background: transparent;
  scrollbar-width: thin;
  scrollbar-color: #c1c1c1 #f1f1f1;
}
.thinking-text::-webkit-scrollbar { width: 4px; }
.thinking-text::-webkit-scrollbar-track { background: #f1f1f1; border-radius: 3px; }
.thinking-text::-webkit-scrollbar-thumb { background: #c1c1c1; border-radius: 3px; }
.thinking-text::-webkit-scrollbar-thumb:hover { background: #a8a8a8; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
