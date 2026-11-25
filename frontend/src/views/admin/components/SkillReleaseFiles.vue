<template>
  <section class="release-files" aria-label="技能文件">
    <div class="files-toolbar">
      <h3>技能文件</h3>
      <el-select v-model="releaseId" class="release-select" aria-label="文件版本" :disabled="!releases.length && !skill.is_mine">
        <el-option v-if="skill.is_mine && skill.development_mode && skill.latest_workspace" value="workspace" label="工作区当前文件" />
        <el-option v-for="release in releases" :key="release.id" :value="release.id" :label="releaseLabel(release)" />
      </el-select>
    </div>
    <div v-loading="loading" class="files-body" element-loading-text="正在加载文件">
      <div v-if="error" class="files-message" role="alert">
        <p>{{ error }}</p>
        <el-button plain @click="loadFiles">重新加载</el-button>
      </div>
      <el-empty v-else-if="!loading && !files.length" description="无" />
      <template v-else-if="files.length">
        <aside class="file-sidebar" aria-label="文件列表">
          <el-tree
            :key="releaseId"
            :data="files"
            node-key="path"
            :current-node-key="currentFile?.path"
            :props="{ children: 'children', label: 'label' }"
            highlight-current
            :expand-on-click-node="true"
            @node-click="selectFile"
          >
            <template #default="{ data }">
              <span class="file-node" :title="data.label">
                <el-icon><Folder v-if="data.type === 'folder'" /><Document v-else /></el-icon>
                <span class="file-node-label">{{ data.label }}</span>
              </span>
            </template>
          </el-tree>
        </aside>
        <main class="file-content">
          <template v-if="currentFile">
            <div class="file-heading">
              <span class="file-path" :title="currentFile.path">{{ currentFile.path }}</span>
              <el-radio-group v-if="isMarkdown" v-model="rawView" size="small" aria-label="文件显示方式">
                <el-radio-button :value="false">预览</el-radio-button>
                <el-radio-button :value="true">源码</el-radio-button>
              </el-radio-group>
            </div>
            <div class="file-preview">
              <MdPreview
                v-if="isMarkdown && !rawView"
                :key="`${releaseId}:${currentFile.path}`"
                class="skill-markdown-preview"
                :model-value="currentFile.content || ''"
              />
              <Codemirror
                v-else
                :key="`${releaseId}:${currentFile.path}`"
                :model-value="currentFile.content || ''"
                :style="{ height: '100%', fontSize: '14px' }"
                :extensions="codeExtensions"
                :editable="false"
                :tab-size="2"
              />
            </div>
          </template>
          <el-empty v-else description="请选择文件" />
        </main>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Document, Folder } from '@element-plus/icons-vue'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import { Codemirror } from 'vue-codemirror'
import { javascript } from '@codemirror/lang-javascript'
import { python } from '@codemirror/lang-python'
import { html } from '@codemirror/lang-html'
import { css } from '@codemirror/lang-css'
import { json } from '@codemirror/lang-json'
import { vue } from '@codemirror/lang-vue'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorState } from '@codemirror/state'
import { assetsApi } from '@/api/assets'

const props = defineProps({
  skill: { type: Object, required: true },
  currentReleaseId: { type: [Number, String], default: null },
})
const releases = computed(() => {
  const values = props.skill.releases?.length ? props.skill.releases : (props.skill.latest_release ? [props.skill.latest_release] : [])
  return values.filter(release => release.status !== 'workspace')
})
const releaseId = ref(null)
const files = ref([])
const currentFile = ref(null)
const rawView = ref(false)
const loading = ref(false)
const error = ref('')
let requestId = 0

const releaseLabel = release => {
  const labels = []
  if (release.id === props.currentReleaseId) labels.push('当前安装')
  if (release.id === props.skill.latest_release?.id) labels.push('最新')
  return `${release.version}${labels.length ? ` · ${labels.join(' / ')}` : ''}`
}
const selectFile = file => {
  if (file.type !== 'file') return
  currentFile.value = file
  rawView.value = false
}
const defaultFile = tree => {
  const queue = [...tree]
  const leaves = []
  while (queue.length) {
    const node = queue.shift()
    if (node.type === 'file') leaves.push(node)
    else queue.push(...(node.children || []))
  }
  return leaves.find(file => file.label.toLowerCase() === 'readme.md')
    || leaves.find(file => file.label.toLowerCase() === 'skill.md')
    || leaves[0] || null
}
const isMarkdown = computed(() => /\.(md|markdown)$/i.test(currentFile.value?.label || ''))
const codeExtensions = computed(() => {
  const extension = currentFile.value?.label.split('.').pop().toLowerCase()
  const languages = {
    js: () => javascript(), jsx: () => javascript({ jsx: true }),
    ts: () => javascript({ typescript: true }), tsx: () => javascript({ jsx: true, typescript: true }),
    py: python, html, css, scss: css, less: css, json, vue,
  }
  const extensions = [oneDark, EditorState.readOnly.of(true)]
  return languages[extension] ? [languages[extension](), ...extensions] : extensions
})
const loadFiles = async () => {
  const pendingId = ++requestId
  files.value = []
  currentFile.value = null
  rawView.value = false
  error.value = ''
  loading.value = Boolean(releaseId.value)
  if (!releaseId.value) return
  try {
    const result = releaseId.value === 'workspace'
      ? await assetsApi.getSkillDevelopmentFiles(props.skill.skill_id)
      : await assetsApi.getSkillReleaseFiles(releaseId.value)
    if (pendingId !== requestId) return
    files.value = result?.files || []
    currentFile.value = defaultFile(files.value)
  } catch (failure) {
    if (pendingId !== requestId) return
    const detail = failure.response?.data?.detail
    error.value = (typeof detail === 'string' ? detail : detail?.message) || '技能文件加载失败，请重试'
  } finally {
    if (pendingId === requestId) loading.value = false
  }
}
watch(() => [props.skill.skill_id, props.currentReleaseId], () => {
  if (props.currentReleaseId === 'workspace' && props.skill.is_mine && props.skill.development_mode && props.skill.latest_workspace) {
    releaseId.value = 'workspace'
    return
  }
  releaseId.value = releases.value.find(release => release.id === props.currentReleaseId)?.id
    || props.skill.latest_release?.id || releases.value[0]?.id || null
}, { immediate: true })
watch(releaseId, loadFiles, { immediate: true })
onBeforeUnmount(() => { requestId++ })
</script>

<style scoped>
.release-files { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 14px; }
.files-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.files-toolbar h3 { margin: 0; color: #313844; font-size: 15px; font-weight: 600; }
.release-select { width: 230px; max-width: 70%; }
.files-body { flex: 1; min-height: 0; display: flex; overflow: hidden; border: 1px solid #e6e9ee; border-radius: 10px; }
.files-body > .el-empty, .files-message { flex: 1; align-self: center; text-align: center; padding: 24px; color: #737d8c; }
.file-sidebar { flex: 0 0 220px; min-width: 0; overflow: auto; padding: 12px 8px; border-right: 1px solid #e6e9ee; background: #fafbfc; }
.file-sidebar :deep(.el-tree) { width: 100%; background: transparent; }
.file-sidebar :deep(.el-tree-node__content) { height: 32px; padding-right: 10px; border-radius: 5px; box-sizing: border-box; }
.file-node { display: flex; flex: 1; min-width: 0; align-items: center; gap: 7px; font-size: 13px; }
.file-node .el-icon { flex-shrink: 0; color: #8c97a6; }
.file-node-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-content { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.file-heading { min-height: 46px; flex-shrink: 0; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 16px; box-sizing: border-box; border-bottom: 1px solid #e6e9ee; }
.file-path { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: #647083; }
.file-heading .el-radio-group { flex-shrink: 0; }
.file-preview { flex: 1; min-height: 0; overflow: auto; }
.file-preview :deep(.md-editor-previewOnly) { box-sizing: border-box; padding: 16px 24px; }
@media (max-width: 640px) {
  .files-body { flex-direction: column; }
  .file-sidebar { flex: 0 0 auto; max-height: 160px; border-right: 0; border-bottom: 1px solid #e6e9ee; }
  .file-heading { padding: 8px 12px; }
  .file-preview :deep(.md-editor-previewOnly) { padding: 12px 16px; }
}
</style>
