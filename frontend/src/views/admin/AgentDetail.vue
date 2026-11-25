<template>
  <div class="agent-detail" v-loading="loading && activeSection === 'basic'">
    <div class="agent-detail-body">
      <AgentWorkspaceNav
        v-if="!expertWorkspace"
        :agent="isEdit ? form : { ...form, name: form.name?.trim() || '未命名 Agent' }"
        :agent-id="route.params.id"
        :active="activeSection === 'basic' ? 'config' : activeSection"
      />

      <main class="config-scroll">
        <div class="config-content" :class="{ 'config-content--resources': activeSection !== 'basic' }">
        <ResourcePageHeader v-if="activeSection === 'basic'" :title="isEdit ? '基本信息' : '新建自定义 Agent'" class="config-header">
          <template #actions>
            <div class="header-actions">
            <el-button v-if="isEdit && basicLoaded && !publicAgent" :icon="Delete" type="danger" plain :disabled="loading || sharingLoading" @click="handleDelete">删除</el-button>
            <el-tooltip v-if="isEdit && basicLoaded && !publicAgent" :content="form.is_public ? '取消后，其他用户将无法继续使用此 Agent' : '公开后，其他用户可在工作台直接使用；绑定资源须为系统或公开资源'" placement="bottom">
              <el-button :icon="form.is_public ? Hide : View" :aria-label="form.is_public ? '设为私有' : '设为公开'" :type="form.is_public ? 'success' : 'info'" :loading="sharingLoading" :disabled="loading" @click="toggleSharing">
                {{ form.is_public ? '设为私有' : '设为公开' }}
              </el-button>
            </el-tooltip>
            <el-button :icon="Check" type="primary" :disabled="!!publicAgent || !basicLoaded || loading || sharingLoading" @click="handleSave">保存</el-button>
            </div>
          </template>
        </ResourcePageHeader>
    <el-alert v-if="loadError && activeSection === 'basic'" :title="loadError" type="error" :closable="false" show-icon>
      <el-button link type="primary" :disabled="loading" @click="fetchData">重新加载</el-button>
    </el-alert>
    <el-form :model="form" label-width="120px" label-position="right" class="config-form">
      <template v-if="activeSection === 'basic'">
      <el-card id="agent-basic" class="section" shadow="never">
        <template #header><span>基本信息</span></template>
        <el-form-item label="名称" required>
          <el-input :readonly="!!publicAgent" v-model="form.name" placeholder="如：代码助手" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input :readonly="!!publicAgent" v-model="form.description" type="textarea" :rows="2" placeholder="一句话描述这个 Agent 的用途" />
        </el-form-item>
        <el-form-item label="头像">
          <AgentAvatarSetting v-model="form.icon" :disabled="!!publicAgent" />
        </el-form-item>
        <el-form-item label="默认模型" v-if="compatibleModels.length > 0">
          <el-select :disabled="!!publicAgent" v-model="form.default_model_id" placeholder="选择默认模型" filterable>
            <el-option
              v-for="m in compatibleModels"
              :key="m.id"
              :label="getModelOptionLabel(m)"
              :value="m.id"
              :disabled="form.is_public && m.scope !== 'platform'"
            >
              <div class="model-option-content">
                <span class="model-option-name">{{ m.name }}</span>
                <span class="model-option-meta">{{ getModelOptionMeta(m) }}</span>
              </div>
            </el-option>
          </el-select>
          <div class="hint">对话时默认使用的模型，用户可在聊天中切换。设为公开前，须选择平台模型并保存；公开期间默认模型仅支持平台模型。</div>
        </el-form-item>
      </el-card>

      <el-card id="agent-identity" class="section" shadow="never">
        <template #header><span>身份设置</span></template>
        <IdentityPromptTemplatePicker v-model="form.system_prompt" :disabled="!!publicAgent" />
        <el-form-item label="系统提示词">
          <MarkdownEditor v-model="form.system_prompt" :read-only="!!publicAgent" :placeholder="systemPromptPlaceholder" />
          <div class="hint">{{ systemPromptHint }}</div>
        </el-form-item>
      </el-card>

      </template>

      <AssetCenter v-else-if="activeSection === 'skills'" workspace-view="skills" workspace-title="技能市场" :agent-id="route.params.id" />
      <AssetCenter v-else-if="activeSection === 'prompts'" workspace-view="prompts" workspace-title="提示词库" :agent-id="route.params.id" />
      <AssetCenter v-else-if="activeSection === 'mcp'" workspace-view="mcp" workspace-title="连接器" :agent-id="route.params.id" />
    </el-form>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import AgentAvatarSetting from '@/components/AgentAvatarSetting.vue'
import { ref, computed, h, inject, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Check, Delete, Hide, View,
} from '@element-plus/icons-vue'
import api from '@/api/request'
import IdentityPromptTemplatePicker from '@/components/IdentityPromptTemplatePicker.vue'
import { enterpriseApi } from '@/api/enterprise'
import ResourcePageHeader from './components/ResourcePageHeader.vue'
import AgentWorkspaceNav from './components/AgentWorkspaceNav.vue'
import AssetCenter from './AgentResourceAccess.vue'
import {
  getCompatibleModelsForRuntime,
  getModelOptionLabel,
  getModelOptionMeta,
} from '@/config/models'

const route = useRoute()
const expertWorkspace = inject('expertWorkspace', null)
const router = useRouter()
const isEdit = computed(() => !!route.params.id)
const loading = ref(false)
const basicLoaded = ref(false)
const publicAgent = ref(null)
const loadError = ref('')
const validSections = new Set(['basic', 'skills', 'prompts', 'mcp'])
const activeSection = ref(validSections.has(route.query.section) ? route.query.section : 'basic')
watch(() => route.query.section, value => {
  activeSection.value = validSections.has(value) ? value : 'basic'
})

const form = reactive({
  id: null,
  name: '',
  description: '',
  icon: '',
  system_prompt: '',
  default_model_id: null,
  runtime_type: 'claude_code',
  thinking_level: 'inherit',
  reasoning_visibility: 'off',
  max_turns: 50,
  timeout_seconds: 600,
  skill_ids: [],
  mcp_ids: [],
  prompt_template_ids: [],
  is_public: false,
})

const allModels = ref([])
const sharingLoading = ref(false)
const systemPromptPlaceholder = '定义这个 Agent 是谁、擅长什么、语气风格。'
const systemPromptHint = '每次对话都会加载这个 Agent 的系统提示词'

// The model catalog is shared with the workbench; this editor only chooses
// a default model and must not prune inherited models when loading.
const compatibleModels = computed(() => getCompatibleModelsForRuntime(
  allModels.value,
  form.runtime_type,
))

const fetchData = async () => {
  loading.value = true
  basicLoaded.value = false
  loadError.value = ''
  try {
    const [models, agentOrSettings] = await Promise.all([
      api.get('/models'),
      isEdit.value ? api.get(`/agents/${route.params.id}`) : enterpriseApi.getAgentRuntimeSettings(),
    ])
    form.runtime_type = agentOrSettings?.runtime_type || 'claude_code'
    allModels.value = models.items || models
    if (!isEdit.value) {
      // Expert agents inherit the workbench catalog. Pick the first runtime
      // compatible model automatically so creation never requires a model
      // selection step.
      const firstModel = getCompatibleModelsForRuntime(
        allModels.value,
        form.runtime_type,
      )[0]
      form.default_model_id = firstModel?.id || null
    }

    if (isEdit.value) {
      const agent = agentOrSettings
      publicAgent.value = agent.can_edit === false ? agent : null
      if (expertWorkspace) expertWorkspace.agent.value = agent
      Object.assign(form, {
        id: agent.id,
        name: agent.name,
        description: agent.description || '',
        icon: agent.icon || '',
        system_prompt: agent.system_prompt || '',
        default_model_id: agent.default_model_id,
        runtime_type: agent.runtime_type || 'claude_code',
        thinking_level: agent.thinking_level || 'inherit',
        reasoning_visibility: agent.reasoning_visibility === 'off' ? 'off' : 'stream',
        max_turns: agent.max_turns || 50,
        timeout_seconds: agent.timeout_seconds || 600,
        skill_ids: agent.skill_ids || [],
        mcp_ids: agent.mcp_ids || [],
        prompt_template_ids: agent.prompt_template_ids || [],
        is_public: Boolean(agent.is_public),
      })
    }
    basicLoaded.value = true
  } catch (e) {
    const detail = e.response?.data?.detail
    loadError.value = '加载失败：' + (typeof detail === 'string' ? detail : (detail?.message || e.message))
  } finally {
    loading.value = false
  }
}

const toggleSharing = async () => {
  if (!isEdit.value || !basicLoaded.value || loading.value || sharingLoading.value || publicAgent.value) return
  sharingLoading.value = true
  try {
    const result = await api.post(`/agents/${route.params.id}/${form.is_public ? 'unpublish' : 'publish'}`)
    form.is_public = Boolean(result.is_public)
    if (expertWorkspace) expertWorkspace.agent.value = result
    ElMessage.success(form.is_public ? 'Agent 已公开' : '已取消公开')
  } catch (e) {
    const body = e.response?.data
    const detail = body?.detail
    const message = typeof detail === 'string' ? detail : detail?.message
    const items = body?.data?.items || detail?.data?.items || detail?.items
    const resources = Array.isArray(items) ? [...new Set(items.filter(item => typeof item === 'string' && item.trim()))] : []
    if (resources.length) {
      await ElMessageBox.alert(h('div', [
        h('p', { style: { margin: '0 0 12px' } }, '请先将以下资源设为公开，再重试：'),
        h('ul', { style: { margin: 0, paddingLeft: '20px', maxHeight: '40vh', overflowY: 'auto', overflowWrap: 'anywhere' } },
          resources.map(item => h('li', { style: { marginBottom: '8px' } }, item))),
      ]), '无法设为公开', { type: 'warning', confirmButtonText: '知道了' }).catch(() => {})
    } else {
      ElMessage.error({ message: message || body?.message || '共享设置更新失败', grouping: true })
    }
  } finally {
    sharingLoading.value = false
  }
}

const handleDelete = async () => {
  if (!isEdit.value || !basicLoaded.value || publicAgent.value || loading.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除 Agent “${form.name}”？删除后将停止运行中的任务并清理相关配置。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    loading.value = true
    await api.delete(`/agents/${route.params.id}`)
    ElMessage.success('已删除')
    await router.replace('/admin/agents')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(e.response?.data?.detail || '删除失败')
    }
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  if (!basicLoaded.value || loading.value || publicAgent.value) return
  if (!form.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  loading.value = true
  try {
    const payload = { ...form }
    for (const field of ['runtime_type', 'thinking_level', 'reasoning_visibility', 'max_turns', 'timeout_seconds']) delete payload[field]
    delete payload.id
    delete payload.model_ids
    delete payload.skill_ids
    delete payload.prompt_template_ids
    // MCPs are installed as user-scoped connections after the agent exists;
    // credentials never travel through the shared agent payload.
    delete payload.mcp_ids
    delete payload.mcp_overrides

    let savedAgent
    if (isEdit.value) {
      try {
        savedAgent = await api.put(`/agents/${route.params.id}`, payload)
      } catch (error) {
        const body = error.response?.data
        const confirmation = body?.data || body?.detail?.data
        if (error.response?.status !== 409 || confirmation?.code !== 'RUNTIME_CHANGE_CONFIRMATION_REQUIRED') throw error
        try {
          await ElMessageBox.confirm('更换 runtime 将强制终止此 Agent 的所有未结束任务（包括其他用户正在使用的任务），清空工作区文件，并重置会话运行状态。未完成的输出将丢失，是否确认？', '提示', {
            type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消',
          })
        } catch {
          return
        }
        savedAgent = await api.put(`/agents/${route.params.id}`, {
          ...payload, confirm_runtime_change: confirmation.target_runtime,
        })
      }
      form.runtime_type = savedAgent.runtime_type
      ElMessage.success('已保存')
    } else {
      savedAgent = await api.post('/agents', payload)
      ElMessage.success('已创建')
      router.replace(`/admin/agents/${savedAgent.id}`)
    }
    if (savedAgent.id && isEdit.value) {
      if (expertWorkspace) expertWorkspace.agent.value = savedAgent
    }
  } catch (e) {
    const body = e.response?.data
    const detail = body?.detail
    ElMessage.error('保存失败：' + (typeof detail === 'string' ? detail : (detail?.message || body?.message || e.message)))
  } finally {
    loading.value = false
  }
}

// Resource panels own their loading state; fetch the editor only when it is opened.
watch(activeSection, section => {
  if (section === 'basic' && !basicLoaded.value && !loading.value) fetchData()
}, { immediate: true })

watch(() => route.params.id, () => {
  basicLoaded.value = false
  loadError.value = ''
  if (activeSection.value === 'basic' && !loading.value) fetchData()
})
</script>

<style scoped>
.agent-detail {
  height: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}

.agent-detail-body {
  min-height: 0;
  flex: 1;
  display: flex;
}

.config-scroll {
  min-width: 0;
  flex: 1;
  overflow: auto;
  scroll-behavior: smooth;
  background: #fff;
}

.config-content {
  width: min(100%, 1304px);
  margin: 0 auto;
  padding: 28px 32px 48px;
  box-sizing: border-box;
}

.config-content--resources {
  width: 100%;
}

.model-option-content {
  width: 100%;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.model-option-name {
  overflow: hidden;
  text-overflow: ellipsis;
}

.model-option-meta {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  color: #909399;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.header h2 {
  margin: 0;
  flex: 1;
}

.header-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.channel-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.channel-status-badge {
  display: inline-flex;
}

:deep(.channel-status-badge .el-badge__content) {
  --el-badge-size: 19px;
  white-space: nowrap;
  /* 徽章搭在按钮右上角：上移 65% 抵消中文视觉下沉、右探 30% 形成角标感 */
  transform: translateY(-65%) translateX(30%);
}

.section {
  margin: 0;
  border: 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  border-radius: 0;
  scroll-margin-top: 12px;
}

.config-form .section:last-child {
  border-bottom: 0;
}

:deep(.section > .el-card__header) {
  padding: 28px 0 16px;
  border-bottom: 0;
  color: var(--el-text-color-primary);
  font-size: 16px;
  font-weight: 600;
}

:deep(.section > .el-card__body) {
  padding: 0 0 32px;
}

.section-hint {
  margin-left: 12px;
  font-size: 12px;
  color: #999;
  font-weight: normal;
}

.full-width { width: 100%; }

.mcp-credentials {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.mcp-credentials-note {
  margin-top: 16px;
}

.mcp-credentials-link {
  margin-top: 8px;
}

.mcp-credentials-toolbar,
.mcp-group-toolbar,
.mcp-config-title {
  display: flex;
  align-items: center;
}

.mcp-credentials-toolbar {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.mcp-credentials-title {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 600;
}

.mcp-config-list {
  margin-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}

:deep(.mcp-config-list .el-collapse-item__header) {
  min-height: 52px;
  height: auto;
  line-height: 1.4;
}

:deep(.mcp-config-list .el-collapse-item__content) {
  padding-bottom: 18px;
}

.mcp-config-title {
  min-width: 0;
  flex: 1;
  gap: 8px;
  padding-right: 12px;
}

.mcp-config-name {
  min-width: 0;
  overflow: hidden;
  color: var(--el-text-color-primary);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-config-count {
  margin-left: auto;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.mcp-config-body {
  padding: 2px 12px 0;
}

.mcp-credential-group + .mcp-credential-group {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--el-border-color-extra-light);
}

.mcp-group-toolbar {
  justify-content: space-between;
  gap: 12px;
  min-height: 32px;
  margin-bottom: 10px;
}

.mcp-group-title {
  color: var(--el-text-color-regular);
  font-size: 13px;
  font-weight: 600;
}

.mcp-group-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.mcp-group-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.mcp-credential-row {
  display: grid;
  grid-template-columns: minmax(180px, 0.8fr) minmax(240px, 1.4fr) 32px;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.mcp-key-control {
  width: 100%;
}

.mcp-key-control :deep(.el-input__inner),
.mcp-key-control :deep(.el-select__selected-item) {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 13px;
}

.mcp-empty-state {
  padding: 18px 12px;
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  text-align: center;
}

@media (max-width: 900px) {
  .config-content {
    padding: 22px 16px 36px;
  }
}

@media (max-width: 720px) {
  .agent-detail-body {
    flex-direction: column;
  }

  .config-header {
    flex-wrap: wrap;
    gap: 12px;
  }

  :deep(.section > .el-card__header) {
    padding-top: 22px;
  }

  :deep(.section > .el-card__body) {
    padding-bottom: 26px;
  }

  .mcp-credentials-toolbar,
  .mcp-group-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .mcp-group-actions {
    justify-content: flex-start;
    width: 100%;
  }

  .mcp-credential-row {
    grid-template-columns: 1fr 32px;
  }

  .mcp-credential-row > :nth-child(2) {
    grid-column: 1;
    grid-row: 2;
  }

  .mcp-credential-row > :last-child {
    grid-column: 2;
    grid-row: 1;
  }

  .mcp-config-body {
    padding-right: 4px;
    padding-left: 4px;
  }
}

.hint {
  flex: 0 0 100%;
  width: 100%;
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.reasoning-select {
  width: min(320px, 100%);
}

.reasoning-hint {
  margin-left: 12px;
}

.reasoning-segmented {
  max-width: 100%;
}

.reasoning-note {
  width: 100%;
}

.runtime-status-panel {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.runtime-status-main,
.runtime-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.runtime-status-main span {
  color: #606266;
  font-size: 13px;
}

.runtime-error {
  padding: 8px 10px;
  border-left: 3px solid #f56c6c;
  background: #fef0f0;
  color: #c45656;
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

/* 技能/MCP 穿梭框加宽 */
:deep(.el-transfer) {
  width: 100%;
  display: flex;
  align-items: center;
}

:deep(.el-transfer-panel) {
  width: 0;
  min-width: 0;
  flex: 1 1 0;
}

:deep(.el-transfer__buttons) {
  width: 72px;
  padding: 0 16px;
  display: flex;
  flex: 0 0 72px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  box-sizing: border-box;
}

:deep(.el-transfer__button:nth-child(2)) {
  margin: 0;
}

@media (max-width: 720px) {
  .header { align-items: flex-start; flex-wrap: wrap; }
  .header-actions { width: 100%; }
  .reasoning-hint { width: 100%; margin-left: 0; }
}
</style>
