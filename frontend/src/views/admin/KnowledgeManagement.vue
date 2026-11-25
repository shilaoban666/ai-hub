<template>
  <div class="page-container knowledge-page">
    <header class="page-header">
      <div>
        <h2>知识库管理</h2>
        <p class="subtitle">上传文件到百炼知识库，可同时存一份到企业钉盘</p>
      </div>
      <div class="header-actions">
        <el-tooltip content="刷新" placement="top">
          <el-button :icon="Refresh" circle aria-label="刷新" :loading="indicesLoading" @click="reloadAll" />
        </el-tooltip>
        <el-button v-if="settings.can_manage" :icon="Setting" @click="router.push('/admin/knowledge-settings')">知识库设置</el-button>
      </div>
    </header>

    <el-alert v-if="settingsLoaded && !settings.bailian_configured" type="warning" :closable="false" show-icon class="block-alert"
      :title="settings.can_manage ? '尚未接入百炼知识库，请先到“系统设置 → 知识库设置”填写 AccessKey 和业务空间 ID' : '知识库尚未接入，请联系超级管理员完成配置'" />
    <el-alert v-if="pageError" :title="pageError" type="error" :closable="false" show-icon class="block-alert" />

    <el-alert v-if="accessLoaded && !access.can_upload" type="info" :closable="false" show-icon class="block-alert"
      :title="access.error || '你所在的部门暂未开通知识库上传；可以浏览知识库文档和做检索测试。需要上传请联系管理员'" />
    <section v-if="access.can_upload" class="panel upload-panel" aria-labelledby="upload-title">
      <div class="panel-header"><h3 id="upload-title">上传文件</h3></div>
      <div class="panel-body">
        <el-form label-position="top" class="target-form">
          <el-form-item label="知识库">
            <el-select v-model="indexId" filterable placeholder="选择知识库" :loading="indicesLoading" :disabled="!settings.bailian_configured" @change="onIndexChange">
              <el-option v-for="item in indices" :key="item.id" :label="item.name || item.id" :value="item.id">
                <span>{{ item.name || item.id }}</span><span class="option-hint">{{ item.id }}</span>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="类目">
            <el-tree-select :key="categoryTreeKey" v-model="categoryId" lazy :load="loadCategories" node-key="id" check-strictly
              :props="{ label: 'name', isLeaf: 'leaf' }" :render-after-expand="false" filterable clearable
              placeholder="选择文件所属类目" :disabled="!settings.bailian_configured" :cache-data="categoryCache" />
          </el-form-item>
        </el-form>

        <el-upload ref="uploadRef" v-model:file-list="fileList" drag multiple :auto-upload="false" :limit="10"
          :accept="acceptTypes" :on-exceed="onExceed" :disabled="!settings.bailian_configured" class="file-drop">
          <el-icon class="drop-icon"><UploadFilled /></el-icon>
          <div class="el-upload__text">将文件拖到此处，或<em>点击选择</em></div>
          <template #tip>
            <div class="el-upload__tip">支持 PDF、Word、Excel、PPT、TXT、Markdown、HTML、图片等，单个文件不超过 100 MB，一次最多 10 个</div>
          </template>
        </el-upload>

        <div class="dingtalk-sync">
          <div class="sync-switch">
            <el-switch v-model="syncDingtalk" :disabled="!settings.bailian_configured" />
            <div>
              <strong>同步存储到钉盘</strong>
              <span>开启后，文件导入知识库成功后会再存一份到所选的企业钉盘目录</span>
            </div>
          </div>
          <div v-if="syncDingtalk" class="sync-detail">
            <el-alert v-if="!dingtalk.configured" type="info" :closable="false" show-icon
              :title="settings.can_manage ? '尚未配置钉钉应用，请到“系统设置 → 知识库设置”填写 Client ID 和 Client Secret' : '管理员尚未配置钉钉应用，暂时无法同步到钉盘'" />
            <template v-else-if="!dingtalk.bound">
              <p class="muted">首次使用需要用钉钉扫码授权，用于确认你在钉盘中的身份和目录权限。</p>
              <el-button type="primary" :loading="authorizing" @click="startDingtalkAuth">钉钉扫码授权</el-button>
            </template>
            <template v-else>
              <div class="bound-line">
                <el-tag type="success" effect="plain">已绑定钉钉：{{ dingtalk.nick || '无' }}</el-tag>
                <el-popconfirm title="解除后需要重新扫码才能同步到钉盘" confirm-button-text="解除" cancel-button-text="取消" @confirm="unbindDingtalk">
                  <template #reference><el-button link type="info">解除绑定</el-button></template>
                </el-popconfirm>
              </div>
              <el-cascader :key="folderTreeKey" v-model="folderPath" class="folder-picker" :props="folderProps" clearable filterable
                placeholder="选择钉盘团队文件目录" @change="onFolderChange" @expand-change="onFolderExpand" />
              <div class="folder-link">
                <el-input v-model="folderLink" clearable placeholder="或粘贴钉盘文件夹链接（只共享了深层目录给你时用这个）"
                  @keyup.enter="useFolderLink" />
                <el-button :loading="resolvingLink" :disabled="!folderLink.trim()" @click="useFolderLink">使用</el-button>
              </div>
              <div v-if="recentFolders.length" class="recent-folders">
                <span class="muted">最近使用：</span>
                <el-check-tag v-for="item in recentFolders" :key="item.node_id" :checked="linkedFolder?.node_id === item.node_id"
                  @change="useFolder(item)">{{ item.path }}</el-check-tag>
              </div>
              <p v-if="folderId" class="folder-target">将存入：{{ folderPathLabel }}</p>
              <p v-else class="folder-target muted">点开文件夹即选中它，可继续点开子文件夹；选不到的目录可以粘贴链接</p>
              <el-alert v-if="folderError" :title="folderError" type="error" :closable="false" show-icon />
            </template>
          </div>
        </div>

        <div class="upload-actions">
          <el-button type="primary" :icon="Upload" :loading="uploading" :disabled="!canUpload" @click="submitUpload">
            {{ uploading ? `上传中 ${uploadPercent}%` : '开始上传' }}
          </el-button>
          <span v-if="uploadBlocker" class="muted">{{ uploadBlocker }}</span>
        </div>
      </div>
    </section>

    <section class="panel">
      <el-tabs v-model="activeTab" class="panel-tabs" @tab-change="onTabChange">
        <el-tab-pane label="上传记录" name="uploads">
          <div class="tab-toolbar">
            <span class="muted">仅显示你本人的上传记录。上传后需要等待百炼解析和导入，通常 1–5 分钟</span>
          </div>
          <el-table v-loading="uploadsLoading" :data="uploads" row-key="id" empty-text="暂无上传记录">
            <el-table-column label="文件" min-width="200" show-overflow-tooltip>
              <template #default="{ row }"><span class="file-name"><el-icon><Document /></el-icon>{{ row.file_name }}</span></template>
            </el-table-column>
            <el-table-column label="大小" width="100" align="right"><template #default="{ row }">{{ fileSize(row.file_size) }}</template></el-table-column>
            <el-table-column label="知识库 / 类目" min-width="170" show-overflow-tooltip>
              <template #default="{ row }">{{ row.index_name || row.index_id }} / {{ row.category_name || row.category_id }}</template>
            </el-table-column>
            <el-table-column label="知识库状态" width="150">
              <template #default="{ row }">
                <el-tooltip :disabled="!row.error_message" :content="row.error_message || ''" placement="top">
                  <el-tag :type="statusMeta(row.status).type" effect="plain">
                    <el-icon v-if="isActive(row.status)" class="status-spinner is-loading"><Loading /></el-icon>{{ statusMeta(row.status).label }}
                  </el-tag>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="钉盘同步" min-width="170">
              <template #default="{ row }">
                <span v-if="row.dingtalk_status === 'none'" class="muted">无</span>
                <template v-else>
                  <el-tooltip :content="row.dingtalk_error || row.dingtalk_folder_path || '无'" placement="top">
                    <el-tag :type="dingtalkMeta(row.dingtalk_status).type" effect="plain">{{ dingtalkMeta(row.dingtalk_status).label }}</el-tag>
                  </el-tooltip>
                  <el-link v-if="row.dingtalk_url" :href="row.dingtalk_url" target="_blank" rel="noopener noreferrer" type="primary" class="drive-link">打开</el-link>
                </template>
              </template>
            </el-table-column>
            <el-table-column label="上传时间" width="170"><template #default="{ row }">{{ time(row.created_at) }}</template></el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-popconfirm :title="`从知识库${row.dingtalk_status === 'success' ? '和钉盘' : ''}彻底删除这个文件？删除后不能恢复`" width="260"
                  confirm-button-text="删除" cancel-button-text="取消" confirm-button-type="danger" @confirm="removeUpload(row)">
                  <template #reference>
                    <el-button link type="danger" :loading="deletingId === row.id"
                      :disabled="isActive(row.status) || row.dingtalk_status === 'pending'">删除</el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
          <div class="pagination-container">
            <el-pagination v-model:current-page="uploadPage" :page-size="10" :total="uploadTotal" layout="total, prev, pager, next" @current-change="reloadUploads" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="知识库文档" name="documents">
          <div class="tab-toolbar">
            <el-input v-model="documentKeyword" :prefix-icon="Search" clearable placeholder="按文件名搜索" class="search-input" @keyup.enter="searchDocuments" @clear="searchDocuments" />
            <el-button @click="searchDocuments">搜索</el-button>
          </div>
          <el-alert v-if="documentsError" :title="documentsError" type="error" :closable="false" show-icon />
          <el-table v-loading="documentsLoading" :data="documents" row-key="id" :empty-text="indexId ? '暂无文档' : '请先选择知识库'">
            <el-table-column prop="name" label="文件名称" min-width="220" show-overflow-tooltip />
            <el-table-column label="类型" width="100"><template #default="{ row }">{{ row.document_type || '无' }}</template></el-table-column>
            <el-table-column label="大小" width="110" align="right"><template #default="{ row }">{{ fileSize(row.size) }}</template></el-table-column>
            <el-table-column label="状态" width="130"><template #default="{ row }"><el-tag :type="documentMeta(row.status).type" effect="plain">{{ documentMeta(row.status).label }}</el-tag></template></el-table-column>
            <el-table-column label="更新时间" width="170"><template #default="{ row }">{{ row.updated_at ? time(Number(row.updated_at) || row.updated_at) : '无' }}</template></el-table-column>
            <el-table-column label="钉盘链接" width="130">
              <template #default="{ row }">
                <el-link v-if="row.dingtalk_url" :href="row.dingtalk_url" target="_blank" rel="noopener noreferrer" type="primary" :icon="Link">在钉盘打开</el-link>
                <span v-else class="muted">无</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="pagination-container">
            <el-pagination v-model:current-page="documentPage" :page-size="20" :total="documentTotal" layout="total, prev, pager, next" @current-change="loadDocuments" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="检索测试" name="retrieve">
          <div class="retrieve-box">
            <el-input v-model="retrieveQuery" type="textarea" :rows="2" maxlength="1000" show-word-limit placeholder="输入问题，测试知识库能检索到哪些内容，例如：报销流程是什么？" />
            <div class="retrieve-actions">
              <el-button type="primary" :icon="Search" :loading="retrieving" :disabled="!indexId || !retrieveQuery.trim()" @click="runRetrieve">检索</el-button>
              <span v-if="retrieveUsage" class="muted">召回 {{ retrieveResults.length }} 条 · RAG Token {{ retrieveUsage.rag_tokens }} · 耗时 {{ retrieveUsage.latency_ms }} ms</span>
              <span class="muted">检索测试会计入知识库调用用量</span>
            </div>
            <el-alert v-if="retrieveError" :title="retrieveError" type="error" :closable="false" show-icon />
            <ol v-if="retrieveResults.length" class="retrieve-results">
              <li v-for="(node, index) in retrieveResults" :key="index">
                <div class="result-meta"><strong>{{ node.doc_name || node.title || '无' }}</strong><span>相关度 {{ Number(node.score || 0).toFixed(3) }}</span></div>
                <p>{{ node.text || '无' }}</p>
              </li>
            </ol>
            <el-empty v-else-if="retrieveUsage" description="没有检索到相关内容" :image-size="64" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Document, Link, Loading, Refresh, Search, Setting, Upload, UploadFilled } from '@element-plus/icons-vue'
import { knowledgeApi, knowledgeErrorText } from '@/api/knowledge'
import { formatBeijingDateTime } from '@/utils/date-time'

const DRAFT_KEY = 'aihub-knowledge-upload-draft'
const route = useRoute()
const router = useRouter()
const acceptTypes = '.pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx,.html,.htm,.png,.jpg,.jpeg,.bmp,.gif,.csv,.epub,.mobi,.json'
const callbackUrl = `${window.location.origin}/admin/knowledge/dingtalk-callback`

const settings = ref({})
const settingsLoaded = ref(false)
const pageError = ref('')
const indices = ref([])
const indicesLoading = ref(false)
const indexId = ref('')
const categoryId = ref('')
const categoryCache = ref([])
const categoryTreeKey = ref(0)
const categoryNames = {}
const fileList = ref([])
const uploadRef = ref()
const syncDingtalk = ref(false)
const dingtalk = ref({ configured: false, bound: false })
const authorizing = ref(false)
const folderPath = ref([])
const folderTreeKey = ref(0)
const folderLabels = {}
const folderError = ref('')
const uploading = ref(false)
const uploadPercent = ref(0)

const activeTab = ref('uploads')
const uploads = ref([])
const uploadTotal = ref(0)
const uploadPage = ref(1)
const uploadsLoading = ref(false)
let pollTimer = null

const documents = ref([])
const documentTotal = ref(0)
const documentPage = ref(1)
const documentKeyword = ref('')
const documentsLoading = ref(false)
const documentsError = ref('')

const retrieveQuery = ref('')
const retrieving = ref(false)
const retrieveResults = ref([])
const retrieveUsage = ref(null)
const retrieveError = ref('')


// A folder chosen by link or from recent uploads, used instead of the tree when set.
const linkedFolder = ref(null)
const folderLink = ref('')
const resolvingLink = ref(false)
const recentFolders = ref([])
const folderId = computed(() => linkedFolder.value?.node_id || (folderPath.value?.length ? folderPath.value.at(-1) : ''))
const folderPathLabel = computed(() => linkedFolder.value?.path
  || (folderPath.value || []).map(id => folderLabels[id] || id).join(' / '))
const uploadBlocker = computed(() => {
  if (!settings.value.bailian_configured) return ''
  if (!indexId.value) return '请选择知识库'
  if (!categoryId.value) return '请选择类目'
  if (!fileList.value.length) return '请选择文件'
  if (syncDingtalk.value && !dingtalk.value.configured) return '钉钉应用未配置，请关闭钉盘同步或联系管理员'
  if (syncDingtalk.value && !dingtalk.value.bound) return '请先扫码绑定钉钉'
  if (syncDingtalk.value && !folderId.value) return '请选择钉盘目录'
  return ''
})
const canUpload = computed(() => settings.value.bailian_configured && !uploadBlocker.value && !uploading.value)

const statusMap = {
  uploading: { label: '上传中', type: 'primary' }, parsing: { label: '解析中', type: 'primary' },
  indexing: { label: '导入知识库中', type: 'primary' }, completed: { label: '已入库', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}
const dingtalkMap = { pending: { label: '入库后同步', type: 'info' }, success: { label: '已存入钉盘', type: 'success' }, failed: { label: '同步失败', type: 'danger' } }
const documentMap = {
  FINISH: { label: '解析成功', type: 'success' }, RUNNING: { label: '处理中', type: 'primary' },
  INSERT_ERROR: { label: '导入失败', type: 'danger' }, DELETED: { label: '已删除', type: 'info' },
}
const statusMeta = value => statusMap[value] || { label: value || '无', type: 'info' }
const dingtalkMeta = value => dingtalkMap[value] || { label: value || '无', type: 'info' }
const documentMeta = value => documentMap[value] || { label: value || '无', type: 'info' }
const isActive = value => ['uploading', 'parsing', 'indexing'].includes(value)
const time = value => value ? formatBeijingDateTime(value) : '无'
function fileSize(bytes) {
  if (bytes === null || bytes === undefined || bytes === '') return '无'
  const value = Number(bytes)
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

async function loadSettings() {
  try {
    settings.value = await knowledgeApi.getSettings()
  } catch (err) {
    pageError.value = knowledgeErrorText(err, '知识库配置加载失败')
  } finally { settingsLoaded.value = true }
}
async function loadDingtalkStatus() {
  try { dingtalk.value = await knowledgeApi.getDingtalkStatus() } catch { dingtalk.value = { configured: false, bound: false } }
}
async function loadIndices() {
  if (!settings.value.bailian_configured) return
  indicesLoading.value = true
  pageError.value = ''
  try {
    const result = await knowledgeApi.getIndices()
    indices.value = result.items || []
    if (!indexId.value) {
      const preferred = indices.value.find(item => item.id === settings.value.default_index_id)
      indexId.value = preferred?.id || indices.value[0]?.id || ''
    }
    if (indexId.value) loadDocuments()
  } catch (err) {
    pageError.value = knowledgeErrorText(err, '知识库列表加载失败')
  } finally { indicesLoading.value = false }
}

let categorySeed = null
async function loadCategories(node, resolve) {
  try {
    if (node.level === 0) {
      const result = await knowledgeApi.getCategories()
      const items = result.items || []
      const ids = new Set(items.map(item => item.id))
      categorySeed = items
      items.forEach(item => { categoryNames[item.id] = item.name })
      // Some workspaces return every category at once; nest them locally in that case.
      return resolve(items.filter(item => !item.parent_id || !ids.has(item.parent_id)).map(toCategoryNode))
    }
    const local = (categorySeed || []).filter(item => item.parent_id === node.data.id)
    if (local.length) return resolve(local.map(toCategoryNode))
    const result = await knowledgeApi.getCategories(node.data.id)
    const children = (result.items || []).filter(item => item.id !== node.data.id)
    children.forEach(item => { categoryNames[item.id] = item.name })
    resolve(children.map(toCategoryNode))
  } catch (err) {
    ElMessage.error(knowledgeErrorText(err, '类目加载失败'))
    resolve([])
  }
}
const toCategoryNode = item => ({ id: item.id, name: item.name || item.id, leaf: false })

const folderProps = {
  lazy: true,
  checkStrictly: true,
  async lazyLoad(node, resolve) {
    folderError.value = ''
    try {
      if (node.level === 0) {
        const result = await knowledgeApi.getDingtalkWorkspaces()
        return resolve((result.items || []).map(item => {
          const label = item.name
          folderLabels[item.root_node_id] = label
          return { value: item.root_node_id, label, leaf: false, workspaceId: item.workspace_id }
        }))
      }
      const result = await knowledgeApi.getDingtalkFolders(node.value)
      resolve((result.items || []).map(item => {
        folderLabels[item.node_id] = item.name
        return { value: item.node_id, label: item.name, leaf: !item.has_children }
      }))
    } catch (err) {
      folderError.value = knowledgeErrorText(err, '钉盘目录加载失败')
      resolve([])
    }
  },
}
function onFolderChange() { linkedFolder.value = null; saveDraft() }
function useFolder(item) {
  linkedFolder.value = { node_id: item.node_id, path: item.path }
  folderPath.value = []
}
async function useFolderLink() {
  if (!folderLink.value.trim()) return
  resolvingLink.value = true
  folderError.value = ''
  try {
    const folder = await knowledgeApi.resolveDingtalkFolder(folderLink.value.trim())
    useFolder(folder)
    folderLink.value = ''
  } catch (err) {
    folderError.value = knowledgeErrorText(err, '无法识别这个钉盘链接')
  } finally { resolvingLink.value = false }
}
async function loadRecentFolders() {
  try { recentFolders.value = (await knowledgeApi.getRecentDingtalkFolders()).items || [] } catch { recentFolders.value = [] }
}
// Opening a folder also selects it, so the target follows the navigation: open 全员文件夹 → 1.技术标准类
// and that is where the file goes, while its subfolders stay open to go deeper.
function onFolderExpand(path) {
  if (!path?.length) return
  linkedFolder.value = null
  folderPath.value = [...path]
  saveDraft()
}

function saveDraft() {
  try {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ indexId: indexId.value, categoryId: categoryId.value, syncDingtalk: syncDingtalk.value }))
  } catch { /* storage may be unavailable */ }
}
function restoreDraft() {
  try {
    const draft = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || 'null')
    if (!draft) return
    indexId.value = draft.indexId || ''
    categoryId.value = draft.categoryId || ''
    syncDingtalk.value = Boolean(draft.syncDingtalk)
  } catch { /* ignore broken drafts */ }
}

async function startDingtalkAuth() {
  authorizing.value = true
  try {
    saveDraft()
    const { url } = await knowledgeApi.getDingtalkAuthorizeUrl(callbackUrl)
    window.location.assign(url)
  } catch (err) {
    ElMessage.error(knowledgeErrorText(err, '无法发起钉钉授权'))
    authorizing.value = false
  }
}
async function unbindDingtalk() {
  try {
    await knowledgeApi.unbindDingtalk()
    folderPath.value = []
    linkedFolder.value = null
    await loadDingtalkStatus()
    ElMessage.success('已解除钉钉绑定')
  } catch (err) { ElMessage.error(knowledgeErrorText(err)) }
}

function onExceed() { ElMessage.warning('一次最多上传 10 个文件') }
function onIndexChange() { documentPage.value = 1; saveDraft(); loadDocuments() }
watch(categoryId, saveDraft)
watch(syncDingtalk, value => {
  saveDraft()
  if (value) { loadDingtalkStatus(); loadRecentFolders() }
})

async function submitUpload() {
  const oversize = fileList.value.find(item => item.size > 100 * 1024 * 1024)
  if (oversize) return ElMessage.error(`${oversize.name} 超过 100 MB 上限`)
  const form = new FormData()
  fileList.value.forEach(item => form.append('files', item.raw, item.name))
  const index = indices.value.find(item => item.id === indexId.value)
  form.append('index_id', indexId.value)
  form.append('index_name', index?.name || indexId.value)
  form.append('category_id', categoryId.value)
  form.append('category_name', categoryNames[categoryId.value] || categoryId.value)
  form.append('sync_dingtalk', syncDingtalk.value ? 'true' : 'false')
  if (syncDingtalk.value) {
    form.append('dingtalk_folder_id', folderId.value)
    form.append('dingtalk_workspace_id', String(folderId.value).split('/')[0] || '')
    form.append('dingtalk_folder_path', folderPathLabel.value)
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    const result = await knowledgeApi.upload(form, event => {
      if (event.total) uploadPercent.value = Math.min(99, Math.round(event.loaded / event.total * 100))
    })
    ElMessage.success(`已提交 ${result.items?.length || 0} 个文件，正在解析入库`)
    fileList.value = []
    activeTab.value = 'uploads'
    uploadPage.value = 1
    await reloadUploads()
  } catch (err) {
    ElMessage.error(knowledgeErrorText(err, '上传失败'))
  } finally { uploading.value = false }
}

const deletingId = ref(null)
async function removeUpload(row) {
  deletingId.value = row.id
  try {
    const result = await knowledgeApi.deleteUpload(row.id)
    ElMessage.success(`已删除：${(result.removed || []).join('、') || '上传记录'}`)
    await Promise.all([reloadUploads(true), loadDocuments()])
  } catch (err) {
    ElMessage.error(knowledgeErrorText(err, '删除失败'))
  } finally { deletingId.value = null }
}
async function reloadUploads(silent = false) {
  if (!silent) uploadsLoading.value = true
  try {
    const result = await knowledgeApi.getUploads({ skip: (uploadPage.value - 1) * 10, limit: 10 })
    uploads.value = result.items || []
    uploadTotal.value = result.total || 0
  } catch (err) {
    if (!silent) ElMessage.error(knowledgeErrorText(err, '上传记录加载失败'))
  } finally {
    uploadsLoading.value = false
    schedulePoll()
  }
}
function schedulePoll() {
  clearTimeout(pollTimer)
  if (uploads.value.some(row => isActive(row.status) || row.dingtalk_status === 'pending')) {
    pollTimer = setTimeout(() => {
      reloadUploads(true)
      if (activeTab.value === 'documents') loadDocuments(true)
    }, 4000)
  }
}

let documentRequest = 0
let linkRetryTimer = null
async function loadDocuments(silent = false, linkRetries = 0) {
  clearTimeout(linkRetryTimer)
  if (!indexId.value) { documents.value = []; documentTotal.value = 0; return }
  const requestId = ++documentRequest
  if (silent !== true) documentsLoading.value = true
  documentsError.value = ''
  try {
    const result = await knowledgeApi.getDocuments({ index_id: indexId.value, page: documentPage.value, page_size: 20, name: documentKeyword.value.trim() || undefined })
    if (requestId !== documentRequest) return
    documents.value = result.items || []
    documentTotal.value = result.total || 0
    // 钉盘 links not seen before are looked up in the background; ask again quietly to pick them up.
    if (result.links_pending && linkRetries < 4) {
      linkRetryTimer = setTimeout(() => loadDocuments(true, linkRetries + 1), 2500)
    }
  } catch (err) {
    documentsError.value = knowledgeErrorText(err, '知识库文档加载失败')
  } finally { documentsLoading.value = false }
}
function searchDocuments() { documentPage.value = 1; loadDocuments() }
function onTabChange(name) { if (name === 'documents') loadDocuments() }

async function runRetrieve() {
  retrieving.value = true
  retrieveError.value = ''
  try {
    const index = indices.value.find(item => item.id === indexId.value)
    const result = await knowledgeApi.retrieve({ query: retrieveQuery.value.trim(), index_id: indexId.value, index_name: index?.name, source: 'console' })
    retrieveResults.value = result.nodes || []
    retrieveUsage.value = result.usage
  } catch (err) {
    retrieveError.value = knowledgeErrorText(err, '检索失败')
    retrieveResults.value = []
    retrieveUsage.value = null
  } finally { retrieving.value = false }
}

async function reloadAll() {
  await loadSettings()
  categoryTreeKey.value += 1
  await Promise.all([loadIndices(), loadDingtalkStatus(), reloadUploads()])
}

const access = ref({})
const accessLoaded = ref(false)
async function loadAccess() {
  try { access.value = await knowledgeApi.getAccess() } catch (err) {
    access.value = { can_upload: false, error: knowledgeErrorText(err, '无法确认上传权限，请稍后刷新') }
  } finally { accessLoaded.value = true }
}
onMounted(async () => {
  loadAccess()
  restoreDraft()
  if (!categoryId.value) categoryId.value = ''
  await loadSettings()
  if (!categoryId.value && settings.value.default_category_id) categoryId.value = settings.value.default_category_id
  await Promise.all([loadIndices(), loadDingtalkStatus(), reloadUploads()])
  if (route.query.dingtalk === 'bound') {
    syncDingtalk.value = true
    ElMessage.success('钉钉绑定成功，请选择钉盘目录')
    router.replace({ query: {} })
  }
})
onBeforeUnmount(() => { clearTimeout(pollTimer); clearTimeout(linkRetryTimer) })
</script>

<style scoped>
.page-container { max-width: 1400px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; gap: 24px; margin-bottom: 20px; }
.page-header h2 { margin: 0; font-size: 24px; color: #303133; }
.subtitle { margin: 6px 0 0; color: #909399; font-size: 13px; }
.header-actions { display: flex; gap: 10px; align-items: center; }
.block-alert { margin-bottom: 16px; }
.panel { background: #fff; border: 1px solid #e4e7ed; border-radius: 6px; margin-bottom: 20px; overflow: hidden; }
.panel-header { display: flex; align-items: center; min-height: 56px; padding: 0 20px; border-bottom: 1px solid #ebeef5; }
.panel-header h3 { margin: 0; font-size: 16px; color: #303133; }
.panel-body { padding: 20px; }
.target-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.target-form :deep(.el-select), .target-form :deep(.el-tree-select) { width: 100%; }
.option-hint { margin-left: 12px; color: #a8abb2; font-size: 12px; }
.file-drop :deep(.el-upload-dragger) { padding: 26px 20px; }
/* Files waiting to be uploaded: blue and larger so they are easy to check before 开始上传. */
.file-drop :deep(.el-upload-list__item) { margin-top: 6px; }
.file-drop :deep(.el-upload-list__item-name) { color: #2f7de1; font-size: 15px; font-weight: 500; }
.file-drop :deep(.el-upload-list__item-name .el-icon) { color: #2f7de1; font-size: 16px; }
.file-drop :deep(.el-upload-list__item-file-name) { color: #2f7de1; }
.drop-icon { font-size: 40px; color: #a8abb2; margin-bottom: 6px; }
.dingtalk-sync { margin-top: 18px; padding: 14px 16px; border: 1px solid #ebeef5; border-radius: 6px; background: #fafbfc; }
.sync-switch { display: flex; align-items: center; gap: 12px; }
.sync-switch div { display: flex; flex-direction: column; gap: 2px; }
.sync-switch strong { font-size: 14px; color: #303133; font-weight: 600; }
.sync-switch span { font-size: 12px; color: #909399; }
.sync-detail { margin-top: 14px; display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }
.bound-line { display: flex; align-items: center; gap: 10px; }
.folder-picker { width: min(520px, 100%); }
.folder-link { display: flex; gap: 8px; width: min(520px, 100%); margin-top: 8px; }
.recent-folders { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 8px; }
.folder-target { margin: 8px 0 0; color: #606266; font-size: 13px; overflow-wrap: anywhere; }
.upload-actions { display: flex; align-items: center; gap: 14px; margin-top: 18px; flex-wrap: wrap; }
.muted { color: #909399; font-size: 12px; }
.panel-tabs { padding: 0 20px 4px; }
.tab-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.search-input { width: 260px; }
.file-name { display: inline-flex; align-items: center; gap: 6px; }
.file-name .el-icon { color: #909399; }
.drive-link { margin-left: 8px; }
.pagination-container { display: flex; justify-content: flex-end; padding: 14px 0 10px; }
.retrieve-box { display: flex; flex-direction: column; gap: 12px; padding-bottom: 16px; }
.retrieve-actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.retrieve-results { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 12px; }
.retrieve-results li { padding: 10px 12px; border: 1px solid #ebeef5; border-radius: 6px; }
.result-meta { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.result-meta span { color: #909399; flex-shrink: 0; }
.retrieve-results p { margin: 8px 0 0; color: #4c4f52; font-size: 13px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.status-spinner { margin-right: 4px; }
@media (max-width: 760px) {
  .target-form { grid-template-columns: 1fr; }
  .page-header { flex-direction: column; align-items: flex-start; }
}
</style>
