<template>
  <div class="model-list">
    <div class="header">
      <h2>自定义模型</h2>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索名称、服务商或描述"
          clearable
          @input="handleSearch"
          style="width: 280px; margin-right: 12px;"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button @click="handleGetApiKey">
          <el-icon><Link /></el-icon>
          获取公司内部API Key
        </el-button>
        <el-button type="primary" @click="handleCreate">
          <el-icon><Plus /></el-icon>
          添加模型
        </el-button>
      </div>
    </div>

    <el-table
      :data="models"
      v-loading="loading"
      stripe
      @row-click="handleSelect"
      style="cursor: pointer;"
    >
      <el-table-column prop="name" label="模型名称" min-width="160" />
      <el-table-column prop="provider" label="服务商" width="120">
        <template #default="{ row }">
          <el-tag size="small" type="primary">{{ row.provider }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="api_protocol" label="API 协议" width="150">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ getModelProtocolLabel(row.api_protocol, true) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="api_key" label="API Key" width="160">
        <template #default="{ row }">
          {{ row.has_api_key ? '已配置' : '无' }}
        </template>
      </el-table-column>
      <el-table-column prop="api_proxy_url" label="API 代理地址" min-width="280" show-overflow-tooltip />
      <el-table-column prop="remarks" label="备注" width="140" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.remarks || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="130">
        <template #default="{ row }">
          <el-button type="primary" :icon="Edit" link size="small" @click.stop="handleEdit(row)">编辑</el-button>
          <el-button type="danger" :icon="Delete" link size="small" @click.stop="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && models.length === 0" description="暂无数据" />

    <div class="pagination-container" v-if="!loading && total > 0">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next, jumper"
        @current-change="handlePageChange"
      />
    </div>

    <!-- 创建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? '编辑模型' : '添加模型'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="120px"
      >
        <el-form-item label="模型名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入模型名称" />
        </el-form-item>
        <el-form-item label="服务商" prop="provider">
          <el-select
            v-model="form.provider"
            placeholder="请选择服务商"
            style="width: 100%"
            @change="handleProviderChange"
          >
            <el-option
              v-for="p in providerOptions"
              :key="p.value"
              :label="p.label"
              :value="p.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            :placeholder="isEditing && editingHasApiKey ? '已配置，留空保留；输入新密钥可替换' : '请输入 API Key'"
            type="password"
            show-password
          />
        </el-form-item>
        <el-form-item label="API 代理地址" prop="api_proxy_url">
          <el-input v-model="form.api_proxy_url" placeholder="请输入 API 代理地址" />
        </el-form-item>
        <el-form-item label="API 协议" prop="api_protocol">
          <el-select v-model="form.api_protocol" style="width: 100%">
            <el-option
              v-for="option in apiProtocolOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="推理能力" prop="reasoning_support">
          <el-select v-model="form.reasoning_support" style="width: 100%">
            <el-option
              v-for="option in reasoningSupportOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注" prop="remarks">
          <el-input
            v-model="form.remarks"
            placeholder="用于区分同名模型（可选），如：官方 / 火山引擎"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleConfirm" :loading="submitting">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { modelsApi } from '@/api/models'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, Search, Plus, Link } from '@element-plus/icons-vue'
import { showError } from '@/utils/error'
import {
  MODEL_PROTOCOL_OPTIONS,
  getModelProtocolLabel,
} from '@/config/models'

const router = useRouter()
const loading = ref(false)
const models = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)
const searchKeyword = ref('')
let searchTimer = null
const dialogVisible = ref(false)
const isEditing = ref(false)
const editingId = ref(null)
const editingHasApiKey = ref(false)
const submitting = ref(false)
const formRef = ref(null)

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

const form = ref({
  name: '',
  provider: '自定义',
  api_key: '',
  api_proxy_url: '',
  api_protocol: '',
  reasoning_support: 'auto',
  remarks: ''
})

const rules = {
  name: [
    { required: true, message: '请输入模型名称', trigger: 'blur' }
  ],
  provider: [
    { required: true, message: '请选择服务商', trigger: 'change' }
  ],
  api_key: [
    {
      validator: (_rule, value, callback) => {
        if (!isEditing.value && !String(value || '').trim()) {
          callback(new Error('请输入 API Key'))
          return
        }
        callback()
      },
      trigger: 'blur',
    }
  ],
  api_proxy_url: [
    { required: true, message: '请输入 API 代理地址', trigger: 'blur' }
  ],
  api_protocol: [
    { required: true, message: '请选择 API 协议', trigger: 'change' }
  ]
}

const handleProviderChange = (value) => {
  if (value && value !== '自定义' && providerProxyMap[value]) {
    form.value.api_proxy_url = providerProxyMap[value]
  }
  if (providerProtocolMap[value]) {
    form.value.api_protocol = providerProtocolMap[value]
  }
}

const fetchModels = async () => {
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const params = { skip, limit: pageSize.value, scope: 'user' }
    if (searchKeyword.value?.trim()) {
      params.search = searchKeyword.value.trim()
    }
    const response = await modelsApi.getList(params)
    models.value = response?.items || []
    total.value = response?.total || 0
  } catch (error) {
    showError(error, '获取列表失败')
    models.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
  fetchModels()
}

const handleSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchModels()
  }, 500)
}

const handleSelect = (row) => {
  handleEdit(row)
}

const handleEdit = (row) => {
  isEditing.value = true
  editingId.value = row.id
  editingHasApiKey.value = Boolean(row.has_api_key)
  form.value = {
    name: row.name,
    provider: row.provider,
    api_key: '',
    api_proxy_url: row.api_proxy_url || '',
    api_protocol: row.api_protocol === 'auto' ? '' : (row.api_protocol || ''),
    reasoning_support: row.reasoning_support || 'auto',
    remarks: row.remarks || ''
  }
  dialogVisible.value = true
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除"${row.name}"吗？此操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await modelsApi.delete(row.id)
    ElMessage.success('删除成功')
    await fetchModels()
  } catch (error) {
    if (error !== 'cancel') {
      showError(error, '删除失败')
    }
  }
}

const handleGetApiKey = () => {
  window.open('http://106.15.78.154:8100/page/display?document_id=67', '_blank')
}

const handleCreate = () => {
  isEditing.value = false
  editingId.value = null
  editingHasApiKey.value = false
  form.value = {
    name: '',
    provider: '自定义',
    api_key: '',
    api_proxy_url: '',
    api_protocol: '',
    reasoning_support: 'auto',
    remarks: ''
  }
  dialogVisible.value = true
}

const handleConfirm = async () => {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    if (isEditing.value) {
      const payload = { ...form.value }
      if (!String(payload.api_key || '').trim()) delete payload.api_key
      await modelsApi.update(editingId.value, payload)
      ElMessage.success('更新成功')
      dialogVisible.value = false
      await fetchModels()
    } else {
      await modelsApi.create(form.value)
      ElMessage.success('创建成功')
      dialogVisible.value = false
      await fetchModels()
    }
  } catch (error) {
    showError(error, isEditing.value ? '更新失败' : '创建失败')
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  fetchModels()
})
</script>

<style scoped>
.model-list {
  max-width: 1400px;
  margin: 0 auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.header h2 {
  margin: 0;
  font-size: 24px;
  color: #333;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}
</style>
