<template>
  <div class="mcp-detail">
    <div class="detail-header">
      <el-button class="back-btn" @click="handleBack" :icon="ArrowLeft">返回</el-button>
      <div class="header-info">
        <h2
          v-if="!isEditingName"
          class="editable-name"
          @click="startEditName"
          title="点击编辑名称"
        >
          {{ mcp.name }}
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
        <el-tag>{{ typeLabel(mcp.type) }}</el-tag>
      </div>
      <div class="header-actions">
        <el-button
          :type="mcp.is_public ? 'success' : 'info'"
          :icon="mcp.is_public ? Hide : View"
          :loading="visibilitySaving"
          :disabled="loading || !mcp.id"
          @click="handleToggleVisibility"
        >
          {{ mcp.is_public ? '设为私有' : '设为公开' }}
        </el-button>
      </div>
    </div>

    <div class="detail-body" v-loading="loading">
      <div class="left-sidebar">
        <div class="info-section">
          <div class="info-header">
            <h3>基本信息</h3>
            <el-button
              type="primary"
              link
              size="small"
              @click="toggleEditInfo"
            >
              编辑
            </el-button>
          </div>
          <div class="info-content">
            <div class="info-item">
              <span class="info-label">描述：</span>
              <span class="info-value">{{ mcp.description || '未设置' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">作者：</span>
              <span class="info-value">{{ mcp.author || '未设置' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">分类：</span>
              <span class="info-value">{{ mcp.tags || '无' }}</span>
            </div>
          </div>
        </div>
        <div class="connection-section">
          <div class="info-header">
            <h3>连接设置</h3>
            <el-button
              type="primary"
              link
              size="small"
              @click="toggleEditConfig"
            >
              编辑
            </el-button>
          </div>

          <div v-if="savedConfigForm" class="connection-content">
            <div class="connection-item">
              <span class="connection-label">类型</span>
              <code>{{ typeLabel(mcp.type) }}</code>
            </div>
            <template v-if="mcp.type === 'stdio'">
              <div class="connection-item">
                <span class="connection-label">命令</span>
                <code>{{ savedConfigForm.command || '未设置' }}</code>
              </div>
              <div v-if="savedConfigForm.args.filter(Boolean).length" class="connection-item">
                <span class="connection-label">参数</span>
                <div class="connection-values">
                  <code v-for="(arg, index) in savedConfigForm.args.filter(Boolean)" :key="index">{{ arg }}</code>
                </div>
              </div>
              <div v-if="savedConfigForm.env.filter(item => item.key).length" class="connection-item">
                <span class="connection-label">环境变量</span>
                <div class="connection-pairs">
                  <div v-for="item in savedConfigForm.env.filter(item => item.key)" :key="item.key">
                    <code>{{ item.key }}</code><span>{{ item.value }}</span>
                  </div>
                </div>
              </div>
            </template>

            <template v-else-if="mcp.type === 'sse' || mcp.type === 'streamable_http'">
              <div class="connection-item">
                <span class="connection-label">URL</span>
                <code>{{ savedConfigForm.url || '未设置' }}</code>
              </div>
              <div v-if="savedConfigForm.headers.filter(item => item.key).length" class="connection-item">
                <span class="connection-label">Headers</span>
                <div class="connection-pairs">
                  <div v-for="item in savedConfigForm.headers.filter(item => item.key)" :key="item.key" class="connection-header-row">
                    <code>{{ item.key }}</code>
                    <span class="secret-value">{{ revealedHeaderKeys.includes(item.key) ? item.value : (item.value ? '••••••••' : '未设置') }}</span>
                    <el-button
                      :icon="revealedHeaderKeys.includes(item.key) ? Hide : View"
                      :aria-label="`${revealedHeaderKeys.includes(item.key) ? '隐藏' : '显示'} ${item.key}`"
                      link
                      @click="toggleHeaderVisibility(item.key)"
                    />
                  </div>
                </div>
              </div>
            </template>

            <pre v-else class="connection-json"><code>{{ savedConfigForm.jsonText || '{}' }}</code></pre>
          </div>

        </div>
      </div>

      <div class="content-area">
        <el-tabs v-model="activeTab" class="content-tabs">
          <el-tab-pane label="使用说明" name="instructions">
            <!-- Preview mode -->
            <div v-if="!isEditing" class="instructions-preview">
              <div class="instructions-body">
                <MdPreview :modelValue="mcp.usage_instructions || ''" />
              </div>
            </div>
            <!-- Edit mode -->
            <div v-else class="instructions-editor">
              <MarkdownEditor media-tools
                v-model="editInstructions"
                language="zh-CN"
                showCodeRowNumber
                :onUploadImg="onUploadImg"
              />
            </div>
          </el-tab-pane>

          <el-tab-pane v-if="false" label="配置" name="config">
            <div class="config-editor">
              <!-- STDIO Preview -->
              <template v-if="mcp.type === 'stdio' && !isEditing">
                <div class="config-preview">
                  <div class="config-field">
                    <label>命令</label>
                    <div class="config-copy-wrap">
                      <el-button class="copy-btn" link size="small" :icon="CopyDocument" @click="copyText(configForm.command || '', '命令')">复制</el-button>
                      <div class="config-code-block">{{ configForm.command || '未设置' }}</div>
                    </div>
                  </div>
                  <div class="config-field" v-if="configForm.args.filter(a => a).length">
                    <label>参数</label>
                    <div class="config-tags">
                      <span class="config-tag" v-for="a in configForm.args.filter(a => a)" :key="a">{{ a }}</span>
                    </div>
                  </div>
                  <div class="config-field" v-if="configForm.env.filter(e => e.key).length">
                    <label>环境变量</label>
                    <table class="config-table">
                      <tbody>
                        <tr v-for="e in configForm.env.filter(e => e.key)" :key="e.key">
                          <td class="config-table-key">{{ e.key }}</td>
                          <td class="config-table-value">{{ e.value }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <div class="config-field">
                    <label>JSON 配置</label>
                    <div class="config-copy-wrap">
                      <el-button class="copy-btn" link size="small" :icon="CopyDocument" @click="copyText(mcpConfigJson, 'JSON 配置')">复制</el-button>
                      <pre class="config-json-preview"><code>{{ mcpConfigJson }}</code></pre>
                    </div>
                  </div>
                </div>
              </template>
              <!-- STDIO Edit -->
              <template v-if="mcp.type === 'stdio' && isEditing">
                <el-form label-width="80px" size="small">
                  <el-form-item label="命令">
                    <el-input v-model="configForm.command" placeholder="如 npx" />
                  </el-form-item>
                  <el-form-item label="参数">
                    <div class="kv-editor">
                      <div class="kv-row" v-for="(arg, index) in configForm.args" :key="index">
                        <el-input v-model="configForm.args[index]" placeholder="参数值" />
                        <el-button type="danger" :icon="Delete" link size="small" @click="removeArg(index)" />
                      </div>
                      <el-button type="primary" link size="small" :icon="Plus" @click="addArg">添加参数</el-button>
                    </div>
                  </el-form-item>
                  <el-form-item label="环境变量">
                    <div class="kv-editor">
                      <div class="kv-row" v-for="(item, index) in configForm.env" :key="index">
                        <el-input v-model="item.key" placeholder="键" />
                        <el-input v-model="item.value" placeholder="值" />
                        <el-button type="danger" :icon="Delete" link size="small" @click="removeEnv(index)" />
                      </div>
                      <el-button type="primary" link size="small" :icon="Plus" @click="addEnv">添加环境变量</el-button>
                    </div>
                  </el-form-item>
                </el-form>
              </template>

              <!-- SSE / Streamable HTTP Preview -->
              <template v-if="(mcp.type === 'sse' || mcp.type === 'streamable_http') && !isEditing">
                <div class="config-preview">
                  <div class="config-field">
                    <label>URL</label>
                    <div class="config-copy-wrap">
                      <el-button class="copy-btn" link size="small" :icon="CopyDocument" @click="copyText(configForm.url || '', 'URL')">复制</el-button>
                      <div class="config-code-block">{{ configForm.url || '未设置' }}</div>
                    </div>
                  </div>
                  <div class="config-field" v-if="configForm.headers.filter(h => h.key).length">
                    <label>请求头</label>
                    <table class="config-table">
                      <tbody>
                        <tr v-for="h in configForm.headers.filter(h => h.key)" :key="h.key">
                          <td class="config-table-key">{{ h.key }}</td>
                          <td class="config-table-value">{{ h.value }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <div class="config-field">
                    <label>JSON 配置</label>
                    <div class="config-copy-wrap">
                      <el-button class="copy-btn" link size="small" :icon="CopyDocument" @click="copyText(mcpConfigJson, 'JSON 配置')">复制</el-button>
                      <pre class="config-json-preview"><code>{{ mcpConfigJson }}</code></pre>
                    </div>
                  </div>
                </div>
              </template>
              <!-- SSE / Streamable HTTP Edit -->
              <template v-if="(mcp.type === 'sse' || mcp.type === 'streamable_http') && isEditing">
                <el-form label-width="80px" size="small">
                  <el-form-item label="URL">
                    <el-input v-model="configForm.url" placeholder="https://example.com/mcp" />
                  </el-form-item>
                  <el-form-item label="请求头">
                    <div class="kv-editor">
                      <div class="kv-row" v-for="(item, index) in configForm.headers" :key="index">
                        <el-input v-model="item.key" placeholder="请求头名称" />
                        <el-input v-model="item.value" placeholder="请求头值" />
                        <el-button type="danger" :icon="Delete" link size="small" @click="removeHeader(index)" />
                      </div>
                      <el-button type="primary" link size="small" :icon="Plus" @click="addHeader">添加请求头</el-button>
                    </div>
                  </el-form-item>
                </el-form>
              </template>

              <!-- JSON Preview -->
              <template v-if="mcp.type === 'json' && !isEditing">
                <div class="config-preview">
                  <div class="config-field">
                    <label>JSON 配置</label>
                    <div class="config-copy-wrap">
                      <el-button class="copy-btn" link size="small" :icon="CopyDocument" @click="copyText(configForm.jsonText || '', 'JSON 配置')">复制</el-button>
                      <pre class="config-json-preview"><code>{{ configForm.jsonText || '未设置' }}</code></pre>
                    </div>
                  </div>
                  <div class="config-field">
                    <label>MCP 配置 JSON</label>
                    <div class="config-copy-wrap">
                      <el-button class="copy-btn" link size="small" :icon="CopyDocument" @click="copyText(mcpConfigJson, 'MCP 配置 JSON')">复制</el-button>
                      <pre class="config-json-preview"><code>{{ mcpConfigJson }}</code></pre>
                    </div>
                  </div>
                </div>
              </template>
              <!-- JSON Edit -->
              <template v-if="mcp.type === 'json' && isEditing">
                <el-input
                  v-model="configForm.jsonText"
                  type="textarea"
                  :rows="12"
                  placeholder='请输入 JSON 配置，如 {"key": "value"}'
                />
              </template>
            </div>
          </el-tab-pane>
        </el-tabs>
        <div class="tab-actions">
          <template v-if="isEditing">
            <el-button type="primary" size="small" @click="handleSaveAll" :loading="saving">
              保存
            </el-button>
            <el-button size="small" @click="handleCancel">取消</el-button>
          </template>
          <el-button v-else type="primary" link size="small" @click="toggleEdit">编辑</el-button>
        </div>
      </div>
    </div>

    <ResourceEditDialog
      v-model="isEditingInfo"
      title="编辑 MCP 基本信息"
      :saving="savingInfo"
      @cancel="handleCancelInfo"
      @save="handleSaveInfo"
    >
      <el-form :disabled="savingInfo" :model="infoForm" label-position="top">
        <el-form-item label="描述">
          <el-input v-model="infoForm.description" type="textarea" :rows="5" />
        </el-form-item>
        <el-form-item label="作者">
          <el-input v-model="infoForm.author" disabled />
        </el-form-item>
        <el-form-item label="分类">
          <McpCategorySelect v-model="infoForm.tags" />
        </el-form-item>
      </el-form>
    </ResourceEditDialog>

    <ResourceEditDialog
      v-model="isEditingConfig"
      title="编辑 MCP 连接设置"
      width="min(920px, calc(100vw - 32px))"
      :saving="savingConfig"
      @cancel="handleCancelConfig"
      @save="handleSaveConfig"
    >
      <el-form :disabled="savingConfig" label-position="top" autocomplete="off" @submit.prevent>
        <el-form-item label="类型">
          <el-select v-model="configForm.type" style="width: 100%" @change="handleConfigTypeChange">
            <el-option label="STDIO" value="stdio" />
            <el-option label="SSE" value="sse" />
            <el-option label="Streamable HTTP" value="streamable_http" />
            <el-option label="JSON" value="json" />
          </el-select>
        </el-form-item>

        <template v-if="configForm.type === 'stdio'">
          <el-form-item label="命令">
            <el-input v-model="configForm.command" placeholder="如 npx" />
          </el-form-item>
          <el-form-item label="参数">
            <div class="kv-editor">
              <div v-for="(arg, index) in configForm.args" :key="index" class="compact-kv-row">
                <el-input v-model="configForm.args[index]" placeholder="参数值" />
                <el-button type="danger" :icon="Delete" link @click="removeArg(index)" />
              </div>
              <el-button type="primary" :icon="Plus" link @click="addArg">添加参数</el-button>
            </div>
          </el-form-item>
          <el-form-item label="环境变量">
            <div class="kv-editor">
              <div v-for="(item, index) in configForm.env" :key="index" class="compact-kv-row compact-kv-row--pair">
                <el-input v-model="item.key" placeholder="名称" />
                <el-input v-model="item.value" placeholder="值" />
                <el-button type="danger" :icon="Delete" link @click="removeEnv(index)" />
              </div>
              <el-button type="primary" :icon="Plus" link @click="addEnv">添加环境变量</el-button>
            </div>
          </el-form-item>
        </template>

        <template v-else-if="configForm.type === 'sse' || configForm.type === 'streamable_http'">
          <el-form-item label="URL">
            <el-input v-model="configForm.url" placeholder="https://example.com/mcp" />
          </el-form-item>
          <el-form-item label="Headers">
            <div class="kv-editor">
              <div v-for="(item, index) in configForm.headers" :key="index" class="compact-kv-row compact-kv-row--pair">
                <el-input v-model="item.key" :name="`mcp-header-name-${index}`" autocomplete="off" placeholder="名称" />
                <el-input v-model="item.value" :name="`mcp-header-value-${index}`" autocomplete="off" placeholder="值" />
                <el-button type="danger" :icon="Delete" link @click="removeHeader(index)" />
              </div>
              <el-button type="primary" :icon="Plus" link @click="addHeader">添加 Header</el-button>
            </div>
          </el-form-item>
        </template>

        <el-form-item v-else label="配置">
          <el-input
            v-model="configForm.jsonText"
            type="textarea"
            :rows="12"
            placeholder='请输入 JSON 配置，如 {"key": "value"}'
          />
        </el-form-item>
      </el-form>
    </ResourceEditDialog>
  </div>
</template>

<script setup>
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import McpCategorySelect from './components/McpCategorySelect.vue'
import ResourceEditDialog from '@/components/ResourceEditDialog.vue'
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { mcpsApi } from '@/api/mcps'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { ArrowLeft, CopyDocument, Delete, Plus, View, Hide } from '@element-plus/icons-vue'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import { uploadImage } from '@/api/upload'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const loading = ref(false)
const saving = ref(false)
const savingInfo = ref(false)
const savingConfig = ref(false)
const visibilitySaving = ref(false)
const mcp = ref({})
const activeTab = ref('instructions')

// Content editing mode
const isEditing = ref(false)
const isEditingConfig = ref(false)
const editInstructions = ref('')
const originalInstructions = ref('')
const savedConfigForm = ref(null)
const revealedHeaderKeys = ref([])

// Name editing
const isEditingName = ref(false)
const editingName = ref('')
const nameInputRef = ref(null)

// Info editing
const isEditingInfo = ref(false)
const infoForm = ref({})
const originalInfo = ref({})

// Config form
const configForm = ref({
  type: 'stdio',
  command: '',
  args: [],
  env: [],
  url: '',
  headers: [],
  jsonText: ''
})

const typeLabelMap = {
  stdio: 'STDIO',
  sse: 'SSE',
  streamable_http: 'Streamable HTTP',
  json: 'JSON'
}
const typeLabel = (type) => typeLabelMap[type] || type

const mcpConfigJson = computed(() => {
  try {
    const config = JSON.parse(mcp.value.config || '{}')
    const name = mcp.value.name || 'server-name'
    let serverConfig = {}

    if (mcp.value.type === 'stdio') {
      serverConfig = {
        command: config.command || '',
        args: config.args || []
      }
      if (config.env && Object.keys(config.env).length > 0) {
        serverConfig.env = config.env
      }
    } else if (mcp.value.type === 'sse' || mcp.value.type === 'streamable_http') {
      serverConfig = {
        type: mcp.value.type === 'streamable_http' ? 'streamable-http' : 'sse',
        url: config.url || ''
      }
      if (config.headers && Object.keys(config.headers).length > 0) {
        serverConfig.headers = config.headers
      }
    } else if (mcp.value.type === 'json') {
      return JSON.stringify({ mcpServers: { [name]: config } }, null, 2)
    }

    return JSON.stringify({ mcpServers: { [name]: serverConfig } }, null, 2)
  } catch {
    return mcp.value.config || ''
  }
})

const onUploadImg = async (files, callback) => {
  const urls = []
  for (const file of files) {
    try {
      const res = await uploadImage(file)
      urls.push(res.url)
    } catch (e) {
      ElMessage.error('图片上传失败')
    }
  }
  callback(urls)
}

// Parse config JSON into form
const parseConfig = (type, configStr) => {
  configForm.value.type = type
  try {
    const config = JSON.parse(configStr || '{}')
    if (type === 'stdio') {
      configForm.value.command = config.command || ''
      configForm.value.args = (config.args || []).map(a => a)
      configForm.value.env = Object.entries(config.env || {}).map(([k, v]) => ({ key: k, value: v }))
      if (configForm.value.args.length === 0) configForm.value.args.push('')
      if (configForm.value.env.length === 0) configForm.value.env.push({ key: '', value: '' })
    } else if (type === 'sse' || type === 'streamable_http') {
      configForm.value.url = config.url || ''
      configForm.value.headers = Object.entries(config.headers || {}).map(([k, v]) => ({ key: k, value: v }))
      if (configForm.value.headers.length === 0) configForm.value.headers.push({ key: '', value: '' })
    } else if (type === 'json') {
      configForm.value.jsonText = JSON.stringify(config, null, 2)
    }
  } catch {
    if (type === 'stdio') {
      configForm.value.args = ['']
      configForm.value.env = [{ key: '', value: '' }]
    } else if (type === 'sse' || type === 'streamable_http') {
      configForm.value.headers = [{ key: '', value: '' }]
    }
  }
}

// Serialize config form to JSON string
const serializeConfig = (type) => {
  if (type === 'stdio') {
    const env = {}
    configForm.value.env.forEach(item => {
      if (item.key.trim()) env[item.key.trim()] = item.value
    })
    return JSON.stringify({
      command: configForm.value.command || '',
      args: configForm.value.args.filter(a => a.trim()),
      env
    })
  } else if (type === 'sse' || type === 'streamable_http') {
    const headers = {}
    configForm.value.headers.forEach(item => {
      if (item.key.trim()) headers[item.key.trim()] = item.value
    })
    return JSON.stringify({
      url: configForm.value.url || '',
      headers
    })
  } else if (type === 'json') {
    try {
      JSON.parse(configForm.value.jsonText)
      return configForm.value.jsonText
    } catch {
      return '{}'
    }
  }
  return '{}'
}

const cloneConfigForm = () => ({
  type: configForm.value.type,
  command: configForm.value.command,
  args: [...configForm.value.args],
  env: configForm.value.env.map(e => ({ key: e.key, value: e.value })),
  url: configForm.value.url,
  headers: configForm.value.headers.map(h => ({ key: h.key, value: h.value })),
  jsonText: configForm.value.jsonText
})

const restoreConfigForm = (saved) => {
  configForm.value.type = saved.type
  configForm.value.command = saved.command
  configForm.value.args = [...saved.args]
  configForm.value.env = saved.env.map(e => ({ key: e.key, value: e.value }))
  configForm.value.url = saved.url
  configForm.value.headers = saved.headers.map(h => ({ key: h.key, value: h.value }))
  configForm.value.jsonText = saved.jsonText
}

const fetchDetail = async () => {
  loading.value = true
  try {
    const data = await mcpsApi.getDetail(route.params.id)
    mcp.value = data
    editInstructions.value = data.usage_instructions || ''
    parseConfig(data.type, data.config)
    savedConfigForm.value = cloneConfigForm()
    revealedHeaderKeys.value = []
  } catch (error) {
    ElMessage.error('获取详情失败')
  } finally {
    loading.value = false
  }
}

const handleBack = () => {
  router.back()
}

const handleToggleVisibility = async () => {
  if (visibilitySaving.value || loading.value || !mcp.value.id) return
  visibilitySaving.value = true
  try {
    const result = await mcpsApi.toggleVisibility(route.params.id)
    mcp.value.is_public = Boolean(result.is_public)
    ElMessage.success(`MCP 已设为${mcp.value.is_public ? '公开' : '私有'}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '切换 MCP 可见性失败')
  } finally {
    visibilitySaving.value = false
  }
}

const copyText = async (text, label = '内容') => {
  if (!text) {
    ElMessage.warning(`${label}为空，无法复制`)
    return
  }

  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success(`${label}已复制`)
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

// Name editing
const startEditName = () => {
  isEditingName.value = true
  editingName.value = mcp.value.name
  nextTick(() => {
    if (nameInputRef.value) {
      nameInputRef.value.focus()
      nameInputRef.value.select()
    }
  })
}

const saveName = async () => {
  if (!editingName.value.trim()) {
    editingName.value = mcp.value.name
    isEditingName.value = false
    return
  }
  if (editingName.value === mcp.value.name) {
    isEditingName.value = false
    return
  }
  try {
    await mcpsApi.update(route.params.id, { name: editingName.value })
    mcp.value.name = editingName.value
    isEditingName.value = false
    ElMessage.success('名称已更新')
  } catch {
    ElMessage.error('更新失败')
    editingName.value = mcp.value.name
    isEditingName.value = false
  }
}

// Info editing
const toggleEditInfo = () => {
  isEditingInfo.value = true
  originalInfo.value = {
    author: authStore.user?.first_name || mcp.value.author,
    description: mcp.value.description,
    tags: mcp.value.tags
  }
  infoForm.value = { ...originalInfo.value }
}

const handleCancelInfo = () => {
  infoForm.value = { ...originalInfo.value }
  isEditingInfo.value = false
}

const handleSaveInfo = async () => {
  const tags = typeof infoForm.value.tags === 'string' ? infoForm.value.tags.trim() : infoForm.value.tags
  if (typeof tags === 'string' && tags.length > 500) {
    ElMessage.warning('分类不能超过 500 个字符')
    return
  }
  savingInfo.value = true
  try {
    const updates = {
      description: infoForm.value.description,
      tags
    }

    await mcpsApi.update(route.params.id, updates)
    mcp.value.description = infoForm.value.description
    mcp.value.tags = tags

    isEditingInfo.value = false
    ElMessage.success('保存成功')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    savingInfo.value = false
  }
}

// Content editing
const toggleEdit = () => {
  isEditing.value = true
  originalInstructions.value = mcp.value.usage_instructions || ''
  editInstructions.value = mcp.value.usage_instructions || ''
}

const handleCancel = () => {
  editInstructions.value = originalInstructions.value
  isEditing.value = false
}

const handleSaveAll = async () => {
  saving.value = true
  try {
    await mcpsApi.update(route.params.id, {
      usage_instructions: editInstructions.value
    })
    mcp.value.usage_instructions = editInstructions.value
    isEditing.value = false
    ElMessage.success('保存成功')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const toggleEditConfig = () => {
  if (!savedConfigForm.value) return
  restoreConfigForm(savedConfigForm.value)
  isEditingConfig.value = true
}

const toggleHeaderVisibility = (key) => {
  revealedHeaderKeys.value = revealedHeaderKeys.value.includes(key)
    ? revealedHeaderKeys.value.filter(item => item !== key)
    : [...revealedHeaderKeys.value, key]
}

const handleCancelConfig = () => {
  restoreConfigForm(savedConfigForm.value)
  isEditingConfig.value = false
}

const handleSaveConfig = async () => {
  savingConfig.value = true
  try {
    const type = configForm.value.type
    const config = serializeConfig(type)
    const updated = await mcpsApi.update(route.params.id, { type, config })
    mcp.value = updated
    parseConfig(updated.type, updated.config)
    savedConfigForm.value = cloneConfigForm()
    revealedHeaderKeys.value = []
    isEditingConfig.value = false
    ElMessage.success('保存成功')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    savingConfig.value = false
  }
}

// Config helpers
const handleConfigTypeChange = (type) => {
  parseConfig(type, type === mcp.value.type ? mcp.value.config : null)
}

const addArg = () => configForm.value.args.push('')
const removeArg = (index) => configForm.value.args.splice(index, 1)
const addEnv = () => configForm.value.env.push({ key: '', value: '' })
const removeEnv = (index) => configForm.value.env.splice(index, 1)
const addHeader = () => configForm.value.headers.push({ key: '', value: '' })
const removeHeader = (index) => configForm.value.headers.splice(index, 1)

onMounted(() => {
  fetchDetail()
})
</script>

<style scoped>
.mcp-detail {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: white;
  border-radius: 4px;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px 12px 12px;
  border-bottom: 1px solid #e8e8e8;
  flex-shrink: 0;
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

.header-info h2 {
  margin: 0;
  font-size: 20px;
}

.header-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  margin-left: 12px;
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
  width: 60%;
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
  border-right: 1px solid #e8e8e8;
  overflow-y: auto;
  flex-shrink: 0;
}

.info-section {
  border-bottom: 1px solid #e8e8e8;
}

.connection-section {
  border-bottom: 1px solid #e8e8e8;
}

.connection-content,
.connection-edit {
  padding: 14px 16px 18px;
}

.connection-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.connection-item {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}

.connection-label {
  color: #606266;
  font-size: 12px;
  font-weight: 600;
}

.connection-item > code,
.connection-values code {
  padding: 5px 8px;
  border-radius: 4px;
  background: #f5f7fa;
  color: #303133;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.connection-values {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.connection-pairs {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  overflow: hidden;
}

.connection-pairs > div {
  display: grid;
  grid-template-columns: minmax(90px, 0.8fr) minmax(0, 1.2fr);
}

.connection-pairs > div + div {
  border-top: 1px solid #ebeef5;
}

.connection-pairs code,
.connection-pairs span {
  padding: 7px 9px;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.connection-pairs .secret-value {
  min-width: 0;
}

.connection-pairs > .connection-header-row {
  grid-template-columns: minmax(90px, 0.8fr) minmax(0, 1.2fr) 28px;
  align-items: center;
}
.connection-header-row .el-button {
  margin: 0;
  padding: 0;
}

.connection-pairs code {
  background: #f5f7fa;
  border-right: 1px solid #ebeef5;
}

.connection-json {
  max-height: 320px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border-radius: 4px;
  background: #1e1e1e;
  color: #9cdcfe;
  font-size: 12px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.compact-kv-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px;
  margin-bottom: 8px;
}

.compact-kv-row--pair {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
}

.compact-kv-row > .el-button {
  min-width: 0;
  margin-left: 0;
  padding-right: 0;
  padding-left: 0;
  justify-self: end;
}

.info-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #e8e8e8;
}

.info-header h3 {
  margin: 0;
  font-size: 14px;
}

.info-actions {
  display: flex;
  gap: 5px;
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
  color: #606266;
  font-size: 12px;
  white-space: nowrap;
  flex-shrink: 0;
}

.info-value {
  color: #303133;
  word-break: break-word;
  flex: 1;
}

.info-edit {
  padding: 12px 16px;
}

.content-area {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
  padding-left: 20px;
}

.tab-actions {
  position: absolute;
  top: 0;
  right: 24px;
  display: flex;
  gap: 8px;
  align-items: center;
  height: 40px;
  z-index: 1;
}

.content-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.content-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow: hidden;
}

.content-tabs :deep(.el-tab-pane) {
  height: 100%;
}

.content-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 0;
}

/* Instructions preview */
.instructions-preview {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.instructions-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.instructions-body :deep(.md-editor-preview) {
  padding: 0;
}

/* Instructions editor */
.instructions-editor {
  height: 100%;
  border-radius: 4px;
  overflow: hidden;
}

.instructions-editor :deep(.md-editor) {
  height: 100%;
}

/* Config editor */
.config-editor {
  padding: 24px;
  max-width: 748px;
}

.kv-editor {
  width: 100%;
}

.kv-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}

.kv-row .el-input {
  flex: 1;
}

/* Config preview */
.config-preview {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.config-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.config-field label {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.config-code-block {
  padding: 10px 14px;
  background: #1e1e1e;
  color: #4ec9b0;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 13px;
  border-radius: 6px;
  line-height: 1.6;
  word-break: break-all;
}

.config-copy-wrap {
  position: relative;
}

.config-copy-wrap .config-code-block,
.config-copy-wrap .config-json-preview {
  padding-right: 76px;
}

.copy-btn {
  position: absolute;
  top: 8px;
  right: 10px;
  z-index: 1;
  padding: 0;
  color: #cfd3dc;
}

.copy-btn:hover {
  color: #409eff;
}

.config-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.config-tag {
  display: inline-block;
  padding: 3px 10px;
  font-size: 13px;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  color: #e6a23c;
  background: #fdf6ec;
  border: 1px solid #faecd8;
  border-radius: 4px;
}

.config-table {
  border-collapse: collapse;
  font-size: 13px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;
}

.config-table tr:not(:last-child) td {
  border-bottom: 1px solid #ebeef5;
}

.config-table-key {
  padding: 8px 14px;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  font-weight: 600;
  color: #303133;
  background: #fafafa;
  width: 1%;
  white-space: nowrap;
  border-right: 1px solid #e4e7ed;
}

.config-table-value {
  padding: 8px 14px;
  color: #606266;
  word-break: break-all;
}

.config-json-preview {
  margin: 0;
  padding: 14px 16px;
  background: #1e1e1e;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.7;
  overflow-x: auto;
}

.config-json-preview code {
  color: #9cdcfe;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
}
</style>
