<template>
  <div class="workspace-tree">
    <header class="tree-toolbar">
      <div class="tree-toolbar-group">
        <el-tooltip content="上传文件" placement="bottom" :enterable="false">
          <el-button class="tree-toolbar-button" :icon="Plus" text :loading="uploading" :disabled="deleting" aria-label="上传文件" @click="openUpload" />
        </el-tooltip>
        <el-tooltip :content="batchMode ? '退出批量选择' : '批量选择'" placement="bottom" :enterable="false" :popper-style="{ pointerEvents: 'none' }">
          <el-button class="tree-toolbar-button" :class="{ 'is-selected': batchMode }" :icon="Finished" text :disabled="deleting || uploading" :aria-label="batchMode ? '退出批量选择' : '批量选择'" :aria-pressed="batchMode" @click="toggleBatchMode" />
        </el-tooltip>
      </div>
      <div class="tree-toolbar-group">
        <el-tooltip content="刷新文件" placement="bottom" :enterable="false">
          <el-button class="tree-toolbar-button" :icon="Refresh" text :loading="loading" :disabled="deleting" aria-label="刷新工作区文件" @click="fetchFiles" />
        </el-tooltip>
        <el-tooltip :content="expanded ? '恢复面板宽度' : '展开文件面板'" placement="bottom" :enterable="false">
          <el-button
            class="tree-toolbar-button"
            :icon="expanded ? ScaleToOriginal : FullScreen"
            text
            :aria-label="expanded ? '恢复文件面板宽度' : '展开文件面板'"
            :aria-pressed="expanded"
            @click="$emit('toggle-expand')"
          />
        </el-tooltip>
        <el-tooltip content="收起文件面板" placement="bottom" :enterable="false">
          <el-button class="tree-toolbar-button" :icon="Close" text aria-label="收起工作区文件" @click="$emit('close')" />
        </el-tooltip>
      </div>
    </header>
    <input ref="uploadInput" class="tree-upload-input" type="file" multiple @change="uploadFiles" />

    <div v-if="batchMode" class="tree-batch-toolbar" :aria-busy="deleting">
      <el-checkbox :model-value="allSelected" :indeterminate="selectedItems.length > 0 && !allSelected" :disabled="loading || deleting || !selectableItems.length" @change="toggleSelectAll">全选</el-checkbox>
      <span class="tree-selection-count" role="status">{{ deleting ? `删除中 ${deleteProgress}/${deleteTotal}` : `已选 ${selectedItems.length} 项` }}</span>
      <el-tooltip content="删除所选" placement="bottom" :enterable="false" :popper-style="{ pointerEvents: 'none' }">
        <el-button class="tree-toolbar-button tree-batch-delete" :icon="Delete" text :loading="deleting" :disabled="loading || deleting || !selectedItems.length" aria-label="删除所选" @click="deleteSelected" />
      </el-tooltip>
    </div>

    <nav v-if="currentPath" class="breadcrumb" aria-label="工作区路径">
      <template v-for="(seg, idx) in breadcrumbs" :key="seg.path">
        <el-icon v-if="idx" class="crumb-separator" aria-hidden="true"><ArrowRight /></el-icon>
        <button
          type="button"
          class="crumb"
          :title="idx === 0 ? '全部文件' : seg.name"
          :aria-label="idx === 0 ? '全部文件' : seg.name"
          :aria-current="idx === breadcrumbs.length - 1 ? 'location' : undefined"
          :disabled="deleting"
          @click="navigateTo(seg.path)"
        ><el-icon v-if="idx === 0"><House /></el-icon><span>{{ idx === 0 ? '全部文件' : seg.name }}</span></button>
      </template>
    </nav>

    <div class="tree-list" v-loading="loading">
      <el-dropdown
        v-for="item in items"
        :key="item.path"
        :ref="dropdown => setContextDropdownRef(item.path, dropdown)"
        class="tree-row-context"
        trigger="contextmenu"
        placement="bottom-start"
        :disabled="batchMode || (item.type === 'dir' && item.is_managed)"
        @command="command => handleFileAction(command, item)"
        @visible-change="visible => handleContextMenuVisible(visible, item)"
      >
        <div
          class="tree-row"
          :class="{
            clickable: item.type === 'dir',
            referenceable: item.type === 'file',
            'context-open': contextMenuPath === item.path,
            'is-selected': batchMode && selectedPaths.includes(item.path),
            'batch-selectable': batchMode && !item.is_managed,
          }"
          @click="batchMode ? toggleItemSelection(item) : item.type === 'dir' && navigateTo(item.path)"
          @dblclick.stop.prevent="!batchMode && item.type === 'file' && handleFileDoubleClick(item)"
        >
          <el-checkbox v-if="batchMode" class="tree-row-checkbox" :model-value="selectedPaths.includes(item.path)" :disabled="item.is_managed || loading || deleting" :aria-label="`选择 ${item.name}`" @click.stop @dblclick.stop @change="toggleItemSelection(item)" />
          <el-icon :size="14" :color="item.type === 'dir' ? '#656c75' : '#92979f'">
            <Folder v-if="item.type === 'dir'" /><Document v-else />
          </el-icon>
          <span class="tree-label">
            <span class="tree-name" :title="item.type === 'file' && item.is_previewable ? `${item.name} · 双击预览` : item.name">{{ item.name }}</span>
            <el-icon
              v-if="item.is_managed"
              class="tree-managed-lock"
              :size="12"
              title="智能体托管内容，不可删除"
            ><Lock /></el-icon>
          </span>
          <span v-if="item.type === 'file' || !item.is_managed" class="tree-trailing">
            <span v-if="item.type === 'file'" class="tree-size">{{ formatSize(item.size) }}</span>
            <span v-if="!batchMode" class="tree-actions">
              <el-dropdown
                trigger="click"
                placement="bottom-end"
                @click.stop
                @dblclick.stop
                @command="command => handleFileAction(command, item, 'actions')"
                @visible-change="visible => handleReferenceMenuVisible(visible, item, 'actions')"
              >
                <el-button
                  class="tree-more-button"
                  :icon="MoreFilled"
                  text
                  circle
                  :aria-label="item.type === 'dir' ? '目录操作' : '文件操作'"
                />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="item.type === 'file' && item.is_previewable" command="preview" :icon="View">
                      预览
                    </el-dropdown-item>
                    <el-dropdown-item v-if="item.type === 'file'" command="download" :icon="Download">
                      下载
                    </el-dropdown-item>
                    <el-dropdown-item v-if="item.type === 'file'" command="context" :icon="Paperclip">
                      添加到上下文
                    </el-dropdown-item>
                    <el-dropdown-item
                      v-if="!item.is_managed"
                      command="delete"
                      :icon="Delete"
                      divided
                    >
                      删除
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </span>
          </span>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-if="item.type === 'file' && item.is_previewable" command="preview" :icon="View">
              预览
            </el-dropdown-item>
            <el-dropdown-item v-if="item.type === 'file'" command="download" :icon="Download">
              下载
            </el-dropdown-item>
            <el-dropdown-item v-if="item.type === 'file'" command="context" :icon="Paperclip">
              添加到上下文
            </el-dropdown-item>
            <el-dropdown-item
              v-if="!item.is_managed"
              command="delete"
              :icon="Delete"
              divided
            >
              删除
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <div v-if="!loading && items.length === 0" class="tree-empty">暂无内容</div>
    </div>

    <el-dialog
      v-model="previewVisible"
      :title="previewData?.name || '文本预览'"
      width="min(860px, calc(100vw - 32px))"
      append-to-body
      destroy-on-close
    >
      <div class="workspace-preview" v-loading="previewLoading">
        <div v-if="previewData" class="workspace-preview-meta">
          <div class="workspace-preview-facts">
            <span>{{ formatSize(previewData.size) || '0B' }}</span>
            <span>{{ previewData.line_count }} 行</span>
          </div>
          <div class="workspace-preview-actions">
            <div v-if="hasRenderedPreview" class="workspace-preview-switch" aria-label="文件显示方式">
              <button
                type="button"
                :class="{ active: previewMode === 'preview' }"
                @click="previewMode = 'preview'"
              >
                <el-icon><View /></el-icon>
                预览
              </button>
              <button
                type="button"
                :class="{ active: previewMode === 'source' }"
                @click="previewMode = 'source'"
              >
                <el-icon><Document /></el-icon>
                源码
              </button>
            </div>
            <el-tooltip content="下载" placement="top">
              <el-button
                :icon="Download"
                circle
                size="small"
                aria-label="下载文件"
                @click="downloadFile(previewData)"
              />
            </el-tooltip>
            <el-tooltip v-if="!previewData.is_managed" content="删除" placement="top">
              <el-button
                :icon="Delete"
                circle
                size="small"
                aria-label="删除文件"
                @click="deletePreviewFile"
              />
            </el-tooltip>
          </div>
        </div>
        <template v-if="previewData">
          <iframe
            v-if="previewMode === 'preview' && previewKind === 'html'"
            class="workspace-html-preview"
            :srcdoc="htmlPreviewDocument"
            sandbox="allow-scripts"
            :title="`${previewData.name} 预览`"
          />
          <div
            v-else-if="previewMode === 'preview' && previewKind === 'markdown'"
            class="workspace-markdown-preview"
          >
            <MessageContent
              :content="previewData.content"
              :html-preview-enabled="false"
              view-only
            />
          </div>
          <pre v-else class="workspace-preview-content"><code>{{ previewData.content }}</code></pre>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { h, ref, computed, nextTick, onBeforeUnmount, onMounted, watch } from 'vue'
import {
  Folder, Document, Refresh, Download, Delete, Lock, View, Close, House, ArrowRight,
  MoreFilled, Paperclip, Plus, FullScreen, ScaleToOriginal, Finished,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api/request'
import { useAuthStore } from '@/stores/auth'
import { buildHtmlPreviewDocument } from '@/utils/html-preview'
import MessageContent from './MessageContent.vue'

const props = defineProps({
  agentId: { type: Number, required: true },
  active: { type: Boolean, default: true },
  expanded: { type: Boolean, default: false },
})

const emit = defineEmits(['add-context', 'close', 'toggle-expand'])
const authStore = useAuthStore()

const currentPath = ref('')
const items = ref([])
const loading = ref(false)
const uploading = ref(false)
const batchMode = ref(false)
const selectedPaths = ref([])
const deleting = ref(false)
const deleteProgress = ref(0)
const deleteTotal = ref(0)
let workspaceVersion = 0
const selectableItems = computed(() => items.value.filter(item => !item.is_managed))
const selectedItems = computed(() => selectableItems.value.filter(item => selectedPaths.value.includes(item.path)))
const allSelected = computed(() => selectableItems.value.length > 0 && selectedItems.value.length === selectableItems.value.length)
const uploadInput = ref(null)
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewData = ref(null)
const previewMode = ref('source')
const contextMenuPath = ref('')
const contextDropdownRefs = new Map()
let pendingReference = null
let referenceFocusFrame = 0
let fetchSequence = 0
const PREVIEW_MAX_BYTES = 1024 * 1024
const WORKSPACE_DOWNLOAD_TIMEOUT_MS = 120000

const previewKind = computed(() => {
  const path = String(previewData.value?.path || '').toLowerCase()
  if (path.endsWith('.html') || path.endsWith('.htm')) return 'html'
  if (path.endsWith('.md') || path.endsWith('.markdown')) return 'markdown'
  return 'source'
})
const hasRenderedPreview = computed(() => previewKind.value !== 'source')
const htmlPreviewDocument = computed(() => (
  previewKind.value === 'html'
    ? buildHtmlPreviewDocument(previewData.value?.content || '')
    : ''
))

const breadcrumbs = computed(() => {
  if (!currentPath.value) return [{ name: '/', path: '' }]
  const segs = currentPath.value.split('/')
  const result = [{ name: '/', path: '' }]
  let acc = ''
  for (const seg of segs) {
    acc = acc ? acc + '/' + seg : seg
    result.push({ name: seg, path: acc })
  }
  return result
})

const navigateTo = (path) => {
  if (deleting.value) return
  selectedPaths.value = []
  items.value = []
  currentPath.value = path
  fetchFiles()
}

const toggleBatchMode = () => {
  if (deleting.value) return
  batchMode.value = !batchMode.value
  selectedPaths.value = []
  contextDropdownRefs.forEach(dropdown => dropdown?.handleClose?.())
}

const toggleItemSelection = item => {
  if (item.is_managed || loading.value || deleting.value) return
  selectedPaths.value = selectedPaths.value.includes(item.path)
    ? selectedPaths.value.filter(path => path !== item.path)
    : [...selectedPaths.value, item.path]
}

const toggleSelectAll = checked => {
  if (loading.value || deleting.value) return
  selectedPaths.value = checked ? selectableItems.value.map(item => item.path) : []
}

const openUpload = () => { if (!deleting.value) uploadInput.value?.click() }

const uploadFiles = async event => {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  if (!files.length) return
  const formData = new FormData()
  files.forEach(file => formData.append('files', file))
  uploading.value = true
  try {
    const response = await api.post(`/agents/${props.agentId}/files/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const count = response?.uploaded?.length || files.length
    ElMessage.success(count === 1 ? '文件已上传' : `已上传 ${count} 个文件`)
    selectedPaths.value = []
    currentPath.value = ''
    await fetchFiles()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '文件上传失败')
  } finally {
    uploading.value = false
  }
}

const fetchFiles = async () => {
  const requestSequence = ++fetchSequence
  const requestedPath = currentPath.value
  loading.value = true
  try {
    const params = requestedPath ? { path: requestedPath } : {}
    const res = await api.get(`/agents/${props.agentId}/files`, { params })
    if (requestSequence === fetchSequence && currentPath.value === requestedPath && res.type === 'dir') {
      items.value = res.items || []
      selectedPaths.value = selectedPaths.value.filter(path => selectableItems.value.some(item => item.path === path))
    }
  } catch (e) {
    // 静默失败
  } finally {
    if (requestSequence === fetchSequence) loading.value = false
  }
}

const formatSize = (bytes) => {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'K'
  return (bytes / (1024 * 1024)).toFixed(1) + 'M'
}

const downloadFile = async (file) => {
  if (Number(file.size || 0) > 20 * 1024 * 1024) {
    ElMessage.warning('工作区文件下载最大支持 20 MiB')
    return
  }
  try {
    const blob = await api.get(`/agents/${props.agentId}/files/download`, {
      params: { path: file.path },
      responseType: 'blob',
      timeout: WORKSPACE_DOWNLOAD_TIMEOUT_MS,
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = file.name
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) {
    let detail = e.response?.data?.detail
    if (e.response?.data instanceof Blob) {
      try {
        const body = JSON.parse(await e.response.data.text())
        detail = body.detail || body.message
      } catch { /* fallback below */ }
    }
    const isTimeout = e.code === 'ECONNABORTED' || e.code === 'ETIMEDOUT'
    ElMessage.error(typeof detail === 'string' ? detail : isTimeout ? '文件下载超时，请重试' : '下载失败')
  }
}

const previewFile = async (file) => {
  if (!/\.html?$/i.test(String(file.path || '')) && Number(file.size || 0) > PREVIEW_MAX_BYTES) {
    ElMessage.warning('文件超过 1 MiB，无法预览')
    return
  }
  previewVisible.value = true
  previewLoading.value = true
  previewData.value = null
  previewMode.value = 'source'
  try {
    const response = await api.get(`/agents/${props.agentId}/files/preview`, {
      params: { path: file.path },
    })
    previewData.value = { ...response, is_managed: !!file.is_managed }
    previewMode.value = ['html', 'markdown'].includes(previewKind.value) ? 'preview' : 'source'
  } catch (e) {
    previewVisible.value = false
    ElMessage.error(e?.response?.data?.detail || '文件预览失败')
  } finally {
    previewLoading.value = false
  }
}

const handleFileDoubleClick = (file) => {
  if (file.is_previewable) {
    previewFile(file)
    return
  }
  ElMessage.warning('该文件类型不支持预览')
}

const addToContext = (file) => {
  emit('add-context', file)
  ElMessage.success('已添加到上下文')
}

const handleFileAction = (command, file, menu = 'context') => {
  if (batchMode.value || deleting.value) return
  if (command === 'preview') previewFile(file)
  else if (command === 'download') downloadFile(file)
  else if (command === 'context') pendingReference = { file, menu, agentId: props.agentId }
  else if (command === 'delete') deleteItem(file)
}

const setContextDropdownRef = (path, dropdown) => {
  if (dropdown) contextDropdownRefs.set(path, dropdown)
  else contextDropdownRefs.delete(path)
}

const handleReferenceMenuVisible = (visible, item, menu) => {
  if (visible || pendingReference?.file.path !== item.path || pendingReference.menu !== menu) return
  const reference = pendingReference
  pendingReference = null
  // Dropdown closure restores its old focus; hand off only after that update finishes.
  nextTick(() => {
    referenceFocusFrame = requestAnimationFrame(() => {
      if (props.active && props.agentId === reference.agentId) addToContext(reference.file)
    })
  })
}

const handleContextMenuVisible = (visible, item) => {
  handleReferenceMenuVisible(visible, item, 'context')
  if (!visible) {
    if (contextMenuPath.value === item.path) contextMenuPath.value = ''
    return
  }

  contextMenuPath.value = item.path
  contextDropdownRefs.forEach((dropdown, path) => {
    if (path !== item.path) dropdown?.handleClose?.()
  })
}

const deletePreviewFile = async () => {
  if (!previewData.value) return
  const deleted = await deleteItem(previewData.value)
  if (deleted) previewVisible.value = false
}

const deleteItem = async (item) => {
  if (deleting.value || item.is_managed) return false
  const isDirectory = item.type === 'dir'
  const subject = isDirectory ? `目录“${item.name}”及其中的全部内容` : `文件“${item.name}”`
  try {
    await ElMessageBox.confirm(`确定删除${subject}吗？此操作不可恢复。`, isDirectory ? '删除目录' : '删除文件', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
    await api.delete(`/agents/${props.agentId}/files`, { params: { path: item.path } })
    ElMessage.success(isDirectory ? '目录已删除' : '文件已删除')
    await fetchFiles()
    return true
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e?.response?.data?.detail || '删除失败')
    return false
  }
}

const deleteSelected = async () => {
  if (deleting.value || loading.value || !selectedItems.value.length) return
  const targets = [...selectedItems.value]
  const agentId = props.agentId
  const version = workspaceVersion
  deleting.value = true
  deleteProgress.value = 0
  deleteTotal.value = targets.length
  try {
    await ElMessageBox.confirm(h('div', [
      h('p', `确定删除选中的 ${targets.length} 项吗？此操作不可恢复。`),
      targets.some(item => item.type === 'dir') ? h('p', '选中的目录及其中全部内容也会删除。') : null,
      h('ul', { style: { maxHeight: '220px', overflowY: 'auto', paddingLeft: '20px', overflowWrap: 'anywhere' } },
        targets.map(item => h('li', { key: item.path }, `${item.path}${item.type === 'dir' ? '/' : ''}`))),
    ]), '批量删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger',
    })
    if (version !== workspaceVersion) return
    const failed = []
    const removed = []
    // Reuse the authorized single-path endpoint and keep failures available for retry.
    for (const item of targets) {
      try {
        await api.delete(`/agents/${agentId}/files`, { params: { path: item.path } })
        removed.push(item.path)
      } catch (error) {
        failed.push({ path: item.path, detail: error?.response?.data?.detail || '删除失败' })
      }
      deleteProgress.value += 1
    }
    if (version !== workspaceVersion) return
    if (previewData.value && removed.some(path => previewData.value.path === path || previewData.value.path.startsWith(`${path}/`))) previewVisible.value = false
    items.value = items.value.filter(item => !removed.includes(item.path))
    selectedPaths.value = failed.map(item => item.path)
    if (failed.length) {
      ElMessage.error(`已删除 ${removed.length} 项，${failed.length} 项失败：${failed[0].path}（${failed[0].detail}）`)
    } else {
      batchMode.value = false
      ElMessage.success(`已删除 ${removed.length} 项`)
    }
    if (props.active) await fetchFiles()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('批量删除失败')
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  if (props.active) fetchFiles()
})

onBeforeUnmount(() => {
  pendingReference = null
  cancelAnimationFrame(referenceFocusFrame)
})

watch(() => props.agentId, () => {
  workspaceVersion += 1
  fetchSequence += 1
  batchMode.value = false
  selectedPaths.value = []
  items.value = []
  currentPath.value = ''
  previewVisible.value = false
  if (props.active) fetchFiles()
})

watch(() => props.active, (active) => {
  if (active) {
    fetchFiles()
  } else {
    // 关闭期间忽略仍在途的旧响应；再次打开会按当前目录重新请求。
    fetchSequence += 1
    loading.value = false
  }
})

defineExpose({ fetchFiles })
</script>

<style scoped>
.workspace-tree { color: #34383f; background: #fff; font-size: 12px; display: flex; flex-direction: column; height: 100%; }
.tree-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 54px;
  gap: 8px;
  padding: 0 12px;
  border-bottom: 1px solid #eeeeec;
  background: #fff;
  box-sizing: border-box;
}
.tree-toolbar-group { display: flex; flex-shrink: 0; align-items: center; gap: 2px; }
.tree-toolbar-button.el-button {
  width: 30px;
  height: 30px;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 4px;
  color: #555b63;
  background: transparent;
}
.tree-toolbar-button.el-button:hover,
.tree-toolbar-button.el-button:focus-visible { color: #111418; background: #f1f1ef; }
.tree-toolbar-button.el-button:focus-visible { outline: 2px solid #737983; outline-offset: 1px; }
.tree-toolbar-button.el-button.is-selected { color: #409eff; background: #ecf5ff; }
.tree-toolbar-button.el-button.is-disabled { color: #c0c4cc; background: transparent; }
.tree-batch-toolbar { display: flex; align-items: center; flex: 0 0 40px; gap: 10px; padding: 0 19px; border-bottom: 1px solid #eeeeec; }
.tree-batch-toolbar :deep(.el-checkbox__label) { font-size: 12px; padding-left: 6px; }
.tree-selection-count { min-width: 0; flex: 1; color: #909399; font-size: 12px; }
.tree-batch-delete.el-button:not(.is-disabled) { color: #f56c6c; }
.tree-row-checkbox { flex: 0 0 14px; height: 24px; margin: 0; }
.tree-row.is-selected { background: #ecf5ff; }
.tree-row.batch-selectable { cursor: pointer; }
.tree-row:has(.tree-row-checkbox):hover .tree-size { opacity: 1; }
.tree-upload-input { display: none; }
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 0 0 34px;
  min-width: 0;
  margin: 0 14px 6px;
  padding: 0 2px;
  overflow-x: auto;
  border: 0;
  background: transparent;
  scrollbar-width: thin;
  box-sizing: border-box;
}
.crumb-separator { flex-shrink: 0; color: #a1a6ae; font-size: 10px; }
.crumb {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 5px;
  max-width: 160px;
  height: 26px;
  padding: 0 5px;
  border: 0;
  border-radius: 4px;
  color: #787e87;
  background: transparent;
  font: inherit;
  cursor: pointer;
  white-space: nowrap;
}
.crumb span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.crumb .el-icon { flex-shrink: 0; font-size: 13px; }
.crumb[aria-current="location"] { color: #3f454e; }
.crumb:hover { color: #292d33; background: #f0f2f5; }
.crumb:focus-visible { outline: 2px solid #737983; outline-offset: -2px; }

.tree-list { padding: 10px 12px 16px; flex: 1; overflow-y: auto; min-height: 0; }
.breadcrumb + .tree-list { padding-top: 2px; }
.tree-list::-webkit-scrollbar { width: 4px; }
.tree-list::-webkit-scrollbar-track { background: #f1f1f1; border-radius: 3px; }
.tree-list::-webkit-scrollbar-thumb { background: #c1c1c1; border-radius: 3px; }
.tree-list::-webkit-scrollbar-thumb:hover { background: #a8a8a8; }
.tree-row-context { display: block; width: 100%; }
.tree-row-context.is-disabled { color: #606266; }
.tree-row {
  min-height: 32px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 7px;
  border-radius: 5px;
  box-sizing: border-box;
}
.tree-row:hover,
.tree-row.context-open { background: #f3f4f5; }
.tree-row.clickable { cursor: pointer; }
.tree-row.referenceable { cursor: default; user-select: none; }
.tree-label {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 4px;
}
.tree-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-managed-lock {
  color: #909399;
  flex: 0 0 auto;
}
.tree-trailing {
  position: relative;
  width: 38px;
  height: 20px;
  flex: 0 0 38px;
}
.tree-size,
.tree-actions {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  transition: opacity 0.15s;
}
.tree-size {
  overflow: hidden;
  color: #c0c4cc;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-actions {
  opacity: 0;
  pointer-events: none;
}
.tree-more-button.el-button {
  width: 24px;
  height: 24px;
  padding: 0;
  color: #909399;
}
.tree-row:hover .tree-size { opacity: 0; }
.tree-row:hover .tree-actions { opacity: 1; pointer-events: auto; }
.tree-more-button.el-button:hover { color: #25282d; }
.tree-empty { padding: 10px 8px; color: #b0b3b8; line-height: 22px; text-align: left; }

.workspace-preview { min-height: 160px; }
.workspace-preview-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
  color: #909399;
  font-size: 12px;
}
.workspace-preview-facts,
.workspace-preview-actions {
  display: flex;
  align-items: center;
}
.workspace-preview-facts { gap: 12px; }
.workspace-preview-actions {
  gap: 6px;
  margin-left: auto;
}
.workspace-preview-switch {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  padding: 2px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  background: #eef1f4;
}
.workspace-preview-switch button {
  height: 24px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  border: 0;
  border-radius: 4px;
  color: #606b78;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  letter-spacing: 0;
}
.workspace-preview-switch button:hover { color: #1f5f99; }
.workspace-preview-switch button.active {
  color: #1f5f99;
  background: #fff;
  box-shadow: 0 1px 3px rgba(31, 45, 61, 0.14);
}
.workspace-html-preview,
.workspace-markdown-preview {
  width: 100%;
  height: min(68vh, 720px);
  min-height: 320px;
  box-sizing: border-box;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  background: #fff;
}
.workspace-html-preview { display: block; }
.workspace-markdown-preview {
  padding: 18px 20px;
  overflow: auto;
}
.workspace-preview-content {
  max-height: min(68vh, 720px);
  margin: 0;
  padding: 14px 16px;
  overflow: auto;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  color: #303133;
  background: #f7f8fa;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre;
  tab-size: 2;
}
</style>
