<template>
  <el-dialog
    :model-value="dialogVisible"
    title="需要授权"
    width="560px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    append-to-body
    class="permission-dialog"
  >
    <div v-if="activePermission" class="dialog-content">
      <div class="dialog-heading">
        <el-icon class="dialog-icon" :class="{ warning: activePermission.tool_name === 'Bash' }">
          <WarningFilled v-if="activePermission.tool_name === 'Bash'" />
          <Tools v-else />
        </el-icon>
        <div class="dialog-title">
          <span class="dialog-tool">{{ activePermission.tool_name }}</span>
          <span class="dialog-message">{{ activePermission.message || '智能体请求使用该工具，请选择授权方式。' }}</span>
        </div>
      </div>

      <div class="dialog-detail">
        <span class="detail-label">参数</span>
        <code>{{ toolDetail(activePermission) }}</code>
      </div>
    </div>

    <template #footer>
      <div class="dialog-actions">
        <el-button
          v-for="action in activeActions"
          :key="action.key"
          :type="action.type"
          :plain="action.plain"
          :text="action.text"
          :disabled="submittingIds.includes(activePermission?.req_id)"
          @click="$emit('decide', activePermission, action.decision, action.remember)"
        >
          {{ action.label }}
        </el-button>
      </div>
    </template>
  </el-dialog>

</template>

<script setup>
import { computed } from 'vue'
import { WarningFilled, Tools } from '@element-plus/icons-vue'

const props = defineProps({
  permissions: { type: Array, default: () => [] },
  submittingIds: { type: Array, default: () => [] },
})

defineEmits(['decide'])

const defaultActions = [
  { key: 'deny-once', label: '本次拒绝', decision: 'deny', remember: false, type: 'danger', plain: true },
  { key: 'allow-session', label: '本轮始终允许', decision: 'allow', remember: true, type: 'success', plain: true },
  { key: 'allow-once', label: '本次允许', decision: 'allow', remember: false, type: 'primary' },
]

const normalizeAction = (action, index) => {
  const decision = action.decision || action.value || action.action
  if (!['allow', 'deny'].includes(decision)) return null
  const remember = Boolean(action.remember || action.scope === 'session' || action.key === 'allow-session')
  return {
    key: action.key || `${decision}-${remember ? 'session' : 'once'}-${index}`,
    label: action.label || action.text || (decision === 'allow' ? '本次允许' : '本次拒绝'),
    decision,
    remember,
    type: action.type || (decision === 'deny' ? 'danger' : 'primary'),
    plain: action.plain ?? (decision === 'deny' || (decision === 'allow' && remember)),
    text: action.textButton ?? action.text ?? false,
  }
}

const permissionActions = (p) => {
  const actions = Array.isArray(p.options) ? p.options : []
  const normalized = actions.map(normalizeAction).filter(Boolean)
  return normalized.length > 0 ? normalized : defaultActions
}

const activePermission = computed(() => props.permissions[0] || null)
const dialogVisible = computed(() => Boolean(activePermission.value))
const activeActions = computed(() => (
  activePermission.value ? permissionActions(activePermission.value) : []
))

const hasToolInput = (p) => {
  const inp = p?.tool_input
  return inp && typeof inp === 'object' && Object.keys(inp).length > 0
}

const toolDetail = (p) => {
  const inp = p.tool_input || {}
  if (inp.command) return inp.command
  if (inp.file_path) return inp.file_path
  if (inp.notebook_path) return inp.notebook_path
  if (inp.pattern) return inp.pattern
  if (inp.url) return inp.url
  return hasToolInput(p) ? JSON.stringify(inp, null, 2) : '无'
}
</script>

<style scoped>
.dialog-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dialog-heading {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 12px;
  border: 1px solid #fde2b5;
  border-radius: 8px;
  background: #fff8ed;
}

.dialog-icon {
  font-size: 24px;
  color: #409eff;
  flex-shrink: 0;
  margin-top: 2px;
}
.dialog-icon.warning {
  color: #e6a23c;
}

.dialog-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.dialog-tool {
  font-weight: 700;
  font-family: 'SF Mono', 'Courier New', monospace;
  color: #303133;
}

.dialog-message {
  color: #606266;
  line-height: 1.6;
}

.dialog-detail {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-label {
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  color: #909399;
}

.dialog-detail code {
  margin: 0;
  padding: 10px 12px;
  border-radius: 6px;
  background: #f5f7fa;
  color: #303133;
  font-family: 'SF Mono', 'Courier New', monospace;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.dialog-actions :deep(.el-button) {
  border-width: 1px;
  border-style: solid;
  font-weight: 600;
}

.dialog-actions :deep(.el-button--danger.is-plain) {
  color: #d93026;
  border-color: #d93026;
  background: #fff5f5;
}

.dialog-actions :deep(.el-button--danger.is-plain:hover) {
  color: #fff;
  border-color: #d93026;
  background: #d93026;
}

.dialog-actions :deep(.el-button--success.is-plain),
.dialog-actions :deep(.el-button--primary.is-plain) {
  color: #3b6ff5;
  border-color: #3b6ff5;
  background: #eef2ff;
}

.dialog-actions :deep(.el-button--success.is-plain:hover),
.dialog-actions :deep(.el-button--primary.is-plain:hover) {
  color: #fff;
  border-color: #3b6ff5;
  background: #3b6ff5;
}

</style>
