<template>
  <span class="skill-metadata-tags">
    <template v-for="tag in tags" :key="tag">
    <button v-if="clickable && !editable" type="button" class="tag-filter"
      :aria-label="`筛选${label}：${tag}`" :aria-pressed="selectedTag === tag"
      @click.stop="emit('select', tag)" @keydown.stop @keyup.stop>
      <el-tag size="small" :effect="selectedTag === tag ? 'dark' : 'light'">{{ tag }}</el-tag>
    </button>
    <el-tag v-else
      size="small"
      effect="light"
      :closable="editable && !disabled"
      :disable-transitions="true"
      @close="removeTag(tag)"
    >{{ tag }}</el-tag>
    </template>
    <span v-if="!tags.length && !editable" class="empty-tags">无</span>
    <el-popover
      v-if="editable"
      v-model:visible="open"
      trigger="click"
      :width="260"
      :disabled="disabled"
      @show="loadOptions"
      @hide="draft = ''"
    >
      <template #reference>
        <el-button class="add-tag" :icon="Plus" :disabled="disabled" :aria-label="`添加${label}`" @click.stop />
      </template>
      <el-select
        ref="selectRef"
        v-model="draft"
        filterable
        allow-create
        default-first-option
        :reserve-keyword="false"
        :loading="loading"
        :teleported="false"
        :aria-label="`选择或输入${label}`"
        placeholder="选择或输入新标签"
        style="width: 100%"
        @change="addTag"
      >
        <el-option v-for="tag in options" :key="tag" :label="tag" :value="tag" :disabled="tags.includes(tag)" />
      </el-select>
      <p v-if="failed" class="options-error">候选标签加载失败，仍可输入添加。<el-button link size="small" @click="loadOptions">重试</el-button></p>
    </el-popover>
  </span>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { skillsApi } from '@/api/skills'
import { addSkillMetadataTags, parseSkillMetadataTags } from '@/utils/skill-metadata-tags'

const props = defineProps({
  modelValue: { type: String, default: '' },
  field: { type: String, default: 'module' },
  editable: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  clickable: { type: Boolean, default: false },
  selectedTag: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'select'])
const tags = computed(() => parseSkillMetadataTags(props.modelValue))
const label = computed(() => props.field === 'roles' ? '适用角色' : '业务模块')
const limit = computed(() => props.field === 'roles' ? 500 : 200)
const open = ref(false)
const draft = ref('')
const loading = ref(false)
const failed = ref(false)
const suggestions = ref([])
const selectRef = ref(null)
const options = computed(() => [...new Set([
  props.field === 'roles' ? '通用' : '全局', ...suggestions.value, ...tags.value,
])])

const loadOptions = async () => {
  if (loading.value) return
  loading.value = true
  failed.value = false
  nextTick(() => selectRef.value?.focus())
  try {
    const result = await skillsApi.getMetadataOptions()
    suggestions.value = result?.[props.field === 'roles' ? 'roles' : 'modules'] || []
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}
const addTag = value => {
  if (props.disabled) return
  const next = addSkillMetadataTags(props.modelValue, value)
  if ([...next].length > limit.value) {
    ElMessage.warning(`${label}标签总长度不能超过 ${limit.value} 个字符`)
    draft.value = ''
    return
  }
  emit('update:modelValue', next)
  draft.value = ''
  open.value = false
}
const removeTag = tag => {
  if (!props.disabled) emit('update:modelValue', tags.value.filter(value => value !== tag).join(','))
}
</script>

<style scoped>
.skill-metadata-tags { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 6px; min-width: 0; max-width: 100%; vertical-align: middle; }
.tag-filter { display: inline-flex; max-width: 100%; padding: 0; border: 0; border-radius: 4px; background: transparent; cursor: pointer; font: inherit; }
.tag-filter :deep(.el-tag) { cursor: pointer; }
.tag-filter:hover { filter: brightness(.95); }
.tag-filter:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.skill-metadata-tags :deep(.el-tag) { max-width: 100%; height: auto; min-height: 20px; }
.skill-metadata-tags :deep(.el-tag__content) { min-width: 0; white-space: normal; overflow-wrap: anywhere; line-height: 18px; }
.skill-metadata-tags :deep(.el-tag__close) { flex-shrink: 0; }
.add-tag { width: 22px; height: 22px; margin: 0; padding: 0; border-style: dashed; color: #409eff; }
.empty-tags { color: #909399; font-size: 13px; }
.options-error { margin: 8px 0 0; color: #909399; font-size: 12px; line-height: 18px; }
</style>
