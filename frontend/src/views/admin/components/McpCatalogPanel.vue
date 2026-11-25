<template>
  <section class="connector-library">
    <div class="library-toolbar">
      <el-input v-model="query" class="workspace-search" type="search" name="connector-search" autocomplete="off" :prefix-icon="Search" clearable placeholder="搜索连接器" aria-label="搜索连接器、作者或说明" />
      <div class="view-switch" role="group" aria-label="连接器范围">
        <button v-for="option in viewOptions" :key="option.value" type="button" :class="{ active: view === option.value }" :aria-pressed="view === option.value" @click="view = option.value">{{ option.label }}</button>
      </div>
      <ResourceCenterCreateButton v-if="!readOnly" resource="mcp" />
    </div>

    <div class="library-summary">
      <div class="source-tabs" role="group" aria-label="连接器来源">
        <span class="source-label">连接器来源</span>
        <button v-for="option in sourceOptions" :key="option.value" type="button" :class="{ active: source === option.value }" :aria-pressed="source === option.value" @click="source = option.value">{{ option.label }}</button>
      </div>
    </div>

    <div v-loading="loading" class="connector-grid">
      <article v-for="card in visibleCards" :key="card.key" class="connector-card" tabindex="0" :aria-label="`连接器 ${textOrNone(card.name)}`" @click="selectedKey = card.key" @keyup.enter.self="selectedKey = card.key">
        <span v-if="card.origins.includes('mine')" class="connector-source-badge">我的</span>
        <div class="connector-card__top">
          <div class="connector-mark">
            <img v-if="card.cover" :src="card.cover" :alt="textOrNone(card.name)" />
            <el-icon v-else><Connection /></el-icon>
          </div>
          <div class="connector-card__identity">
            <h3 :title="textOrNone(card.name)">{{ textOrNone(card.name) }}</h3>
            <div class="connector-byline">
              <span class="connector-author" :title="textOrNone(card.author)">{{ textOrNone(card.author) }}</span>
              <span class="connector-separator" aria-hidden="true">·</span>
              <span class="connector-type">{{ transportLabel(card.transport_type) }}</span>
            </div>
          </div>
        </div>
        <p class="connector-description">{{ textOrNone(card.description) }}</p>
        <div v-if="card.connection" class="connector-settings" :class="{ 'is-enabled': card.connection.status === 'active' }" @click.stop @keyup.stop>
          <el-button v-if="canConfigure(card)" class="auth-config" text :icon="Key" :aria-label="card.transport_type === 'stdio' ? '环境变量' : '认证配置'" :title="card.transport_type === 'stdio' ? '编辑环境变量' : `编辑认证配置：${authModeLabel(card.connection.auth_mode)}`" :disabled="readOnly || busy" @click="$emit('configure', card.connection)">
            <span class="auth-label">{{ card.transport_type === 'stdio' ? '环境变量' : '认证配置' }}</span>
            <span v-if="card.transport_type !== 'stdio'" class="auth-mode">{{ authModeLabel(card.connection.auth_mode) }}</span>
            <el-icon class="config-arrow"><ArrowRight /></el-icon>
          </el-button>
          <label v-if="!systemMode && !card.connection.is_system" class="connection-toggle">
            <span>启用</span>
            <el-switch :model-value="card.connection.status === 'active'" :aria-label="`启用 ${textOrNone(card.name)}`" :disabled="readOnly || busy" :loading="actionId === card.connection.id && actionType === 'toggle'" @change="$emit('toggle', card.connection)" />
          </label>
        </div>
        <div class="connector-card__actions" @click.stop @keyup.stop>
          <el-button v-if="card.connection" class="inspect-action" text :icon="View" :loading="inspectionId === card.connection.id" @click="$emit('inspect', card.connection)">查看资源</el-button>
          <el-button v-else class="inspect-action" text :icon="Document" @click="selectedKey = card.key">详情</el-button>
          <el-button v-if="!card.connection" type="primary" plain :loading="connectingId === card.source_id" :disabled="readOnly || busy || loading || Boolean(error)" @click="$emit('connect', card)">连接</el-button>
          <el-button v-else-if="canDisconnect(card)" type="danger" plain :loading="actionId === card.connection.id && actionType === 'disconnect'" :disabled="readOnly || busy" @click="$emit('disconnect', card.connection)">取消连接</el-button>
          <span v-else class="managed-note">系统默认</span>
        </div>
      </article>
      <el-empty v-if="!loading && !error && !filteredCards.length" class="empty-state" :description="query ? '没有匹配的连接器' : '没有符合条件的连接器'" />
    </div>
    <div v-if="error" class="library-status" role="alert">
      <span>{{ error }}</span><el-button link type="primary" @click="$emit('refresh')">重试</el-button>
    </div>
    <div v-else-if="visibleCards.length < filteredCards.length" class="library-status">
      <el-button text @click="visibleCount += pageSize">加载更多</el-button>
    </div>

    <el-dialog :model-value="Boolean(selectedCard)" class="connector-info-dialog" title="连接器详情" width="min(760px, calc(100vw - 32px))" destroy-on-close @update:model-value="value => { if (!value) selectedKey = null }">
      <div v-if="selectedCard" class="connector-detail">
        <span v-if="selectedCard.origins.includes('mine')" class="connector-source-badge">我的</span>
        <div class="connector-card__top">
          <div class="connector-mark">
            <img v-if="selectedCard.cover" :src="selectedCard.cover" :alt="textOrNone(selectedCard.name)" />
            <el-icon v-else><Connection /></el-icon>
          </div>
          <div class="connector-card__identity">
            <h2>{{ textOrNone(selectedCard.name) }}</h2>
            <div class="connector-byline">
              <span class="connector-author" :title="textOrNone(selectedCard.author)">{{ textOrNone(selectedCard.author) }}</span>
              <span class="connector-separator" aria-hidden="true">·</span>
              <span class="connector-type">{{ transportLabel(selectedCard.transport_type) }}</span>
            </div>
          </div>
        </div>
        <p class="detail-description">{{ textOrNone(selectedCard.description) }}</p>
        <div v-if="selectedCard.connection" class="connector-settings" :class="{ 'is-enabled': selectedCard.connection.status === 'active' }">
          <el-button v-if="canConfigure(selectedCard)" class="auth-config" text :icon="Key" :aria-label="selectedCard.transport_type === 'stdio' ? '环境变量' : '认证配置'" :title="selectedCard.transport_type === 'stdio' ? '编辑环境变量' : `编辑认证配置：${authModeLabel(selectedCard.connection.auth_mode)}`" :disabled="readOnly || busy" @click="$emit('configure', selectedCard.connection)">
            <span class="auth-label">{{ selectedCard.transport_type === 'stdio' ? '环境变量' : '认证配置' }}</span>
            <span v-if="selectedCard.transport_type !== 'stdio'" class="auth-mode">{{ authModeLabel(selectedCard.connection.auth_mode) }}</span>
            <el-icon class="config-arrow"><ArrowRight /></el-icon>
          </el-button>
          <label v-if="!systemMode && !selectedCard.connection.is_system" class="connection-toggle">
            <span>启用</span>
            <el-switch :model-value="selectedCard.connection.status === 'active'" :aria-label="`启用 ${textOrNone(selectedCard.name)}`" :disabled="readOnly || busy" :loading="actionId === selectedCard.connection.id && actionType === 'toggle'" @change="$emit('toggle', selectedCard.connection)" />
          </label>
        </div>
        <div class="connector-card__actions">
          <el-button v-if="selectedCard.connection" class="inspect-action" text :icon="View" :loading="inspectionId === selectedCard.connection.id" @click="$emit('inspect', selectedCard.connection)">查看资源</el-button>
          <el-button v-if="!selectedCard.connection" type="primary" plain :loading="connectingId === selectedCard.source_id" :disabled="readOnly || busy || loading || Boolean(error)" @click="$emit('connect', selectedCard)">连接</el-button>
          <el-button v-else-if="canDisconnect(selectedCard)" type="danger" plain :loading="actionId === selectedCard.connection.id && actionType === 'disconnect'" :disabled="readOnly || busy" @click="$emit('disconnect', selectedCard.connection)">取消连接</el-button>
          <span v-else class="managed-note">系统默认</span>
        </div>
      </div>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowRight, Connection, Document, Key, Search, View } from '@element-plus/icons-vue'
import ResourceCenterCreateButton from './ResourceCenterCreateButton.vue'
import { buildMcpCatalog, filterMcpCatalog } from '@/utils/mcp-catalog'
import '@/assets/styles/workspace-search.css'

const props = defineProps({
  sources: { type: Array, default: () => [] },
  connections: { type: Array, default: () => [] },
  readOnly: { type: Boolean, default: false },
  systemMode: { type: Boolean, default: false },
  agentId: { type: [Number, String], default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  connectingId: { type: Number, default: null },
  actionId: { type: [Number, String], default: null },
  actionType: { type: String, default: '' },
  inspectionId: { type: [Number, String], default: null },
})
defineEmits(['connect', 'disconnect', 'configure', 'inspect', 'toggle', 'refresh'])
const query = ref('')
const view = ref('all')
const source = ref('all')
const selectedKey = ref(null)
const pageSize = 18
const visibleCount = ref(pageSize)
const viewOptions = [{ label: '全部', value: 'all' }, { label: '已连接', value: 'connected' }]
const sourceOptions = computed(() => [
  { label: '全部', value: 'all' },
  ...(!props.systemMode ? [{ label: '我的', value: 'mine' }] : []),
  { label: '公开', value: 'public' },
  ...(!props.systemMode && !props.agentId ? [{ label: '系统默认', value: 'system_default' }] : []),
])
const cards = computed(() => buildMcpCatalog(props.sources, props.connections))
const filteredCards = computed(() => filterMcpCatalog(cards.value, { view: view.value, source: source.value, query: query.value }))
const visibleCards = computed(() => filteredCards.value.slice(0, visibleCount.value))
const selectedCard = computed(() => cards.value.find(card => card.key === selectedKey.value))
const busy = computed(() => props.connectingId !== null || props.actionId !== null)
const textOrNone = value => String(value ?? '').trim() || '无'
const transportLabel = value => ({ stdio: 'stdio', sse: 'SSE', streamable_http: 'Streamable HTTP', 'streamable-http': 'Streamable HTTP', http: 'HTTP', json: 'JSON' })[value] || textOrNone(value)
const authModeLabel = value => ({ none: '不发送认证', manual: '手动请求头', current_user: '当前登录身份' })[value] || '手动请求头'
const canDisconnect = card => props.systemMode || !card.connection.is_system
const canConfigure = card => ['http', 'sse', 'streamable_http', 'streamable-http'].includes(card.transport_type) || (!props.systemMode && card.transport_type === 'stdio')
watch([query, view, source], () => { visibleCount.value = pageSize })
watch(() => [props.agentId, props.systemMode, props.readOnly], () => {
  query.value = ''
  view.value = 'all'
  source.value = 'all'
  selectedKey.value = null
  visibleCount.value = pageSize
})
</script>

<style scoped>
.workspace-search.el-input { --el-input-text-color: #303133; --el-input-placeholder-color: #303133; }
.connector-library { min-width: 0; }
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
.connector-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; align-items: stretch; align-content: start; }
.connector-card { position: relative; display: flex; min-width: 0; flex-direction: column; padding: 18px; border: 1px solid #e4e8ee; border-radius: 12px; background: #fff; cursor: pointer; box-sizing: border-box; transition: border-color .15s, box-shadow .15s; }
.connector-card:hover { border-color: #c5d6e8; box-shadow: 0 4px 16px #1834520a; }
.connector-card:focus-visible { outline: 2px solid #83b3e4; outline-offset: 2px; }
.connector-source-badge { position: absolute; top: 12px; right: 12px; padding: 1px 7px; border-radius: 5px; color: #285886; background: #eaf2fa; font-size: 11px; line-height: 18px; }
.connector-source-badge + .connector-card__top h3 { padding-right: 40px; }
.connector-card__top { display: flex; min-width: 0; align-items: center; gap: 12px; }
.connector-mark { width: 40px; height: 40px; display: grid; flex: 0 0 40px; place-items: center; overflow: hidden; border-radius: 10px; color: #4c7198; background: #f0f5fb; font-size: 19px; }
.connector-mark img { width: 100%; height: 100%; object-fit: cover; }
.connector-card__identity { min-width: 0; flex: 1; }
.connector-card h3 { display: -webkit-box; margin: 0; overflow: hidden; color: #24272d; font-size: 14px; line-height: 21px; font-weight: 650; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.connector-byline { display: flex; align-items: center; gap: 6px; min-width: 0; margin-top: 4px; color: #737d8b; font-size: 12px; }
.connector-author { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.connector-separator { flex-shrink: 0; }
.connector-type { flex-shrink: 0; white-space: nowrap; }
.connector-description { display: -webkit-box; flex: 0 0 42px; height: 42px; margin: 16px 0; overflow: hidden; color: #303133; font-size: 13px; line-height: 21px; white-space: pre-line; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.connector-settings { display: flex; align-items: center; gap: 12px; min-height: 38px; padding: 6px 10px 6px 12px; border: 1px solid #e4eaf2; border-radius: 9px; background: #f8fafc; color: #596678; box-sizing: border-box; transition: border-color .15s, background .15s, color .15s; }
.connector-settings.is-enabled { border-color: #b9d8f5; background: #f1f7fd; color: #285b8d; }
.connector-settings .auth-config { flex: 1; min-width: 0; max-width: 100%; height: 32px; margin: 0; padding: 0; border: 0; border-radius: 4px; color: inherit; background: transparent; font-size: 12px; font-weight: 400; transition: color .15s; }
.connector-settings .auth-config:not(.is-disabled):hover { color: #409eff; background: transparent; }
.connector-settings .auth-config:focus-visible { outline: 2px solid #83b3e4; outline-offset: 2px; }
.auth-config :deep(> span) { flex: 1; min-width: 0; gap: 6px; }
.auth-label { flex-shrink: 0; }
.auth-mode { min-width: 0; overflow: hidden; padding: 1px 5px; border: 1px solid #e4eaf2; border-radius: 4px; color: #8a96a5; background: #fff; font-size: 11px; line-height: 16px; text-overflow: ellipsis; }
.connector-settings.is-enabled .auth-mode { border-color: #d7e7f7; color: #4d83b5; }
.config-arrow { flex-shrink: 0; margin-left: auto; color: #8a96a5; font-size: 11px; transition: color .15s; }
.auth-config:not(.is-disabled):hover .config-arrow { color: #409eff; }
.connection-toggle { display: inline-flex; flex-shrink: 0; align-items: center; gap: 6px; margin-left: auto; padding-left: 10px; border-left: 1px solid #e4eaf2; color: inherit; font-size: 12px; cursor: pointer; }
.connector-settings.is-enabled .connection-toggle { border-left-color: #d7e7f7; }
.connection-toggle :deep(.el-switch) { --el-switch-on-color: #409eff; --el-switch-off-color: #c5ced9; transform: scale(.9); transform-origin: right center; }
.connector-card__actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 6px; margin-top: auto; }
.connector-card > .connector-settings + .connector-card__actions { padding-top: 16px; }
.connector-card__actions :deep(.el-button) { margin-left: 0; padding-right: 12px; padding-left: 12px; }
.connector-card__actions .inspect-action { margin-right: auto; padding-left: 0; color: #737d8b; }
.managed-note { color: #737d8b; font-size: 13px; line-height: 32px; }
.empty-state { grid-column: 1 / -1; }
.library-status { display: flex; align-items: center; justify-content: center; gap: 10px; min-height: 48px; margin-top: 16px; color: #737d8b; font-size: 13px; }
.connector-info-dialog :deep(.el-dialog__body) { padding-top: 4px; }
.connector-detail { position: relative; display: flex; flex-direction: column; gap: 20px; padding: 4px 2px 2px; }
.connector-detail .connector-source-badge { top: 4px; right: 2px; }
.connector-detail .connector-source-badge + .connector-card__top h2 { padding-right: 48px; }
.connector-detail .connector-card__top { align-items: flex-start; gap: 14px; }
.connector-detail .connector-mark { width: 48px; height: 48px; flex-basis: 48px; }
.connector-detail h2 { margin: 0; color: #24272d; font-size: 18px; overflow-wrap: anywhere; }
.connector-detail .connector-byline { flex-wrap: wrap; }
.connector-detail .connector-author { overflow: visible; white-space: pre-wrap; overflow-wrap: anywhere; }
.detail-description { margin: 6px 0 0; color: #303133; font-size: 13px; line-height: 21px; white-space: pre-wrap; overflow-wrap: anywhere; }
.connector-detail .connector-card__actions { margin-top: 0; padding-top: 0; }
@media (max-width: 1100px) { .connector-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) {
  .library-toolbar { align-items: stretch; }
  .library-summary { margin-top: 18px; }
  .source-tabs { width: 100%; }
  .connector-grid { grid-template-columns: 1fr; }
}
</style>
