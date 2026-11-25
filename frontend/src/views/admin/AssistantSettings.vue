<template>
  <div class="settings-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>智能体设置</h1>
        <p class="settings-status">
          <span v-if="!settingsLoaded">设置尚未加载</span>
          <span v-else-if="published">当前已生效 v{{ published.version }} · {{ formatTime(published.published_at) }}</span>
          <span v-else>尚未生效</span>
          <el-tag v-if="draft" size="small" type="warning" effect="plain">草稿 v{{ draft.version }} 待生效</el-tag>
          <el-tag v-if="isDirty" size="small" type="info" effect="plain">有未保存修改</el-tag>
        </p>
      </div>
      <div class="heading-actions">
        <el-button :icon="Refresh" :disabled="loading || saving || publishing || modelSaving" @click="load">刷新</el-button>
        <el-button
          type="primary"
          :icon="Promotion"
          :loading="publishing"
          :disabled="!canPublish || saving || publishing || modelSaving"
          @click="publish"
        >
          保存并生效
        </el-button>
      </div>
    </div>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="Runtime 设置" name="runtime">
        <el-form :model="form" :disabled="!settingsLoaded || saving || publishing" label-position="top" class="settings-form">
          <section class="assistant-section" aria-labelledby="assistant-runtime-heading">
            <p class="runtime-scope-hint">以下配置统一应用于 AI 工作台、自定义 Agent 和消息渠道。</p>
            <div class="form-grid">
              <el-form-item label="Runtime">
                <el-segmented v-model="form.runtime_type" :options="runtimeOptions" />
              </el-form-item>
              <el-form-item label="推理强度">
                <el-select v-model="form.thinking_level">
                  <el-option v-for="option in thinkingLevelOptions" :key="option.value" :label="option.label" :value="option.value" />
                </el-select>
                <div class="setting-hint">实际档位仍受所选模型能力限制</div>
              </el-form-item>
              <el-form-item label="最大轮次">
                <el-input-number v-model="form.max_turns" :min="1" :max="200" />
              </el-form-item>
              <el-form-item label="推理过程显示">
                <el-segmented v-model="form.reasoning_visibility" :options="reasoningVisibilityOptions" />
                <div class="setting-hint">外部消息渠道始终隐藏；显示时实时展示，推理完成后自动收起</div>
              </el-form-item>
              <el-form-item label="超时（秒）">
                <el-input-number v-model="form.timeout_seconds" :min="60" :max="3600" :step="60" />
              </el-form-item>
              <el-form-item label="单用户并发运行数">
                <el-input-number v-model="form.max_concurrent_runs" :min="1" :max="20" />
              </el-form-item>
            </div>
          </section>

          <el-button type="primary" :icon="DocumentChecked" :loading="saving" :disabled="!isDirty || loading || publishing || modelSaving" @click="saveDraft">保存草稿</el-button>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="积分策略" name="credits">
        <el-alert title="按模型返回的 Token 用量实时扣除积分，不预占额度；积分用尽时自动终止运行。" type="info" :closable="false" />
        <el-form :model="form" :disabled="!settingsLoaded || saving || publishing" label-position="top" class="settings-form">
          <div class="form-grid">
            <el-form-item label="界面名称">
              <el-input v-model="form.credit_display_name" maxlength="50" />
            </el-form-item>
            <el-form-item label="英文名称">
              <el-input v-model="form.credit_display_name_en" maxlength="50" />
            </el-form-item>
            <el-form-item label="新用户开箱额度">
              <el-input-number v-model="form.initial_claim_amount" :min="0" :step="0.01" :precision="2" :controls="false" />
            </el-form-item>
            <el-form-item label="每日领取额度">
              <el-input-number v-model="form.daily_claim_amount" :min="0" :step="0.01" :precision="2" :controls="false" />
            </el-form-item>

            <el-form-item label="低余额提醒值">
              <el-input-number v-model="form.low_balance_threshold" :min="0" :step="0.01" :precision="2" :controls="false" />
            </el-form-item>
            <el-form-item label="领取时区">
              <el-input v-model="form.claim_timezone" maxlength="50" />
            </el-form-item>
          </div>
          <el-button type="primary" :icon="DocumentChecked" :loading="saving" :disabled="!isDirty || loading || publishing || modelSaving" @click="saveDraft">
            保存草稿
          </el-button>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="积分充值" name="recharge">
        <CreditRecharge :published-settings="published" />
      </el-tab-pane>

      <el-tab-pane label="平台模型" name="models">
        <div class="table-toolbar">
          <el-button type="primary" :icon="Plus" @click="openModelDialog()">新增平台模型</el-button>
        </div>
        <el-table :data="models" border>
          <el-table-column label="模型" min-width="180"><template #default="{ row }">{{ row.name?.trim() || '无' }}</template></el-table-column>
          <el-table-column label="提供方" width="130"><template #default="{ row }">{{ row.provider?.trim() || '无' }}</template></el-table-column>
          <el-table-column label="协议" width="180"><template #default="{ row }">{{ row.api_protocol?.trim() || '无' }}</template></el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="row.is_enabled ? 'success' : 'info'">
                {{ row.is_enabled ? '已启用' : '已停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="费率版本" width="110">
            <template #default="{ row }">v{{ row.pricing_version || 0 }}</template>
          </el-table-column>
          <el-table-column label="操作" width="168" fixed="right">
            <template #default="{ row }">
              <div class="model-actions">
                <el-button text size="small" type="primary" :icon="Edit" @click="openModelDialog(row)">编辑</el-button>
                <el-button text size="small" type="danger" :icon="Delete" @click="deleteModel(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

    </el-tabs>

    <el-dialog v-model="modelDialogVisible" :title="modelForm.id ? '编辑平台模型' : '新增平台模型'" width="680px">
      <el-form :model="modelForm" label-position="top">
        <div class="form-grid">
          <el-form-item label="模型名称" required><el-input v-model="modelForm.name" /></el-form-item>
          <el-form-item label="提供方" required><el-input v-model="modelForm.provider" /></el-form-item>
          <el-form-item label="API 协议">
            <el-select v-model="modelForm.api_protocol">
              <el-option label="Anthropic Messages" value="anthropic-messages" />
              <el-option label="OpenAI Completions" value="openai-completions" />
            </el-select>
          </el-form-item>
          <el-form-item label="启用"><el-switch v-model="modelForm.is_enabled" /></el-form-item>
        </div>
        <el-form-item label="API Key" :required="!modelForm.has_api_key">
          <el-input
            v-model="modelForm.api_key"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="modelForm.has_api_key ? '已配置，留空保留原密钥；输入新密钥可替换' : '请输入 API Key'"
          />
        </el-form-item>
        <el-form-item label="API Base URL"><el-input v-model="modelForm.api_proxy_url" /></el-form-item>
        <el-alert
          v-if="modelRatesAreFree"
          class="pricing-alert"
          :title="`当前四项费率均为 0，用户使用该模型不会消耗${creditDisplayName(published?.credit_display_name)}`"
          type="warning"
          :closable="false"
          show-icon
        />
        <div class="rate-grid">
          <el-form-item label="输入费率"><el-input-number v-model="modelForm.input_rate" :min="0" :controls="false" /></el-form-item>
          <el-form-item label="输出费率"><el-input-number v-model="modelForm.output_rate" :min="0" :controls="false" /></el-form-item>
          <el-form-item label="缓存读取费率"><el-input-number v-model="modelForm.cache_read_rate" :min="0" :controls="false" /></el-form-item>
          <el-form-item label="缓存创建费率"><el-input-number v-model="modelForm.cache_creation_rate" :min="0" :controls="false" /></el-form-item>
        </div>
        <el-form-item label="费率精度">
          <el-input-number v-model="modelForm.rate_scale" :min="1" :controls="false" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="modelSaving" @click="saveModel">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentChecked, Edit, Plus, Promotion, Refresh } from '@element-plus/icons-vue'
import { enterpriseApi } from '@/api/enterprise'
import { RUNTIME_INFO } from '@/config/runtimes'
import { creditDisplayName, DEFAULT_CREDIT_DISPLAY_NAME } from '@/utils/credit-points'
import CreditRecharge from './components/CreditRecharge.vue'

const route = useRoute()
const activeTab = ref(['credits', 'recharge', 'models'].includes(route.query.tab) ? route.query.tab : 'runtime')
const loading = ref(false)
const settingsLoaded = ref(false)
const loadError = ref('')
const saving = ref(false)
const publishing = ref(false)
const modelSaving = ref(false)
const modelDialogVisible = ref(false)
const draft = ref(null)
const published = ref(null)
const models = ref([])
const savedPayloadSignature = ref('')
const runtimeOptions = [
  { label: 'Claude Agent', value: 'claude_code' },
]
const thinkingLevelLabels = {
  inherit: '继承 Runtime / 模型默认值', off: '关闭额外推理', minimal: '最小',
  low: '低', medium: '中', high: '高', xhigh: '超高', max: '最高', adaptive: '自适应',
}
const thinkingLevelOptions = computed(() => (
  RUNTIME_INFO[form.runtime_type]?.thinking_levels || ['inherit']
).map(value => ({ value, label: thinkingLevelLabels[value] || value })))
const reasoningVisibilityOptions = [
  { label: '隐藏', value: 'off' },
  { label: '显示', value: 'stream' },
]

const defaults = {
  runtime_type: 'claude_code', max_turns: 50,
  thinking_level: 'inherit', reasoning_visibility: 'off',
  timeout_seconds: 600, credit_display_name: DEFAULT_CREDIT_DISPLAY_NAME, credit_display_name_en: 'Credits',
  initial_claim_amount: 0, daily_claim_amount: 0, per_run_limit: 0,
  low_balance_threshold: 0, claim_timezone: 'Asia/Shanghai', max_concurrent_runs: 1,
}
const creditSettingKeys = [
  'initial_claim_amount',
  'daily_claim_amount',
  'per_run_limit',
  'low_balance_threshold',
]
const form = reactive({ ...defaults })
const newModel = () => ({
  id: null, name: '', provider: 'Anthropic', api_key: '', has_api_key: false, api_proxy_url: '',
  api_protocol: 'anthropic-messages', reasoning_support: 'auto', remarks: '',
  is_enabled: true, input_rate: 0, output_rate: 0, cache_read_rate: 0,
  cache_creation_rate: 0, rate_scale: 1000000,
})
const modelForm = reactive(newModel())
const modelRatesAreFree = computed(() => [
  modelForm.input_rate,
  modelForm.output_rate,
  modelForm.cache_read_rate,
  modelForm.cache_creation_rate,
].every(rate => Number(rate || 0) === 0))

const settingsPayload = () => Object.fromEntries(Object.keys(defaults).map(key => [key, form[key]]))
const payloadSignature = () => JSON.stringify(settingsPayload())
const isDirty = computed(() => settingsLoaded.value && payloadSignature() !== savedPayloadSignature.value)
const canPublish = computed(() => settingsLoaded.value && !loading.value && (Boolean(draft.value) || isDirty.value))
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN') : '无'
const errorText = (error, fallback) => {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : (detail?.message || fallback)
}
const applySettings = settings => {
  loadError.value = ''
  draft.value = settings.draft
  published.value = settings.published
  Object.assign(form, defaults, settings.draft || settings.published || {})
  if (form.reasoning_visibility === 'on') form.reasoning_visibility = 'stream'
  creditSettingKeys.forEach(key => { form[key] = Number(form[key] || 0) })
  savedPayloadSignature.value = payloadSignature()
  settingsLoaded.value = true
}

const load = async () => {
  loading.value = true
  settingsLoaded.value = false
  loadError.value = ''
  try {
    const [settings, modelResult] = await Promise.all([
      enterpriseApi.getAgentSettings(),
      enterpriseApi.getPlatformModels(),
    ])
    applySettings(settings)
    models.value = modelResult.items || []
  } catch (error) {
    loadError.value = errorText(error, '设置加载失败，请点击刷新重试')
  } finally {
    loading.value = false
  }
}

const saveDraft = async () => {
  if (!isDirty.value || loading.value || saving.value || publishing.value || modelSaving.value) return
  saving.value = true
  try {
    const saved = await enterpriseApi.saveAgentSettings(settingsPayload())
    applySettings({ draft: saved, published: published.value })
    ElMessage.success('草稿已保存')
  } catch (error) {
    ElMessage.error(errorText(error, '保存失败'))
  } finally {
    saving.value = false
  }
}

const publish = async () => {
  if (!canPublish.value || saving.value || publishing.value || modelSaving.value) return
  if (form.daily_claim_amount <= 0) {
    activeTab.value = 'credits'
    ElMessage.warning('每日领取额度必须大于 0')
    return
  }
  publishing.value = true
  try {
    await ElMessageBox.confirm(
      '将保存当前配置并立即生效。新运行将统一使用这版设置，正在执行的任务保持原有配置。',
      '保存并生效智能体设置',
      { type: 'warning' },
    )
  } catch {
    publishing.value = false
    return
  }
  try {
    const saved = await enterpriseApi.publishAgentSettings(settingsPayload())
    applySettings({ draft: null, published: saved })
    ElMessage.success('设置已生效')
  } catch (error) {
    ElMessage.error(errorText(error, '生效失败'))
  } finally {
    publishing.value = false
  }
}

const openModelDialog = row => {
  Object.assign(modelForm, newModel(), row || {}, { api_key: '' })
  modelDialogVisible.value = true
}

const saveModel = async () => {
  if (modelSaving.value || saving.value || publishing.value || loading.value) return
  if (!modelForm.name || (!modelForm.id && !modelForm.api_key)) {
    ElMessage.warning('请填写模型名称和 API Key')
    return
  }
  modelSaving.value = true
  try {
    const payload = { ...modelForm }
    delete payload.id
    const saved = modelForm.id
      ? await enterpriseApi.updatePlatformModel(modelForm.id, payload)
      : await enterpriseApi.createPlatformModel(payload)
    const index = models.value.findIndex(model => model.id === saved.id)
    if (index >= 0) models.value.splice(index, 1, saved)
    else models.value.unshift(saved)
    modelDialogVisible.value = false
    ElMessage.success('平台模型已保存')
  } catch (error) {
    ElMessage.error(errorText(error, '模型保存失败'))
  } finally {
    modelSaving.value = false
  }
}

const deleteModel = async row => {
  if (modelSaving.value || saving.value || publishing.value || loading.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除平台模型“${row.name?.trim() || '无'}”？删除后将无法恢复。`,
      '删除平台模型',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    modelSaving.value = true
    await enterpriseApi.deletePlatformModel(row.id)
    models.value = models.value.filter(model => model.id !== row.id)
    ElMessage.success('平台模型已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(errorText(error, '平台模型删除失败'))
    }
  } finally {
    modelSaving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.settings-page { max-width: 1400px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.page-heading h1 { margin: 0; color: #1f2937; font-size: 24px; letter-spacing: 0; }
.page-heading p { margin: 7px 0 0; color: #667085; font-size: 13px; }
.settings-status { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.heading-actions, .table-toolbar { display: flex; gap: 10px; }
.settings-tabs { border-top: 1px solid #e5e7eb; }
.settings-form { max-width: 900px; padding-top: 12px; }
.assistant-section + .assistant-section { margin-top: 20px; padding-top: 28px; border-top: 1px solid var(--el-border-color-lighter); }
.runtime-scope-hint { margin: 0 0 24px; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.6; }
.assistant-section-title { margin: 0 0 24px; color: var(--el-text-color-primary); font-size: 16px; font-weight: 600; line-height: 1.5; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; }
.rate-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0 16px; }
.table-toolbar { justify-content: flex-end; margin: 8px 0 14px; }
.model-actions { display: flex; align-items: center; flex-wrap: nowrap; gap: 4px; white-space: nowrap; }
.model-actions .el-button { flex: 0 0 auto; margin: 0; padding: 6px 8px; border-radius: 6px; }
.pricing-alert { margin-bottom: 16px; }
.el-select, .el-input-number { width: 100%; }
.assistant-name-field, .assistant-description-field { grid-column: 1 / -1; }
.setting-hint { width: 100%; margin-top: 8px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
@media (max-width: 760px) {
  .page-heading { align-items: stretch; flex-direction: column; }
  .form-grid, .rate-grid { grid-template-columns: 1fr; }
}
</style>
