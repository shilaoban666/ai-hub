<template>
  <div class="mcp-list">
    <div class="header">
      <h2>MCP 管理</h2>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索名称、描述、分类或作者"
          clearable
          @input="handleSearch"
          style="width: 300px; margin-right: 12px;"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="handleCreate">
          <el-icon><Plus /></el-icon>
          新建 MCP 服务
        </el-button>
      </div>
    </div>

    <el-row :gutter="20" v-loading="loading">
      <el-col
        :xs="24"
        :sm="12"
        :md="8"
        :lg="6"
        v-for="mcp in mcps"
        :key="mcp.id"
        style="margin-bottom: 20px;"
      >
        <el-card
          class="mcp-card"
          shadow="hover"
          @click="handleSelect(mcp)"
        >
          <div class="mcp-cover" v-if="mcp.cover">
            <img :src="mcp.cover" alt="cover" />
            <div class="cover-overlay" @click.stop>
              <el-button
                type="primary"
                :icon="Picture"
                size="small"
                @click="handleChangeCover(mcp)"
              >
                更换
              </el-button>
              <el-button
                type="danger"
                :icon="Delete"
                size="small"
                @click="handleDeleteCover(mcp)"
                style="margin-left: 8px;"
              >
                删除
              </el-button>
            </div>
          </div>
          <div class="mcp-icon" v-else>
            <el-icon :size="48">
              <Connection />
            </el-icon>
            <div class="icon-overlay" @click.stop>
              <el-button
                type="primary"
                :icon="Picture"
                size="small"
                @click="handleChangeCover(mcp)"
              >
                更换
              </el-button>
            </div>
          </div>
          <div class="mcp-info">
            <h3>{{ mcp.name }}</h3>
            <div class="mcp-meta">
              <span class="meta-item">类型：{{ typeLabel(mcp.type) }}</span>
              <span class="meta-item meta-center">作者：{{ mcp.author || '无' }}</span>
            </div>
            <p class="description">描述：{{ mcp.description || '无' }}</p>
            <div class="mcp-tags">
              <span class="tags-label">分类：</span>
              <el-tag
                size="small"
                class="tag-item"
                type="primary"
              >
                {{ mcp.tags || '无' }}
              </el-tag>
            </div>
          </div>

          <div class="mcp-actions" @click.stop>
            <el-tooltip :content="mcp.is_public ? '公开' : '私有'" placement="top">
              <el-button
                :type="mcp.is_public ? 'success' : 'info'"
                :icon="mcp.is_public ? View : Hide"
                link
                size="small"
                @click="handleToggleVisibility(mcp)"
              />
            </el-tooltip>
            <el-button
              type="primary"
              :icon="Edit"
              link
              size="small"
              @click="handleEdit(mcp)"
            />
            <el-button
              type="danger"
              :icon="Delete"
              link
              size="small"
              @click="handleDelete(mcp)"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!loading && mcps.length === 0" description="暂无数据" />

    <div class="pagination-container" v-if="!loading && mcps.length > 0">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next, jumper"
        @current-change="handlePageChange"
      />
    </div>

    <!-- 创建对话框 -->
    <el-dialog
      v-model="createDialogVisible"
      title="新建 MCP 服务"
      width="640px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-width="80px"
        autocomplete="off"
      >
        <div class="form-section-heading form-section-heading--first" aria-label="基本信息">
          <el-icon><InfoFilled /></el-icon>
          <span>基本信息</span>
        </div>
        <el-form-item label="服务名称" prop="name">
          <el-input v-model="createForm.name" placeholder="请输入服务名称" autocomplete="off" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="5"
            placeholder="请输入描述"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item label="作者" prop="author">
          <el-input v-model="createForm.author" placeholder="请输入作者" disabled autocomplete="off" />
        </el-form-item>
        <el-form-item label="分类" prop="tags">
          <McpCategorySelect v-model="createForm.tags" />
        </el-form-item>
        <div class="form-section-heading" aria-label="连接设置">
          <el-icon><Connection /></el-icon>
          <span>连接设置</span>
        </div>
        <el-form-item label="类型" prop="type">
          <el-select v-model="createForm.type" placeholder="请选择类型" style="width: 100%">
            <el-option label="STDIO" value="stdio" />
            <el-option label="SSE" value="sse" />
            <el-option label="Streamable HTTP" value="streamable_http" />
            <el-option label="JSON" value="json" />
          </el-select>
        </el-form-item>
        <template v-if="createForm.type === 'stdio'">
          <el-form-item label="命令" prop="command">
            <el-input v-model="createForm.command" placeholder="如 npx" autocomplete="off" />
          </el-form-item>
          <el-form-item label="参数">
            <div class="kv-editor">
              <div v-for="(arg, index) in createForm.args" :key="index" class="single-value-row">
                <el-input v-model="createForm.args[index]" placeholder="参数值" autocomplete="off" />
                <el-button type="danger" :icon="Delete" link @click="removeArg(index)" />
              </div>
              <el-button type="primary" :icon="Plus" link @click="addArg">添加参数</el-button>
            </div>
          </el-form-item>
        </template>
        <el-form-item v-if="createForm.type === 'stdio'" label="环境变量">
          <div class="kv-editor">
            <div v-for="(item, index) in createForm.env" :key="index" class="kv-row">
              <el-input v-model="item.key" placeholder="变量名" autocomplete="off" />
              <el-input v-model="item.value" placeholder="变量值" show-password autocomplete="off" />
              <el-button type="danger" :icon="Delete" link @click="removeConfigRow('env', index)" />
            </div>
            <el-button type="primary" :icon="Plus" link @click="addConfigRow('env')">
              添加环境变量
            </el-button>
          </div>
        </el-form-item>
        <el-form-item
          v-if="createForm.type === 'sse' || createForm.type === 'streamable_http'"
          label="URL"
          prop="url"
        >
          <el-input
            v-model="createForm.url"
            placeholder="https://example.com/mcp"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item
          v-if="createForm.type === 'sse' || createForm.type === 'streamable_http'"
          label="Headers"
        >
          <div class="kv-editor">
            <div v-for="(item, index) in createForm.headers" :key="index" class="kv-row">
              <el-input v-model="item.key" placeholder="Header 名称" autocomplete="off" />
              <el-input v-model="item.value" placeholder="Header 值" show-password autocomplete="off" />
              <el-button type="danger" :icon="Delete" link @click="removeConfigRow('headers', index)" />
            </div>
            <el-button type="primary" :icon="Plus" link @click="addConfigRow('headers')">
              添加 Header
            </el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="createForm.type === 'json'" label="JSON 配置" prop="jsonText">
          <el-input
            v-model="createForm.jsonText"
            type="textarea"
            :rows="9"
            placeholder='请输入 JSON 配置，如 {"key": "value"}'
            autocomplete="off"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleConfirmCreate" :loading="creating">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { mcpsApi } from '@/api/mcps'
import { useAuthStore } from '@/stores/auth'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, Search, Picture, View, Hide, Connection, Plus, InfoFilled } from '@element-plus/icons-vue'
import { showError } from '@/utils/error'
import McpCategorySelect from './components/McpCategorySelect.vue'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const mcps = ref([])
const currentPage = ref(1)
const pageSize = ref(12)
const total = ref(0)
const searchKeyword = ref('')
let searchTimer = null
const createDialogVisible = ref(false)
const creating = ref(false)
const createFormRef = ref(null)

const createForm = ref({
  name: '',
  type: 'stdio',
  author: '',
  description: '',
  tags: '基础服务',
  command: '',
  args: [],
  url: '',
  jsonText: '',
  env: [],
  headers: []
})

const createRules = {
  name: [
    { required: true, message: '请输入服务名称', trigger: 'blur' }
  ],
  type: [
    { required: true, message: '请选择类型', trigger: 'change' }
  ],
  author: [
    { required: true, message: '请输入作者', trigger: 'blur' }
  ],
  tags: [
    {
      validator: (_rule, value, callback) => {
        const category = typeof value === 'string' ? value.trim() : ''
        if (category.length > 500) {
          callback(new Error('分类不能超过 500 个字符'))
        } else {
          callback()
        }
      },
      trigger: ['blur', 'change']
    }
  ],
  description: [
    { required: true, message: '请输入描述', trigger: 'blur' }
  ],
  command: [
    { required: true, whitespace: true, message: '请输入命令', trigger: 'blur' }
  ],
  url: [
    { required: true, whitespace: true, message: '请输入 URL', trigger: 'blur' }
  ],
  jsonText: [
    { required: true, whitespace: true, message: '请输入 JSON 配置', trigger: 'blur' }
  ]
}

const typeLabelMap = {
  stdio: 'STDIO',
  sse: 'SSE',
  streamable_http: 'Streamable HTTP',
  json: 'JSON'
}

const typeLabel = (type) => typeLabelMap[type] || type

const fetchMcps = async () => {
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const params = { skip, limit: pageSize.value }
    if (searchKeyword.value?.trim()) {
      params.search = searchKeyword.value.trim()
    }
    const response = await mcpsApi.getList(params)
    mcps.value = response?.items || []
    total.value = response?.total || 0
  } catch (error) {
    showError(error, '获取列表失败')
    mcps.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
  fetchMcps()
}

const handleSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchMcps()
  }, 500)
}

const handleSelect = (mcp) => {
  if (mcp?.id) {
    router.push(`/admin/mcp/${mcp.id}`)
  }
}

const handleEdit = (mcp) => {
  router.push(`/admin/mcp/${mcp.id}`)
}

const handleDelete = async (mcp) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除"${mcp.name}"吗？此操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await mcpsApi.delete(mcp.id)
    ElMessage.success('删除成功')
    await fetchMcps()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const handleToggleVisibility = async (mcp) => {
  try {
    const result = await mcpsApi.toggleVisibility(mcp.id)
    mcp.is_public = result.is_public
    ElMessage.success(`已设为${result.is_public ? '公开' : '私有'}`)
  } catch (error) {
    ElMessage.error('切换可见性失败')
  }
}

const handleCreate = () => {
  createForm.value = {
    name: '',
    type: 'stdio',
    author: authStore.user?.first_name || '',
    description: '',
    tags: '基础服务',
    command: '',
    args: [],
    url: '',
    jsonText: '',
    env: [],
    headers: []
  }
  createDialogVisible.value = true
}

const addArg = () => {
  createForm.value.args.push('')
}

const removeArg = (index) => {
  createForm.value.args.splice(index, 1)
}

const addConfigRow = (field) => {
  createForm.value[field].push({ key: '', value: '' })
}

const removeConfigRow = (field, index) => {
  createForm.value[field].splice(index, 1)
}

const configRowsToObject = (rows, caseInsensitive = false) => {
  const result = {}
  const seen = new Set()
  for (const item of rows) {
    const key = item.key.trim()
    if (!key && item.value) throw new Error('配置值对应的名称不能为空')
    if (!key) continue
    const normalizedKey = caseInsensitive ? key.toLowerCase() : key
    if (seen.has(normalizedKey)) throw new Error(`配置名称 ${key} 重复`)
    seen.add(normalizedKey)
    result[key] = item.value
  }
  return result
}

const handleConfirmCreate = async () => {
  if (!createFormRef.value) return
  try {
    await createFormRef.value.validate()
  } catch {
    return
  }

  creating.value = true
  try {
    const env = configRowsToObject(createForm.value.env)
    const headers = configRowsToObject(createForm.value.headers, true)
    let jsonConfig = '{}'
    if (createForm.value.type === 'json' && createForm.value.jsonText.trim()) {
      try {
        jsonConfig = JSON.stringify(JSON.parse(createForm.value.jsonText))
      } catch {
        throw new Error('配置 JSON 格式不正确')
      }
    }
    const defaultConfig = {
      stdio: JSON.stringify({
        command: createForm.value.command.trim(),
        args: createForm.value.args.map(arg => arg.trim()).filter(Boolean),
        env
      }),
      sse: JSON.stringify({ url: createForm.value.url.trim(), headers }),
      streamable_http: JSON.stringify({ url: createForm.value.url.trim(), headers }),
      json: jsonConfig
    }[createForm.value.type] || '{}'

    const {
      command: _command,
      args: _args,
      url: _url,
      jsonText: _jsonText,
      env: _env,
      headers: _headers,
      ...formData
    } = createForm.value
    const newMcp = await mcpsApi.create({
      ...formData,
      tags: typeof formData.tags === 'string' ? formData.tags.trim() : formData.tags,
      config: defaultConfig
    })

    ElMessage.success('创建成功')
    createDialogVisible.value = false
    router.push(`/admin/mcp/${newMcp.id}`)
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('配置')) {
      ElMessage.warning(error.message)
    } else {
      ElMessage.error('创建失败')
    }
  } finally {
    creating.value = false
  }
}

const handleChangeCover = (mcp) => {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.onchange = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    if (file.size > 1048576) {
      ElMessage.error('图片大小不能超过1MB')
      return
    }
    if (!file.type.startsWith('image/')) {
      ElMessage.error('只能上传图片文件')
      return
    }
    try {
      const result = await mcpsApi.uploadCover(mcp.id, file)
      if (result?.cover) {
        mcp.cover = result.cover
        ElMessage.success('封面更换成功')
        await fetchMcps()
      }
    } catch (error) {
      ElMessage.error('封面上传失败')
    }
  }
  input.click()
}

const handleDeleteCover = async (mcp) => {
  try {
    await ElMessageBox.confirm(
      '确定要删除封面吗？',
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await mcpsApi.deleteCover(mcp.id)
    mcp.cover = null
    ElMessage.success('封面删除成功')
    await fetchMcps()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('封面删除失败')
    }
  }
}

onMounted(() => {
  fetchMcps()
})
</script>

<style scoped>
.mcp-list {
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

.mcp-card {
  cursor: pointer;
  transition: all 0.3s;
  height: 100%;
  position: relative;
}

.mcp-card:hover {
  transform: translateY(-4px);
}

.mcp-card:hover .mcp-actions {
  opacity: 1;
}

.mcp-cover {
  position: relative;
  width: calc(100% + 40px);
  height: 150px;
  overflow: hidden;
  margin: -20px -20px 10px -20px;
}

.mcp-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center center;
  display: block;
}

.cover-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.3s;
}

.mcp-cover:hover .cover-overlay {
  opacity: 1;
}

.mcp-actions {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  gap: 1px;
  z-index: 10;
  opacity: 0;
  transition: opacity 0.3s;
}

.mcp-actions .el-button + .el-button {
  margin-left: 5px;
}

.mcp-actions .el-button {
  padding: 2px;
  min-width: auto;
}

.mcp-icon {
  position: relative;
  width: calc(100% + 40px);
  height: 150px;
  overflow: hidden;
  margin: -20px -20px 10px -20px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #409eff;
}

.icon-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.3s;
}

.mcp-icon:hover .icon-overlay {
  opacity: 1;
}

.mcp-info {
  text-align: center;
}

.mcp-info h3 {
  margin: 10px 0;
  font-size: 18px;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
  font-size: 13px;
  color: #606266;
}

.meta-item {
  display: inline-block;
}

.meta-center {
  flex: 1;
  text-align: center;
}

.mcp-info .description {
  margin-top: 10px;
  color: #666;
  font-size: 13px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-align: left;
}

.mcp-tags {
  margin-top: 10px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.tags-label {
  font-size: 13px;
  color: #606266;
}

.tag-item {
  margin: 0;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 4px;
  padding: 0;
}

.kv-editor {
  width: 100%;
}

.form-section-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 24px 0 20px;
  padding: 9px 12px;
  border-left: 3px solid #409eff;
  border-radius: 4px;
  background: #f5f7fa;
  color: #303133;
  font-size: 14px;
  font-weight: 600;
}

.form-section-heading .el-icon {
  color: #409eff;
  font-size: 16px;
}

.form-section-heading--first {
  margin-top: 0;
}

.kv-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 32px;
  gap: 8px;
  margin-bottom: 8px;
}

.single-value-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 32px;
  gap: 8px;
  margin-bottom: 8px;
}

@media (max-width: 640px) {
  .kv-row {
    grid-template-columns: 1fr 1fr 28px;
  }
}
</style>
