<template>
  <section class="process-group" :class="{ expanded, running, streaming, 'has-error': hasError, 'has-warning': hasWarning }">
    <component
      v-if="running || streaming"
      :is="blocks.length ? 'button' : 'div'"
      class="activity-summary"
      :class="{ 'is-interactive': blocks.length }"
      :type="blocks.length ? 'button' : undefined"
      :aria-expanded="blocks.length ? expanded : undefined"
      @click="blocks.length ? toggle() : undefined"
    >
      <span class="activity-title" role="status" aria-live="polite">
        <span class="chat-activity-text" :title="[activity?.title, activity?.detail].filter(Boolean).join(' ')">
          {{ activity?.title || '正在处理任务' }}<span v-if="activity?.detail" class="activity-detail">{{ activity.detail }}</span>
        </span>
        <el-icon v-if="blocks.length" class="expand-icon" :class="{ rotated: expanded }"><ArrowRight /></el-icon>
      </span>
    </component>
    <button
      v-else-if="blocks.length"
      type="button"
      class="process-group-header"
      :aria-expanded="expanded"
      @click="toggle"
    >
      <span class="process-group-left">
        <el-icon v-if="running" class="process-status is-running"><Loading /></el-icon>
        <el-icon v-else-if="hasError" class="process-status is-error"><CircleClose /></el-icon>
        <el-icon v-else-if="hasWarning" class="process-status is-warning"><Warning /></el-icon>
        <span v-if="processTitle" class="process-title">{{ processTitle }}</span>
        <span v-if="showDuration && durationText && !running && !streaming" class="process-duration">{{ durationText }}</span>
        <span v-if="!streaming" class="process-summary">{{ hasError || hasWarning ? '本轮 ' : '' }}{{ summaryText }}</span>
      </span>
      <el-icon class="expand-icon" :class="{ rotated: expanded }"><ArrowRight /></el-icon>
    </button>

    <div v-show="expanded" class="process-group-body" role="region" aria-label="执行过程详情" tabindex="0">
      <div
        v-for="(block, index) in blocks"
        :key="`${block.type}-${index}`"
        class="process-step"
        :class="{ 'is-last': index === blocks.length - 1, 'is-error': blockSeverities[index] === 'error', 'is-warning': blockSeverities[index] === 'warning' }"
      >
        <ThinkingBlock
          v-if="block.type === 'thinking'"
          :content="block.content"
          :start-time="block.startTime"
          :end-time="block.endTime"
          :duration-ms="block.duration_ms"
        />
        <template v-else-if="block.type === 'tool_use'">
          <ToolCallCard
            :name="block.name"
            :input="block.input"
            :result="block.result"
            :severity="blockSeverities[index]"
            :start-time="block.startTime"
            :end-time="block.endTime"
            :duration-ms="block.duration_ms"
            :view-only="viewOnly"
          />
        </template>
      </div>
    </div>

    <template v-for="(block, index) in blocks" :key="`preview-${index}`">
      <HtmlPreviewCard
        v-if="block.type === 'tool_use' && toolResultHtml(block)"
        :content="toolResultHtml(block)"
        :view-only="viewOnly"
      />
    </template>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import '@/assets/styles/chat-activity.css'
import { ArrowRight, CircleClose, Loading, Warning } from '@element-plus/icons-vue'
import { getToolResultHtml, getToolResultSeverity } from '@/utils/agent-chat-blocks'
import HtmlPreviewCard from './HtmlPreviewCard.vue'
import ThinkingBlock from './ThinkingBlock.vue'
import ToolCallCard from './ToolCallCard.vue'

const props = defineProps({
  blocks: { type: Array, default: () => [] },
  activity: { type: Object, default: null },
  durationMsOverride: { type: Number, default: null },
  summaryOverride: { type: String, default: null },
  showDuration: { type: Boolean, default: true },
  running: { type: Boolean, default: false },
  streaming: { type: Boolean, default: false },
  viewOnly: { type: Boolean, default: false },
})

const toolHtmlCache = new WeakMap()

const thinkingCount = computed(() => props.blocks.filter(block => block.type === 'thinking').length)
const toolCount = computed(() => props.blocks.filter(block => block.type === 'tool_use').length)
const blockSeverities = computed(() => props.blocks.map(block => (
  block.type === 'tool_use' ? getToolResultSeverity(block.result, block.is_error) : ''
)))
const hasError = computed(() => blockSeverities.value.includes('error'))
const hasWarning = computed(() => blockSeverities.value.includes('warning'))
const expanded = ref(false)
const processTitle = computed(() => {
  if (props.running) return '执行过程'
  // The whole streaming reply has one global timer at the top. Completed
  // process segments keep their place in the answer without introducing a
  // second "已完成" status while the reply is still running.
  if (props.streaming) return ''
  if (hasError.value) return '执行异常'
  if (hasWarning.value) return blockSeverities.value.filter(value => value === 'warning').length === toolCount.value
    ? '调用被拦截' : '部分调用被拦截'
  return '本轮'
})
const summaryText = computed(() => {
  if (props.summaryOverride !== null) return props.summaryOverride
  const parts = []
  if (thinkingCount.value) parts.push(`${thinkingCount.value} 段思考`)
  if (toolCount.value) parts.push(`${toolCount.value} 次工具调用`)
  return parts.join(' · ')
})
const totalDurationMs = computed(() => {
  if (props.running) return null
  if (Number.isFinite(props.durationMsOverride)) return props.durationMsOverride
  const explicitDurations = props.blocks
    .map(block => Number(block?.duration_ms))
    .filter(Number.isFinite)
  if (explicitDurations.length) return explicitDurations.reduce((total, value) => total + Math.max(0, value), 0)

  const starts = props.blocks.map(block => Number(block?.startTime)).filter(Number.isFinite)
  const ends = props.blocks.map(block => Number(block?.endTime)).filter(Number.isFinite)
  if (!starts.length || !ends.length || props.running) return null
  return Math.max(0, Math.max(...ends) - Math.min(...starts))
})
const durationText = computed(() => {
  const ms = totalDurationMs.value
  if (!Number.isFinite(ms) || ms <= 0) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 10000) return `${(ms / 1000).toFixed(1)}s`
  if (ms >= 60000) {
    const seconds = Math.round(ms / 1000)
    return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  }
  return `${Math.round(ms / 1000)}s`
})

const toolResultHtml = block => getToolResultHtml(block, toolHtmlCache)

const toggle = () => { expanded.value = !expanded.value }
</script>

<style scoped>
.process-group {
  --chat-warning-color: #e6a23c;
  margin: 8px 0;
}

.process-group-header {
  width: fit-content;
  max-width: 100%;
  min-height: 22px;
  padding: 0 4px 0 0;
  display: flex;
  align-items: center;
  gap: 10px;
  border: 0;
  border-radius: 5px;
  color: inherit;
  background: transparent;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.process-group-header:hover {
  background: transparent;
}

.process-group-header:focus-visible {
  outline: 2px solid #79a8d8;
  outline-offset: 2px;
}

.process-group-left {
  min-width: 0;
  flex: 0 1 auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.process-status,
.expand-icon {
  flex-shrink: 0;
  font-size: 14px;
}

.process-status.is-running {
  color: #7b8794;
  animation: spin 1.5s linear infinite;
}

.process-status.is-done { color: #747b83; }
.process-status.is-error { color: var(--el-color-danger); }
.process-status.is-warning { color: #858b92; }
.process-group:not(.running).has-error .process-title { color: var(--el-color-danger); }

.process-title,
.process-summary {
  color: #777e86;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  font-weight: 400;
  line-height: 22px;
}

.process-title {
  flex-shrink: 0;
}

.process-title + .process-summary {
  margin-left: -2px;
}

.process-duration {
  flex-shrink: 0;
  color: #858b92;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  font-variant-numeric: tabular-nums;
}

.process-summary {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.expand-icon {
  color: #777e86;
  transition: transform 0.2s;
}

.process-group-header .expand-icon {
  opacity: 0;
}

.process-group-header:hover .expand-icon,
.process-group-header:focus-visible .expand-icon,
.process-group.expanded .process-group-header .expand-icon {
  opacity: 1;
}

.expand-icon.rotated {
  transform: rotate(90deg);
}

.activity-summary {
  display: flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  height: 22px;
  box-sizing: border-box;
  padding: 0;
  margin: 0;
  background: transparent;
  border: 0;
  color: inherit;
  font: inherit;
  text-align: left;
}
.activity-summary.is-interactive {
  position: relative;
  cursor: pointer;
}
.activity-summary.is-interactive:focus-visible {
  outline: 2px solid #79a8d8;
  outline-offset: 2px;
}
.activity-title { display: flex; align-items: center; gap: 6px; min-width: 0; width: 100%; margin: 0; color: #a0a5ac; font-size: calc(14px + var(--workspace-font-size-offset, 0px)); font-weight: 400; line-height: 22px; }
.activity-title > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.activity-title .expand-icon { flex: 0 0 auto; color: #c0c4cc; opacity: 0; }
.activity-summary:hover .activity-title .expand-icon,
.activity-summary:focus-visible .activity-title .expand-icon,
.process-group.expanded .activity-title .expand-icon { opacity: 1; }
.activity-detail { margin-left: 8px; font-size: inherit; }
@media (prefers-reduced-motion: reduce) {
  .process-status.is-running { animation: none; }
}
@media (max-width: 480px) {
  .process-group-header { gap: 6px; }
  .process-group-left { flex-wrap: wrap; row-gap: 2px; }
}

.process-group-body {
  margin: 2px 0 8px 6px;
  padding: 2px 4px 2px 14px;
  max-height: min(480px, 50dvh);
  overflow-y: auto;
  overscroll-behavior-y: contain;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: #c1c1c1 transparent;
}

.process-group-body:focus-visible {
  outline: 2px solid #79a8d8;
  outline-offset: 2px;
}

.process-step {
  position: relative;
}

.process-step::before {
  position: absolute;
  top: 0;
  bottom: 0;
  left: -10px;
  width: 1px;
  background: #e3e5e2;
  content: '';
}

.process-step::after {
  position: absolute;
  top: 14px;
  left: -13px;
  width: 7px;
  height: 7px;
  border: 2px solid #fff;
  border-radius: 50%;
  background: #a2a7ad;
  box-sizing: border-box;
  content: '';
}

.process-step.is-last::before {
  bottom: calc(100% - 15px);
}

.process-group.running .process-step:last-child::after {
  background: #30343a;
  box-shadow: 0 0 0 3px #eceeed;
}

.process-group .process-step.is-error::after {
  background: var(--el-color-danger);
}
.process-group .process-step.is-warning::after {
  background: var(--chat-warning-color);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

</style>
