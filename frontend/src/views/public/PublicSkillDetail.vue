<template>
  <div class="skill-detail">
    <div class="detail-header">
      <el-button class="back-btn" @click="handleBack" :icon="ArrowLeft">返回</el-button>
      <div class="header-info">
        <h2>{{ skill.name }}</h2>
        <el-tag>版本：{{ skill.version }}</el-tag>
      </div>
      <div class="header-actions"></div>
    </div>

    <div class="detail-body" v-loading="loading">
      <div class="left-sidebar">
        <div class="info-section">
          <div class="info-header">
            <h3>基本信息</h3>
          </div>
          <div class="info-content">
            <div class="info-item">
              <span class="info-label">描述：</span>
              <span class="info-value">{{ skill.description || '未设置' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">版本：</span>
              <span class="info-value">{{ skill.version }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">作者：</span>
              <span class="info-value">{{ skill.author || '未设置' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">业务模块：</span>
              <SkillMetadataTags class="info-value" :model-value="skill.module" />
            </div>
            <div class="info-item">
              <span class="info-label">适用角色：</span>
              <SkillMetadataTags class="info-value" :model-value="skill.roles" field="roles" />
            </div>
          </div>
        </div>

        <!-- Git 仓库信息 -->
        <div class="info-section" v-if="isGitBound">
          <div class="info-header">
            <h3>Git 仓库</h3>
            <el-popover placement="bottom-end" :width="450" trigger="click">
              <template #reference>
                <el-icon class="install-trigger-icon"><Connection /></el-icon>
              </template>
              <div class="install-popover-content">
                <div class="install-title">安装命令</div>
                <div class="install-cmd-group">
                  <span class="install-cmd-label">全局安装</span>
                  <div class="install-command-box">
                    <code class="install-command">{{ globalInstallCommand }}</code>
                    <el-button type="primary" size="small" :icon="CopyDocument" @click="copyCommand(globalInstallCommand)">复制</el-button>
                  </div>
                </div>
                <div class="install-cmd-group">
                  <span class="install-cmd-label">当前项目</span>
                  <div class="install-command-box">
                    <code class="install-command">{{ localInstallCommand }}</code>
                    <el-button type="primary" size="small" :icon="CopyDocument" @click="copyCommand(localInstallCommand)">复制</el-button>
                  </div>
                </div>
              </div>
            </el-popover>
          </div>
          <div class="info-content">
            <div class="info-item">
              <span class="info-label">服务商：</span>
              <span class="info-value">{{ gitProviderName }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">仓库：</span>
              <span class="info-value"><a :href="skill.git_repo_url" target="_blank" style="color: var(--brand-600);">{{ gitRepoName }}</a></span>
            </div>
            <div class="info-item">
              <span class="info-label">分支：</span>
              <span class="info-value">{{ skill.git_branch || 'main' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">同步状态：</span>
              <span class="info-value">{{ gitSyncStatusText }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">同步方向：</span>
              <span class="info-value">{{ gitSyncDirectionText }}</span>
            </div>
            <div class="info-item" v-if="skill.git_last_synced_at">
              <span class="info-label">同步时间：</span>
              <span class="info-value">{{ formatTime(skill.git_last_synced_at) }}</span>
            </div>
          </div>
        </div>

        <div class="file-tree">
          <div class="tree-header">
            <h3>文件列表</h3>
          </div>
          <el-tree
            :data="fileTree"
            :props="treeProps"
            @node-click="handleNodeClick"
            node-key="id"
            :current-node-key="currentFile?.id"
            highlight-current
          >
            <template #default="{ node, data }">
              <span class="tree-node" :class="{ 'is-skill-md': data.label === 'SKILL.md' }">
                <span class="node-label">
                  <el-icon v-if="data.type === 'folder'"><Folder /></el-icon>
                  <el-icon v-else><Document /></el-icon>
                  <span>{{ node.label }}</span>
                </span>
              </span>
            </template>
          </el-tree>
        </div>

        <div class="release-history">
          <div class="release-header">
            <h3>发布历史</h3>
          </div>
          <div class="release-list">
            <div
              v-for="release in displayedReleases"
              :key="release.id"
              class="release-item"
            >
              <div class="release-info">
                <div class="release-title-row">
                  <div class="release-version">版本：{{ release.version }}</div>
                  <el-dropdown
                    trigger="click"
                    placement="bottom-end"
                    @click.stop
                    @command="command => handleReleaseAction(command, release)"
                  >
                    <el-button
                      class="release-more-button"
                      text
                      circle
                      :icon="MoreFilled"
                      aria-label="版本操作"
                    />
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item
                          v-if="release.description"
                          command="notes"
                          :icon="Document"
                        >
                          版本日志
                        </el-dropdown-item>
                        <el-dropdown-item command="copy" :icon="Link">复制链接</el-dropdown-item>
                        <el-dropdown-item command="download" :icon="Download">导出技能</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
                <button
                  v-if="release.description"
                  type="button"
                  class="release-description"
                  title="查看完整版本描述"
                  @click="showReleaseNotes(release)"
                >
                  {{ release.description }}
                </button>
                <div class="release-time">{{ formatTime(release.created_at) }}</div>
              </div>
            </div>
            <el-empty v-if="releases.length === 0" description="暂无发布记录" :image-size="60" />
            <div v-if="hasMoreReleases" class="load-more">
              <el-button link type="primary" size="small" @click="loadMoreReleases">
                查看更多
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <div class="content-area">
        <div v-if="!currentFile" class="empty-file-placeholder">
          <el-empty description="未选择文件" :image-size="80" />
        </div>
        <template v-else>
          <div class="content-header">
            <span class="current-file">
              <el-icon v-if="currentFile.type === 'folder'"><Folder /></el-icon>
              <el-icon v-else><Document /></el-icon>
              {{ currentFile.label }}
            </span>
            <div class="content-actions" v-if="currentFile.type === 'file' && isMarkdownFile">
              <el-button
                type="primary"
                link
                size="small"
                @click="toggleRawView"
              >
                {{ isRawView ? '预览' : '源码' }}
              </el-button>
            </div>
          </div>

          <div v-if="currentFile.type === 'folder'" class="folder-view">
            <el-icon class="folder-icon"><Folder /></el-icon>
          </div>

          <div v-else class="preview-mode">
            <template v-if="isMarkdownFile">
              <MdPreview
                v-if="!isRawView"
                class="skill-markdown-preview"
                :modelValue="currentFile?.content || ''"
              />
              <Codemirror
                v-else
                :modelValue="currentFile?.content || ''"
                :style="{ height: '100%', fontSize: '14px' }"
                :extensions="codeExtensions"
                :editable="false"
                :indent-with-tab="true"
                :tab-size="2"
              />
            </template>
            <Codemirror
              v-else
              :modelValue="currentFile?.content || ''"
              :style="{ height: '100%', fontSize: '14px' }"
              :extensions="codeExtensions"
              :editable="false"
              :indent-with-tab="true"
              :tab-size="2"
            />
          </div>
        </template>
      </div>
    </div>

    <el-dialog
      v-model="releaseNotesDialogVisible"
      title="版本描述"
      width="min(520px, 92vw)"
      @closed="activeReleaseNotes = null"
    >
      <template v-if="activeReleaseNotes">
        <div class="release-notes-meta">
          <strong>版本 {{ activeReleaseNotes.version }}</strong>
          <span>{{ formatTime(activeReleaseNotes.created_at) }}</span>
        </div>
        <div class="release-notes-content">{{ activeReleaseNotes.description }}</div>
      </template>
      <template #footer>
        <el-button type="primary" @click="releaseNotesDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import SkillMetadataTags from '@/components/SkillMetadataTags.vue'
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { publicSkillsApi } from '@/api/skills'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Folder, Document, Link, Download, CopyDocument, Connection, MoreFilled } from '@element-plus/icons-vue'
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
import { formatBeijingDateTime } from '@/utils/date-time'

const router = useRouter()
const route = useRoute()

const loading = ref(false)
const skill = ref({})
const currentFile = ref(null)
const releases = ref([])
const releaseNotesDialogVisible = ref(false)
const activeReleaseNotes = ref(null)
const releaseDisplayCount = ref(5)
const releasePageSize = 5
const isRawView = ref(false)

const globalInstallCommand = computed(() => {
  const url = skill.value?.git_repo_url || ''
  return `npx skills add ${url} -g`
})

const localInstallCommand = computed(() => {
  const url = skill.value?.git_repo_url || ''
  return `npx skills add ${url}`
})

const copyCommand = async (command) => {
  try {
    await navigator.clipboard.writeText(command)
    ElMessage.success('安装命令已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

const displayedReleases = computed(() => {
  return releases.value.slice(0, releaseDisplayCount.value)
})

const hasMoreReleases = computed(() => {
  return releases.value.length > releaseDisplayCount.value
})

const treeProps = {
  children: 'children',
  label: 'label'
}

const fileTree = ref([])

const isMarkdownFile = computed(() => {
  if (!currentFile.value) return false
  const ext = currentFile.value.label.split('.').pop().toLowerCase()
  return ['md', 'markdown'].includes(ext)
})

const isGitBound = computed(() => !!skill.value?.git_repo_url)

const gitRepoName = computed(() => {
  const url = skill.value?.git_repo_url || ''
  try {
    const pathname = new URL(url).pathname.replace(/\.git$/, '')
    return pathname.replace(/^\//, '')
  } catch {
    return url
  }
})

const gitProviderName = computed(() => {
  const p = skill.value?.git_provider
  if (p === 'github') return 'GitHub'
  return 'GitLab'
})

const gitSyncStatusType = computed(() => {
  const map = { synced: 'success', syncing: '', error: 'danger' }
  return map[skill.value?.git_sync_status] || 'info'
})

const gitSyncStatusText = computed(() => {
  const map = { synced: '已同步', syncing: '同步中', error: '同步错误' }
  return map[skill.value?.git_sync_status] || '未同步'
})

const gitSyncDirectionText = computed(() => {
  const map = { 0: '未同步', 1: 'Git → 本地', 2: '本地 → Git' }
  return map[skill.value?.git_sync_direction] || '未同步'
})

const codeExtensions = computed(() => {
  if (!currentFile.value) return [oneDark]

  const ext = currentFile.value.label.split('.').pop().toLowerCase()
  const langMap = {
    'js': javascript({ jsx: false }),
    'jsx': javascript({ jsx: true }),
    'ts': javascript({ typescript: true }),
    'tsx': javascript({ jsx: true, typescript: true }),
    'py': python(),
    'html': html(),
    'css': css(),
    'scss': css(),
    'less': css(),
    'json': json(),
    'vue': vue(),
  }

  const lang = langMap[ext]
  return lang ? [lang, oneDark] : [oneDark]
})

const fetchSkillDetail = async () => {
  loading.value = true
  try {
    const data = await publicSkillsApi.getDetail(route.params.id)
    skill.value = data

    if (data.files) {
      try {
        const parsedFiles = JSON.parse(data.files)
        if (parsedFiles.tree && Array.isArray(parsedFiles.tree)) {
          const sortTree = (nodes) => {
            nodes.sort((a, b) => {
              if (a.type !== b.type) return a.type === 'folder' ? -1 : 1
              return a.label.localeCompare(b.label)
            })
            nodes.filter(n => n.type === 'folder').forEach(n => {
              if (n.children) sortTree(n.children)
            })
          }
          sortTree(parsedFiles.tree)
          fileTree.value = parsedFiles.tree
        }
      } catch (e) {
        console.error('解析文件树失败:', e)
      }
    }

    // 优先展示根目录 README.md，没有则 SKILL.md，再没有则第一个文件（BFS）
    const findFileBFS = (nodes, matchName = null) => {
      const queue = [...nodes]
      while (queue.length > 0) {
        const node = queue.shift()
        if (node.type === 'file') {
          if (matchName) {
            if (node.label.toLowerCase() === matchName.toLowerCase()) {
              return node
            }
          } else {
            return node
          }
        }
        if (node.children) {
          queue.push(...node.children)
        }
      }
      return null
    }

    const defaultFile = findFileBFS(fileTree.value, 'README.md')
      || findFileBFS(fileTree.value, 'SKILL.md')
      || findFileBFS(fileTree.value)
    if (defaultFile) {
      currentFile.value = defaultFile
    }
  } catch (error) {
    ElMessage.error('获取详情失败')
  } finally {
    loading.value = false
  }
}

const fetchReleases = async () => {
  try {
    releases.value = await publicSkillsApi.getReleases(route.params.id)
    releaseDisplayCount.value = releasePageSize
  } catch (error) {
    console.error('获取发布历史失败:', error)
  }
}

const loadMoreReleases = () => {
  releaseDisplayCount.value += releasePageSize
}

const handleReleaseAction = (command, release) => {
  if (command === 'notes') return showReleaseNotes(release)
  if (command === 'copy') return copyReleaseUrl(release)
  if (command === 'download') return downloadRelease(release)
}

const showReleaseNotes = (release) => {
  activeReleaseNotes.value = release
  releaseNotesDialogVisible.value = true
}

const copyReleaseUrl = async (release) => {
  const url = `${window.location.origin}${release.file_url}`
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('链接已复制到剪贴板')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

const downloadRelease = (release) => {
  const url = `${window.location.origin}${release.file_url}`
  const link = document.createElement('a')
  link.href = url
  link.download = release.file_url.split('/').pop()
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

const formatTime = (time) => {
  return formatBeijingDateTime(time, { second: undefined })
}

const handleBack = () => {
  router.back()
}

const handleNodeClick = (data) => {
  if (data.type === 'file') {
    currentFile.value = data
    isRawView.value = false
  } else if (data.type === 'folder') {
    currentFile.value = data
    isRawView.value = false
  }
}

const toggleRawView = () => {
  isRawView.value = !isRawView.value
}

onMounted(() => {
  fetchSkillDetail()
  fetchReleases()
})
</script>

<style scoped>
.skill-detail {
  height: calc(100dvh - 109px);
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--card);
  border-radius: 18px;
  box-shadow: var(--shadow);
  border: 1px solid var(--border-soft);
  overflow: hidden;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px 12px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.back-btn {
  margin-right: 8px;
  flex-shrink: 0;
  border: none;
  color: var(--ink-soft);
  padding: 5px 8px 5px 0;
}

.back-btn:hover {
  color: var(--brand-600);
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
  color: var(--ink);
}

.detail-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.left-sidebar {
  width: 300px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--border);
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: none;
  scrollbar-color: transparent transparent;
}

.left-sidebar:hover {
  scrollbar-width: thin;
  scrollbar-color: #c7d0dc transparent;
}

.left-sidebar::-webkit-scrollbar {
  width: 0;
}

.left-sidebar:hover::-webkit-scrollbar {
  width: 4px;
}

.left-sidebar::-webkit-scrollbar-track {
  background: transparent;
}

.left-sidebar::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 3px;
}

.left-sidebar:hover::-webkit-scrollbar-thumb {
  background: #c7d0dc;
}

.left-sidebar::-webkit-scrollbar-thumb:hover {
  background: #98a6b8;
}

.info-section {
  width: 299px;
  flex: none;
  border-bottom: 1px solid var(--border);
  background: var(--card);
}

.info-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--card);
}

.info-header h3 {
  margin: 0;
  font-size: 14px;
  color: var(--ink);
}

.info-content {
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
}

.info-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.info-label {
  font-weight: 500;
  color: var(--ink-soft);
  font-size: 12px;
  white-space: nowrap;
  flex-shrink: 0;
}

.info-value {
  color: var(--ink);
  word-break: break-word;
  flex: 1;
}

.file-tree {
  width: 299px;
  flex: none;
}

.release-history {
  width: 299px;
  flex: none;
  border-top: 1px solid var(--border);
}

.release-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.release-header h3 {
  margin: 0;
  font-size: 14px;
  color: var(--ink);
}

.release-list {
  overflow: visible;
}

.release-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-soft);
}

.release-item:last-child {
  border-bottom: none;
}

.release-item:hover {
  background-color: var(--brand-50);
}

.release-info {
  flex: 1;
  min-width: 0;
}

.release-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.release-version {
  font-size: 13px;
  font-weight: normal;
  color: var(--ink);
}

.release-more-button.el-button {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  padding: 0;
}

.release-description {
  display: block;
  width: 100%;
  margin: 3px 0 4px;
  padding: 0;
  border: 0;
  color: var(--ink-soft);
  background: transparent;
  font-size: 12px;
  line-height: 18px;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.release-description:hover {
  color: var(--brand-600);
}

.release-description:focus-visible {
  outline: 2px solid var(--brand-600);
  outline-offset: 2px;
}

.release-notes-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  color: var(--ink);
}

.release-notes-meta span {
  flex-shrink: 0;
  color: var(--ink-soft);
  font-size: 12px;
}

.release-notes-content {
  max-height: 50vh;
  overflow-y: auto;
  padding-top: 12px;
  border-top: 1px solid var(--border-soft);
  color: var(--ink-soft);
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.release-time {
  font-size: 12px;
  color: var(--ink-soft);
}

.load-more {
  text-align: center;
  padding: 8px 0;
}

.file-tree :deep(.el-tree) {
  padding: 8px 12px;
}

.file-tree :deep(.el-tree-node__content) {
  height: auto;
  padding: 4px 0;
}

.tree-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tree-header h3 {
  margin: 0;
  font-size: 14px;
  color: var(--ink);
}

.tree-node {
  display: flex;
  align-items: center;
  width: 100%;
  justify-content: space-between;
  overflow: hidden;
  padding: 2px 0;
}

.node-label {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.node-label span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.content-area {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.empty-file-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.content-header {
  padding: 12px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.current-file {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--ink-soft);
}

.content-actions {
  display: flex;
  gap: 8px;
}

.folder-view {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}

.folder-icon {
  font-size: 120px;
  color: var(--brand-200);
}

.preview-mode {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px;
  scrollbar-color: #c7d0dc transparent;
  scrollbar-width: thin;
}

.preview-mode::-webkit-scrollbar {
  width: 4px;
}

.preview-mode::-webkit-scrollbar-track {
  background: transparent;
}

.preview-mode::-webkit-scrollbar-thumb {
  background: #c7d0dc;
  border-radius: 3px;
}

.preview-mode::-webkit-scrollbar-thumb:hover {
  background: #98a6b8;
}

.preview-mode :deep(.cm-editor) {
  height: 100%;
}

.install-trigger-icon {
  font-size: 16px;
  color: var(--ink-soft);
  cursor: pointer;
  transition: color 0.2s;
}

.install-trigger-icon:hover {
  color: var(--brand-600);
}

.install-popover-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.install-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
}

.install-cmd-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.install-cmd-label {
  font-size: 12px;
  color: var(--ink-soft);
}

.install-command-box {
  display: flex;
  align-items: center;
  gap: 10px;
}

.install-command {
  flex: 1;
  font-size: 13px;
  color: #e6e6e6;
  word-break: break-all;
  font-family: 'Courier New', Courier, monospace;
  background: #1e1e1e;
  padding: 8px 12px;
  border-radius: 4px;
  line-height: 1.6;
}

@media (max-width: 760px) {
  .skill-detail {
    height: calc(100dvh - 93px);
  }
}
</style>
