<template>
  <div class="metadata-filters" :class="{ 'metadata-filters--flat': flat }" role="group" aria-label="技能标签筛选">
    <template v-if="flat">
      <div v-for="field in fields" :key="field.key" class="filter-row" role="group" :aria-label="field.label" :aria-busy="loading">
        <span class="filter-label">{{ field.label }}</span>
        <div class="filter-options">
          <button type="button" :class="{ active: !props[field.key] }" :aria-pressed="!props[field.key]" @click="emit('change', field.key, '')">全部</button>
          <button v-for="tag in optionsFor(field)" :key="tag" type="button"
            :class="{ active: props[field.key] === tag }" :aria-pressed="props[field.key] === tag"
            @click="emit('change', field.key, tag)">{{ tag }}</button>
          <el-icon v-if="loading" class="filter-loading is-loading" role="status" aria-label="加载中"><Loading /></el-icon>
        </div>
      </div>
    </template>
    <template v-else>
    <el-select
      v-for="field in fields"
      :key="field.key"
      :model-value="field.key === 'module' ? module : role"
      :aria-label="field.label"
      :placeholder="`全部${field.label}`"
      filterable clearable :loading="loading"
      @change="emit('change', field.key, $event || '')"
      @visible-change="visible => visible && loadOptions()"
    >
      <el-option v-for="tag in optionsFor(field)" :key="tag" :label="tag" :value="tag" />
    </el-select>
    <el-button v-if="module || role" link @click="emit('change', 'all', '')">清除标签筛选</el-button>
    </template>
    <el-button v-if="failed" link type="warning" @click="loadOptions">标签加载失败，重试</el-button>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { skillsApi, publicSkillsApi } from '@/api/skills'

const props = defineProps({
  module: { type: String, default: '' },
  role: { type: String, default: '' },
  publicOnly: { type: Boolean, default: false },
  flat: { type: Boolean, default: false },
})
const emit = defineEmits(['change'])
const fields = [
  { key: 'module', options: 'modules', label: '业务模块' },
  { key: 'role', options: 'roles', label: '适用角色' },
]
const options = ref({ modules: [], roles: [] })
const loading = ref(false)
const failed = ref(false)
const optionsFor = field => [...new Set([
  ...(options.value[field.options] || []), props[field.key],
].filter(Boolean))]
const loadOptions = async () => {
  if (loading.value) return
  loading.value = true
  failed.value = false
  try {
    options.value = await (props.publicOnly ? publicSkillsApi : skillsApi).getMetadataOptions()
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}
onMounted(loadOptions)
</script>

<style scoped>
.metadata-filters { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.metadata-filters :deep(.el-select) { width: 200px; max-width: 100%; }
.metadata-filters--flat { align-items: stretch; flex-direction: column; gap: var(--skill-filter-row-gap, 8px); }
.filter-row { display: flex; align-items: flex-start; gap: 14px; min-width: 0; }
.filter-label { flex-shrink: 0; color: #858c96; font-size: 13px; line-height: 30px; }
.filter-options { display: flex; flex: 1; flex-wrap: wrap; align-items: center; gap: 6px; min-width: 0; }
.filter-options button { box-sizing: border-box; min-height: 30px; max-width: 100%; padding: 4px 13px; border: 1px solid transparent; border-radius: 16px; color: #666e7b; background: transparent; cursor: pointer; font: inherit; font-size: 13px; line-height: 20px; overflow-wrap: anywhere; text-align: left; }
.filter-options button:hover { color: #24272c; background: #f3f4f5; }
.filter-options button.active { color: #2c5f95; background: #eef5fc; border-color: #d7e7f7; font-weight: 600; }
.filter-options button:focus-visible { outline: 2px solid #8a9098; outline-offset: 1px; }
.filter-loading { margin-left: 14px; color: #858c96; font-size: 12px; }
</style>
