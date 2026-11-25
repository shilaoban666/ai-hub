<template>
  <div class="mcp-detail">
    <div class="detail-header">
      <el-button class="back-btn" @click="handleBack" :icon="ArrowLeft">返回</el-button>
      <div class="header-info">
        <h2>{{ mcp.name }}</h2>
        <el-tag type="primary">{{ typeLabel(mcp.type) }}</el-tag>
      </div>
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
          <div class="info-header connection-header">
            <h3>连接设置</h3>
            <el-tooltip :content="showConnectionJson ? '显示字段配置' : '显示 JSON 配置'" placement="top">
              <el-button
                :icon="Sort"
                link
                circle
                class="connection-toggle"
                :class="{ 'is-active': showConnectionJson }"
                :aria-label="showConnectionJson ? '显示字段配置' : '显示 JSON 配置'"
                @click="showConnectionJson = !showConnectionJson"
              />
            </el-tooltip>
          </div>
          <div v-if="showConnectionJson" class="connection-content">
            <div class="connection-item">
              <span class="connection-label">类型</span>
              <code>{{ typeLabel(mcp.type) }}</code>
            </div>
            <div class="connection-json-wrap">
              <el-button
                class="connection-json-copy"
                :icon="CopyDocument"
                link
                size="small"
                @click="copyText(mcpConfigJson, 'JSON 配置')"
              >
                复制
              </el-button>
              <pre class="connection-json"><code>{{ mcpConfigJson }}</code></pre>
            </div>
          </div>
          <div v-else class="connection-content">
            <div class="connection-item">
              <span class="connection-label">类型</span>
              <code>{{ typeLabel(mcp.type) }}</code>
            </div>
            <template v-if="mcp.type === 'stdio'">
              <div class="connection-item">
                <span class="connection-label">命令</span>
                <code>{{ configForm.command || '未设置' }}</code>
              </div>
              <div v-if="configForm.args.filter(Boolean).length" class="connection-item">
                <span class="connection-label">参数</span>
                <div class="connection-values">
                  <code v-for="(arg, index) in configForm.args.filter(Boolean)" :key="index">{{ arg }}</code>
                </div>
              </div>
              <div v-if="configForm.env.filter(item => item.key).length" class="connection-item">
                <span class="connection-label">环境变量</span>
                <div class="connection-pairs">
                  <div v-for="item in configForm.env.filter(item => item.key)" :key="item.key">
                    <code>{{ item.key }}</code><span>隐藏</span>
                  </div>
                </div>
              </div>
            </template>

            <template v-else-if="mcp.type === 'sse' || mcp.type === 'streamable_http'">
              <div class="connection-item">
                <span class="connection-label">URL</span>
                <code>{{ configForm.url || '未设置' }}</code>
              </div>
              <div v-if="configForm.headers.filter(item => item.key).length" class="connection-item">
                <span class="connection-label">Headers</span>
                <div class="connection-pairs">
                  <div v-for="item in configForm.headers.filter(item => item.key)" :key="item.key">
                    <code>{{ item.key }}</code>
                    <span>需填写真实信息</span>
                  </div>
                </div>
              </div>
            </template>

            <pre v-else class="connection-json"><code>{{ configForm.jsonText || '{}' }}</code></pre>
          </div>
        </div>
      </div>

      <div class="content-area">
        <el-tabs v-model="activeTab" class="content-tabs">
          <el-tab-pane label="使用说明" name="instructions">
            <div class="instructions-view">
              <div class="instructions-body">
                <MdPreview :modelValue="mcp.usage_instructions || ''" />
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane v-if="false" label="配置" name="config">
            <div class="config-editor">
              <template v-if="mcp.type === 'stdio'">
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

              <template v-else-if="mcp.type === 'sse' || mcp.type === 'streamable_http'">
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

              <template v-else-if="mcp.type === 'json'">
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
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { publicMcpsApi } from '@/api/mcps'
import { ElMessage } from 'element-plus'
import { ArrowLeft, CopyDocument, Sort } from '@element-plus/icons-vue'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'

const router = useRouter()
const route = useRoute()

const loading = ref(false)
const mcp = ref({})
const activeTab = ref('instructions')
const showConnectionJson = ref(false)

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
    } else if (mcp.value.type === 'sse' || mcp.value.type === 'streamable_http') {
      serverConfig = {
        type: mcp.value.type === 'streamable_http' ? 'streamable-http' : 'sse',
        url: config.url || ''
      }
      if (config.headers && Object.keys(config.headers).length > 0) {
        serverConfig.headers = Object.fromEntries(
          Object.keys(config.headers).map(key => [key, '需填写真实信息'])
        )
      }
    } else if (mcp.value.type === 'json') {
      return JSON.stringify({ mcpServers: { [name]: config } }, null, 2)
    }

    return JSON.stringify({ mcpServers: { [name]: serverConfig } }, null, 2)
  } catch {
    return mcp.value.config || ''
  }
})

const configForm = ref({
  command: '',
  args: [],
  env: [],
  url: '',
  headers: [],
  jsonText: ''
})

const parseConfig = (type, configStr) => {
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

const fetchDetail = async () => {
  loading.value = true
  try {
    const data = await publicMcpsApi.getDetail(route.params.id)
    mcp.value = data
    parseConfig(data.type, data.config)
  } catch (error) {
    ElMessage.error('获取详情失败')
  } finally {
    loading.value = false
  }
}

const handleBack = () => {
  router.back()
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

onMounted(() => {
  fetchDetail()
})
</script>

<style scoped>
.mcp-detail {
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

.header-info h2 {
  margin: 0;
  font-size: 20px;
  color: var(--ink);
}

.detail-body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.left-sidebar {
  width: 300px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  flex-shrink: 0;
}

.info-section {
  border-bottom: 1px solid var(--border);
}

.connection-section {
  border-bottom: 1px solid var(--border);
}

.connection-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.connection-toggle {
  width: 26px;
  height: 26px;
  color: var(--ink-soft);
}

.connection-toggle:hover {
  color: var(--brand-600);
  background: var(--brand-50);
}

.connection-toggle :deep(.el-icon) {
  transform: rotate(90deg);
}

.connection-toggle.is-active {
  color: var(--brand-600);
  background: var(--brand-50);
}

.connection-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 14px 16px 18px;
}

.connection-item {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}

.connection-label {
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 600;
}

.connection-item > code,
.connection-values code {
  padding: 5px 8px;
  border-radius: 4px;
  background: var(--bg);
  color: var(--ink);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.connection-values {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.connection-pairs {
  border: 1px solid var(--border-soft);
  border-radius: 4px;
  overflow: hidden;
}

.connection-pairs > div {
  display: grid;
  grid-template-columns: minmax(90px, 0.8fr) minmax(0, 1.2fr);
}

.connection-pairs > div + div {
  border-top: 1px solid var(--border-soft);
}

.connection-pairs code,
.connection-pairs span {
  padding: 7px 9px;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.connection-pairs code {
  background: var(--bg);
  border-right: 1px solid var(--border-soft);
}

.connection-json {
  max-height: 320px;
  margin: 0;
  padding: 12px;
  overflow-x: auto;
  overflow-y: auto;
  border-radius: 4px;
  background: #1e1e1e;
  color: #9cdcfe;
  font-size: 12px;
  white-space: pre;
  overflow-wrap: normal;
}

.connection-json-wrap {
  position: relative;
}

.connection-json-wrap .connection-json {
  padding-right: 62px;
}

.connection-json-copy {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 1;
  color: #cfd3dc;
}

.connection-json-copy:hover {
  color: var(--brand-600);
}

.info-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
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

.content-area {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding-left: 20px;
}

.content-tabs {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.content-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.content-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 0;
}

.content-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
}

.instructions-body :deep(.md-editor-preview) {
  padding: 0;
}

.instructions-view {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.instructions-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px;
}

.config-editor {
  padding: 24px;
  max-width: 748px;
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
  color: var(--ink);
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
  color: var(--brand-600);
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
  color: var(--brand-600);
  background: var(--brand-50);
  border: 1px solid var(--border);
  border-radius: 4px;
}

.config-table {
  border-collapse: collapse;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.config-table tr:not(:last-child) td {
  border-bottom: 1px solid var(--border-soft);
}

.config-table-key {
  padding: 8px 14px;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  font-weight: 600;
  color: var(--ink);
  background: var(--bg);
  width: 1%;
  white-space: nowrap;
  border-right: 1px solid var(--border);
}

.config-table-value {
  padding: 8px 14px;
  color: var(--ink-soft);
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

@media (max-width: 760px) {
  .mcp-detail {
    height: calc(100dvh - 93px);
  }
}
</style>
