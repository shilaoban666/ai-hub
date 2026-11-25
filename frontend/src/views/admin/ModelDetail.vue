<template>
  <div class="model-detail">
    <div class="detail-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" @click="router.push('/admin/models')">返回</el-button>
        <template v-if="!editingName">
          <h2>{{ model.name }}</h2>
          <el-button :icon="Edit" link size="small" @click="startEditName" />
        </template>
        <el-input
          v-else
          v-model="editNameValue"
          class="name-input"
          @blur="saveName"
          @keyup.enter="saveName"
          ref="nameInputRef"
        />
        <el-tag size="small" type="primary" style="margin-left: 12px;">{{ model.provider }}</el-tag>
      </div>
      <div class="header-right">
        <template v-if="editing">
          <el-button @click="cancelEdit">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveModel">保存</el-button>
        </template>
        <template v-else>
          <el-button type="primary" :icon="Edit" @click="startEdit">编辑</el-button>
          <el-button type="danger" :icon="Delete" @click="handleDelete">删除</el-button>
        </template>
      </div>
    </div>

    <div class="detail-body" v-loading="loading">
      <div class="info-panel">
        <div class="info-section">
          <h3>基本信息</h3>
          <div class="info-grid">
            <div class="info-item">
              <label>服务商</label>
              <template v-if="editing">
                <el-select
                  v-model="editForm.provider"
                  @change="handleProviderChange"
                  style="width: 100%"
                >
                  <el-option
                    v-for="p in providerOptions"
                    :key="p.value"
                    :label="p.label"
                    :value="p.value"
                  />
                </el-select>
              </template>
              <span v-else>{{ model.provider }}</span>
            </div>
            <div class="info-item">
              <label>API Key</label>
              <template v-if="editing">
                <el-input
                  v-model="editForm.api_key"
                  type="password"
                  show-password
                  :placeholder="model.has_api_key ? '已配置，留空保留；输入新密钥可替换' : '请输入 API Key'"
                />
              </template>
              <span v-else>{{ maskedKey }}</span>
            </div>
            <div class="info-item">
              <label>API 代理地址</label>
              <template v-if="editing">
                <el-input v-model="editForm.api_proxy_url" placeholder="请输入 API 代理地址" />
              </template>
              <span v-else>{{ model.api_proxy_url || '无' }}</span>
            </div>
            <div class="info-item">
              <label>API 协议</label>
              <template v-if="editing">
                <el-select v-model="editForm.api_protocol" style="width: 100%">
                  <el-option
                    v-for="option in apiProtocolOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
              </template>
              <span v-else>{{ apiProtocolLabel(model.api_protocol) }}</span>
            </div>
            <div class="info-item">
              <label>推理能力</label>
              <template v-if="editing">
                <el-select v-model="editForm.reasoning_support" style="width: 100%">
                  <el-option
                    v-for="option in reasoningSupportOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
              </template>
              <span v-else>{{ reasoningSupportLabel(model.reasoning_support) }}</span>
            </div>
          </div>
        </div>

        <div class="info-section">
          <h3>备注</h3>
          <template v-if="editing">
            <el-input
              v-model="editForm.remarks"
              placeholder="用于区分同名模型（可选），如：官方 / 火山引擎"
            />
          </template>
          <p v-else>{{ model.remarks || '无' }}</p>
        </div>

        <div class="info-section">
          <h3>时间信息</h3>
          <div class="info-item">
            <label>创建时间</label>
            <span>{{ formatTime(model.created_at) }}</span>
          </div>
          <div class="info-item">
            <label>更新时间</label>
            <span>{{ formatTime(model.updated_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { modelsApi } from '@/api/models'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Edit, Delete } from '@element-plus/icons-vue'
import {
  MODEL_PROTOCOL_OPTIONS,
  getModelProtocolLabel,
} from '@/config/models'
import { showError } from '@/utils/error'
import { formatBeijingDateTime } from '@/utils/date-time'

const router = useRouter()
const route = useRoute()
const modelId = Number(route.params.id)

const loading = ref(false)
const model = ref({})
const editing = ref(false)
const saving = ref(false)
const editingName = ref(false)
const editNameValue = ref('')
const nameInputRef = ref(null)

const providerOptions = [
  { label: '自定义', value: '自定义' },
  { label: 'Qwen（通义千问）', value: 'Qwen' },
  { label: 'MiniMax', value: 'MiniMax' },
  { label: 'OPENAI', value: 'OPENAI' },
  { label: 'GLM（智谱）', value: 'GLM' },
  { label: 'Kimi（月之暗面）', value: 'Kimi' },
  { label: 'DeepSeek', value: 'DeepSeek' },
  { label: 'Claude（Anthropic）', value: 'Claude' },
  { label: 'Gemini（Google）', value: 'Gemini' }
]

const providerProxyMap = {
  'Qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  'MiniMax': 'https://api.minimax.chat/v1',
  'OPENAI': 'https://api.openai.com/v1',
  'GLM': 'https://open.bigmodel.cn/api/paas/v4',
  'Kimi': 'https://api.moonshot.cn/v1',
  'DeepSeek': 'https://api.deepseek.com/v1',
  'Claude': 'https://api.anthropic.com/v1',
  'Gemini': 'https://generativelanguage.googleapis.com/v1beta/openai'
}

const apiProtocolOptions = MODEL_PROTOCOL_OPTIONS

const providerProtocolMap = {
  Claude: 'anthropic-messages',
  Qwen: 'openai-completions',
  MiniMax: 'openai-completions',
  OPENAI: 'openai-completions',
  GLM: 'openai-completions',
  Kimi: 'openai-completions',
  DeepSeek: 'openai-completions',
  Gemini: 'openai-completions',
}

const reasoningSupportOptions = [
  { label: '自动识别', value: 'auto' },
  { label: '支持推理', value: 'enabled' },
  { label: '不支持推理', value: 'disabled' },
]

const editForm = ref({
  provider: '',
  api_key: '',
  api_proxy_url: '',
  api_protocol: '',
  reasoning_support: 'auto',
  remarks: ''
})

const apiProtocolLabel = value => getModelProtocolLabel(value)

const reasoningSupportLabel = (value) => (
  reasoningSupportOptions.find(option => option.value === (value || 'auto'))?.label || value
)

const maskedKey = computed(() => {
  return model.value.has_api_key ? '已配置' : '无'
})

const formatTime = (t) => {
  if (!t) return '无'
  return formatBeijingDateTime(t, { fallback: '无' })
}

const fetchModel = async () => {
  loading.value = true
  try {
    const res = await modelsApi.getDetail(modelId)
    model.value = res
  } catch (error) {
    ElMessage.error('获取模型信息失败')
    router.push('/admin/models')
  } finally {
    loading.value = false
  }
}

const startEditName = () => {
  editNameValue.value = model.value.name
  editingName.value = true
  nextTick(() => {
    nameInputRef.value?.focus()
  })
}

const saveName = async () => {
  if (!editNameValue.value.trim()) {
    editingName.value = false
    return
  }
  try {
    await modelsApi.update(modelId, { name: editNameValue.value.trim() })
    model.value.name = editNameValue.value.trim()
    ElMessage.success('名称已更新')
  } catch (error) {
    ElMessage.error('更新名称失败')
  }
  editingName.value = false
}

const startEdit = () => {
  editForm.value = {
    provider: model.value.provider,
    api_key: '',
    api_proxy_url: model.value.api_proxy_url || '',
    api_protocol: model.value.api_protocol === 'auto' ? '' : (model.value.api_protocol || ''),
    reasoning_support: model.value.reasoning_support || 'auto',
    remarks: model.value.remarks || ''
  }
  editing.value = true
}

const cancelEdit = () => {
  editing.value = false
}

const handleProviderChange = (value) => {
  if (value && value !== '自定义' && providerProxyMap[value]) {
    editForm.value.api_proxy_url = providerProxyMap[value]
  }
  if (providerProtocolMap[value]) {
    editForm.value.api_protocol = providerProtocolMap[value]
  }
}

const saveModel = async () => {
  if (!editForm.value.api_protocol) {
    ElMessage.warning('请选择 API 协议')
    return
  }
  saving.value = true
  try {
    const payload = { ...editForm.value }
    if (!String(payload.api_key || '').trim()) delete payload.api_key
    const res = await modelsApi.update(modelId, payload)
    model.value = res
    ElMessage.success('保存成功')
    editing.value = false
  } catch (error) {
    showError(error, '保存失败')
  } finally {
    saving.value = false
  }
}

const handleDelete = async () => {
  try {
    await ElMessageBox.confirm(
      `确定要删除"${model.value.name}"吗？此操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await modelsApi.delete(modelId)
    ElMessage.success('删除成功')
    router.push('/admin/models')
  } catch (error) {
    if (error !== 'cancel') {
      showError(error, '删除失败')
    }
  }
}

onMounted(() => {
  fetchModel()
})
</script>

<style scoped>
.model-detail {
  max-width: 900px;
  margin: 0 auto;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-left h2 {
  margin: 0;
  font-size: 22px;
  color: #333;
}

.name-input {
  width: 260px;
}

.header-right {
  display: flex;
  gap: 8px;
}

.detail-body {
  display: flex;
  gap: 24px;
}

.info-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.info-section {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.info-section h3 {
  margin: 0 0 16px 0;
  font-size: 16px;
  color: #333;
  border-bottom: 1px solid #eee;
  padding-bottom: 10px;
}

.info-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-item label {
  font-size: 13px;
  color: #909399;
}

.info-item span {
  font-size: 15px;
  color: #333;
  word-break: break-all;
}
</style>
