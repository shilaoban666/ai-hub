<template>
  <div class="template-detail">
    <div class="detail-header">
      <el-button class="back-btn" @click="router.push('/admin/prompt-templates')" :icon="ArrowLeft">返回</el-button>
      <div class="header-info">
        <h2
          v-if="!isEditingName"
          class="editable-name"
          @click="startEditName"
          :title="'点击编辑名称'"
        >
          {{ template.name }}
        </h2>
        <el-input
          v-else
          v-model="editingName"
          @blur="saveName"
          @keyup.enter="saveName"
          ref="nameInputRef"
          size="large"
          class="name-input"
        />
        <el-tag size="small" type="primary">{{ template.category }}</el-tag>
      </div>
      <div class="header-actions">
        <template v-if="editing">
          <el-button @click="cancelEdit">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveTemplate">保存</el-button>
        </template>
        <template v-else>
          <el-button
            :type="template.is_public ? 'success' : 'info'"
            :icon="template.is_public ? View : Hide"
            @click="handleToggleVisibility"
          >{{ template.is_public ? '设为私有' : '设为公开' }}</el-button>
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
              <label>作者</label>
              <span>{{ template.author || '匿名' }}</span>
            </div>
            <div class="info-item">
              <label>分类</label>
              <template v-if="editing">
                <PromptCategorySelect v-model="editForm.category" />
              </template>
              <span v-else>{{ template.category }}</span>
            </div>
            <div class="info-item">
              <label>描述</label>
              <template v-if="editing">
                <el-input v-model="editForm.description" type="textarea" :rows="3" placeholder="请输入描述" />
              </template>
              <span v-else>{{ template.description || '暂无描述' }}</span>
            </div>
          </div>
        </div>

        <div class="info-section">
          <h3>提示词内容</h3>
          <template v-if="editing">
            <MarkdownEditor v-model="editForm.content" placeholder="请输入提示词，支持 Markdown，使用 {{变量名}} 表示占位符" />
          </template>
          <pre class="prompt-content" v-else v-html="highlightedContent" />
        </div>

        <div class="info-section">
          <h3>变量定义</h3>
          <template v-if="editing">
            <div class="variables-editor">
              <div v-for="(v, index) in editVariables" :key="index" class="variable-row">
                <el-input v-model="v.name" placeholder="变量名" size="small" style="width: 120px" />
                <el-select v-model="v.type" size="small" style="width: 90px">
                  <el-option label="字符串" value="string" />
                  <el-option label="数字" value="number" />
                  <el-option label="布尔" value="boolean" />
                </el-select>
                <el-input v-model="v.default" placeholder="默认值" size="small" style="width: 100px" />
                <el-input v-model="v.description" placeholder="描述" size="small" style="width: 120px" />
                <el-checkbox v-model="v.required" size="small">必填</el-checkbox>
                <el-button :icon="Delete" link size="small" type="danger" @click="editVariables.splice(index, 1)" />
              </div>
              <el-button :icon="Plus" size="small" @click="editVariables.push({ name: '', type: 'string', default: '', description: '', required: false })">
                添加变量
              </el-button>
            </div>
          </template>
          <template v-else>
            <el-table :data="parsedVariables" v-if="parsedVariables.length > 0" size="small">
              <el-table-column prop="name" label="变量名" min-width="100" />
              <el-table-column prop="type" label="类型" min-width="80" />
              <el-table-column prop="default" label="默认值" min-width="100" />
              <el-table-column prop="description" label="描述" min-width="120" />
              <el-table-column prop="required" label="必填" min-width="80">
                <template #default="{ row }">
                  {{ row.required ? '是' : '否' }}
                </template>
              </el-table-column>
            </el-table>
            <p v-else class="text-muted">无变量定义</p>
          </template>
        </div>

        <div class="info-section">
          <h3>时间信息</h3>
          <div class="info-item">
            <label>创建时间</label>
            <span>{{ formatTime(template.created_at) }}</span>
          </div>
          <div class="info-item">
            <label>更新时间</label>
            <span>{{ formatTime(template.updated_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { promptTemplatesApi } from '@/api/prompt-templates'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Edit, Delete, Plus, View, Hide } from '@element-plus/icons-vue'
import { formatBeijingDateTime } from '@/utils/date-time'
import PromptCategorySelect from './components/PromptCategorySelect.vue'

const router = useRouter()
const route = useRoute()
const templateId = Number(route.params.id)

const loading = ref(false)
const template = ref({})
const editing = ref(false)
const saving = ref(false)
const isEditingName = ref(false)
const editingName = ref('')
const nameInputRef = ref(null)
const editVariables = ref([])

const editForm = ref({
  category: '',
  content: '',
  description: ''
})

const parseVariables = (str) => {
  if (!str) return []
  try {
    return JSON.parse(str)
  } catch {
    return []
  }
}

const parsedVariables = computed(() => parseVariables(template.value.variables))

const highlightedContent = computed(() => {
  const content = template.value.content || ''
  return content.replace(
    /\{\{(\w+)\}\}/g,
    '<mark class="var-highlight">{{ $1 }}</mark>'
  )
})

const formatTime = (t) => {
  if (!t) return '无'
  return formatBeijingDateTime(t, { fallback: '无' })
}

const fetchTemplate = async () => {
  loading.value = true
  try {
    const res = await promptTemplatesApi.getDetail(templateId)
    template.value = res
  } catch (error) {
    ElMessage.error('获取提示词信息失败')
    router.push('/admin/prompt-templates')
  } finally {
    loading.value = false
  }
}

const startEditName = () => {
  isEditingName.value = true
  editingName.value = template.value.name
  nextTick(() => {
    if (nameInputRef.value) {
      nameInputRef.value.focus()
      nameInputRef.value.select()
    }
  })
}

const saveName = async () => {
  if (!editingName.value.trim()) {
    ElMessage.warning('名称不能为空')
    editingName.value = template.value.name
    isEditingName.value = false
    return
  }

  if (editingName.value === template.value.name) {
    isEditingName.value = false
    return
  }

  try {
    await promptTemplatesApi.update(templateId, { name: editingName.value })
    template.value.name = editingName.value
    isEditingName.value = false
    ElMessage.success('名称已更新')
  } catch (error) {
    ElMessage.error('更新失败')
    editingName.value = template.value.name
    isEditingName.value = false
  }
}

const startEdit = () => {
  editForm.value = {
    category: template.value.category,
    content: template.value.content,
    description: template.value.description || ''
  }
  editVariables.value = parseVariables(template.value.variables).map(v => ({ ...v }))
  editing.value = true
}

const cancelEdit = () => {
  editing.value = false
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
  const existingMap = new Map(editVariables.value.map(v => [v.name, v]))
  editVariables.value = foundNames.map(name => {
    return existingMap.get(name) || { name, type: 'string', default: '', description: '', required: false }
  })
}

watch(() => editForm.value.content, (newContent) => {
  syncVariablesFromContent(newContent)
})

const saveTemplate = async () => {
  const category = typeof editForm.value.category === 'string' ? editForm.value.category.trim() : ''
  if (!category) {
    ElMessage.warning('请选择或输入分类')
    return
  }
  if (category.length > 50) {
    ElMessage.warning('分类不能超过 50 个字符')
    return
  }
  saving.value = true
  try {
    const payload = {
      ...editForm.value,
      category,
      variables: editVariables.value.length > 0 ? JSON.stringify(editVariables.value) : null
    }
    const res = await promptTemplatesApi.update(templateId, payload)
    template.value = res
    ElMessage.success('保存成功')
    editing.value = false
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const handleToggleVisibility = async () => {
  try {
    const result = await promptTemplatesApi.toggleVisibility(templateId)
    template.value.is_public = result.is_public
    ElMessage.success(`提示词已设为${result.is_public ? '公开' : '私有'}`)
  } catch (error) {
    ElMessage.error('切换可见性失败')
  }
}

const handleDelete = async () => {
  try {
    await ElMessageBox.confirm(
      `确定要删除"${template.value.name}"吗？此操作不可恢复。`,
      '删除确认',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    await promptTemplatesApi.delete(templateId)
    ElMessage.success('删除成功')
    router.push('/admin/prompt-templates')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

onMounted(() => {
  fetchTemplate()
})
</script>

<style scoped>
.template-detail {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: white;
  border-radius: 4px;
  max-width: 1400px;
  margin: 0 auto;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px 12px 12px;
  border-bottom: 1px solid #e8e8e8;
}

.back-btn {
  margin-right: 8px;
  flex-shrink: 0;
  border: none;
  color: #606266;
  padding: 5px 8px 5px 0;
}

.back-btn:hover {
  color: #409eff;
  background: transparent;
}

.header-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.header-info h2 {
  margin: 0;
  font-size: 20px;
}

.editable-name {
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s;
}

.editable-name:hover {
  background-color: #f5f5f5;
  color: #409eff;
}

.name-input {
  width: 80%;
}

.name-input :deep(.el-input__wrapper) {
  font-size: 20px;
  font-weight: 600;
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

.prompt-content {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 14px;
  line-height: 1.6;
  color: #333;
  background: #f8f9fa;
  padding: 16px;
  border-radius: 6px;
  margin: 0;
}

.prompt-content :deep(.var-highlight) {
  background: #fef08a;
  color: #854d0e;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 500;
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

.text-muted {
  color: #909399;
  margin: 0;
}
</style>
