<template>
  <div class="tool-card" :class="statusClass">
    <div
      class="tool-card-header"
      role="button"
      tabindex="0"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
      @keydown.enter.prevent="expanded = !expanded"
      @keydown.space.prevent="expanded = !expanded"
    >
      <div class="tool-left">
        <el-icon v-if="status === 'running'" class="tool-status running"><Loading /></el-icon>
        <el-icon v-else-if="status === 'error'" class="tool-status error"><CircleClose /></el-icon>
        <el-icon v-else-if="status === 'warning'" class="tool-status warning" title="调用被拦截" aria-label="调用被拦截"><Warning /></el-icon>
        <el-icon v-else class="tool-icon"><SkillIcon v-if="name === 'Skill'" /><WrenchIcon v-else /></el-icon>
        <span class="tool-name" :title="name">{{ name }}</span>

        <!-- 摘要（一行截断） -->
        <span class="tool-summary" v-if="summaryText" :title="summaryText">{{ summaryText }}</span>
      </div>

      <div class="tool-right">
        <span class="tool-duration" v-if="durationText">{{ durationText }}</span>
        <el-icon class="expand-icon" :class="{ rotated: expanded }"><ArrowDown /></el-icon>
      </div>
    </div>

    <!-- 展开的详情 -->
    <div class="tool-card-body" v-show="expanded">
      <div class="tool-section" v-if="input || result !== undefined">
        <div class="tool-section-title">
          调用详情
          <span v-if="result !== undefined" class="result-meta">{{ resultLines }} 行</span>
          <el-button
            v-if="resultText && !viewOnly"
            size="small"
            text
            class="copy-btn"
            @click.stop="copyResult"
          >复制</el-button>
        </div>
        <div
          class="tool-io-grid"
          :class="{ single: !input || result === undefined }"
        >
          <div v-if="input" class="tool-io-panel">
            <div class="tool-io-label">输入</div>
            <pre class="tool-json">{{ JSON.stringify(input, null, 2) }}</pre>
          </div>
          <div v-if="result !== undefined" class="tool-io-panel tool-output-panel">
            <div class="tool-io-label">输出</div>
            <div class="tool-output-wrap" :class="{ collapsed: isLongResult && !resultExpanded }">
              <pre class="tool-output" :class="{ 'json-output': displayResultJson, 'is-error': status === 'error', 'is-warning': status === 'warning' }">{{ displayResultJson || displayResultText }}</pre>
              <div v-if="isLongResult && !resultExpanded" class="output-fade"></div>
            </div>
          </div>
        </div>
        <el-button
          v-if="isLongResult"
          size="small"
          text
          class="expand-result-btn"
          @click="resultExpanded = !resultExpanded"
        >
          {{ resultExpanded ? '收起' : '展开全部' }}
          <el-icon><ArrowDown v-if="!resultExpanded" /><ArrowUp v-else /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Loading, CircleClose, Warning, ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import SkillIcon from '@/components/icons/SkillIcon.vue'
import WrenchIcon from '@/components/icons/WrenchIcon.vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  name: { type: String, default: '' },
  input: { type: Object, default: null },
  result: { type: String, default: undefined },
  severity: { type: String, default: '' },
  startTime: { type: Number, default: null },
  endTime: { type: Number, default: null },
  durationMs: { type: Number, default: null },
  viewOnly: { type: Boolean, default: false },
})

const expanded = ref(false)

const status = computed(() => {
  if (props.result !== undefined) return props.severity || 'done'
  if (props.endTime) return 'done'
  if (props.input) return 'running'
  return 'pending'
})

const statusClass = computed(() => `status-${status.value}`)

const summaryText = computed(() => {
  const inp = props.input || {}
  if (props.name === 'Skill' && typeof inp.skill === 'string') return inp.skill.trim()
  if (props.name === 'Bash' && inp.command) return inp.command.slice(0, 60)
  if (inp.file_path) return inp.file_path
  if (inp.pattern) return inp.pattern
  if (inp.url) return inp.url
  return ''
})

const resultText = computed(() => {
  if (props.result === undefined) return ''
  return String(props.result)
})

const isLongResult = computed(() => resultText.value.length > 5000)
const resultExpanded = ref(false)

const displayResultText = computed(() => (
  isLongResult.value && !resultExpanded.value
    ? resultText.value.slice(0, 5000)
    : resultText.value
))

const displayResultJson = computed(() => {
  const raw = displayResultText.value
  if (!raw || (isLongResult.value && !resultExpanded.value)) return null
  try {
    const parsed = JSON.parse(raw)
    return JSON.stringify(parsed, null, 2)
  } catch {
    return null
  }
})

const resultLines = computed(() => {
  return (resultText.value || '').split('\n').length
})

const copyResult = async () => {
  try {
    await navigator.clipboard.writeText(resultText.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败')
  }
}

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
</script>

<style scoped>
.tool-card {
  margin: 0;
}

.tool-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 30px;
  padding: 3px 5px;
  border-radius: 5px;
  cursor: pointer;
  user-select: none;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
}
.tool-card-header:hover {
  background: #f5f6f4;
}
.tool-card-header:focus-visible {
  outline: 2px solid #aeb3b8;
  outline-offset: -2px;
}

.tool-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.tool-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.tool-status {
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  flex-shrink: 0;
}
.tool-status.running { color: #7b8794; animation: spin 1.5s linear infinite; }
.tool-status.error { color: var(--el-color-danger); }
.tool-status.warning { color: var(--chat-warning-color, #e6a23c); }

.tool-icon { flex-shrink: 0; color: #8b9096; font-size: 14px; }
.tool-name {
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  font-weight: 400;
  color: #777d84;
  min-width: 0;
  flex-shrink: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-summary {
  color: #909399;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.tool-duration {
  white-space: nowrap;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  color: #a3aab3;
  font-family: 'SF Mono', Consolas, monospace;
  font-variant-numeric: tabular-nums;
}

.expand-icon {
  font-size: 12px;
  color: #c0c4cc;
  transition: transform 0.2s;
}
.expand-icon.rotated { transform: rotate(180deg); }

.tool-card-body {
  padding: 2px 6px 10px 25px;
  container-type: inline-size;
}

.tool-section { margin-top: 8px; }
.tool-section-title {
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  color: #909399;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0;
}

.tool-io-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  background: #f5f7fa;
  border-radius: 6px;
  overflow: hidden;
}
.tool-io-grid.single {
  grid-template-columns: minmax(0, 1fr);
}
.tool-io-panel {
  min-width: 0;
  padding: 8px 10px 10px;
}
.tool-output-panel {
  border-left: 1px solid #e4e7ed;
}
.tool-io-grid.single .tool-output-panel {
  border-left: 0;
}
.tool-io-label {
  margin-bottom: 4px;
  color: #909399;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
}

.tool-json, .tool-output {
  background: transparent;
  padding: 0;
  border-radius: 0;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  font-family: 'SF Mono', 'Courier New', monospace;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: normal;
  overflow-wrap: anywhere;
  margin: 0;
}
.tool-json {
  color: #1f2937;
  max-height: min(320px, 40dvh);
  overflow-y: auto;
  scrollbar-width: thin;
}
.tool-output {
  color: #374151;
}
.tool-output.is-error {
  color: var(--el-color-danger);
}
.tool-output.is-warning {
  color: var(--chat-warning-color, #e6a23c);
}
.json-output {
  color: #1f2937;
}

.tool-output-wrap {
  position: relative;
  max-height: min(320px, 40dvh);
  overflow-y: auto;
  border-radius: 6px;
  scrollbar-width: thin;
  scrollbar-color: #c1c1c1 #f1f1f1;
}
.tool-output-wrap::-webkit-scrollbar { width: 4px; }
.tool-output-wrap::-webkit-scrollbar-track { background: #f1f1f1; border-radius: 3px; }
.tool-output-wrap::-webkit-scrollbar-thumb { background: #c1c1c1; border-radius: 3px; }
.tool-output-wrap::-webkit-scrollbar-thumb:hover { background: #a8a8a8; }
.tool-output-wrap.collapsed {
  max-height: 120px;
  overflow: hidden;
}
.output-fade {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 40px;
  background: linear-gradient(transparent, #f5f7fa);
  pointer-events: none;
}

.result-meta {
  font-size: calc(10px + var(--workspace-font-size-offset, 0px));
  color: #c0c4cc;
  font-weight: 400;
  margin-left: auto;
}
.tool-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.copy-btn {
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  padding: 0 4px;
  height: auto;
  color: #909399;
}
.copy-btn:hover { color: #409eff; }

.expand-result-btn {
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  padding: 2px 0;
  color: #909399;
  width: 100%;
  justify-content: center;
}
.expand-result-btn:hover { color: #409eff; }

@container (max-width: 560px) {
  .tool-io-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .tool-output-panel {
    border-top: 1px solid #e4e7ed;
    border-left: 0;
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
