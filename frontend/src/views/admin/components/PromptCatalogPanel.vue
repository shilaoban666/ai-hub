<template>
  <section class="prompt-library">
    <div class="library-toolbar">
      <el-input
        v-model="query"
        class="workspace-search"
        :prefix-icon="Search"
        clearable
        placeholder="搜索提示词"
        aria-label="搜索提示词"
        @keyup.enter="searchNow"
        @clear="searchNow"
      />
      <div class="view-switch" role="group" aria-label="提示词范围">
        <button
          v-for="option in viewOptions"
          :key="option.value"
          type="button"
          :class="{ active: installedOnly === option.value }"
          :aria-pressed="installedOnly === option.value"
          @click="selectView(option.value)"
        >{{ option.label }}</button>
      </div>
      <ResourceCenterCreateButton v-if="!readOnly" resource="prompts" />
    </div>

    <div class="library-summary">
      <div class="source-tabs" role="group" aria-label="提示词来源">
        <span class="source-label">提示词来源</span>
        <button
          v-for="option in sourceOptions"
          :key="option.value"
          type="button"
          :class="{ active: source === option.value }"
          :aria-pressed="source === option.value"
          @click="selectSource(option.value)"
        >{{ option.label }}</button>
      </div>
    </div>

    <el-alert v-if="error" type="error" show-icon :closable="false">
      {{ error }} <el-button link type="primary" @click="refresh">重试</el-button>
    </el-alert>
    <el-table
      v-else
      v-loading="loading"
      class="asset-table"
      :data="rows"
      row-key="id"
      :empty-text="loading ? '加载中' : (installedOnly ? '没有符合条件的已安装提示词' : '没有符合条件的提示词')"
    >
      <el-table-column label="名称" min-width="200">
        <template #default="{ row }">
          <span class="asset-name">
            <span :title="textOrNone(row.name)">{{ textOrNone(row.name) }}</span>
            <span v-if="row.origins?.includes('mine')" class="origin-badge origin-badge--mine">我的</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="作者" width="130">
        <template #default="{ row }">{{ textOrNone(row.author) }}</template>
      </el-table-column>
      <el-table-column label="分类" width="130">
        <template #default="{ row }">{{ textOrNone(row.category) }}</template>
      </el-table-column>
      <el-table-column
        label="内容预览"
        min-width="260"
        :show-overflow-tooltip="{ popperStyle: {
          width: '480px', maxWidth: 'calc(100vw - 32px)', boxSizing: 'border-box',
          whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', lineHeight: '1.6',
        } }"
        :tooltip-formatter="({ row }) => textOrNone(row.content)"
      >
        <template #default="{ row }"><span class="prompt-preview">{{ textOrNone(row.content) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <span v-if="isInherited(row)" class="managed-note">系统默认</span>
          <span v-else-if="readOnly" class="managed-note">{{ row.installed ? '已安装' : '未安装' }}</span>
          <el-button
            v-else
            link
            :type="row.installed ? 'danger' : 'primary'"
            :loading="actionId === row.id"
            :disabled="loading || actionId !== null"
            @click="changeInstallation(row)"
          >{{ row.installed ? '卸载' : '安装' }}</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-if="!error && total > pageSize"
      class="library-pagination"
      layout="prev, pager, next"
      :pager-count="5"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      :disabled="loading"
      @update:current-page="selectPage"
    />
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { assetsApi } from '@/api/assets'
import ResourceCenterCreateButton from './ResourceCenterCreateButton.vue'
import '@/assets/styles/workspace-search.css'

const props = defineProps({
  agentId: { type: Number, default: null },
  systemMode: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})

const query = ref('')
const installedOnly = ref(false)
const source = ref('all')
const page = ref(1)
const pageSize = 20
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const actionId = ref(null)
let searchTimer
let request = 0
let disposed = false

const viewOptions = [
  { label: '全部', value: false },
  { label: '已安装', value: true },
]
const sourceOptions = computed(() => [
  { label: '全部', value: 'all' },
  ...(!props.systemMode ? [{ label: '我的', value: 'mine' }] : []),
  { label: '公开', value: 'public' },
  ...(!props.systemMode ? [{ label: '系统默认', value: 'system_default' }] : []),
])
const textOrNone = value => String(value ?? '').trim() ? String(value) : '无'
const isInherited = row => row.is_system && !props.agentId && !props.systemMode
const errorMessage = (err, fallback) => {
  const detail = err.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : fallback
}

const refresh = async () => {
  clearTimeout(searchTimer)
  if (disposed) return
  const currentRequest = ++request
  loading.value = true
  error.value = ''
  try {
    const result = await assetsApi.getPromptCatalog({
      q: query.value.trim() || undefined,
      source: source.value,
      installed_only: installedOnly.value,
      system_mode: props.systemMode || undefined,
      agent_id: props.agentId || undefined,
      skip: (page.value - 1) * pageSize,
      limit: pageSize,
    })
    if (currentRequest !== request) return
    total.value = result.total
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize))
    if (page.value > lastPage) return selectPage(lastPage)
    rows.value = result.items
  } catch (err) {
    if (currentRequest !== request) return
    rows.value = []
    total.value = 0
    error.value = errorMessage(err, '提示词库加载失败')
  } finally {
    if (currentRequest === request) loading.value = false
  }
}

const selectPage = value => {
  page.value = value
  return refresh()
}
const searchNow = () => selectPage(1)
const selectView = value => {
  installedOnly.value = value
  return searchNow()
}
const selectSource = value => {
  source.value = value
  return searchNow()
}
watch(query, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(searchNow, 250)
}, { flush: 'sync' })

const changeInstallation = async row => {
  if (props.readOnly || isInherited(row) || actionId.value !== null) return
  actionId.value = row.id
  const uninstall = row.installed
  try {
    if (uninstall) {
      const scope = props.systemMode ? '默认助手' : props.agentId ? '当前智能体' : '工作台'
      const name = textOrNone(row.name)
      const message = props.systemMode
        ? '确定从' + scope + '卸载「' + name + '」？其他工作台和智能体将无法继续使用这个系统提示词。'
        : '确定从' + scope + '卸载「' + name + '」？原提示词会保留。'
      await ElMessageBox.confirm(message, '卸载提示词', { type: 'warning' })
      if (disposed) return
      if (props.systemMode) await assetsApi.deleteSystemPrompt(row.id)
      else if (props.agentId) await assetsApi.unbindPrompt(row.id, props.agentId)
      else await assetsApi.removeWorkspacePrompt(row.id)
    } else if (props.systemMode) {
      await assetsApi.createSystemPrompt({
        source_template_id: row.id,
        name: row.name,
        category: row.category || '其他',
        content: row.content,
        description: row.description || null,
        variables: row.variables || null,
      })
    } else {
      await assetsApi.importPrompt({ source_template_id: row.id, ...(props.agentId ? { agent_id: props.agentId } : {}) })
    }
    if (disposed) return
    ElMessage.success(uninstall ? '提示词已卸载' : '提示词已安装')
    await refresh()
  } catch (err) {
    if (!disposed && err !== 'cancel' && err !== 'close') {
      ElMessage.error(errorMessage(err, uninstall ? '提示词卸载失败' : '提示词安装失败'))
    }
  } finally {
    actionId.value = null
  }
}

refresh()
onBeforeUnmount(() => {
  disposed = true
  request++
  clearTimeout(searchTimer)
})
defineExpose({ refresh })
</script>

<style scoped>
.workspace-search.el-input { --el-input-text-color: #303133; --el-input-placeholder-color: #303133; }
.prompt-library { min-width: 0; }
.library-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-height: 40px; }
.view-switch { height: 32px; display: inline-flex; flex: 0 0 auto; align-items: center; gap: 2px; padding: 3px; border-radius: 7px; background: #f0f1f3; box-sizing: border-box; }
.view-switch button { min-width: 58px; height: 26px; padding: 0 10px; border: 0; border-radius: 5px; color: #303133; background: transparent; cursor: pointer; font: inherit; font-size: 13px; line-height: 26px; }
.view-switch button.active { color: #202328; background: #fff; box-shadow: 0 1px 2px #14182014; font-weight: 600; }
.view-switch button:focus-visible, .source-tabs button:focus-visible { outline: 2px solid #8a9098; outline-offset: 1px; }
.library-summary { display: flex; align-items: center; margin: 22px 0 24px; }
.source-tabs { min-width: 0; display: flex; align-items: center; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.source-tabs::-webkit-scrollbar { display: none; }
.source-label { flex-shrink: 0; margin-right: 8px; color: #303133; font-size: 13px; line-height: 30px; }
.source-tabs button { box-sizing: border-box; height: 30px; flex: 0 0 auto; padding: 4px 13px; border: 1px solid transparent; border-radius: 16px; color: #303133; background: transparent; cursor: pointer; font: inherit; font-size: 13px; line-height: 20px; white-space: nowrap; }
.source-tabs button:hover { color: #24272c; background: #f3f4f5; }
.source-tabs button.active { color: #2c5f95; background: #eef5fc; border-color: #d7e7f7; font-weight: 600; }
.asset-table { border-top: 1px solid #ebecef; font-size: var(--el-font-size-base); }
.asset-table :deep(.el-table__header th.el-table__cell) { height: 42px; color: #747a83; background: #fafafa; font-size: inherit; font-weight: 600; }
.asset-table :deep(.el-table__row td.el-table__cell) { height: 48px; color: #353940; }
.prompt-preview { color: #303133; }
.asset-table :deep(.el-button) { font-size: inherit; }
.asset-table :deep(.el-table__inner-wrapper::before) { background: #e8eaed; }
.asset-name { max-width: 100%; display: inline-flex; align-items: center; gap: 8px; }
.asset-name > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.origin-badge { flex: 0 0 auto; padding: 1px 6px; border-radius: 4px; color: #5f6672; background: #f0f2f5; font-size: 11px; line-height: 18px; }
.origin-badge--mine { color: #285886; background: #eaf2fa; }
.managed-note { color: #8a9099; white-space: nowrap; }
.library-pagination { justify-content: flex-end; margin-top: 16px; }
@media (max-width: 760px) {
  .library-toolbar { align-items: stretch; }
  .library-summary { margin-top: 18px; }
  .source-tabs { width: 100%; }
}
</style>
