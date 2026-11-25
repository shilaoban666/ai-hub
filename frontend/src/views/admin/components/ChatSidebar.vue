<template>
  <!-- 左侧边栏：会话搜索与历史 -->
  <div class="chat-sidebar" :class="{ 'chat-sidebar--compact-history': compactHistory }">
    <div class="sidebar-heading">
      <span v-if="compactHistory">最近对话</span>
      <span v-else>历史对话<span v-if="embedded || (integrated && sessionsTotal > 0)" title="对话总数">（{{ sessionsTotal }}）</span></span>
      <el-button v-if="!integrated && !embedded" :icon="Plus" size="small" text @click="$emit('new-session')">
        新对话
      </el-button>
    </div>

    <!-- 搜索 -->
    <div v-if="!compactHistory" class="search-box">
      <el-input
        v-model="sessionSearch"
        size="small"
        placeholder="搜索对话..."
        aria-label="搜索对话"
        clearable
        :prefix-icon="Search"
      />
    </div>

    <!-- 会话列表 -->
    <div
      ref="sessionList"
      class="session-list"
      :aria-busy="sessionsLoading"
      @scroll.passive="handleSessionScroll"
    >
      <section v-for="group in groupedSessions" :key="group.key" class="session-group">
        <h3 v-if="!compactHistory">{{ group.label }}</h3>
        <div
          v-for="s in group.items"
          :key="s.id"
          class="session-item"
          :class="sessionClass(s)"
          @click="$emit('select-session', s.id)"
        >
          <div class="session-top">
            <button v-if="compactHistory" type="button" class="session-title session-open"
              :aria-current="isSameSessionId(currentSessionId, s.id) ? 'true' : undefined"
              :title="`${getSessionTitle(s)} · ${s.message_count ?? 0} 条消息`"
              @click.stop="$emit('select-session', s.id)">{{ getSessionTitle(s) }}</button>
            <span v-else class="session-title">{{ getSessionTitle(s) }}</span>
            <el-icon v-if="isStreamingSession(s)" class="session-running" title="响应中">
              <Loading />
            </el-icon>
            <el-icon v-if="isChannelSession(s)" class="session-readonly" title="只读会话">
              <Lock />
            </el-icon>
            <div class="session-end">
              <span v-if="compactHistory" class="session-time">
                {{ formatCompactTime(s.last_message_at || s.created_at) }}
              </span>
              <el-button
                v-if="!isChannelSession(s)"
                class="session-delete"
                :icon="Delete"
                link
                size="small"
                aria-label="删除对话"
                @click.stop="$emit('delete-session', s.id)"
              />
            </div>
          </div>
          <div v-if="!compactHistory" class="session-meta">
            <div class="session-meta-left">
              <span>{{ s.message_count || 0 }} 条消息</span>
              <span v-if="isChannelSession(s)" class="session-source">
                <el-icon><Connection /></el-icon>
                {{ getChannelMeta(s)?.displayName }}
              </span>
            </div>
            <span v-if="s.last_message_at" class="session-time">
              {{ formatTime(s.last_message_at) }}
            </span>
          </div>
        </div>
      </section>
      <div v-if="sessionsLoading" class="session-skeleton" role="status" aria-label="正在加载历史对话">
        <div v-if="sessions.length === 0" class="session-skeleton-group" aria-hidden="true"></div>
        <div v-for="index in (sessions.length === 0 ? 6 : 2)" :key="index" class="session-skeleton-item" aria-hidden="true">
          <div class="session-skeleton-title"></div>
          <div class="session-skeleton-meta">
            <span></span>
            <span></span>
          </div>
        </div>
      </div>
      <div v-if="!sessionsLoading && filteredSessions.length === 0" class="session-empty">
        {{ sessionSearch ? '无匹配对话' : '暂无对话' }}
      </div>
      <div
        v-if="!sessionsLoading && sessionsHasMore && listScrollable"
        class="session-load-state"
      >继续下拉加载</div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import {
  Delete, Search, Loading, Connection, Lock, Plus,
} from '@element-plus/icons-vue'
import { formatBeijingDate, getBeijingDateTimeParts, parseBackendDateTime } from '@/utils/date-time'

const props = defineProps({
  integrated: { type: Boolean, default: false },
  compactHistory: { type: Boolean, default: false },
  embedded: { type: Boolean, default: false },
  agent: { type: Object, default: null },
  agentId: { type: Number, default: 0 },
  sessions: { type: Array, default: () => [] },
  sessionsTotal: { type: Number, default: 0 },
  currentSessionId: { type: Number, default: null },
  streamingSessionId: { type: [Number, String], default: null },
  streamingSessionIds: { type: Array, default: () => [] },
  sessionsLoading: { type: Boolean, default: false },
  sessionsHasMore: { type: Boolean, default: false },
})

const emit = defineEmits([
  'new-session', 'select-session', 'delete-session', 'load-more-sessions',
])

const sessionSearch = ref('')
const sessionList = ref(null)
const listScrollable = ref(false)
let listResizeObserver
let autoLoadKey = null

const checkScrollable = () => {
  const el = sessionList.value
  if (!el || el.clientHeight === 0) return
  // Include the native scrollbar gutter in the right inset, so both text edges stay symmetric.
  el.style.setProperty('--session-scrollbar-width', `${el.offsetWidth - el.clientWidth}px`)
  listScrollable.value = el.scrollHeight > el.clientHeight + 1
  if (listScrollable.value || props.sessionsLoading || !props.sessionsHasMore || sessionSearch.value) return
  // Only retry automatically after the list makes progress, not after a failed/empty page.
  const key = `${props.agentId}:${props.sessions.length}`
  if (autoLoadKey === key) return
  autoLoadKey = key
  emit('load-more-sessions')
}

watch([() => props.sessions, () => props.sessions.length, () => props.sessionsLoading, () => props.sessionsHasMore, sessionSearch], checkScrollable, { flush: 'post' })
onMounted(() => {
  listResizeObserver = new ResizeObserver(checkScrollable)
  if (sessionList.value) listResizeObserver.observe(sessionList.value)
  checkScrollable()
})
onBeforeUnmount(() => listResizeObserver?.disconnect())

const filteredSessions = computed(() => {
  if (!sessionSearch.value) return props.sessions
  const q = sessionSearch.value.toLowerCase()
  return props.sessions.filter(s =>
    getSessionTitle(s).toLowerCase().includes(q)
  )
})

const groupedSessions = computed(() => {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const recent = new Date(today)
  recent.setDate(today.getDate() - 7)
  const groups = [
    { key: 'today', label: '今天', items: [] },
    { key: 'yesterday', label: '昨天', items: [] },
    { key: 'recent', label: '最近 7 天', items: [] },
    { key: 'earlier', label: '更早', items: [] },
  ]
  filteredSessions.value.forEach(session => {
    const date = parseBackendDateTime(session.last_message_at || session.created_at)
    const group = !date || date < recent
      ? groups[3]
      : date < yesterday
        ? groups[2]
        : date < today
          ? groups[1]
          : groups[0]
    group.items.push(session)
  })
  return groups.filter(group => group.items.length)
})

const isSameSessionId = (a, b) => {
  if (a === null || a === undefined || b === null || b === undefined) return false
  return String(a) === String(b)
}

const isStreamingSession = (session) => (
  !!session?.active_run_id || isSameSessionId(session?.id, props.streamingSessionId)
  || props.streamingSessionIds.some(sessionId => isSameSessionId(session?.id, sessionId))
)

const getChannelMeta = () => null
const isChannelSession = () => false

const sessionClass = session => {
  const channel = getChannelMeta(session)
  return {
    active: isSameSessionId(props.currentSessionId, session.id),
    'channel-session': !!channel,
    [`${channel?.slug}-session`]: !!channel,
  }
}

const getSessionTitle = session => (
  getChannelMeta(session)?.displayName || session?.title || '新对话'
)

const formatTime = (ts) => {
  const d = parseBackendDateTime(ts)
  if (!d) return ''
  const now = new Date()
  const diff = Math.max(0, now - d)
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前'
  return formatBeijingDate(d, { fallback: '' })
}

const formatCompactTime = value => {
  const date = getBeijingDateTimeParts(value)
  if (!date) return '无'
  const today = getBeijingDateTimeParts(new Date())
  if (date.year !== today.year) return `${date.year}-${date.month}-${date.day}`
  if (date.month === today.month && date.day === today.day) return `${date.hour}:${date.minute}`
  return `${Number(date.month)}月${Number(date.day)}日`
}

const handleSessionScroll = (event) => {
  const el = event.target
  if (!el) return
  listScrollable.value = el.scrollHeight > el.clientHeight + 1
  if (!props.sessionsHasMore || props.sessionsLoading) return
  if (!listScrollable.value) return
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 48) {
    emit('load-more-sessions')
  }
}
</script>

<style scoped>
.chat-sidebar {
  width: 264px;
  background: var(--workspace-panel-bg, #fafafa);
  border-right: 1px solid var(--workspace-border, #eceef1);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.sidebar-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 46px;
  padding: 0 12px 0 16px;
  color: #33373d;
  font-weight: 400;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
}
.sidebar-heading :deep(.el-button) {
  height: 30px;
  padding: 0 9px;
  border-radius: 6px;
  color: #555b62;
  font-weight: 500;
}
.sidebar-heading :deep(.el-button:hover) { color: #202329; background: var(--workspace-hover-bg, #f1f2f4); }

.search-box {
  padding: 0 9px 10px;
}
.search-box :deep(.el-input__wrapper) {
  min-height: 32px;
  border-radius: 6px;
  background: var(--workspace-control-bg, #ededef);
  box-shadow: none;
}
.search-box :deep(.el-input__wrapper:hover),
.search-box :deep(.el-input__wrapper.is-focus) { background: #fff; box-shadow: 0 0 0 1px #d7d9d7 inset; }

.session-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  scrollbar-width: thin;
  scrollbar-color: transparent transparent;
}
.session-group { margin: 0 0 10px; }
.session-group h3 { margin: 0; padding: 7px 16px 4px; color: #9a9fa7; font-size: calc(10px + var(--workspace-font-size-offset, 0px)); font-weight: 600; }
.session-list:hover {
  scrollbar-color: #c1c1c1 transparent;
}
.session-list::-webkit-scrollbar { width: 4px; }
.session-list::-webkit-scrollbar-track { background: transparent; }
.session-list::-webkit-scrollbar-thumb { background: transparent; border-radius: 3px; }
.session-list:hover::-webkit-scrollbar-thumb { background: #c1c1c1; }
.session-list::-webkit-scrollbar-thumb:hover { background: #a8a8a8; }

.session-item {
  margin: 1px 7px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.session-item:hover { background: var(--workspace-hover-bg, #f1f2f4); }
.session-item.active {
  background: var(--workspace-active-bg, #e7e8eb);
  border-left: 0;
  font-weight: 500;
}
.session-item.weixin-session { border-left-color: #67c23a; }
.session-item.weixin-session.active {
  background: #f0f9eb;
  border-left-color: #67c23a;
}
.session-item.dingtalk-session { border-left-color: #1677ff; }
.session-item.dingtalk-session.active {
  background: #ecf5ff;
  border-left-color: #1677ff;
}

.session-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.session-end { display: flex; flex-shrink: 0; align-items: center; }
.session-title {
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  color: #353940;
  line-height: 20px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.session-running {
  flex-shrink: 0;
  margin-left: 6px;
  color: #409eff;
  animation: session-spin 1s linear infinite;
}
.session-readonly {
  flex-shrink: 0;
  margin-left: 6px;
  color: #909399;
}
.weixin-session .session-readonly { color: #67c23a; }
.dingtalk-session .session-readonly { color: #1677ff; }
.session-delete {
  width: 22px;
  height: 22px;
  margin-left: 3px;
  padding: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
.session-item:hover .session-delete { opacity: 1; }

@keyframes session-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.session-meta {
  display: flex;
  justify-content: space-between;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  color: #9a9ea4;
  margin-top: 2px;
}
.session-meta-left {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}
.session-source {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: #606266;
  white-space: nowrap;
}
.weixin-session .session-source { color: #529b2e; }
.dingtalk-session .session-source { color: #1677ff; }
.session-time { flex-shrink: 0; }
.session-empty {
  text-align: center;
  color: #c0c4cc;
  padding: 20px;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
}
.session-load-state {
  text-align: center;
  color: #c0c4cc;
  padding: 10px 12px;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
}

.session-skeleton { padding: 0 17px 10px; animation: session-skeleton-pulse 1.8s ease-in-out infinite; }
.session-skeleton-group { width: 30px; height: 8px; margin: 9px 0 6px; border-radius: 3px; background: #e5e7eb; }
.session-skeleton-item { padding: 12px 0; }
.session-skeleton-title { width: 84%; height: 12px; border-radius: 3px; background: #e5e7eb; }
.session-skeleton-item:nth-child(3n) .session-skeleton-title { width: 66%; }
.session-skeleton-item:nth-child(3n + 1) .session-skeleton-title { width: 74%; }
.session-skeleton-meta { display: flex; justify-content: space-between; margin-top: 10px; }
.session-skeleton-meta span { width: 44px; height: 8px; border-radius: 3px; background: #eceef1; }
.session-skeleton-meta span:last-child { width: 36px; }
@keyframes session-skeleton-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .5; }
}
@media (prefers-reduced-motion: reduce) {
  .session-skeleton { animation: none; }
}

@media (max-width: 900px) {
  .chat-sidebar {
    position: fixed;
    top: 102px;
    bottom: 0;
    left: 0;
    width: min(84vw, 320px);
    height: auto;
    z-index: 1200;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    box-shadow: 4px 0 14px rgba(0, 0, 0, 0.16);
  }

  .chat-sidebar.mobile-open {
    transform: translateX(0);
  }

  .session-delete {
    opacity: 1;
  }
}

.chat-sidebar.chat-sidebar--integrated {
  position: static;
  width: 100%;
  height: 100%;
  border-right: 0;
  transform: none;
  box-shadow: none;
}

.chat-sidebar--compact-history .sidebar-heading {
  min-height: 28px;
  padding: 0 28px;
  color: var(--workspace-muted);
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
}
.chat-sidebar--compact-history .search-box { padding: 0 0 5px; }
.chat-sidebar--compact-history .search-box :deep(.el-input__wrapper) {
  min-height: 30px;
  padding: 0 10px;
  border-radius: 7px;
  background: var(--workspace-hover-bg);
}
.chat-sidebar--compact-history .search-box :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  box-shadow: 0 0 0 1px var(--workspace-focus) inset;
}
.chat-sidebar--compact-history .search-box :deep(.el-input__inner::placeholder) { color: var(--workspace-muted); }
.chat-sidebar--compact-history .session-list {
  box-sizing: border-box;
  scrollbar-gutter: stable;
  padding-left: 16px;
  padding-right: max(0px, calc(16px - var(--session-scrollbar-width, 0px)));
}
.chat-sidebar--compact-history .session-group { margin-bottom: 0; }
.chat-sidebar--compact-history .session-item { margin: 2px 0; padding: 0 12px; border-radius: 8px; }
.chat-sidebar--compact-history .session-item.active { background: var(--workspace-active-bg); }
.chat-sidebar--compact-history .session-top { min-height: var(--workspace-row-height, 32px); gap: 8px; }
.chat-sidebar--compact-history .session-open {
  align-self: stretch;
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 4px;
  color: var(--workspace-ink, #181818);
  background: none;
  font: inherit;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  font-weight: inherit;
  text-align: left;
  cursor: pointer;
}
.chat-sidebar--compact-history .session-open:focus-visible { outline: 2px solid var(--workspace-focus); outline-offset: -2px; }
.chat-sidebar--compact-history .session-item:is(:hover, .active) .session-open { color: var(--workspace-strong, #000); }
.chat-sidebar--compact-history .session-item.active .session-open { font-weight: 500; }
.chat-sidebar--compact-history .session-top > .el-icon { margin-left: 0; color: var(--workspace-muted); }
.chat-sidebar--compact-history .session-time { color: var(--workspace-subtle, #999); font-size: calc(11px + var(--workspace-font-size-offset, 0px)); }
.chat-sidebar--compact-history .session-empty,
.chat-sidebar--compact-history .session-load-state { color: var(--workspace-muted); }
.chat-sidebar--compact-history .session-skeleton-item { padding: calc((var(--workspace-row-height, 32px) - 12px) / 2) 0; }
.chat-sidebar--compact-history .session-skeleton-meta { display: none; }
@media (min-width: 901px) and (hover: hover) and (pointer: fine) {
  .chat-sidebar--compact-history .session-end { display: grid; justify-items: end; }
  .chat-sidebar--compact-history .session-end > * { grid-area: 1 / 1; }
  .chat-sidebar--compact-history .session-item:not(.channel-session):is(:hover, :focus-within) .session-time { visibility: hidden; }
}
.chat-sidebar--compact-history .session-item:focus-within .session-delete { opacity: 1; }
@media (max-width: 900px), (hover: none), (pointer: coarse) {
  .chat-sidebar--compact-history .session-top { min-height: var(--workspace-row-height, 42px); }
  .chat-sidebar--compact-history .session-delete { opacity: 1; }
}
</style>
