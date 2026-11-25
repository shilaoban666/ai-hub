<template>
  <el-form-item label="提示词模板">
    <el-select
      :disabled="disabled"
      :loading="loading"
      v-model="appliedTemplateId"
      placeholder="从自己的或公开的提示词模板复用"
      filterable
      clearable
      no-data-text="无"
      style="width: 100%;"
      @change="handleApplyTemplate"
    >
      <el-option
        v-for="t in usableTemplates"
        :key="t.id"
        :label="`${t.name}（${t.category?.trim() || '无'}） · ${templateSourceLabel(t)}`"
        :value="t.id"
      >
        <div class="identity-template-option">
          <span class="identity-template-name">{{ t.name }}（{{ t.category?.trim() || '无' }}）</span>
          <el-tag size="small" :type="isOwnTemplate(t) ? 'primary' : 'success'" effect="plain">
            {{ templateSourceLabel(t) }}
          </el-tag>
        </div>
      </el-option>
    </el-select>
    <div v-if="loadError" class="template-load-error">
      <span>提示词模板加载失败</span>
      <el-button link type="primary" :disabled="disabled || loading" @click="loadTemplates">重新加载</el-button>
    </div>
  </el-form-item>

  <!-- 提示词模板变量填写弹窗 -->
  <el-dialog
    v-model="varDialogVisible"
    title="填写模板变量"
    width="min(480px, calc(100vw - 32px))"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
  >
    <el-form label-width="120px" :disabled="disabled" v-if="currentTemplate">
      <el-form-item
        v-for="v in currentVariables"
        :key="v.name"
        :label="v.name"
        :required="v.required"
      >
        <el-input
          v-model="varForm[v.name]"
          :placeholder="v.description || ('请输入 ' + v.name)"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="cancelVariables">取消</el-button>
      <el-button type="primary" :disabled="disabled" @click="confirmVariables">填入系统提示词</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { promptTemplatesApi } from '@/api/prompt-templates'

const props = defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const authStore = useAuthStore()
const templates = ref([])
const usableTemplates = computed(() => templates.value.filter(template => !template.is_system))
const appliedTemplateId = ref(null)
const loading = ref(false)
const loadError = ref(false)
const loadTemplates = async () => {
  loading.value = true
  loadError.value = false
  try {
    const result = await promptTemplatesApi.getUsable({ limit: 200, include_system: false })
    templates.value = result.items || []
  } catch {
    templates.value = []
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function isOwnTemplate(template) {
  const userId = authStore.user?.id ?? authStore.user?.user_id
  return userId != null && template.user_id != null && String(template.user_id) === String(userId)
}

function templateSourceLabel(template) {
  if (isOwnTemplate(template)) return template.is_public ? '我的 · 已公开' : '我的'
  return template.is_public ? '公开' : '无'
}

const varDialogVisible = ref(false)
const currentTemplate = ref(null)
const currentVariables = ref([])
const varForm = ref({})

const parseVariables = (str) => {
  if (!str) return []
  try {
    const variables = JSON.parse(str)
    return Array.isArray(variables) ? variables : []
  } catch {
    return []
  }
}

const renderTemplate = (template, values) => {
  const content = template.content || ''
  return content.replace(/\{\{(\w+)\}\}/g, (_, name) => {
    const val = values?.[name]
    return val !== undefined && val !== '' ? String(val) : ''
  })
}

// 从提示词模板复用身份提示词：无变量直接填入，有变量弹窗收集后渲染填入
const handleApplyTemplate = (templateId) => {
  if (props.disabled || templateId == null) return
  const t = usableTemplates.value.find(item => item.id === templateId)
  if (!t) return
  const vars = parseVariables(t.variables)
  if (vars.length === 0) {
    if (props.modelValue && props.modelValue !== t.content) {
      ElMessage.info('已用模板内容覆盖系统提示词，可在下方继续修改')
    }
    emit('update:modelValue', t.content || '')
    return
  }
  // 有变量：弹窗收集
  currentTemplate.value = t
  currentVariables.value = vars
  varForm.value = {}
  vars.forEach(v => {
    varForm.value[v.name] = v.default ?? ''
  })
  varDialogVisible.value = true
}

const confirmVariables = () => {
  if (props.disabled || !currentTemplate.value) return
  for (const v of currentVariables.value) {
    if (v.required && !String(varForm.value[v.name] ?? '').trim()) {
      ElMessage.warning(`请填写变量：${v.name}`)
      return
    }
  }
  const rendered = renderTemplate(currentTemplate.value, varForm.value)
  if (props.modelValue && props.modelValue !== rendered) {
    ElMessage.info('已用模板内容覆盖系统提示词，可在下方继续修改')
  }
  emit('update:modelValue', rendered)
  varDialogVisible.value = false
}

// 取消弹窗：还原选择器选中态，保持身份提示词不变
const cancelVariables = () => {
  varDialogVisible.value = false
  appliedTemplateId.value = null
}

onMounted(loadTemplates)
</script>

<style scoped>
.identity-template-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.identity-template-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.identity-template-option .el-tag {
  flex-shrink: 0;
}

.template-load-error { display: flex; align-items: center; gap: 8px; margin-top: 8px; color: var(--el-color-danger); font-size: 12px; }
</style>
