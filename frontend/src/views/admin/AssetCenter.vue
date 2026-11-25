<template>
  <main class="resource-center" :class="{ 'resource-center--embedded': embedded }">
    <ResourcePageHeader v-if="!embedded"
      :title="workspaceTitle || (systemMode ? '系统资源' : '能力配置')"
      :description="workspaceView ? '' : (systemMode ? '仅配置默认助手使用的技能、MCP 和提示词。自定义 Agent 的资源由各智能体独立维护。' : '管理当前账号使用的技能、MCP 和提示词。')"
    >
      <template #actions>
      <el-tooltip content="刷新当前资源" placement="bottom">
        <el-button :icon="Refresh" circle text aria-label="刷新资源" @click="loadAll" />
      </el-tooltip>
      </template>
    </ResourcePageHeader>

    <nav v-if="!workspaceView" class="resource-nav" :aria-label="systemMode ? '系统资源导航' : '能力配置导航'">
      <button
        v-for="item in navItems"
        :key="item.value"
        type="button"
        :class="{ active: activeView === item.value }"
        @click="activeView = item.value"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
        <b v-if="item.count">{{ item.count }}</b>
      </button>
    </nav>

    <section class="resource-workspace">
      <SkillCatalogPanel v-if="activeView === 'skills'" ref="skillPanel" :system-mode="systemMode" :agent-id="agentId" :read-only="readOnly" />

      <McpCatalogPanel
        v-else-if="activeView === 'mcp'"
        :sources="mcpSources"
        :connections="connections"
        :system-mode="systemMode"
        :agent-id="agentId"
        :read-only="readOnly"
        :loading="loading"
        :error="connectionLoadError"
        :connecting-id="mcpPicker.importing ? mcpPicker.selected?.id : null"
        :action-id="connectionActionId"
        :action-type="connectionActionType"
        :inspection-id="inspectionDialog.loading ? inspectionDialog.row?.id : null"
        @connect="connectCatalogMcp"
        @disconnect="deleteConnection"
        @configure="openMcpHeaders"
        @inspect="openMcpInspector"
        @toggle="toggleConnection"
        @refresh="loadAll"
      />

      <PromptCatalogPanel
        v-else-if="activeView === 'prompts'"
        :key="[systemMode, agentId, readOnly].join(':')"
        ref="promptPanel"
        :system-mode="systemMode"
        :agent-id="agentId"
        :read-only="readOnly"
      />
    </section>

    <el-dialog
      v-model="headerDialog.open"
      class="mcp-auth-dialog"
      width="min(640px, calc(100vw - 32px))"
      @closed="headerDialog.rows = []"
    >
      <template #header>
        <div class="auth-dialog-heading">
          <span class="auth-dialog-icon"><el-icon><Key /></el-icon></span>
          <div>
            <h2>{{ headerDialog.kind === 'env' ? '环境变量配置' : '认证配置' }}</h2>
            <p>{{ headerDialog.name }}</p>
          </div>
        </div>
      </template>
      <el-form v-loading="headerDialog.loading" class="auth-dialog-content" autocomplete="off" @submit.prevent>
        <template v-if="headerDialog.kind === 'headers'">
        <section v-if="headerDialog.resource === 'system'" class="auth-config-section">
          <el-switch v-model="headerDialog.inheritSystem" active-text="跟随系统配置" aria-label="跟随系统配置" @change="handleAuthInheritanceChange" />
          <p class="auth-inheritance-help">{{ headerDialog.inheritSystem ? '使用系统认证方式和请求头，并跟随系统后续修改。关闭后可配置个人认证。' : '个人认证方式仅对你生效；附加请求头与系统合并，同名项使用个人配置。' }}</p>
        </section>
        <section class="auth-config-section">
          <div class="auth-section-heading">
            <h3>认证方式</h3>
            <span>Authorization 来源</span>
          </div>
          <el-segmented
            v-model="headerDialog.authMode"
            class="auth-mode-segmented"
            :options="authModeOptions"
            :disabled="headerDialog.inheritSystem"
            @change="handleAuthModeChange"
          />
          <div class="auth-mode-summary" :class="`auth-mode-summary--${headerDialog.authMode}`">
            <el-icon><InfoFilled /></el-icon>
            <div>
              <strong>{{ authModeTitle(headerDialog.authMode) }}</strong>
              <span>{{ authModeHelp(headerDialog.authMode) }}</span>
            </div>
          </div>
        </section>
        <section v-if="!headerDialog.inheritSystem" class="auth-config-section auth-headers-section">
          <McpHeaderEditor
            v-model="headerDialog.rows"
            :allow-authorization="headerDialog.authMode === 'manual'"
          >
            <template #heading>
              <div class="auth-section-heading auth-section-heading--headers">
                <h3>附加请求头</h3>
                <span v-if="headerDialog.rows.length" class="header-count">{{ headerDialog.rows.length }} 项</span>
              </div>
            </template>
          </McpHeaderEditor>
        </section>
        </template>
        <section v-else class="auth-config-section auth-headers-section">
          <McpHeaderEditor
            v-model="headerDialog.rows"
            :allow-authorization="false"
            name-label="环境变量名称"
            value-label="环境变量值"
            name-placeholder="例如 API_KEY"
            value-placeholder="环境变量值"
            add-label="添加环境变量"
            empty-title="没有环境变量"
            empty-description="此 stdio MCP 暂未配置环境变量"
          >
            <template #heading>
              <div class="auth-section-heading auth-section-heading--headers">
                <h3>环境变量</h3>
                <span v-if="headerDialog.rows.length" class="header-count">{{ headerDialog.rows.length }} 项</span>
              </div>
            </template>
          </McpHeaderEditor>
        </section>
      </el-form>
      <template #footer>
        <div class="auth-dialog-footer">
          <el-button @click="headerDialog.open = false">取消</el-button>
          <el-button type="primary" :loading="headerDialog.saving" :disabled="headerDialog.loading || headerDialog.failed" @click="saveMcpHeaders">保存配置</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="inspectionDialog.open"
      class="mcp-inspection-dialog"
      width="min(1040px, calc(100vw - 32px))"
      :title="`${inspectionDialog.name || '连接器'} · 资源列表`"
      @closed="inspectionDialog.data = null"
    >
      <el-alert v-if="inspectionDialog.error" type="error" :closable="false" show-icon :title="inspectionDialog.error" />
      <div v-else v-loading="inspectionDialog.loading" class="inspection-body">
        <McpResourceInspector :data="inspectionDialog.data" />
      </div>
    </el-dialog>

    <el-dialog
      v-model="importHeaderDialog.open"
      class="mcp-auth-dialog mcp-import-header-dialog"
      :title="importHeaderDialog.kind === 'headers' ? '认证配置' : '配置 MCP 认证信息'"
      width="min(640px, calc(100vw - 32px))"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="false"
    >
      <template #header>
        <div class="auth-dialog-heading">
          <span class="auth-dialog-icon"><el-icon><Key /></el-icon></span>
          <div><h2>{{ importHeaderDialog.kind === 'headers' ? '认证配置' : '环境变量配置' }}</h2><p>{{ importHeaderDialog.name }}</p></div>
        </div>
      </template>
      <el-form v-if="importHeaderDialog.kind === 'headers'" class="auth-dialog-content" autocomplete="off" @submit.prevent>
        <section class="auth-config-section">
          <div class="auth-section-heading"><h3>认证方式</h3><span>Authorization 来源</span></div>
          <el-segmented v-model="importHeaderDialog.authMode" class="auth-mode-segmented" :options="authModeOptions" @change="handleImportAuthModeChange" />
          <div class="auth-mode-summary" :class="`auth-mode-summary--${importHeaderDialog.authMode}`">
            <el-icon><InfoFilled /></el-icon>
            <div><strong>{{ authModeTitle(importHeaderDialog.authMode) }}</strong><span>{{ authModeHelp(importHeaderDialog.authMode) }}</span></div>
          </div>
        </section>
        <section class="auth-config-section auth-headers-section">
          <McpHeaderEditor v-model="importHeaderDialog.rows" :allow-authorization="importHeaderDialog.authMode === 'manual'">
            <template #heading>
              <div class="auth-section-heading auth-section-heading--headers"><h3>附加请求头</h3><span v-if="importHeaderDialog.rows.length" class="header-count">{{ importHeaderDialog.rows.length }} 项</span></div>
            </template>
          </McpHeaderEditor>
        </section>
      </el-form>
      <el-form v-else class="import-header-form" autocomplete="off" @submit.prevent>
        <div v-for="row in importHeaderDialog.rows" :key="`${row.kind}:${row.name}`" class="import-header-row">
          <label><span class="import-header-kind">{{ row.kindLabel }}</span>{{ row.name }}</label>
          <el-input
            v-model="row.value"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="`请输入 ${row.name} 的值`"
            @keyup.enter="saveImportHeaders"
          />
        </div>
      </el-form>
      <p class="import-header-help">这些认证信息只保存到本次资源中心连接，不会修改 MCP 管理中的原始配置，也不会影响其他工作台或智能体连接。</p>
      <template #footer>
        <div class="auth-dialog-footer">
          <el-button @click="cancelImportHeaders">取消</el-button>
          <el-button type="primary" :loading="importHeaderDialog.saving" @click="saveImportHeaders">保存并继续</el-button>
        </div>
      </template>
    </el-dialog>

  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import {
  Connection, Files, Refresh,
  InfoFilled, Key,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { assetsApi } from '@/api/assets'
import { mcpsApi, publicMcpsApi } from '@/api/mcps'
import SkillCatalogPanel from './components/SkillCatalogPanel.vue'
import SkillIcon from '@/components/icons/SkillIcon.vue'
import McpCatalogPanel from './components/McpCatalogPanel.vue'
import { loadMcpCatalogSources } from '@/utils/mcp-catalog'
import PromptCatalogPanel from './components/PromptCatalogPanel.vue'
import ResourcePageHeader from './components/ResourcePageHeader.vue'
import McpHeaderEditor from './components/McpHeaderEditor.vue'
import McpResourceInspector from './components/McpResourceInspector.vue'

const props = defineProps({
  readOnly: { type: Boolean, default: false },
  systemMode: { type: Boolean, default: false },
  embedded: { type: Boolean, default: false },
  workspaceView: { type: String, default: '' },
  workspaceTitle: { type: String, default: '' },
  agentId: { type: [Number, String], default: null },
})
const systemMode = computed(() => props.systemMode)
const embedded = computed(() => props.embedded)
const agentId = computed(() => Number(props.agentId) > 0 ? Number(props.agentId) : null)
const agentMode = computed(() => Boolean(agentId.value) && !systemMode.value)

const activeView = ref('skills')
watch(() => props.workspaceView, value => { activeView.value = value || 'skills' }, { immediate: true })
const connections = ref([])
const mcpSources = ref([])
const connectionLoadError = ref('')
const loading = ref(false)
const skillPanel = ref(null)
const promptPanel = ref(null)
const connectionActionId = ref(null)
const connectionActionType = ref('')
const headerDialog = reactive({ open: false, name: '', resource: '', id: null, kind: 'headers', rows: [], authMode: 'manual', inheritSystem: false, systemAuthMode: 'manual', loading: false, saving: false, failed: false })
const inspectionDialog = reactive({ open: false, name: '', row: null, loading: false, error: '', data: null })
const importHeaderDialog = reactive({ open: false, name: '', kind: 'headers', authMode: 'manual', rows: [], savedHeaders: {}, authorizationRows: [], saving: false, resolve: null })
const authModeOptions = [
  { label: '不发送认证', value: 'none' },
  { label: '手动配置', value: 'manual' },
  { label: '当前登录身份', value: 'current_user' },
]
const authModeTitle = mode => ({
  none: '不携带身份凭据',
  manual: '使用已保存的请求头',
  current_user: '按会话复用登录身份',
})[mode] || ''
const authModeHelp = mode => ({
  none: '不会向 MCP 发送 Authorization，附加请求头不受影响。',
  manual: 'Authorization 等请求头将加密保存，并用于后续请求。',
  current_user: '工作台在线对话使用登录用户的 Bearer Token，不保存 Token。微信、钉钉等后台渠道没有浏览器登录态，请改用手动配置或不发送认证。仅支持 Claude Agent Runtime。',
})[mode] || ''
const mcpPicker = reactive({ selected: null, importing: false })
const navItems = [
  { value: 'skills', label: '技能', icon: SkillIcon },
  { value: 'prompts', label: '提示词库', icon: Files },
  { value: 'mcp', label: 'MCP', icon: Connection },
]

const items = result => result?.items || []
let resourceRequest = 0
const loadAll = async () => {
  const request = ++resourceRequest
  if (activeView.value !== 'mcp') {
    loading.value = false
    return activeView.value === 'skills' ? skillPanel.value?.refresh() : promptPanel.value?.refresh()
  }
  loading.value = true
  connectionLoadError.value = ''
  try {
    const [result, sources] = await Promise.all([
      systemMode.value ? assetsApi.getSystemMcpDefinitions() : assetsApi.getMcpConnections(agentMode.value ? { agent_id: agentId.value } : undefined),
      loadMcpCatalogSources({ mineApi: mcpsApi, publicApi: publicMcpsApi, systemMode: systemMode.value, readOnly: props.readOnly }),
    ])
    if (request !== resourceRequest) return
    // Custom agents only use their explicitly bound connections.
    connections.value = (agentMode.value ? items(result).filter(row => !row.is_system) : items(result))
      .map(row => ({ ...row, agent_bound: agentMode.value }))
    mcpSources.value = sources
  } catch (error) {
    if (request !== resourceRequest) return
    const message = requestErrorMessage(error, '资源加载失败')
    connections.value = []
    mcpSources.value = []
    connectionLoadError.value = message
    ElMessage.error(message)
  } finally {
    if (request === resourceRequest) loading.value = false
  }
}
const requestErrorMessage = (error, fallback) => {
  const detail = error.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail.message === 'string' && detail.message.trim()) return detail.message
  if (Array.isArray(detail)) return detail.map(item => item?.msg).filter(Boolean).join('；') || fallback
  return fallback
}
const headerPayload = rows => {
  const entries = []
  const names = new Set()
  for (const row of rows) {
    const name = row.name.trim()
    if (!name && !row.value) continue
    if (!/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(name)) throw new Error('请输入有效的请求头名称')
    if (names.has(name.toLowerCase())) throw new Error('请求头名称不能重复')
    if (!row.value && row.configured) {
      entries.push([name, null])
      names.add(name.toLowerCase())
      continue
    }
    if (!row.value) throw new Error('请输入请求头值')
    if (name.toLowerCase() === 'authorization' && row.value.trim().toLowerCase() === 'bearer') throw new Error('请输入 Bearer Token')
    if (/[\r\n]/.test(row.value)) throw new Error('请求头值不能包含换行')
    names.add(name.toLowerCase())
    entries.push([name, row.value])
  }
  return Object.fromEntries(entries)
}
const secretPayload = rows => {
  const entries = []
  const names = new Set()
  for (const row of rows) {
    const name = String(row.name || '').trim()
    if (!name && !row.value) continue
    if (!name) throw new Error('请输入环境变量名称')
    if (names.has(name)) throw new Error('环境变量名称不能重复')
    if (!row.value && row.configured) entries.push([name, null])
    else if (!row.value) throw new Error('请输入环境变量值')
    else if (/[\r\n]/.test(row.value)) throw new Error('环境变量值不能包含换行')
    else entries.push([name, row.value])
    names.add(name)
  }
  return Object.fromEntries(entries)
}
const openMcpHeaders = async row => {
  if (props.readOnly) return
  const resource = systemMode.value ? 'definitions' : (row.is_system ? 'system' : 'connections')
  const id = !systemMode.value && row.is_system ? row.definition_id : row.id
  const kind = row.transport_type === 'stdio' ? 'env' : 'headers'
  Object.assign(headerDialog, { open: true, name: row.name, resource, id, kind, rows: [], authMode: 'manual', inheritSystem: false, systemAuthMode: 'manual', loading: true, failed: false })
  try {
    const result = kind === 'headers'
      ? await assetsApi.getMcpHeaders(headerDialog.resource, headerDialog.id, agentId.value || undefined)
      : await assetsApi.getMcpSecrets(headerDialog.resource, headerDialog.id, agentId.value || undefined)
    headerDialog.authMode = result.auth_mode || 'manual'
    headerDialog.inheritSystem = resource === 'system' && result.inherit_system === true
    headerDialog.systemAuthMode = result.system_auth_mode || 'manual'
    headerDialog.rows = (kind === 'headers' ? result.headers : result.fields).map(item => ({
      name: item.name,
      value: '',
      configured: item.configured !== false,
    }))
  } catch (error) {
    headerDialog.failed = true
    ElMessage.error(requestErrorMessage(error, '请求头加载失败'))
  } finally { headerDialog.loading = false }
}
const openMcpInspector = async row => {
  Object.assign(inspectionDialog, { open: true, name: row.name, row, loading: true, error: '', data: null })
  try {
    const result = systemMode.value || row.is_system
      ? await assetsApi.inspectSystemMcp(systemMode.value ? row.id : row.definition_id)
      : await assetsApi.inspectMcpConnection(row.id, agentId.value || undefined)
    inspectionDialog.data = result
  } catch (error) {
    inspectionDialog.error = requestErrorMessage(error, 'MCP 资源列表加载失败')
  } finally { inspectionDialog.loading = false }
}
const handleAuthModeChange = mode => {
  if (mode === 'manual') return
  headerDialog.rows = headerDialog.rows.filter(row => row.name.trim().toLowerCase() !== 'authorization')
}
const handleAuthInheritanceChange = inherit => {
  if (inherit) headerDialog.authMode = headerDialog.systemAuthMode
  handleAuthModeChange(headerDialog.authMode)
}
const saveMcpHeaders = async () => {
  if (props.readOnly) return
  let values
  try {
    values = headerDialog.kind === 'headers'
      ? (headerDialog.inheritSystem ? {} : headerPayload(headerDialog.rows))
      : secretPayload(headerDialog.rows)
  }
  catch (error) { return ElMessage.warning(error.message) }
  headerDialog.saving = true
  try {
    if (headerDialog.kind === 'headers') {
      await assetsApi.updateMcpHeaders(
        headerDialog.resource,
        headerDialog.id,
        values,
        headerDialog.authMode,
        headerDialog.inheritSystem,
        agentId.value || undefined,
      )
    } else {
      await assetsApi.updateMcpSecrets(headerDialog.resource, headerDialog.id, values, agentId.value || undefined)
    }
    headerDialog.open = false
    ElMessage.success(headerDialog.kind === 'env' ? '环境变量已保存' : '认证配置已保存')
    await loadAll()
  } catch (error) { ElMessage.error(requestErrorMessage(error, headerDialog.kind === 'env' ? '环境变量保存失败' : '请求头保存失败')) }
  finally { headerDialog.saving = false }
}
const toggleConnection = async row => {
  if (props.readOnly) return
  const nextStatus = row.status === 'active' ? 'disabled' : 'active'
  connectionActionId.value = row.id
  connectionActionType.value = 'toggle'
  try {
    await assetsApi.setMcpConnectionStatus(row.id, nextStatus, agentId.value || undefined)
    ElMessage.success(nextStatus === 'active' ? '连接器已启用' : '连接器已停用')
    await loadAll()
  } catch (error) {
    ElMessage.error(requestErrorMessage(error, nextStatus === 'active' ? '连接器启用失败' : '连接器停用失败'))
  } finally {
    connectionActionId.value = null
    connectionActionType.value = ''
  }
}

const deleteConnection = async row => {
  if (props.readOnly) return
  try {
    const message = agentMode.value
      ? `确定取消当前智能体与 ${row.name} 的连接？不影响 AI 工作台或其他智能体。`
      : `确定取消${systemMode.value ? '默认助手' : '工作台'}与 ${row.name} 的连接？需要时可重新连接。`
    await ElMessageBox.confirm(message, '取消连接', { type: 'warning' })
    connectionActionId.value = row.id
    connectionActionType.value = 'disconnect'
    if (systemMode.value) await assetsApi.deleteMcpDefinition(row.id)
    else if (agentMode.value) await assetsApi.unbindMcpConnection(row.id, agentId.value)
    else await assetsApi.removeMcp(row)
    ElMessage.success('已取消连接')
    await loadAll()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(requestErrorMessage(error, '取消连接失败'))
  } finally {
    connectionActionId.value = null
    connectionActionType.value = ''
  }
}

const parseMcpConfig = value => {
  if (!value) return {}
  if (typeof value === 'object') return value
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}
const objectKeys = value => value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value) : []
const normalizedMcpPickerConfig = (config, transportType) => {
  if (transportType !== 'json') return config || {}
  const servers = config?.mcpServers
  if (!Object.hasOwn(config || {}, 'mcpServers')) return config || {}
  if (objectKeys(servers).length !== 1) throw new Error('JSON MCP 配置的 mcpServers 必须包含一个服务，请拆分后添加')
  const candidate = Object.values(servers)[0]
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) throw new Error('JSON MCP 服务配置必须是对象')
  return candidate
}
const mcpSecretFields = (config, transportType) => {
  const candidate = normalizedMcpPickerConfig(config, transportType)
  const normalizedType = String(transportType || '').replaceAll('-', '_').toLowerCase()
  const declared = String(candidate?.type || '').replaceAll('-', '_').toLowerCase()
  const effectiveType = normalizedType === 'json'
    ? (['stdio', 'http', 'sse', 'streamable_http'].includes(declared) ? declared : candidate?.command ? 'stdio' : 'http')
    : normalizedType
  const kind = effectiveType === 'stdio' ? 'env' : 'headers'
  const kindLabel = kind === 'env' ? '环境变量' : '请求头'
  return objectKeys(candidate?.[kind]).map(fieldName => ({ kind, kindLabel, name: fieldName }))
}
const requestImportHeaders = (name, fields, savedHeaders = {}) => new Promise(resolve => {
  importHeaderDialog.name = name
  importHeaderDialog.kind = fields[0]?.kind || 'headers'
  importHeaderDialog.authMode = 'manual'
  importHeaderDialog.savedHeaders = savedHeaders
  importHeaderDialog.authorizationRows = []
  importHeaderDialog.rows = fields.map(field => ({ ...field, value: '', configured: field.kind === 'headers' && typeof savedHeaders[field.name] === 'string' && Boolean(savedHeaders[field.name].trim()) }))
  importHeaderDialog.saving = false
  importHeaderDialog.resolve = resolve
  importHeaderDialog.open = true
})
const finishImportHeaders = result => {
  const resolve = importHeaderDialog.resolve
  importHeaderDialog.resolve = null
  importHeaderDialog.open = false
  importHeaderDialog.savedHeaders = {}
  importHeaderDialog.rows = []
  importHeaderDialog.authorizationRows = []
  if (resolve) resolve(result)
}
const cancelImportHeaders = () => finishImportHeaders(null)
const handleImportAuthModeChange = mode => {
  if (mode === 'manual') {
    importHeaderDialog.rows.push(...importHeaderDialog.authorizationRows)
    importHeaderDialog.authorizationRows = []
  } else {
    const authorizationRows = importHeaderDialog.rows.filter(row => row.name.trim().toLowerCase() === 'authorization')
    if (authorizationRows.length) importHeaderDialog.authorizationRows = authorizationRows
    importHeaderDialog.rows = importHeaderDialog.rows.filter(row => row.name.trim().toLowerCase() !== 'authorization')
  }
}
const saveImportHeaders = () => {
  if (importHeaderDialog.kind === 'headers') {
    try {
      const headers = headerPayload(importHeaderDialog.rows)
      for (const name of Object.keys(headers)) {
        if (headers[name] !== null) continue
        const savedName = Object.keys(importHeaderDialog.savedHeaders).find(key => key.toLowerCase() === name.toLowerCase())
        if (!savedName) throw new Error('修改请求头名称后，请重新填写请求头值')
        headers[name] = importHeaderDialog.savedHeaders[savedName]
      }
      finishImportHeaders({ secrets: { headers }, authMode: importHeaderDialog.authMode })
    } catch (error) { ElMessage.warning(error.message) }
    return
  }
  const missing = importHeaderDialog.rows.find(row => !String(row.value || '').trim())
  if (missing) {
    ElMessage.warning(`请填写${missing.kindLabel}：${missing.name}`)
    return
  }
  importHeaderDialog.saving = true
  const secrets = {}
  for (const row of importHeaderDialog.rows) {
    if (!secrets[row.kind]) secrets[row.kind] = {}
    secrets[row.kind][row.name] = row.value
  }
  finishImportHeaders({ secrets, authMode: 'manual' })
  importHeaderDialog.saving = false
}
const connectCatalogMcp = card => {
  if (props.readOnly || card.connection || !card.source_id || mcpPicker.importing || connectionActionId.value !== null) return
  mcpPicker.selected = { ...card, id: card.source_id, type: card.transport_type }
  return importSelectedMcp()
}
const importSelectedMcp = async () => {
  if (props.readOnly) return
  if (!mcpPicker.selected || mcpPicker.importing) return
  mcpPicker.importing = true
  try {
    const selected = mcpPicker.selected
    const systemImport = systemMode.value
    const targetAgentId = systemImport ? undefined : agentId.value || undefined
    const inOriginalScope = () => mcpPicker.selected === selected && !props.readOnly
      && systemMode.value === systemImport
      && (systemImport || (agentId.value || undefined) === targetAgentId)
    if (systemMode.value) {
      const detail = await publicMcpsApi.getDetail(selected.id)
      if (!inOriginalScope()) return
      const secretFields = mcpSecretFields(parseMcpConfig(detail?.config), selected.type)
      const authentication = secretFields.length
        ? await requestImportHeaders(selected.name, secretFields)
        : { secrets: {}, authMode: 'manual' }
      if (authentication === null || !inOriginalScope()) return
      await assetsApi.createSystemMcpDefinition({
        source_mcp_service_id: selected.id,
        name: selected.name,
        description: selected.description || null,
        transport_type: selected.type,
        config: {},
        ...authentication.secrets,
        auth_mode: authentication.authMode,
      })
    } else {
      const ownSource = selected.picker_source !== 'public'
      const detailApi = ownSource ? mcpsApi : publicMcpsApi
      const detail = await detailApi.getDetail(selected.id)
      if (!inOriginalScope()) return
      const config = parseMcpConfig(detail?.config)
      const secretFields = mcpSecretFields(config, selected.type)
      const savedHeaders = ownSource && secretFields.some(field => field.kind === 'headers')
        ? normalizedMcpPickerConfig(config, selected.type).headers || {} : {}
      const authentication = secretFields.length
        ? await requestImportHeaders(selected.name, secretFields, savedHeaders)
        : { secrets: {}, authMode: 'manual' }
      if (authentication === null || !inOriginalScope()) return
      await assetsApi.installMcp(selected.id, targetAgentId, authentication.secrets, authentication.authMode)
    }
    ElMessage.success(`已连接 ${selected.name}`)
    await loadAll()
  } catch (error) {
    ElMessage.error(requestErrorMessage(error, '连接器连接失败'))
  } finally {
    mcpPicker.importing = false
  }
}
watch([activeView, agentId, systemMode, () => props.readOnly], () => {
  mcpPicker.selected = null
  cancelImportHeaders()
  headerDialog.open = false
  inspectionDialog.open = false
  connections.value = []
  mcpSources.value = []
  if (activeView.value === 'mcp') loadAll()
  else {
    resourceRequest++
    loading.value = false
  }
}, { immediate: true })
onBeforeUnmount(() => {
  resourceRequest++
  mcpPicker.selected = null
  cancelImportHeaders()
})
</script>

<style scoped>
.resource-center { width: min(1240px, 100%); min-width: 0; margin: 0 auto; }
.resource-center--embedded { width: 100%; }
.resource-nav { display: flex; gap: 2px; margin-top: 28px; overflow-x: auto; overflow-y: hidden; border-bottom: 1px solid #dfe2e7; scrollbar-width: none; -ms-overflow-style: none; }
.resource-nav::-webkit-scrollbar { display: none; width: 0; height: 0; }
.resource-center--embedded .resource-nav { margin-top: 0; }
.resource-nav button { position: relative; height: 44px; display: flex; flex: 0 0 auto; align-items: center; gap: 7px; padding: 0 13px; border: 0; color: #666d78; background: transparent; cursor: pointer; font: inherit; font-size: 13px; }
.resource-nav button::after { content: ''; position: absolute; right: 10px; bottom: -1px; left: 10px; height: 2px; background: transparent; }
.resource-nav button:hover, .resource-nav button.active { color: #171a20; }
.resource-nav button.active::after { background: #171a20; }
.resource-nav b { min-width: 18px; padding: 1px 4px; border-radius: 8px; color: #fff; background: #d84b4b; font-size: 10px; text-align: center; }
.resource-workspace { padding-top: 20px; }
.auth-mode-label { display: inline-flex; align-items: center; gap: 5px; color: #606772; white-space: nowrap; }
.auth-dialog-heading { display: flex; min-width: 0; align-items: center; gap: 12px; }
.auth-dialog-icon { width: 36px; height: 36px; display: inline-flex; flex: 0 0 36px; align-items: center; justify-content: center; border: 1px solid #dbe7f4; border-radius: 8px; color: #28649c; background: #eef5fb; font-size: 18px; }
.auth-dialog-heading h2 { margin: 0; color: #262a31; font-size: 17px; font-weight: 650; letter-spacing: 0; line-height: 22px; }
.auth-dialog-heading p { margin: 2px 0 0; overflow: hidden; color: #858c97; font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.auth-dialog-content { display: flex; flex-direction: column; gap: 22px; }
.auth-config-section { min-width: 0; }
.auth-inheritance-help { margin: 8px 0 0; color: #767d87; font-size: 12px; line-height: 19px; }
.auth-headers-section { padding-top: 20px; border-top: 1px solid #eceef2; }
.auth-section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.auth-section-heading h3 { margin: 0; color: #343840; font-size: 14px; font-weight: 650; letter-spacing: 0; }
.auth-section-heading > span, .auth-section-heading p { margin: 0; color: #949ba6; font-size: 12px; }
.auth-section-heading--headers { align-items: center; justify-content: flex-start; gap: 8px; margin-bottom: 0; }
.header-count { padding: 1px 6px; border-radius: 4px; color: #68717d; background: #f0f2f5; font-size: 11px; line-height: 18px; }
.auth-mode-segmented { width: 100%; }
.auth-mode-segmented :deep(.el-segmented__group) { width: 100%; }
.auth-mode-segmented :deep(.el-segmented__item) { min-width: 0; flex: 1 1 0; }
.auth-mode-summary { display: flex; align-items: flex-start; gap: 10px; margin-top: 12px; padding: 11px 12px; border-left: 3px solid #9ba4af; color: #626a75; background: #f6f7f8; }
.auth-mode-summary > .el-icon { flex: 0 0 auto; margin-top: 2px; font-size: 15px; }
.auth-mode-summary > div { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.auth-mode-summary strong { color: #3f4650; font-size: 13px; font-weight: 600; line-height: 19px; }
.auth-mode-summary span { font-size: 12px; line-height: 18px; }
.auth-mode-summary--manual { border-left-color: #4f8fc9; color: #526d86; background: #f1f6fb; }
.auth-mode-summary--manual strong { color: #2c5f8d; }
.auth-mode-summary--current_user { border-left-color: #4d8a66; color: #587161; background: #f1f7f3; }
.auth-mode-summary--current_user strong { color: #37684b; }
.auth-dialog-footer { display: flex; justify-content: flex-end; gap: 8px; }
.import-header-name { margin: 0 0 4px; overflow: hidden; color: #343840; font-size: 15px; font-weight: 650; line-height: 22px; text-overflow: ellipsis; white-space: nowrap; }
.import-header-intro { margin: 0 0 16px; color: #626a75; font-size: 13px; line-height: 20px; }
.import-header-form { display: flex; flex-direction: column; gap: 14px; }
.import-header-row { display: grid; grid-template-columns: minmax(150px, 0.8fr) minmax(0, 2fr); align-items: center; gap: 12px; }
.import-header-row label { overflow: hidden; color: #343840; font-size: 13px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; text-overflow: ellipsis; white-space: nowrap; }
.import-header-kind { display: inline-block; margin-right: 6px; color: #7b8491; font-family: inherit; font-size: 11px; }
.import-header-help { margin: 18px 0 0; padding: 10px 12px; border-left: 3px solid #7a9fc5; color: #667085; background: #f4f7fa; font-size: 12px; line-height: 19px; }
:deep(.mcp-auth-dialog) { --el-dialog-padding-primary: 20px; border-radius: 8px; }
:deep(.mcp-auth-dialog .el-dialog__header) { padding-bottom: 16px; border-bottom: 1px solid #eceef2; }
:deep(.mcp-auth-dialog .el-dialog__body) { padding-top: 20px; padding-bottom: 18px; }
:deep(.mcp-auth-dialog .el-dialog__footer) { padding-top: 14px; border-top: 1px solid #eceef2; }
:deep(.mcp-import-header-dialog) { --el-dialog-padding-primary: 20px; border-radius: 8px; }
:deep(.mcp-import-header-dialog .el-dialog__footer) { padding-top: 14px; border-top: 1px solid #eceef2; }
@media (max-width: 760px) {
  .resource-nav { margin-top: 22px; }
  .auth-dialog-content { gap: 18px; }
  .import-header-row { grid-template-columns: 1fr; gap: 6px; }
  .auth-section-heading { gap: 10px; }
  .auth-section-heading > span { display: none; }
  .auth-mode-segmented :deep(.el-segmented__item-label) { padding: 0 8px; font-size: 12px; }
  .auth-section-heading--headers { gap: 8px; }
  .auth-mode-summary { padding: 10px; }
}
</style>
