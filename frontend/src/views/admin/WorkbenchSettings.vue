<template>
  <div class="settings-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>默认助手设置</h1>
        <p v-if="activeTab !== 'resources'" class="settings-status">
          <span v-if="!settingsLoaded">设置尚未加载</span>
          <span v-else-if="published">当前已发布 v{{ published.version }} · {{ formatTime(published.published_at) }}</span>
          <span v-else>尚未发布</span>
          <el-tag v-if="draft" size="small" type="warning" effect="plain">草稿 v{{ draft.version }} 待发布</el-tag>
          <span v-if="draft">保存人：{{ userName(draft.created_by) }} · {{ formatTime(draft.updated_at) }}</span>
          <el-tag v-if="isDirty" size="small" type="info" effect="plain">有未保存修改</el-tag>
        </p>
        <p v-else>仅配置默认助手使用的技能、MCP 和提示词。自定义 Agent 的资源由各智能体独立维护。</p>
      </div>
      <div v-if="activeTab !== 'resources'" class="heading-actions">
        <el-button :icon="Refresh" :disabled="loading || saving || publishing || iconUploading || mascotUploading" @click="load">刷新</el-button>
        <el-button
          type="primary"
          :icon="Promotion"
          :loading="publishing"
          :disabled="!canPublish || saving || publishing || iconUploading || mascotUploading"
          @click="publish"
        >
          {{ draft ? '发布草稿' : '保存并发布' }}
        </el-button>
        <el-button :icon="Clock" @click="openHistory">发布历史</el-button>
      </div>
    </div>

    <el-alert v-if="loadError && activeTab !== 'resources'" :title="loadError" type="error" :closable="false" show-icon />
    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="基本信息" name="assistant">
        <el-form :model="form" :disabled="editingLocked" label-width="120px" label-position="right" class="settings-form">
          <el-card class="settings-section" shadow="never">
            <template #header><span>基本信息</span></template>
            <el-form-item label="名称" required>
              <el-input v-model="form.assistant_name" maxlength="200" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="form.assistant_description" type="textarea" :rows="2" maxlength="20000" />
            </el-form-item>
            <el-form-item label="头像" required>
              <AgentAvatarSetting v-model="form.assistant_icon" :disabled="editingLocked" show-characters @uploading="value => iconUploading = value" />
            </el-form-item>
            <el-form-item label="悬浮小精灵" required>
              <AssistantCharacterPicker v-model="form.assistant_mascot" :disabled="editingLocked" :allow-text="false" @uploading="value => mascotUploading = value" />
            </el-form-item>
            <el-form-item label="默认模型" required>
              <el-select v-model="form.default_model_id" placeholder="选择已启用的平台模型">
                <el-option
                  v-for="model in enabledModels"
                  :key="model.id"
                  :label="model.name"
                  :value="model.id"
                />
              </el-select>
              <div v-if="!enabledModels.length && settingsLoaded" class="setting-hint">暂无可用的平台模型，请先在智能体设置中配置已启用且兼容的模型。</div>
            </el-form-item>
          </el-card>
          <el-card class="settings-section" shadow="never">
            <template #header><span>身份设置</span></template>
            <IdentityPromptTemplatePicker v-model="form.system_prompt" :disabled="editingLocked" />
            <el-form-item label="系统提示词">
              <MdPreview v-if="editingLocked" :model-value="form.system_prompt?.trim() || '无'" class="system-prompt-preview" />
              <MarkdownEditor v-else v-model="form.system_prompt" class="system-prompt-editor"
                editor-id="workbench-system-prompt" language="zh-CN" :max-length="200000"
                placeholder="定义这个助手是谁、擅长什么、语气风格。支持 Markdown 格式。" />
              <div class="setting-hint">每次对话都会加载默认助手的系统提示词</div>
            </el-form-item>
          </el-card>
          <el-form-item>
            <el-button type="primary" :icon="DocumentChecked" :loading="saving" :disabled="editingLocked || iconUploading || mascotUploading" @click="saveDraft">
              保存草稿
            </el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="系统资源" name="resources" lazy>
        <AssetCenter system-mode embedded />
      </el-tab-pane>

    </el-tabs>
    <el-dialog v-model="historyVisible" title="发布历史" width="92vw" top="5vh" class="workbench-publication-dialog">
      <el-alert v-if="historyError" :title="historyError" type="error" :closable="false" show-icon />
      <el-table v-loading="historyLoading" :data="historyItems" empty-text="无" class="history-table" height="100%">
        <el-table-column label="版本" width="100">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">{{ row.status === 'published' ? '当前已发布' : '历史版本' }}</template>
        </el-table-column>
        <el-table-column label="修改项" min-width="200">
          <template #default="{ row }">{{ changedFieldNames(row.changes) }}</template>
        </el-table-column>
        <el-table-column label="草稿保存人" min-width="140">
          <template #default="{ row }">{{ userName(row.created_by) }}</template>
        </el-table-column>
        <el-table-column label="发布人" min-width="140">
          <template #default="{ row }">{{ userName(row.published_by) }}</template>
        </el-table-column>
        <el-table-column label="发布时间" min-width="200">
          <template #default="{ row }">{{ formatTime(row.published_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="viewRelease(row)">查看变更</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="historyPage" :page-size="HISTORY_PAGE_SIZE" :total="historyTotal"
        layout="total, prev, pager, next" :disabled="historyLoading" @current-change="loadHistory" />
    </el-dialog>
    <el-dialog v-model="releaseVisible" :title="`发布变更 · v${selectedRelease?.version ?? ''}`"
      width="92vw" top="5vh" class="workbench-publication-dialog" append-to-body destroy-on-close>
      <div v-if="selectedRelease" class="release-content">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="发布时间">{{ formatTime(selectedRelease.published_at) }}</el-descriptions-item>
          <el-descriptions-item label="发布人">{{ userName(selectedRelease.published_by) }}</el-descriptions-item>
          <el-descriptions-item label="草稿保存人">{{ userName(selectedRelease.created_by) }}</el-descriptions-item>
        </el-descriptions>
        <section v-for="(change, field) in selectedRelease.changes" :key="field" class="release-change">
          <h3 class="release-prompt-title">{{ CHANGE_LABELS[field] || field }}</h3>
          <div class="release-change-values">
            <div v-for="side in CHANGE_SIDES" :key="side.key" class="release-change-value">
              <h4>{{ side.label }}</h4>
              <div class="release-value-content">
                <el-tooltip :content="`复制${side.label}内容`" placement="top">
                  <el-button class="release-copy-button" :icon="CopyDocument" circle text
                    :aria-label="`复制${CHANGE_LABELS[field] || field}${side.label}内容`"
                    :disabled="copyingRelease || isEmptyChange(change[side.key])"
                    @click="copyReleaseValue(field, change[side.key])" />
                </el-tooltip>
                <span v-if="isAppearance(field) && change[side.key]?.trim()" class="release-avatar">
                  <AssistantIcon :icon="change[side.key]" />
                </span>
                <pre v-else class="release-prompt-source">{{ changeValue(field, change[side.key]) }}</pre>
              </div>
            </div>
          </div>
        </section>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Clock, CopyDocument, DocumentChecked, Promotion, Refresh, View } from '@element-plus/icons-vue'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import { enterpriseApi } from '@/api/enterprise'
import { adminApi } from '@/api/admin'
import { getCompatibleModelsForRuntime } from '@/config/models'
import AssetCenter from './AssetCenter.vue'
import AssistantCharacterPicker from '@/components/AssistantCharacterPicker.vue'
import AgentAvatarSetting from '@/components/AgentAvatarSetting.vue'
import AssistantIcon from '@/components/AssistantIcon.vue'
import IdentityPromptTemplatePicker from '@/components/IdentityPromptTemplatePicker.vue'

const route = useRoute()
const activeTab = ref(route.query.tab === 'resources' ? 'resources' : 'assistant')
const loading = ref(false)
const settingsLoaded = ref(false)
const loadError = ref('')
const saving = ref(false)
const publishing = ref(false)
const iconUploading = ref(false)
const mascotUploading = ref(false)
const draft = ref(null)
const published = ref(null)
const models = ref([])
const HISTORY_PAGE_SIZE = 20
const historyVisible = ref(false)
const historyLoading = ref(false)
const historyError = ref('')
const historyItems = ref([])
const historyPage = ref(1)
const historyTotal = ref(0)
const releaseVisible = ref(false)
const selectedRelease = ref(null)
const displayValue = value => value == null || (typeof value === 'string' && !value.trim()) ? '无' : value
const CHANGE_LABELS = {
  assistant_name: '名称', assistant_description: '描述', assistant_icon: '头像',
  assistant_mascot: '悬浮小精灵', default_model_id: '默认模型 ID',
  noun_highlight_enabled: '名词解释高亮', noun_explanation_url: '名词解释链接',
  system_prompt: '系统提示词',
}
const changedFieldNames = changes => Object.keys(changes || {}).map(field => CHANGE_LABELS[field] || field).join('、') || '无'
const CHANGE_SIDES = [{ key: 'before', label: '修改前' }, { key: 'after', label: '修改后' }]
const isAppearance = field => field === 'assistant_icon' || field === 'assistant_mascot'
const changeValue = (field, value) => field === 'noun_highlight_enabled' && value != null
  ? (value ? '开启' : '关闭') : displayValue(value)
const copyingRelease = ref(false)
const isEmptyChange = value => value == null || (typeof value === 'string' && !value.trim())
const copyReleaseValue = async (field, value) => {
  if (copyingRelease.value || isEmptyChange(value)) return
  copyingRelease.value = true
  try {
    await navigator.clipboard.writeText(String(changeValue(field, value)))
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败，请检查浏览器剪贴板权限')
  } finally {
    copyingRelease.value = false
  }
}
const viewRelease = row => {
  selectedRelease.value = { ...row }
  releaseVisible.value = true
}
const usersById = reactive({})
const userName = id => id == null ? '无' : (
  usersById[id]?.first_name?.trim() || usersById[id]?.username?.trim() || `用户 ${id}`
)
const loadUserNames = async items => {
  const ids = [...new Set(items.flatMap(item => [item?.created_by, item?.published_by]))]
    .filter(id => id != null && !usersById[id])
  if (!ids.length) return
  try {
    const result = await adminApi.getUsers({ ids: ids.join(','), limit: ids.length })
    for (const user of result.items || result) usersById[user.id] = user
  } catch { /* Directory access is optional; retain user identifiers on failure. */ }
}
const loadHistory = async () => {
  if (historyLoading.value) return
  historyLoading.value = true
  historyError.value = ''
  try {
    const result = await enterpriseApi.getWorkbenchSettingsHistory({
      skip: (historyPage.value - 1) * HISTORY_PAGE_SIZE, limit: HISTORY_PAGE_SIZE,
    })
    historyItems.value = result.items
    historyTotal.value = result.total
    await loadUserNames(result.items)
  } catch (error) {
    historyItems.value = []
    historyError.value = errorText(error)
  } finally { historyLoading.value = false }
}
const openHistory = () => {
  if (historyVisible.value) return
  historyVisible.value = true
  historyPage.value = 1
  loadHistory()
}
const savedPayloadSignature = ref('')
const defaults = {
  assistant_name: 'AI 助手', assistant_icon: 'H', assistant_mascot: '@cow',
  assistant_description: '', system_prompt: '', default_model_id: null,
}
const form = reactive({ ...defaults })
const enabledModels = computed(() => getCompatibleModelsForRuntime(
  models.value.filter(model => model.is_enabled && model.has_api_key), 'claude_code',
))
const settingsPayload = () => Object.fromEntries(Object.keys(defaults).map(key => [key, form[key]]))
const signature = () => JSON.stringify(settingsPayload())
const isDirty = computed(() => settingsLoaded.value && signature() !== savedPayloadSignature.value)
const editingLocked = computed(() => !settingsLoaded.value || loading.value || saving.value || publishing.value || Boolean(draft.value))
const canPublish = computed(() => settingsLoaded.value && !loading.value)
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN') : '无'
const errorText = error => {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : (detail?.message || '操作失败')
}
const applySettings = settings => {
  loadError.value = ''
  draft.value = settings.draft
  published.value = settings.published
  Object.assign(form, defaults, settings.draft || settings.published || {})
  savedPayloadSignature.value = signature()
  settingsLoaded.value = true
  loadUserNames([settings.draft, settings.published])
}
const load = async () => {
  loading.value = true
  settingsLoaded.value = false
  loadError.value = ''
  try {
    const [settings, result] = await Promise.all([
      enterpriseApi.getWorkbenchSettings(), enterpriseApi.getPlatformModels(),
    ])
    applySettings(settings)
    models.value = result.items || []
  } catch (error) {
    loadError.value = `${errorText(error)}，请点击刷新重试`
  } finally {
    loading.value = false
  }
}
const saveDraft = async () => {
  if (editingLocked.value || iconUploading.value || mascotUploading.value) return
  saving.value = true
  try {
    const saved = await enterpriseApi.saveWorkbenchSettings(settingsPayload())
    applySettings({ draft: saved, published: published.value })
    ElMessage.success('草稿已保存')
  } catch (error) { ElMessage.error(errorText(error)) }
  finally { saving.value = false }
}
const publish = async () => {
  if (!canPublish.value || saving.value || publishing.value || iconUploading.value || mascotUploading.value) return
  if (!form.assistant_name?.trim() || !form.assistant_icon?.trim() || !form.default_model_id) {
    activeTab.value = 'assistant'
    ElMessage.warning('请填写名称、头像并选择默认平台模型')
    return
  }
  if (!enabledModels.value.some(model => model.id === form.default_model_id)) {
    activeTab.value = 'assistant'
    ElMessage.warning('当前默认模型不可用，请重新选择已启用且兼容的平台模型')
    return
  }
  publishing.value = true
  try {
    await ElMessageBox.confirm('新用户将使用这版默认助手，已有用户下次进入 AI 工作台时同步更新。', draft.value ? '发布待发布草稿' : '保存并发布默认助手设置', { type: 'warning' })
  } catch {
    publishing.value = false
    return
  }
  try {
    const saved = await enterpriseApi.publishWorkbenchSettings(draft.value ? undefined : settingsPayload())
    applySettings({ draft: null, published: saved })
    ElMessage.success('默认助手设置已发布')
  } catch (error) { ElMessage.error(errorText(error)) }
  finally { publishing.value = false }
}
onMounted(load)
</script>

<style scoped>
.system-prompt-editor { width: 100%; height: 560px; min-width: 0; }
.system-prompt-preview { width: 100%; max-height: 560px; overflow: auto; }
:global(.workbench-publication-dialog) { height: 90vh; display: flex; flex-direction: column; }
:global(.workbench-publication-dialog .el-dialog__body) { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.history-table { flex: 1; min-height: 0; }
.release-content { flex: 1; min-height: 0; overflow: auto; }
.release-content :deep(.el-descriptions__cell) { overflow-wrap: anywhere; }
.release-prompt-source { white-space: pre-wrap; overflow-wrap: anywhere; }
.release-change-values { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.release-change-value { min-width: 0; }
.release-value-content { position: relative; min-height: 48px; background: var(--el-fill-color-light); }
.release-copy-button { position: absolute; top: 4px; right: 4px; width: 32px; height: 32px; }
.release-change-value h4 { margin: 0 0 8px; font-size: 14px; color: var(--el-text-color-secondary); }
.release-avatar { display: inline-flex; width: 44px; height: 44px; align-items: center; justify-content: center; }
.release-prompt-title { margin: 24px 0 8px; font-size: 16px; }
.release-prompt-source { margin: 0; padding: 16px 48px 16px 16px; font: 14px/1.7 monospace; }
.el-pagination { margin-top: 16px; justify-content: flex-end; }
.settings-page { max-width: 1400px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.page-heading h1 { margin: 0; color: #1f2937; font-size: 24px; letter-spacing: 0; }
.page-heading p { margin: 7px 0 0; color: #667085; font-size: 13px; }
.settings-status { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.heading-actions { display: flex; gap: 10px; }
.settings-tabs { border-top: 1px solid #e5e7eb; }
.settings-form { max-width: 1240px; }
.settings-section { margin: 0; border: 0; border-radius: 0; background: transparent; }
.settings-section + .settings-section { border-top: 1px solid var(--el-border-color-lighter); }
:deep(.settings-section > .el-card__header) { padding: 28px 0 16px; border-bottom: 0; color: var(--el-text-color-primary); font-size: 16px; font-weight: 600; }
:deep(.settings-section > .el-card__body) { padding: 0 0 32px; }
.el-select { width: 100%; }
.setting-hint { flex: 0 0 100%; width: 100%; margin-top: 8px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
@media (max-width: 760px) {
  .release-change-values { grid-template-columns: minmax(0, 1fr); }
  .page-heading { align-items: stretch; flex-direction: column; }
  .heading-actions { flex-wrap: wrap; }
  :deep(.settings-section > .el-card__header) { padding-top: 22px; }
  :deep(.settings-section > .el-card__body) { padding-bottom: 26px; }
}
</style>
