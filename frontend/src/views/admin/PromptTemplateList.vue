<template>
  <div class="template-list">
    <div class="header">
      <h2>提示词管理</h2>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索名称、分类或描述"
          clearable
          @input="handleSearch"
          style="width: 280px; margin-right: 12px;"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="handleCreate">
          <el-icon><Plus /></el-icon>
          新建提示词
        </el-button>
      </div>
    </div>

    <el-table
      :data="templates"
      v-loading="loading"
      stripe
      @row-click="handleSelect"
      style="cursor: pointer;"
    >
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="category" label="分类" width="120">
        <template #default="{ row }">
          <el-tag size="small" type="primary">{{ row.category }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="content" label="内容预览" min-width="280">
        <template #default="{ row }">
          {{ truncateContent(row.content) }}
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.description || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="author" label="作者" width="120">
        <template #default="{ row }">
          {{ row.author || '匿名' }}
        </template>
      </el-table-column>
      <el-table-column label="公开" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_public ? 'success' : 'info'">
            {{ row.is_public ? '公开' : '私有' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="180">
        <template #default="{ row }">
          <el-button
            :type="row.is_public ? 'success' : 'info'"
            :icon="row.is_public ? View : Hide"
            link size="small"
            @click.stop="handleToggleVisibility(row)"
          >{{ row.is_public ? '设为私有' : '设为公开' }}</el-button>
          <el-button type="primary" :icon="Edit" link size="small" @click.stop="handleEdit(row)">编辑</el-button>
          <el-button type="danger" :icon="Delete" link size="small" @click.stop="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && templates.length === 0" description="暂无数据" />

    <div class="pagination-container" v-if="!loading && total > 0">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next, jumper"
        @current-change="handlePageChange"
      />
    </div>

    <el-dialog
      v-model="dialogVisible"
      class="prompt-template-dialog"
      align-center
      :title="isEditing ? '编辑提示词' : '新建提示词'"
      width="1100px"
      :style="{ maxWidth: 'calc(100vw - 32px)' }"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="100px"
      >
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="请输入描述（可选）"
          />
        </el-form-item>
        <el-form-item label="分类" prop="category">
          <PromptCategorySelect v-model="form.category" />
        </el-form-item>
        <el-form-item label="提示词内容" prop="content">
          <MarkdownEditor
            v-model="form.content"
            class="prompt-content-editor"
            editor-id="prompt-template-form"
            language="zh-CN"
            placeholder="请输入提示词，使用 {{变量名}} 表示占位符，例如：请用 {{language}} 语言编写一段 {{task}} 的代码"
          />
        </el-form-item>
        <el-form-item label="变量定义">
          <div class="variables-editor">
            <div
              v-for="(v, index) in variablesList"
              :key="index"
              class="variable-row"
            >
              <el-input v-model="v.name" placeholder="变量名" size="small" style="width: 120px" />
              <el-select v-model="v.type" size="small" style="width: 90px">
                <el-option label="字符串" value="string" />
                <el-option label="数字" value="number" />
                <el-option label="布尔" value="boolean" />
              </el-select>
              <el-input v-model="v.default" placeholder="默认值" size="small" style="width: 100px" />
              <el-input v-model="v.description" placeholder="描述" size="small" style="width: 120px" />
              <el-checkbox v-model="v.required" size="small">必填</el-checkbox>
              <el-button :icon="Delete" link size="small" type="danger" @click="removeVariable(index)" />
            </div>
            <el-button :icon="Plus" size="small" @click="addVariable">添加变量</el-button>
          </div>
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
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import 'md-editor-v3/lib/style.css'
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { promptTemplatesApi } from '@/api/prompt-templates'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, Search, Plus, View, Hide } from '@element-plus/icons-vue'
import PromptCategorySelect from './components/PromptCategorySelect.vue'

const router = useRouter()
const loading = ref(false)
const templates = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)
const searchKeyword = ref('')
let searchTimer = null
const dialogVisible = ref(false)
const isEditing = ref(false)
const editingId = ref(null)
const submitting = ref(false)
const formRef = ref(null)
const variablesList = ref([])

const form = ref({
  name: '',
  category: '其他',
  content: '',
  description: ''
})

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  category: [
    { required: true, message: '请选择或输入分类', trigger: 'change' },
    {
      validator: (_rule, value, callback) => {
        const category = typeof value === 'string' ? value.trim() : ''
        if (!category) {
          callback(new Error('请选择或输入分类'))
        } else if (category.length > 50) {
          callback(new Error('分类不能超过 50 个字符'))
        } else {
          callback()
        }
      },
      trigger: ['blur', 'change']
    }
  ],
  content: [{ required: true, message: '请输入提示词内容', trigger: 'blur' }]
}

const truncateContent = (content) => {
  if (!content) return '-'
  return content.length > 60 ? content.slice(0, 60) + '...' : content
}

const parseVariables = (variablesStr) => {
  if (!variablesStr) return []
  try {
    return JSON.parse(variablesStr)
  } catch {
    return []
  }
}

const addVariable = () => {
  variablesList.value.push({ name: '', type: 'string', default: '', description: '', required: false })
}

const removeVariable = (index) => {
  variablesList.value.splice(index, 1)
}

const extractVariableNames = (content) => {
  if (!content) return []
  const names = new Set()
  const regex = /\{\{(\w+)\}\}/g
  let match
  while ((match = regex.exec(content)) !== null) {
    names.add(match[1])
  }
  return [...names]
}

const syncVariablesFromContent = (content) => {
  const foundNames = extractVariableNames(content)
  const existingMap = new Map(variablesList.value.map(v => [v.name, v]))
  variablesList.value = foundNames.map(name => {
    return existingMap.get(name) || { name, type: 'string', default: '', description: '', required: false }
  })
}

watch(() => form.value.content, (newContent) => {
  syncVariablesFromContent(newContent)
})

const fetchTemplates = async () => {
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const params = { skip, limit: pageSize.value }
    if (searchKeyword.value?.trim()) {
      params.search = searchKeyword.value.trim()
    }
    const response = await promptTemplatesApi.getList(params)
    templates.value = response?.items || []
    total.value = response?.total || 0
  } catch (error) {
    ElMessage.error('获取列表失败')
    templates.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
  fetchTemplates()
}

const handleSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchTemplates()
  }, 500)
}

const handleSelect = (row) => {
  router.push(`/admin/prompt-templates/${row.id}`)
}

const handleEdit = (row) => {
  isEditing.value = true
  editingId.value = row.id
  form.value = {
    name: row.name,
    category: row.category,
    content: row.content,
    description: row.description || ''
  }
  variablesList.value = parseVariables(row.variables)
  dialogVisible.value = true
}

const handleToggleVisibility = async (row) => {
  try {
    const result = await promptTemplatesApi.toggleVisibility(row.id)
    row.is_public = result.is_public
    ElMessage.success(`提示词已设为${result.is_public ? '公开' : '私有'}`)
  } catch (error) {
    ElMessage.error('切换可见性失败')
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除"${row.name}"吗？此操作不可恢复。`,
      '删除确认',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    await promptTemplatesApi.delete(row.id)
    ElMessage.success('删除成功')
    await fetchTemplates()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const handleCreate = () => {
  isEditing.value = false
  editingId.value = null
  form.value = {
    name: '',
    category: '其他',
    content: '',
    description: ''
  }
  variablesList.value = []
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
    const payload = {
      ...form.value,
      category: form.value.category.trim(),
      variables: variablesList.value.length > 0 ? JSON.stringify(variablesList.value) : null
    }
    if (isEditing.value) {
      await promptTemplatesApi.update(editingId.value, payload)
      ElMessage.success('更新成功')
      dialogVisible.value = false
      await fetchTemplates()
    } else {
      await promptTemplatesApi.create(payload)
      ElMessage.success('创建成功')
      dialogVisible.value = false
      await fetchTemplates()
    }
  } catch (error) {
    ElMessage.error(isEditing.value ? '更新失败' : '创建失败')
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  fetchTemplates()
})
</script>

<style scoped>
:global(.prompt-template-dialog.el-dialog) { max-height: calc(100dvh - 32px); display: flex; flex-direction: column; }
:global(.prompt-template-dialog > .el-dialog__body) { min-height: 0; overflow-y: auto; }
:global(.prompt-template-dialog > .el-dialog__header), :global(.prompt-template-dialog > .el-dialog__footer) { flex-shrink: 0; }
.prompt-content-editor { width: 100%; height: 480px; min-width: 0; }
.template-list {
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

.variables-editor {
  width: 100%;
}

.variable-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
</style>
