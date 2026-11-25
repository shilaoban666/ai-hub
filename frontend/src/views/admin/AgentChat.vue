<template>
  <div
    class="agent-chat-page"
    :class="{
      'workspace-open': workspaceOpen,
      'workspace-expanded': workspaceOpen && workspaceExpanded,
      'agent-chat--embedded': embedded,
      'agent-chat--expert': !personalChat && !embedded,
    }"
  >
    <template v-if="isValidId">
    <div class="agent-chat-body">
    <div
      class="agent-chat-sidebar"
      :class="{ 'agent-chat-sidebar--plain': personalChat || embedded || expertWorkspace || workbenchChat }"
    >
      <AgentWorkspaceNav v-if="!personalChat && !embedded && !expertWorkspace && !workbenchChat" :agent="agent" :agent-id="agentId" active="chat" @new-session="handleSidebarNewSession" />
      <div class="agent-history-sidebar">
        <Teleport :to="workspaceSidebar?.historyTarget || '#workspace-history'" :disabled="!workspaceSidebar?.enabled.value" defer>
          <ChatSidebar
            :class="{ 'mobile-open': mobileSidebarOpen, 'chat-sidebar--integrated': workspaceSidebar?.enabled.value }"
            :integrated="!!workspaceSidebar?.enabled.value || (!personalChat && !embedded)"
            :compact-history="workbenchChat"
            :embedded="embedded"
            :agent="agent"
            :agent-id="agentId"
            :sessions="sessions"
            :sessions-total="sessionsTotal"
            :current-session-id="currentSessionId"
            :streaming-session-id="streamingSessionId"
            :streaming-session-ids="streamingSessionIds"
            :sessions-loading="sessionsLoading"
            :sessions-has-more="sessionsHasMore"
            @new-session="handleSidebarNewSession"
            @select-session="handleSidebarSelectSession"
            @delete-session="handleDeleteSession"
            @load-more-sessions="handleLoadMoreSessions"
          />
        </Teleport>
      </div>
    </div>
    <div
      v-if="mobileSidebarOpen && !workspaceSidebar?.enabled.value"
      class="mobile-sidebar-backdrop"
      aria-hidden="true"
      @click="mobileSidebarOpen = false"
    />

    <!-- 中间对话区 -->
    <div
      class="chat-center"
      :class="{
        'channel-readonly': currentSessionReadOnly,
        'dingtalk-readonly': currentSessionChannel?.slug === 'dingtalk',
      }"
    >
      <AgentWorkspaceHeader :show-identity="false"
        v-if="!embedded"
        :agent="agent"
        :agent-id="agentId"
        :runtime-type="currentRuntimeType"
        :personal-chat="personalChat"
        active="chat"
        :show-tabs="false"
      >
        <template #actions>
          <el-tooltip
            v-if="(personalChat || workbenchChat) && credit"
            :content="credit.claimed_today
              ? `${credit.display_name}余额 ${formatCreditPoints(credit.available_balance)}`
              : `${credit.display_name}余额 ${formatCreditPoints(credit.available_balance)}，点击领取今日${credit.display_name}`"
            placement="bottom"
          >
            <span class="header-tool-wrap">
              <el-button
                :icon="Coin"
                circle
                text
                class="header-tool-button"
                :loading="creditClaiming"
                :aria-label="credit.claimed_today ? `查看${credit.display_name}余额` : `领取今日${credit.display_name}`"
                @click="claimCredits"
              />
              <span v-if="!credit.claimed_today" class="header-tool-dot" aria-hidden="true" />
            </span>
          </el-tooltip>
          <el-tooltip
            :content="shareToken ? '已分享，点击查看分享设置' : '分享当前对话'"
            placement="bottom"
          >
            <span class="header-tool-wrap">
              <el-button
                :icon="Share"
                circle
                text
                class="header-tool-button"
                :class="{ 'is-active': !!shareToken }"
                :loading="shareLoading || shareStatusLoading"
                :disabled="!currentSessionId || visibleStreaming || historyMessagesLoading"
                :aria-label="shareToken ? '查看分享设置' : '分享当前对话'"
                :aria-pressed="!!shareToken"
                @click="handleShareConversation"
              />
            </span>
          </el-tooltip>
          <el-tooltip content="工作区文件" placement="bottom">
            <el-button
              :icon="workspaceOpen ? FolderOpened : Folder"
              circle
              text
              class="header-tool-button"
              :class="{ 'is-active': workspaceOpen }"
              aria-label="工作区文件"
              :aria-pressed="workspaceOpen"
              @click="workspaceOpen = !workspaceOpen"
            />
          </el-tooltip>
        </template>
      </AgentWorkspaceHeader>
      <div v-if="!workspaceSidebar?.enabled.value" class="mobile-chat-toolbar">
        <el-button
          :icon="Menu"
          circle
          text
          aria-label="打开会话列表"
          @click="openMobileSidebar"
        />
        <el-tooltip v-if="embedded" content="新对话" placement="bottom">
          <el-button :icon="Plus" circle text aria-label="新对话" @click="handleSidebarNewSession" />
        </el-tooltip>
        <span class="mobile-chat-title">{{ mobileChatTitle }}</span>
        <div v-if="embedded" class="embed-chat-actions">
          <el-tooltip v-if="(personalChat || workbenchChat) && credit" :content="`${credit.display_name}余额 ${formatCreditPoints(credit.available_balance)}`" placement="bottom">
            <span class="header-tool-wrap">
              <el-button :icon="Coin" circle text class="header-tool-button" :loading="creditClaiming" :aria-label="credit.claimed_today ? `查看${credit.display_name}余额` : `领取今日${credit.display_name}`" @click="claimCredits" />
              <span v-if="!credit.claimed_today" class="header-tool-dot" aria-hidden="true" />
            </span>
          </el-tooltip>
          <el-tooltip content="工作区文件" placement="bottom">
            <el-button :icon="workspaceOpen ? FolderOpened : Folder" circle text class="header-tool-button" :class="{ 'is-active': workspaceOpen }" aria-label="工作区文件" :aria-pressed="workspaceOpen" @click="workspaceOpen = !workspaceOpen" />
          </el-tooltip>
          <el-tooltip :content="shareToken ? '已分享，点击查看分享设置' : '分享当前对话'" placement="bottom">
            <span class="header-tool-wrap">
              <el-button :icon="Share" circle text class="header-tool-button" :class="{ 'is-active': !!shareToken }" :loading="shareLoading || shareStatusLoading" :disabled="!currentSessionId || visibleStreaming || historyMessagesLoading" :aria-label="shareToken ? '查看分享设置' : '分享当前对话'" :aria-pressed="!!shareToken" @click="handleShareConversation" />
            </span>
          </el-tooltip>
        </div>
        <el-button
          v-if="canConfigureChannels"
          :icon="Connection"
          circle
          text
          aria-label="渠道设置"
          @click="router.push('/workspace/assistant/channels')"
        />
      </div>
      <ChatMain
        ref="chatMainRef"
        v-model:input-text="inputText"
        :display-messages="displayMessages"
        :agent-id="agentId"
        :history-loading="historyMessagesLoading"
        :history-has-more="historyMessagesHasMore"
        :older-history-loading="olderMessagesLoading"
        :current-blocks="visibleCurrentBlocks"
        :streaming="visibleStreaming"
        :send-locked="historyMessagesLoading || historyMessagesLoadFailed || currentSessionReadOnly"
        :pending-permissions="visiblePermissionQueue"
        :permission-submitting-ids="permissionSubmittingIds"
        :runtime-type="currentRuntimeType"
        :run-status="visibleRunStatus"
        :run-started-at="activeStreamState?.startedAt"
        :run-charged-points="activeStreamState?.chargedPoints"
        :run-token-count="visibleRunTokenCount"
        :run-failure="visibleRunFailure"
        :context-notice="visibleContextNotice"
        :agent-models="agentModels"
        :models-loading="modelsLoading"
        :allow-custom-models="personalChat"
        :selected-model-id="selectedModelId"
        :agent-skills="agentSkills"
        :agent-skills-loading="agentSkillsLoading"
        :show-default-suggestions="personalChat && personalSkillsLoaded"
        :suggestion-key="sessionViewKey"
        :selected-skill-id="selectedSkillId"
        :usable-templates="usableTemplates"
        :token-used="tokenStats.used"
        :input-tokens="tokenStats.input"
        :output-tokens="tokenStats.output"
        :cache-tokens="tokenStats.cache"
        :token-available="tokenStats.available"
        :token-complete="tokenStats.complete"
        :token-has-replies="tokenStats.hasReplies"
        :agent-name="agent?.name || ''"
        :agent-icon="agent?.icon || 'H'"
        :credit-display-name="credit?.display_name || ''"
        :show-credit-usage="true"
        :identity-mcp-names="identityMcpNames"
        :scrollbar-right-offset="3"
        @send="handleSend"
        @stop="handleStop"
        @permission-decide="handlePermissionDecide"
        @switch-model="handleSwitchModel"
        @refresh-models="refreshModels"
        @switch-skill="handleSwitchSkill"
        @use-welcome-suggestion="handleUseWelcomeSuggestion"
        @fill-input="handleFillInput"
        @feedback-change="handleFeedbackChange"
        @regenerate="handleRegenerate"
        @retry-run="handleRetryRun"
        @retry-narrow-run="handleNarrowRetry"
        @continue-run="handleContinueRun"
        @dismiss-run-failure="lastRunFailure = null"
        @load-older="handleLoadOlderMessages"
        :upload-file="handleUploadFile"
        :context-chips="contextChips"
        v-model:permission-mode="permissionMode"
        @remove-chip="handleRemoveChip"
        @clear-chips="handleClearChips"
        @add-workspace-file="handleAddWorkspaceFile"
      />
      <div
        v-if="currentSessionReadOnly"
        class="readonly-bar"
        :class="{ 'readonly-bar--dingtalk': currentSessionChannel?.slug === 'dingtalk' }"
      >
        <span class="readonly-status">
          <el-icon><Lock /></el-icon>
          {{ currentSessionChannel?.displayName }} 会话 · 只读
        </span>
        <el-button
          v-if="canConfigureChannels"
          link
          type="primary"
          :icon="Connection"
          @click="router.push('/workspace/assistant/channels')"
        >
          渠道设置
        </el-button>
      </div>
    </div>

    </div>

    <!-- 右侧工作区文件面板 -->
    <div class="workspace-panel" :class="{ open: workspaceOpen, expanded: workspaceExpanded }">
      <div v-show="workspaceOpen" class="workspace-body">
        <WorkspaceTree
          ref="workspaceTreeRef"
          :agent-id="agentId"
          :active="workspaceOpen"
          :expanded="workspaceExpanded"
          @close="closeWorkspace"
          @toggle-expand="workspaceExpanded = !workspaceExpanded"
          @add-context="handleAddWorkspaceFile"
        />
      </div>
    </div>
    </template>

    <!-- 路由 id 非法时兜底，避免渲染聊天 UI 触发 422 -->
    <div v-else class="agent-invalid">
      <el-empty description="智能体不存在或 ID 无效" />
      <el-button type="primary" @click="$router.push('/admin/agents')">返回列表</el-button>
    </div>

    <el-dialog
      v-model="shareDialogVisible"
      title="分享对话"
      width="min(520px, calc(100vw - 32px))"
      :close-on-click-modal="false"
    >
      <p class="share-dialog-description">获得链接的人无需登录即可查看当前对话。</p>
      <el-input :model-value="shareUrl" readonly>
        <template #append>
          <el-button :icon="CopyDocument" :loading="shareCopying" aria-label="复制分享链接" @click="copyShareUrl" />
        </template>
      </el-input>
      <template #footer>
        <el-button type="danger" plain :loading="shareRevoking" @click="revokeShare">
          取消分享
        </el-button>
        <el-button type="primary" :icon="CopyDocument" :loading="shareCopying" @click="copyShareUrl">
          复制链接
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch, computed, inject, onMounted, onBeforeUnmount, nextTick, toRaw } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Coin, Folder, FolderOpened, Close, Connection, CopyDocument, Lock, Menu, Plus, Share } from '@element-plus/icons-vue'
import api, { refreshAccessToken, getAccessTokenForRequest } from '@/api/request'
import { enterpriseApi } from '@/api/enterprise'
import { extractToolResultHtml, mergeToolBlocks } from '@/utils/agent-chat-blocks'
import { readAgentStream } from '@/utils/agent-stream'
import { parseBackendDateTime } from '@/utils/date-time'
import { formatCreditPoints } from '@/utils/credit-points'
import { copyToClipboard } from '@/utils/clipboard'
import {
  applyAgentRunTerminalEvent,
  getAgentRunFailurePresentation,
  getAgentRunErrorDetails,
  getAgentRunStatusMeta,
} from '@/utils/agent-run-state'
import { renderMarkdown } from '@/utils/markdown'
import { assetsApi } from '@/api/assets'
import ChatSidebar from './components/ChatSidebar.vue'
import ChatMain from './components/ChatMain.vue'
import WorkspaceTree from './components/WorkspaceTree.vue'
import AgentWorkspaceHeader from './components/AgentWorkspaceHeader.vue'
import AgentWorkspaceNav from './components/AgentWorkspaceNav.vue'

const route = useRoute()
const router = useRouter()
const props = defineProps({
  agentIdOverride: { type: Number, default: null },
  personalChat: { type: Boolean, default: false },
  workbenchChat: { type: Boolean, default: false },
  embedded: { type: Boolean, default: false },
  pageContext: { type: Object, default: null },
  initialBootstrap: { type: Object, default: null },
})
const agentId = props.agentIdOverride ?? Number.parseInt(route.params.id, 10)
const isValidId = Number.isFinite(agentId) && agentId > 0
const initialBootstrap = props.personalChat && props.initialBootstrap?.assistant_id === agentId
  ? props.initialBootstrap : null

// ---- State ----
const agent = ref(null)
const sessions = ref([])
const sessionsTotal = ref(0)
const sessionsLoadedCount = ref(0)
const sessionsLoading = ref(true)
let sessionsRequestPending = false
let sessionStatusTimer = null
const currentSessionId = ref(null)
const currentSessionMetadata = ref(null)
const displayMessages = ref([])
const shareDialogVisible = ref(false)
const shareLoading = ref(false)
const shareCopying = ref(false)
const shareStatusLoading = ref(false)
const shareRevoking = ref(false)
const shareToken = ref('')
// 账户和单位属于当前用户，可在默认助手和专家之间共用启动数据。
const credit = ref(props.initialBootstrap?.credit || null)
watch(() => props.initialBootstrap?.credit, value => {
  if (value) credit.value = value
})
const creditClaiming = ref(false)
const shareUrl = computed(() => (
  shareToken.value ? `${window.location.origin}/share/${shareToken.value}` : ''
))
const historyMessagesLoading = ref(false)
const historyMessagesLoadFailed = ref(false)
const historyMessagesHasMore = ref(false)
const olderMessagesLoading = ref(false)
const currentBlocks = ref([])
const streaming = ref(false)
const streamingSessionId = ref(null)
const streamingViewKey = ref(0)
const sessionViewKey = ref(0)
const inputText = ref('')
const chatMainRef = ref(null)
const workspaceTreeRef = ref(null)
const workspaceSidebar = inject('workspaceSidebar', null)
const expertWorkspace = inject('expertWorkspace', null)
const embeddedPrompt = inject('embeddedPrompt', null)
const embeddedReady = ref(false)
const nounHighlightSettings = computed(() => expertWorkspace?.agent.value?.id === agentId
  ? expertWorkspace.agent.value
  : agent.value)
const matchesWorkbenchAgent = computed(() => props.personalChat
  ? !Number(route.query.agent)
  : Number(route.query.agent) === agentId)
const chatRouteActive = computed(() => !chatDisposed && (props.workbenchChat
  ? route.name === 'WorkspaceChat' && matchesWorkbenchAgent.value
  : !expertWorkspace || (
  route.name === 'AdminAgentChat' && Number(route.params.id) === agentId
)))
watch(agent, value => {
  if (expertWorkspace && Number(route.params.id) === agentId) expertWorkspace.agent.value = value
})
const mobileSidebarOpen = workspaceSidebar?.mobileSidebarOpen || ref(false)

// Runtime
const availableRuntimes = ref([])
// Model & Skill selection
const agentModels = ref([])
const modelsLoading = ref(false)
const selectedModelId = ref(null)
const agentSkills = ref([])
const agentSkillsLoading = ref(true)
const personalSkillsLoaded = ref(false)
const identityMcpNames = ref([])
const selectedSkillId = ref(null)  // null = 未指定单个技能
const selectedFiles = ref([])      // 工作区文件路径或 OSS 图片公网链接
const filePreviewUrls = ref({})
const pendingFileUploads = ref(0)
let chatDisposed = false
watch([selectedFiles, displayMessages], ([paths, messages]) => {
  const retainedPaths = new Set([...paths, ...messages.flatMap(message => message.attachedFiles || [])])
  for (const [path, url] of Object.entries(filePreviewUrls.value)) {
    if (!retainedPaths.has(path)) {
      URL.revokeObjectURL(url)
      delete filePreviewUrls.value[path]
    }
  }
})
const usableTemplates = ref([])     // 当前用户的提示词模板（聊天框下拉用）
const permissionMode = ref('acceptEdits')

// Permission
const currentRunId = ref(null)
const currentRunPhase = ref('idle')
const lastRunFailure = ref(null)
const permissionQueue = ref([])
const permissionSubmittingIds = ref([])
const activeStreamState = ref(null)
// Each conversation owns its own observer and transient stream state.  The
// backend may run several sessions for one user at the same time, so a single
// page-level streaming flag would incorrectly lock every composer.
const streamStates = ref([])
let streamSequence = 0
const STREAM_RENDER_INTERVAL_MS = 50
let streamRenderTimer = null
let lastStreamRenderAt = 0
let pendingStreamState = null
const SESSION_PAGE_SIZE = 20
const MESSAGE_PAGE_SIZE = 10
const DRAFT_STORAGE_KEY = `agent-chat-drafts:${agentId}`

const loadSessionDrafts = () => {
  try {
    const saved = JSON.parse(sessionStorage.getItem(DRAFT_STORAGE_KEY) || '{}')
    return new Map(Object.entries(saved))
  } catch {
    return new Map()
  }
}

const sessionDrafts = loadSessionDrafts()
let draftSaveTimer = null

const persistSessionDrafts = () => {
  try {
    const entries = [...sessionDrafts.entries()].filter(([, value]) => value)
    if (entries.length > 0) {
      sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(Object.fromEntries(entries)))
    } else {
      sessionStorage.removeItem(DRAFT_STORAGE_KEY)
    }
  } catch {
    // Storage can be unavailable in hardened/private browsing contexts.
  }
}

const saveSessionDraft = (sessionId, value) => {
  if (sessionId === null || sessionId === undefined) return
  if (value) sessionDrafts.set(String(sessionId), value)
  else sessionDrafts.delete(String(sessionId))
  persistSessionDrafts()
}

const sessionsHasMore = computed(() => sessionsLoadedCount.value < sessionsTotal.value)

const sameSessionId = (a, b) => {
  if (a === null || a === undefined || b === null || b === undefined) return a === b
  return String(a) === String(b)
}

const getMessageResponseSession = (response, sessionId) => {
  const nested = response?.session && typeof response.session === 'object'
    ? response.session
    : {}
  const source = nested.source ?? response?.session_source ?? response?.source
  const sourceBindingId = nested.source_binding_id
    ?? response?.session_source_binding_id
    ?? response?.source_binding_id
  const hasMetadata = Object.keys(nested).length > 0
    || source !== undefined
    || sourceBindingId !== undefined
  if (!hasMetadata) return null

  const metadata = {
    ...nested,
    id: nested.id ?? response?.session_id ?? sessionId,
  }
  if (source !== undefined) metadata.source = source
  if (sourceBindingId !== undefined) metadata.source_binding_id = sourceBindingId
  if (!metadata.title && response?.session_title) metadata.title = response.session_title
  return metadata
}

const mergeCurrentSessionMetadata = (response, sessionId) => {
  const metadata = getMessageResponseSession(response, sessionId)
  if (!metadata) return null

  const index = sessions.value.findIndex(session => sameSessionId(session.id, metadata.id))
  const existing = index >= 0 ? sessions.value[index] : null
  const merged = { ...(existing || {}), ...metadata }
  currentSessionMetadata.value = merged
  if (merged.model_id) selectedModelId.value = merged.model_id
  if (index >= 0) {
    sessions.value = sessions.value.map((session, itemIndex) => (
      itemIndex === index ? merged : session
    ))
  } else {
    // Deep-linked sessions may not be in the first page. Keep the server page count
    // separate so this synthetic list entry does not shift the next pagination offset.
    sessions.value = [...sessions.value, merged]
  }
  return merged
}

const getSessionFallbackTitle = (content) => {
  const text = (content || '').replace(/\s+/g, ' ').trim()
  return text ? text.slice(0, 30) : '新对话'
}

const touchStreamingSessionInList = (sessionId, content) => {
  if (sessionId === null || sessionId === undefined) return
  const now = new Date().toISOString()
  const existing = sessions.value.find(s => sameSessionId(s.id, sessionId))
  const previousTotal = Math.max(Number(sessionsTotal.value || 0), sessions.value.length)
  const touched = {
    ...(existing || {}),
    id: existing?.id ?? sessionId,
    title: existing?.title || getSessionFallbackTitle(content),
    message_count: existing ? Math.max(Number(existing.message_count || 0), 1) : 1,
    last_message_at: now,
    updated_at: now,
    created_at: existing?.created_at || now,
  }
  const nextSessions = [
    touched,
    ...sessions.value.filter(s => !sameSessionId(s.id, sessionId)),
  ]
  sessions.value = sessions.value.length >= SESSION_PAGE_SIZE
    ? nextSessions.slice(0, SESSION_PAGE_SIZE)
    : nextSessions
  if (!existing) {
    sessionsTotal.value = Math.max(previousTotal + 1, sessions.value.length)
  }
}

const currentSession = computed(() => (
  sessions.value.find(session => sameSessionId(session.id, currentSessionId.value))
  || (sameSessionId(currentSessionMetadata.value?.id, currentSessionId.value)
    ? currentSessionMetadata.value
    : null)
))
const currentRuntimeType = computed(() => (
  agent.value?.runtime_type || currentSession.value?.runtime_type || 'claude_code'
))
const getSessionChannel = () => null
const isChannelSession = () => false
const currentSessionChannel = computed(() => null)
const currentSessionReadOnly = computed(() => false)
const canConfigureChannels = computed(() => false)

watch(inputText, (value) => {
  window.clearTimeout(draftSaveTimer)
  if (currentSessionId.value === null || currentSessionReadOnly.value) return
  const draftSessionId = currentSessionId.value
  draftSaveTimer = window.setTimeout(() => {
    saveSessionDraft(draftSessionId, value)
  }, 250)
})
const mobileChatTitle = computed(() => (
  currentSessionChannel.value?.displayName
  || currentSession.value?.title
  || agent.value?.name
  || '智能体对话'
))
const readonlyWarning = () => `${currentSessionChannel.value?.displayName || '渠道 ClawBot'} 会话为只读`

const isStreamFinished = streamState => (
  !!streamState?.finished
)

const streamSessionId = streamState => streamState?.sessionId ?? streamState?.requestedSessionId

const streamMatchesCurrentView = (streamState) => {
  if (!streamState) return false
  const sessionId = streamSessionId(streamState)
  if (sessionId !== null && sessionId !== undefined) {
    return sameSessionId(currentSessionId.value, sessionId)
  }
  return currentSessionId.value === null && sessionViewKey.value === streamState.viewKey
}

const findStreamForView = () => streamStates.value.find(streamState => (
  !isStreamFinished(streamState) && streamMatchesCurrentView(streamState)
)) || null

const findStreamByRunId = runId => streamStates.value.find(streamState => (
  runId && streamState.runId && String(streamState.runId) === String(runId)
)) || null

const streamingSessionIds = computed(() => streamStates.value
  .filter(streamState => !isStreamFinished(streamState))
  .map(streamState => streamSessionId(streamState))
  .filter(sessionId => sessionId !== null && sessionId !== undefined))

const activateStreamForCurrentView = () => {
  const streamState = findStreamForView()
  activeStreamState.value = streamState
  streaming.value = !!streamState
  streamingSessionId.value = streamSessionId(streamState)
  streamingViewKey.value = streamState?.viewKey || 0
  currentRunId.value = streamState?.runId || null
  currentRunPhase.value = streamState?.phase || 'idle'
  currentBlocks.value = streamState ? [...streamState.blocks] : []
  permissionQueue.value = streamState ? [...streamState.permissionQueue] : []
  return streamState
}

const isActiveStreamState = (streamState) => (
  !!streamState && streamStates.value.some(item => toRaw(item) === toRaw(streamState))
)

const isStreamVisibleInCurrentView = (streamState = activeStreamState.value) => {
  if (!streamState || !isActiveStreamState(streamState)) return false
  return toRaw(activeStreamState.value) === toRaw(streamState) && streamMatchesCurrentView(streamState)
}

const isViewingStreamSession = () => isStreamVisibleInCurrentView()
const visibleStreaming = computed(() => (
  isViewingStreamSession()
))
const visibleCurrentBlocks = computed(() => visibleStreaming.value ? currentBlocks.value : [])
const visiblePermissionQueue = computed(() => visibleStreaming.value ? permissionQueue.value : [])
const visibleRunStatus = computed(() => (
  visibleStreaming.value ? getAgentRunStatusMeta(currentRunPhase.value) : null
))
const visibleContextNotice = computed(() => (
  visibleStreaming.value ? (activeStreamState.value?.contextNotice || '') : ''
))
const visibleRunTokenCount = computed(() => {
  const usage = activeStreamState.value?.usage
  if (!usage) return null
  return buildTurnMetrics(usage, null)?.totalTokens ?? null
})
const visibleRunFailure = computed(() => {
  const failure = lastRunFailure.value
  if (!failure || visibleStreaming.value) return null
  if (!sameSessionId(failure.sessionId, currentSessionId.value)) return null
  return failure.viewKey === undefined || failure.viewKey === sessionViewKey.value ? failure : null
})

const createStreamState = ({ userContent = '', requestedSessionId = null, viewKey = 0, startedAt = null } = {}) => ({
  runId: null,
  requestedSessionId,
  sessionId: null,
  viewKey,
  userContent,
  idempotencyKey: null,
  blocks: [],
  permissionQueue: [],
  resolvedPermissionIds: new Set(),
  phase: 'connecting',
  failed: false,
  cancelled: false,
  error: '',
  errorCode: '',
  errorDetails: null,
  contextNotice: '',
  terminalEventReceived: false,
  startedAt: Number.isFinite(startedAt) && startedAt > 0 ? startedAt : Date.now(),
  usage: null,
  durationMs: null,
  chargedPoints: null,
  finished: false,
})

const syncStreamStateToView = (streamState) => {
  if (!isActiveStreamState(streamState)) return
  if (!isStreamVisibleInCurrentView(streamState)) return
  currentRunId.value = streamState.runId
  currentRunPhase.value = streamState.phase
  streaming.value = !isStreamFinished(streamState)
  currentBlocks.value = [...streamState.blocks]
  permissionQueue.value = [...streamState.permissionQueue]
  chatMainRef.value?.followStream?.()
}

const flushStreamStateToView = () => {
  if (streamRenderTimer !== null) {
    window.clearTimeout(streamRenderTimer)
    streamRenderTimer = null
  }
  const streamState = pendingStreamState
  pendingStreamState = null
  if (streamState) {
    lastStreamRenderAt = Date.now()
    syncStreamStateToView(streamState)
  }
}

const scheduleStreamStateSync = (streamState) => {
  // Background streams keep their state in the collection; rendering them is
  // only useful when their session is currently selected.
  if (!isStreamVisibleInCurrentView(streamState)) return
  pendingStreamState = streamState
  if (streamRenderTimer !== null) return
  const elapsed = Date.now() - lastStreamRenderAt
  const delay = Math.max(0, STREAM_RENDER_INTERVAL_MS - elapsed)
  streamRenderTimer = window.setTimeout(() => {
    streamRenderTimer = null
    const scheduledState = pendingStreamState
    pendingStreamState = null
    if (scheduledState) {
      lastStreamRenderAt = Date.now()
      syncStreamStateToView(scheduledState)
    }
  }, delay)
}

// Token tracking -- 汇总当前会话每轮由 runtime 返回的真实 usage。
const tokenStats = ref({
  used: null,
  input: 0,
  output: 0,
  cache: 0,
  available: false,
  complete: false,
  hasReplies: false,
})

// 保留函数名以减少调用点噪声；此处不再估算文本，而是聚合已保存的真实指标。
const recomputeHistoryTokens = () => {
  const assistantMessages = displayMessages.value.filter(message => message.role === 'assistant')
  const recorded = assistantMessages.filter(message => Number.isFinite(message.metrics?.totalTokens))
  tokenStats.value = {
    used: recorded.length
      ? recorded.reduce((sum, message) => sum + message.metrics.totalTokens, 0)
      : null,
    input: recorded.reduce((sum, message) => sum + (message.metrics.inputTokens || 0), 0),
    output: recorded.reduce((sum, message) => sum + (message.metrics.outputTokens || 0), 0),
    cache: recorded.reduce((sum, message) => sum + (message.metrics.cacheTokens || 0), 0),
    available: recorded.length > 0,
    complete: !historyMessagesHasMore.value
      && assistantMessages.length > 0
      && recorded.length === assistantMessages.length,
    hasReplies: assistantMessages.length > 0,
  }
}

// 切换/新建会话时清零，等待历史消息中的真实 usage。
const resetTokenStats = () => {
  tokenStats.value = {
    used: null,
    input: 0,
    output: 0,
    cache: 0,
    available: false,
    complete: false,
    hasReplies: false,
  }
}

const usageNumber = (usage, ...keys) => {
  for (const key of keys) {
    const value = Number(usage?.[key])
    if (Number.isFinite(value)) return value
  }
  return null
}

const mergeTurnUsage = (total, current) => {
  if (!current || typeof current !== 'object') return total
  const merged = { ...(total || {}) }
  Object.entries(current).forEach(([key, value]) => {
    const numeric = Number(value)
    if (Number.isFinite(numeric)) merged[key] = Number(merged[key] || 0) + numeric
  })
  return merged
}

const buildTurnMetrics = (usage, durationMs, chargedPoints = null) => {
  const inputTokens = usageNumber(usage, 'input_tokens', 'prompt_tokens')
  const outputTokens = usageNumber(usage, 'output_tokens', 'completion_tokens')
  const cacheReadTokens = usageNumber(usage, 'cache_read_input_tokens', 'cache_read_tokens')
  const cacheCreationTokens = usageNumber(usage, 'cache_creation_input_tokens', 'cache_creation_tokens')
  const reportedTotal = usageNumber(usage, 'total_tokens')
  const tokenParts = [inputTokens, outputTokens, cacheReadTokens, cacheCreationTokens]
  const hasTokenBreakdown = tokenParts.some(value => value !== null)
  const numericDuration = durationMs === null || durationMs === undefined
    ? null
    : Number(durationMs)
  const numericChargedPoints = chargedPoints === null || chargedPoints === undefined
    ? null
    : Number(chargedPoints)

  return {
    durationMs: numericDuration !== null && Number.isFinite(numericDuration) && numericDuration >= 0
      ? numericDuration
      : null,
    totalTokens: reportedTotal ?? (hasTokenBreakdown
      ? tokenParts.reduce((sum, value) => sum + (value || 0), 0)
      : null),
    inputTokens,
    outputTokens,
    cacheReadTokens,
    cacheCreationTokens,
    cacheTokens: cacheReadTokens === null && cacheCreationTokens === null
      ? null
      : (cacheReadTokens || 0) + (cacheCreationTokens || 0),
    totalInputTokens: inputTokens === null && cacheReadTokens === null && cacheCreationTokens === null
      ? null
      : (inputTokens || 0) + (cacheReadTokens || 0) + (cacheCreationTokens || 0),
    nonCacheInputTokens: inputTokens,
    cacheHit: cacheReadTokens === null ? null : cacheReadTokens > 0,
    chargedPoints: Number.isFinite(numericChargedPoints) ? numericChargedPoints : null,
  }
}

// Workspace panel
const workspaceOpen = ref(false)
const workspaceExpanded = ref(false)
let workspaceRefreshTimer = null
let workspaceRefreshPending = false

const scheduleWorkspaceRefresh = (delay = 300) => {
  workspaceRefreshPending = true
  if (!workspaceOpen.value) return
  window.clearTimeout(workspaceRefreshTimer)
  workspaceRefreshTimer = window.setTimeout(() => {
    workspaceRefreshTimer = null
    workspaceRefreshPending = false
    workspaceTreeRef.value?.fetchFiles()
  }, delay)
}

watch(workspaceOpen, async (open) => {
  if (!open) {
    workspaceExpanded.value = false
    window.clearTimeout(workspaceRefreshTimer)
    workspaceRefreshTimer = null
    return
  }
  await nextTick()
  // WorkspaceTree 首次挂载会自行加载；这里消费关闭期间积累的刷新标记。
  workspaceRefreshPending = false
})

const closeWorkspace = () => {
  workspaceOpen.value = false
  workspaceExpanded.value = false
}

let messageLoadSequence = 0

// ---- Computed ----
const contextChips = computed(() => {
  const chips = []
  // 技能 chip
  if (selectedSkillId.value) {
    const skill = agentSkills.value.find(s => s.id === selectedSkillId.value)
    if (skill) chips.push({ id: `skill-${skill.id}`, type: 'skill', label: skill.name })
  }
  // 文件 chips
  selectedFiles.value.forEach(f => {
    // 取文件名作为显示，不含路径前缀
    const name = f.includes('/') ? f.split('/').pop() : f
    chips.push({ id: `file-${f}`, type: 'file', label: name, path: f, previewUrl: f.startsWith('https://') ? f : filePreviewUrls.value[f] })
  })
  return chips
})

const normalizePermissionEvent = (evt, fallbackRunId = currentRunId.value) => {
  const toolName = evt.tool_name || evt.name || evt.tool?.name || 'Tool'
  const toolInput = evt.tool_input ?? evt.input ?? evt.arguments ?? evt.tool?.input ?? {}
  const reqId = evt.req_id || evt.id || `${evt.run_id || fallbackRunId || 'run'}-${toolName}-${Date.now()}`
  return {
    req_id: reqId,
    run_id: evt.run_id || fallbackRunId,
    tool_name: toolName,
    tool_input: toolInput,
    tool_key: evt.tool_key || toolName,
    options: evt.options || evt.choices || null,
    message: evt.message || evt.content || '',
  }
}

const recordRunFailure = (streamState) => {
  const failureMessage = streamState.error || '智能体运行失败，请稍后重试'
  const presentation = getAgentRunFailurePresentation(
    failureMessage,
    streamState.errorCode,
  )
  lastRunFailure.value = {
    sessionId: streamState.sessionId ?? streamState.requestedSessionId,
    viewKey: streamState.viewKey,
    content: streamState.userContent,
    errorCode: streamState.errorCode,
    details: streamState.errorDetails || getAgentRunErrorDetails(failureMessage, streamState.errorCode),
    ...presentation,
    suggestNarrow: /chunk|limit|过大|上下文|token|separator/i.test(failureMessage),
    canContinue: streamState.blocks?.some(block => block.type === 'tool_use'),
  }
}

// ---- SSE Parser ----
const handleSseEvent = (evt, streamState) => {
  switch (evt.type) {
    case 'snapshot_reset':
      streamState.previousBlocks = streamState.blocks
      streamState.blocks = []
      streamState.permissionQueue = []
      streamState.usage = null
      streamState.failed = false
      streamState.cancelled = false
      streamState.error = ''
      streamState.errorCode = ''
      streamState.errorDetails = null
      streamState.terminalEventReceived = false
      streamState.streamEnded = false
      break
    case 'snapshot_applied':
      // Replacing a snapshot must not restart the visible thinking/tool timer.
      streamState.blocks.forEach((block, index) => {
        const previous = streamState.previousBlocks?.[index]
        if (!previous || previous.type !== block.type || previous.tool_use_id !== block.tool_use_id) return
        if (previous.startTime !== undefined) block.startTime = previous.startTime
        if (previous.endTime !== undefined) block.endTime = previous.endTime
      })
      delete streamState.previousBlocks
      break
    case 'run_queued':
      streamState.runId = evt.run_id
      streamState.sessionId = evt.session_id || null
      if (streamState.resuming && evt.user_content && isStreamVisibleInCurrentView(streamState)) {
        streamState.userContent = evt.user_content
        const lastMessage = displayMessages.value.at(-1)
        if (lastMessage?.role !== 'user' || lastMessage.content !== evt.user_content) {
          displayMessages.value.push({
            id: `pending-${evt.run_id}`, role: 'user', content: evt.user_content,
            created_at: new Date().toISOString(),
            attachedFiles: evt.attached_files || [], images: messageImages(evt.attached_files || []),
            _html: renderMarkdown(evt.user_content),
          })
        }
      }
      if (streamState.phase !== 'stopping') streamState.phase = 'queued'
      const sessionIsCurrent = streamState.sessionId && (
        isStreamVisibleInCurrentView(streamState)
        || (streamState.requestedSessionId === null
          && currentSessionId.value === null
          && sessionViewKey.value === streamState.viewKey)
      )
      if (sessionIsCurrent) {
        const shouldAttachCreatedSession = (
          streamState.requestedSessionId === null &&
          currentSessionId.value === null &&
          sessionViewKey.value === streamState.viewKey
        )
        streamingSessionId.value = streamState.sessionId
        touchStreamingSessionInList(streamState.sessionId, streamState.userContent)
        if (shouldAttachCreatedSession) {
          currentSessionId.value = streamState.sessionId
          if (chatRouteActive.value) router.replace({ query: { ...route.query, session: streamState.sessionId } })
        }
      }
      break
    case 'run_start': {
      streamState.runId = evt.run_id
      streamState.sessionId = evt.session_id || null
      const persistedStartedAt = parseBackendDateTime(evt.started_at)?.getTime()
      if (Number.isFinite(persistedStartedAt) && persistedStartedAt > 0) {
        // Include preparation/queue time; replaying run_start must not reset the clock.
        streamState.startedAt = Number.isFinite(streamState.startedAt) && streamState.startedAt > 0
          ? Math.min(streamState.startedAt, persistedStartedAt)
          : persistedStartedAt
      }
      if (streamState.phase !== 'stopping') streamState.phase = 'running'
      const runIsCurrent = streamState.sessionId && (
        isStreamVisibleInCurrentView(streamState)
        || (streamState.requestedSessionId === null
          && currentSessionId.value === null
          && sessionViewKey.value === streamState.viewKey)
      )
      if (runIsCurrent) {
        const shouldAttachCreatedSession = (
          streamState.requestedSessionId === null &&
          currentSessionId.value === null &&
          sessionViewKey.value === streamState.viewKey
        )
        streamingSessionId.value = streamState.sessionId
        touchStreamingSessionInList(streamState.sessionId, streamState.userContent)
        if (shouldAttachCreatedSession) {
          currentSessionId.value = streamState.sessionId
          if (chatRouteActive.value) router.replace({ query: { ...route.query, session: streamState.sessionId } })
        }
      }
      break
    }

    case 'permission_request':
      {
        const permission = normalizePermissionEvent(evt, streamState.runId)
        if (streamState.resolvedPermissionIds.has(permission.req_id)) break
        if (streamState.phase !== 'stopping') streamState.phase = 'waiting_permission'
        const exists = streamState.permissionQueue.some(item => item.req_id === permission.req_id)
        if (!exists) {
          streamState.permissionQueue = [...streamState.permissionQueue, permission]
        }
      }
      break

    case 'permission_sync':
      streamState.permissionQueue = streamState.permissionQueue.filter(item => evt.pending_ids.includes(item.req_id))
      if (!streamState.permissionQueue.length && streamState.phase === 'waiting_permission') streamState.phase = 'running'
      break

    case 'stream_end':
      streamState.streamEnded = true
      if (!streamState.terminalEventReceived) {
        applyAgentRunTerminalEvent(streamState, {
          type: evt.status === 'succeeded' ? 'done' : evt.status === 'cancelled' ? 'cancelled' : 'error',
          content: evt.error || '', error_code: evt.error_code,
        })
      }
      break

    case 'text': {
      if (streamState.phase !== 'stopping') streamState.phase = 'running'
      const lastText = streamState.blocks[streamState.blocks.length - 1]
      if (lastText && lastText.type === 'text') {
        lastText.content += evt.content
      } else {
        _finalizeThinking(streamState)
        _finalizeToolUse(streamState)
        streamState.blocks = [...streamState.blocks, { type: 'text', content: evt.content }]
      }
      break
    }
    case 'thinking': {
      if (streamState.phase !== 'stopping') streamState.phase = 'running'
      const lastThink = streamState.blocks[streamState.blocks.length - 1]
      if (lastThink && lastThink.type === 'thinking') {
        lastThink.content += evt.content
      } else {
        _finalizeToolUse(streamState)
        streamState.blocks = [...streamState.blocks, {
          type: 'thinking', content: evt.content, startTime: Date.now(),
        }]
      }
      break
    }
    case 'tool_use':
      if (streamState.phase !== 'stopping') streamState.phase = 'running'
      _finalizeThinking(streamState)
      _finalizeToolUse(streamState)
      streamState.blocks = [...streamState.blocks, {
        type: 'tool_use',
        name: evt.name,
        input: evt.input,
        tool_use_id: evt.tool_use_id,
        startTime: Date.now(),
      }]
      break
    case 'tool_result': {
      // 合并到对应的 tool_use 卡片中，不另外新建卡片
      const blocks = [...streamState.blocks]
      // 优先按 tool_use_id 精确匹配；id 缺失或未命中时回退到最后一个未完成的 tool_use，
      // 避免因 ID 不匹配导致结果丢失、卡片一直转圈
      let idx = evt.tool_use_id
        ? blocks.findLastIndex(b => b.type === 'tool_use' && b.tool_use_id === evt.tool_use_id)
        : -1
      if (idx < 0) {
        idx = blocks.findLastIndex(b => b.type === 'tool_use' && b.result === undefined)
      }
      if (idx >= 0) {
        blocks[idx] = {
          ...blocks[idx],
          result: evt.content,
          resultHtml: typeof evt.resultHtml === 'string' ? evt.resultHtml : extractToolResultHtml(evt.content),
          is_error: evt.is_error,
          endTime: Date.now(),
        }
        streamState.blocks = blocks
      }
      // 工具执行后可能产生/修改文件，自动刷新工作区文件树
      const previousTool = streamState.previousBlocks?.find(block => block.type === 'tool_use' && block.tool_use_id === evt.tool_use_id)
      if (!previousTool || previousTool.result !== evt.content) scheduleWorkspaceRefresh()
      break
    }
    case 'artifacts': {
      const files = evt.files || evt.metadata?.files || []
      streamState.blocks = [
        ...streamState.blocks.filter(block => block.type !== 'artifacts'),
        { type: 'artifacts', files },
      ]
      scheduleWorkspaceRefresh()
      break
    }
    case 'usage':
      if (evt.usage) {
        streamState.usage = mergeTurnUsage(streamState.usage, evt.usage)
      }
      break
    case 'credit_usage': {
      const progress = evt.metadata || {}
      if (evt.usage) streamState.usage = evt.usage
      if (progress.charged_points != null) streamState.chargedPoints = progress.charged_points
      if (credit.value && progress.available_balance != null) {
        credit.value = { ...credit.value, available_balance: progress.available_balance }
        window.dispatchEvent(new CustomEvent('aihub:credit-account-updated', { detail: credit.value }))
      }
      break
    }
    case 'turn_metrics':
      streamState.assistantMessageId = evt.assistant_message_id || streamState.assistantMessageId
      streamState.usage = evt.usage || streamState.usage
      streamState.durationMs = evt.duration_ms
      streamState.chargedPoints = evt.charged_points ?? streamState.chargedPoints
      break
    case 'info':
      if (streamState.phase !== 'stopping') streamState.phase = 'running'
      break
    case 'context_notice':
      streamState.contextNotice = evt.content || ''
      break
    case 'error':
      applyAgentRunTerminalEvent(streamState, evt)
      _finalizeThinking(streamState)
      _finalizeToolUse(streamState)
      if (isStreamVisibleInCurrentView(streamState)) recordRunFailure(streamState)
      break
    case 'cancelled':
      applyAgentRunTerminalEvent(streamState, evt)
      _finalizeThinking(streamState)
      _finalizeToolUse(streamState)
      break
    case 'done':
      applyAgentRunTerminalEvent(streamState, evt)
      _finalizeThinking(streamState)
      _finalizeToolUse(streamState)
      _appendDoneContentIfNeeded(streamState, evt.content)
      break
  }
  // 合并同一帧内的 SSE 增量，避免高频响应式渲染和 Markdown 重算。
  scheduleStreamStateSync(streamState)
}

const _appendDoneContentIfNeeded = (streamState, content) => {
  const finalText = (content || '').trim()
  if (!finalText) return

  const streamedText = streamState.blocks
    .filter(b => b.type === 'text')
    .map(b => b.content || '')
    .join('')
    .trim()
  if (streamedText) return

  streamState.blocks = [...streamState.blocks, { type: 'text', content }]
}

const _finalizeThinking = (streamState) => {
  const blocks = streamState.blocks
  const last = blocks[blocks.length - 1]
  if (last && last.type === 'thinking' && !last.endTime) {
    last.endTime = Date.now()
  }
}

const _finalizeToolUse = (streamState) => {
  // 兜底：工具结果可能因输出截断、事件丢失或 tool_use_id 不匹配而未送达。
  // 当模型已进入下一阶段（文本/思考/下一工具）或流结束时，把仍在 running 的
  // 最后一个 tool_use 标记完成，避免加载图标一直转。真实结果若后到仍会覆盖。
  const blocks = streamState.blocks
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i]
    if (b.type === 'tool_use') {
      if (b.result === undefined && !b.endTime) {
        b.endTime = Date.now()
      }
      return
    }
  }
}

// ---- API calls ----
let skillSyncPending = false
const syncInstalledSkills = async () => {
  if (!isValidId || skillSyncPending || chatDisposed) return
  skillSyncPending = true
  try {
    await api.post(`/agents/${agentId}/skills/sync`)
  } catch (error) {
    if (!chatDisposed) ElMessage.error('技能同步失败，发送消息时将重新检查')
  } finally {
    skillSyncPending = false
  }
}
watch(currentSessionId, () => { syncInstalledSkills() })

let agentLoadSequence = 0
const fetchAgent = async () => {
  const requestId = ++agentLoadSequence
  if (!props.personalChat) agentSkillsLoading.value = true
  try {
    const result = initialBootstrap?.assistant?.id === agentId
      ? initialBootstrap.assistant
      : await api.get(`/agents/${agentId}`)
    if (chatDisposed || requestId !== agentLoadSequence) return
    agent.value = result
    // 初始化模型和技能选择
    agentModels.value = agent.value.models || []
    selectedModelId.value = currentSessionMetadata.value?.model_id
      || (currentSessionId.value ? null : (selectedModelId.value || agent.value.default_model_id))
    if (!props.personalChat) agentSkills.value = agent.value.skills || []
    selectedSkillId.value = null
  } catch (e) {
    if (!chatDisposed && requestId === agentLoadSequence) ElMessage.error('加载智能体失败')
  } finally {
    if (!props.personalChat && !chatDisposed && requestId === agentLoadSequence) agentSkillsLoading.value = false
    if (expertWorkspace && Number(route.params.id) === agentId) expertWorkspace.agentLoading.value = false
  }
}

const fetchSessions = async ({ reset = true, silent = false } = {}) => {
  if (sessionsRequestPending) return
  sessionsRequestPending = true
  if (!silent) sessionsLoading.value = true
  try {
    const skip = reset ? 0 : sessionsLoadedCount.value
    const res = await api.get(`/agents/${agentId}/sessions`, {
      params: { skip, limit: SESSION_PAGE_SIZE },
    })
    const items = res.items || []
    const loadedCount = reset ? items.length : sessionsLoadedCount.value + items.length
    sessionsTotal.value = res.total ?? loadedCount
    if (reset) {
      const selectedMetadata = sameSessionId(
        currentSessionMetadata.value?.id,
        currentSessionId.value,
      ) ? currentSessionMetadata.value : null
      sessions.value = selectedMetadata && !items.some(item => sameSessionId(item.id, selectedMetadata.id))
        ? [...items, selectedMetadata]
        : items
    } else {
      sessions.value = [
        ...sessions.value,
        ...items.filter(item => !sessions.value.some(session => sameSessionId(session.id, item.id))),
      ]
    }
    sessionsLoadedCount.value = loadedCount
    const selected = sessions.value.find(session => sameSessionId(session.id, currentSessionId.value))
    if (selected) {
      currentSessionMetadata.value = selected
      if (selected.model_id) selectedModelId.value = selected.model_id
    }
  } catch (e) {
    ElMessage.error('加载会话失败')
  } finally {
    sessionsRequestPending = false
    if (!silent) sessionsLoading.value = false
    window.clearTimeout(sessionStatusTimer)
    if (!chatDisposed && sessions.value.some(session => session.active_run_id)) {
      sessionStatusTimer = window.setTimeout(() => fetchSessions({ silent: true }), 3000)
    }
  }
}

const handleLoadMoreSessions = () => {
  if (!sessionsHasMore.value || sessionsLoading.value) return
  fetchSessions({ reset: false })
}

const fetchRuntimes = async () => {
  try {
    const res = await api.get('/agents/runtimes')
    availableRuntimes.value = res.items || []
  } catch (e) {
    // 使用本地默认值（仅列出已稳定可用的 runtime）
    availableRuntimes.value = [
      { type: 'claude_code', label: 'Claude Agent', description: 'Anthropic 官方 CLI agent' },
    ]
  }
}

const messageImages = paths => paths
  .filter(path => /\.(png|jpe?g|gif|webp)$/i.test(path))
  .map(path => ({ path, previewUrl: path.startsWith('https://') ? path : filePreviewUrls.value[path] || '' }))

const mapHistoryMessages = items => items.map((m, index) => {
  if (m.role === 'assistant') {
    let blocks = []
    let payload = null
    try {
      payload = JSON.parse(m.content)
      blocks = payload
    } catch {
      blocks = [{ type: 'text', content: m.content }]
    }
    if (typeof blocks === 'object' && blocks.blocks) blocks = blocks.blocks
    if (!Array.isArray(blocks)) blocks = [{ type: 'text', content: String(m.content) }]
    blocks = mergeToolBlocks(blocks)
    const previousMessage = items[index - 1]
    const previousCreatedAt = parseBackendDateTime(previousMessage?.created_at)
    const messageCreatedAt = parseBackendDateTime(m.created_at)
    const legacyDuration = previousMessage?.role === 'user' && previousMessage.created_at && m.created_at
      && previousCreatedAt && messageCreatedAt
      ? Math.max(0, messageCreatedAt.getTime() - previousCreatedAt.getTime())
      : null
    return {
      id: 'a-' + m.id,
      messageId: m.id,
      role: 'assistant',
      feedback: m.feedback || null,
      runId: m.run_id || null,
      blocks,
      metrics: buildTurnMetrics(
        payload?.usage,
        payload?.duration_ms ?? legacyDuration,
        m.charged_points,
      ),
      _saved: true,
    }
  }
  return {
    id: 'u-' + m.id,
    messageId: m.id,
    role: m.role,
    created_at: m.created_at,
    content: m.content,
    attachedFiles: m.attached_files || [],
    skill: m.skill || null,
    images: messageImages(m.attached_files || []),
    _saved: true,
    _html: renderMarkdown(m.content || ''),
  }
})

const sameIdentifier = (left, right) => (
  left !== null && left !== undefined
  && right !== null && right !== undefined
  && String(left) === String(right)
)

const upsertStreamAssistantMessage = (streamState) => {
  if (!streamState?.blocks?.length) return

  const assistantMessageId = streamState.assistantMessageId
  const matchingIndex = displayMessages.value.findIndex(message => (
    message.role === 'assistant'
    && ((assistantMessageId !== null && assistantMessageId !== undefined
      && sameIdentifier(message.messageId, assistantMessageId))
      || sameIdentifier(message.runId, streamState.runId))
  ))
  const existing = matchingIndex >= 0 ? displayMessages.value[matchingIndex] : null
  const assistantMsg = {
    id: existing?.id || `a-${streamState.runId || Date.now()}`,
    messageId: assistantMessageId || existing?.messageId || null,
    runId: streamState.runId || existing?.runId || null,
    role: 'assistant',
    failed: streamState.failed,
    blocks: streamState.blocks.map(block => ({ ...block })),
    metrics: buildTurnMetrics(
      streamState.usage,
      streamState.durationMs ?? (Date.now() - streamState.startedAt),
      streamState.chargedPoints,
    ),
  }
  if (matchingIndex >= 0) {
    displayMessages.value = displayMessages.value.map((message, index) => (
      index === matchingIndex ? assistantMsg : message
    ))
  } else {
    displayMessages.value = [...displayMessages.value, assistantMsg]
  }
  recomputeHistoryTokens()
}

const fetchMessages = async (sessionId) => {
  const loadSequence = ++messageLoadSequence
  historyMessagesLoading.value = true
  historyMessagesLoadFailed.value = false
  historyMessagesHasMore.value = false
  try {
    const res = await api.get(`/agents/${agentId}/sessions/${sessionId}/messages`, {
      params: { limit: MESSAGE_PAGE_SIZE },
    })
    if (loadSequence !== messageLoadSequence || !sameSessionId(currentSessionId.value, sessionId)) {
      return false
    }
    mergeCurrentSessionMetadata(res, sessionId)
    if (currentSessionReadOnly.value) inputText.value = ''
    const items = res.items || []
    historyMessagesHasMore.value = !!res.has_more
    displayMessages.value = mapHistoryMessages(items)
    recomputeHistoryTokens()
    chatMainRef.value?.scrollToBottom()
    return true
  } catch (e) {
    if (loadSequence === messageLoadSequence && sameSessionId(currentSessionId.value, sessionId)) {
      displayMessages.value = []
      const status = e.response?.status
      if (status === 403 || status === 404) {
        const pendingInput = inputText.value
        handleNewSession()
        inputText.value = pendingInput
        ElMessage.warning('该会话不存在或无权访问，已切换为新对话')
      } else {
        historyMessagesLoadFailed.value = true
        ElMessage.error('加载历史消息失败，请重新选择会话或新建对话')
      }
    }
    return false
  } finally {
    if (loadSequence === messageLoadSequence && sameSessionId(currentSessionId.value, sessionId)) {
      historyMessagesLoading.value = false
    }
  }
}

const handleLoadOlderMessages = async () => {
  if (olderMessagesLoading.value || !historyMessagesHasMore.value) return
  const sessionId = currentSessionId.value
  const beforeId = displayMessages.value[0]?.messageId
  if (!sessionId || !beforeId) return

  olderMessagesLoading.value = true
  const scrollSnapshot = chatMainRef.value?.getScrollSnapshot?.() || { height: 0, top: 0 }
  try {
    const res = await api.get(`/agents/${agentId}/sessions/${sessionId}/messages`, {
      params: { limit: MESSAGE_PAGE_SIZE, before_id: beforeId },
    })
    if (!sameSessionId(currentSessionId.value, sessionId)) return
    const existingIds = new Set(displayMessages.value.map(message => message.messageId))
    const olderMessages = mapHistoryMessages(res.items || [])
      .filter(message => !existingIds.has(message.messageId))
    displayMessages.value = [...olderMessages, ...displayMessages.value]
    historyMessagesHasMore.value = !!res.has_more
    recomputeHistoryTokens()
    chatMainRef.value?.restoreAfterPrepend?.(scrollSnapshot)
  } catch {
    ElMessage.error('加载更早消息失败')
  } finally {
    if (sameSessionId(currentSessionId.value, sessionId)) olderMessagesLoading.value = false
  }
}

// ---- Session handlers ----
let shareStatusSequence = 0

const loadConversationShareStatus = async (sessionId) => {
  const sequence = ++shareStatusSequence
  shareStatusLoading.value = true
  try {
    const response = await api.get(`/agents/${agentId}/sessions/${sessionId}/share`)
    if (sequence !== shareStatusSequence || !sameSessionId(currentSessionId.value, sessionId)) return
    shareToken.value = response?.token || ''
  } catch {
    if (sequence === shareStatusSequence && sameSessionId(currentSessionId.value, sessionId)) {
      shareToken.value = ''
    }
  } finally {
    if (sequence === shareStatusSequence) shareStatusLoading.value = false
  }
}

const handleShareConversation = async () => {
  const sessionId = currentSessionId.value
  if (!sessionId || shareLoading.value) return
  if (shareToken.value) {
    shareDialogVisible.value = true
    return
  }
  shareLoading.value = true
  try {
    const response = await api.post(`/agents/${agentId}/sessions/${sessionId}/share`)
    if (!sameSessionId(currentSessionId.value, sessionId)) return
    shareToken.value = response.token
    shareDialogVisible.value = true
  } catch (requestError) {
    ElMessage.error(requestError.response?.data?.detail || '创建分享链接失败')
  } finally {
    shareLoading.value = false
  }
}

const copyShareUrl = async () => {
  if (!shareUrl.value || shareCopying.value) return
  shareCopying.value = true
  try {
    await copyToClipboard(shareUrl.value)
    ElMessage.success('分享链接已复制')
  } catch {
    ElMessage.error('复制失败，请手动复制链接')
  } finally {
    shareCopying.value = false
  }
}

const revokeShare = async () => {
  const sessionId = currentSessionId.value
  if (!sessionId || shareRevoking.value) return
  try {
    await ElMessageBox.confirm(
      '取消后，当前分享链接将立即失效。',
      '取消分享',
      { confirmButtonText: '取消分享', cancelButtonText: '保留分享', type: 'warning' },
    )
  } catch {
    return
  }

  shareRevoking.value = true
  try {
    await api.delete(`/agents/${agentId}/sessions/${sessionId}/share`)
    shareStatusSequence += 1
    shareDialogVisible.value = false
    shareToken.value = ''
    ElMessage.success('已取消分享')
  } catch (requestError) {
    ElMessage.error(requestError.response?.data?.detail || '取消分享失败')
  } finally {
    shareRevoking.value = false
  }
}

const handleSelectSession = async (sessionId) => {
  if (chatDisposed || (props.workbenchChat && !chatRouteActive.value)) return
  if (currentSessionId.value !== null && !currentSessionReadOnly.value) {
    saveSessionDraft(currentSessionId.value, inputText.value)
  }
  sessionViewKey.value += 1
  currentSessionId.value = sessionId
  const targetSession = sessions.value.find(
    session => sameSessionId(session.id, sessionId),
  )
  currentSessionMetadata.value = targetSession || null
  selectedModelId.value = targetSession?.model_id || agent.value?.default_model_id || null
  currentBlocks.value = []
  olderMessagesLoading.value = false
  selectedFiles.value = []
  selectedSkillId.value = null
  inputText.value = isChannelSession(targetSession)
    ? ''
    : (sessionDrafts.get(String(sessionId)) || '')
  const selectedStream = activateStreamForCurrentView()
  router.replace({ query: { ...route.query, session: sessionId } })
  resetTokenStats()  // 清零上个会话残留,避免用量不随会话变化
  const loaded = await fetchMessages(sessionId)
  if (loaded && selectedStream) syncStreamStateToView(selectedStream)
  if (loaded && !findStreamForView() && currentSessionMetadata.value?.active_run_id) {
    void handleSend({ resumeRun: { ...currentSessionMetadata.value } })
  }
  await nextTick()
  chatMainRef.value?.focusInput()
}

watch(currentSessionId, sessionId => {
  shareStatusSequence += 1
  shareDialogVisible.value = false
  shareToken.value = ''
  shareStatusLoading.value = false
  if (sessionId) loadConversationShareStatus(sessionId)
})

const handleNewSession = () => {
  if (currentSessionId.value !== null && !currentSessionReadOnly.value) {
    saveSessionDraft(currentSessionId.value, inputText.value)
  }
  messageLoadSequence += 1
  historyMessagesLoading.value = false
  historyMessagesLoadFailed.value = false
  sessionViewKey.value += 1
  currentSessionId.value = null
  currentSessionMetadata.value = null
  selectedModelId.value = agent.value?.default_model_id || null
  displayMessages.value = []
  historyMessagesHasMore.value = false
  olderMessagesLoading.value = false
  currentBlocks.value = []
  selectedFiles.value = []
  selectedSkillId.value = null
  inputText.value = ''
  activateStreamForCurrentView()
  resetTokenStats()
  if (chatRouteActive.value && route.query.session) {
    const query = { ...route.query }
    delete query.session
    router.replace({ query })
  }
  nextTick(() => chatMainRef.value?.focusInput())
}

let personalSkillsRequest = null
const fetchPersonalSkills = () => {
  if (!props.personalChat || chatDisposed) return Promise.resolve(false)
  if (personalSkillsRequest) return personalSkillsRequest
  agentSkillsLoading.value = true
  personalSkillsRequest = assetsApi.getAvailableSkills().then(catalog => {
    if (chatDisposed) return false
    agentSkills.value = (catalog?.items || [])
      .map(skill => ({
        id: skill.skill_id,
        name: skill.name,
        conversation_examples: skill.conversation_examples || [],
      }))
    return true
  }).catch(() => {
    if (!chatDisposed) agentSkills.value = []
    return false
  }).finally(() => {
    personalSkillsRequest = null
    if (!chatDisposed) {
      agentSkillsLoading.value = false
      personalSkillsLoaded.value = true
    }
  })
  return personalSkillsRequest
}

const refreshModels = async () => {
  if (!isValidId || modelsLoading.value || chatDisposed) return
  modelsLoading.value = true
  try {
    const result = await api.get(`/agents/${agentId}/models`)
    if (!chatDisposed) agentModels.value = result.items || []
  } catch (error) {
    if (!chatDisposed) ElMessage.error('模型列表刷新失败，请稍后重试')
  } finally {
    modelsLoading.value = false
  }
}

const fetchIdentityMcpStatus = async () => {
  try {
    const result = props.personalChat
      ? await assetsApi.getMcpConnections()
      : await api.get(`/agents/${agentId}`)
    identityMcpNames.value = (props.personalChat ? (result?.items || []) : (result?.mcp_connections || []))
      .filter(connection => (!connection.status || connection.status === 'active') && connection.auth_mode === 'current_user')
      .map(connection => connection.name)
  } catch {
    identityMcpNames.value = []
  }
}

const applySkillExample = async () => {
  const example = route.query.skillExample
  if (!chatRouteActive.value || props.embedded || typeof example !== 'string' || !example.trim()) return false
  const skillId = Number(route.query.skillExampleId)
  handleNewSession()
  const viewKey = sessionViewKey.value
  const query = { ...route.query }
  delete query.skillExample
  delete query.skillExampleId
  delete query.session
  await router.replace({ query })
  syncInstalledSkills()
  // Resolve the installed skill before filling the composer so the first send
  // carries the skill reference, even when the chat was already mounted.
  await Promise.all([fetchAgent(), fetchPersonalSkills()])
  if (!chatRouteActive.value || sessionViewKey.value !== viewKey || inputText.value) return true
  if (Number.isSafeInteger(skillId) && skillId > 0) {
    const skill = agentSkills.value.find(item => item.id === skillId)
    if (!skill) {
      ElMessage.warning('该技能暂不可用，请检查安装状态')
      return true
    }
    selectedSkillId.value = skill.id
  }
  inputText.value = example
  nextTick(() => chatMainRef.value?.focusInput())
  return true
}

watch(() => [route.name, route.query.session, route.query.agent, route.query.skillExample], async ([name, value], [previousName]) => {
  if (props.workbenchChat && !chatRouteActive.value) {
    shareDialogVisible.value = false
    workspaceOpen.value = false
    return
  }
  if (expertWorkspace && !chatRouteActive.value) {
    shareDialogVisible.value = false
    workspaceOpen.value = false
    return
  }
  if (expertWorkspace && name !== previousName) {
    if (!route.query.skillExample) fetchAgent()
    fetchIdentityMcpStatus()
    fetchUsableTemplates()
  }
  if (props.workbenchChat && !props.personalChat && name !== previousName) {
    if (!route.query.skillExample) fetchAgent()
    fetchIdentityMcpStatus()
    fetchUsableTemplates()
  }
  if (props.personalChat && !props.embedded && name !== 'WorkspaceChat') {
    shareDialogVisible.value = false
    workspaceOpen.value = false
    return
  }
  if (props.personalChat && name !== previousName) {
    if (!route.query.skillExample) fetchPersonalSkills()
    fetchIdentityMcpStatus()
    fetchUsableTemplates()
  }
  if (route.query.skillExample && await applySkillExample()) return
  const requestedSessionId = Number.parseInt(value, 10)
  if (Number.isInteger(requestedSessionId) && requestedSessionId > 0) {
    if (!sameSessionId(requestedSessionId, currentSessionId.value)) {
      await handleSelectSession(requestedSessionId)
    }
    return
  }
  if (currentSessionId.value !== null) handleNewSession()
})

const openMobileSidebar = () => {
  workspaceOpen.value = false
  mobileSidebarOpen.value = true
}

const handleSidebarNewSession = async () => {
  mobileSidebarOpen.value = false
  if (props.workbenchChat && !chatRouteActive.value) {
    await router.push({ path: '/workspace/chat', query: props.personalChat ? {} : { agent: agentId } })
  }
  if (expertWorkspace && !chatRouteActive.value) await router.push(`/admin/agents/${agentId}/chat`)
  if (props.personalChat && !props.embedded && route.name !== 'WorkspaceChat') await router.push('/workspace/chat')
  handleNewSession()
}

const handleSidebarSelectSession = async (sessionId) => {
  mobileSidebarOpen.value = false
  if (props.workbenchChat && !chatRouteActive.value) {
    await router.push({ path: '/workspace/chat', query: {
      ...(props.personalChat ? {} : { agent: agentId }), session: sessionId,
    } })
    return
  }
  if (expertWorkspace && !chatRouteActive.value) {
    await router.push({ path: `/admin/agents/${agentId}/chat`, query: { session: sessionId } })
    return
  }
  if (props.personalChat && !props.embedded && route.name !== 'WorkspaceChat') {
    await router.push({ path: '/workspace/chat', query: { session: sessionId } })
    return
  }
  await handleSelectSession(sessionId)
}

const handleDeleteSession = async (sessionId) => {
  const session = sessions.value.find(item => sameSessionId(item.id, sessionId))
  if (isChannelSession(session)) {
    ElMessage.warning(`${getSessionChannel(session).displayName} 会话为只读记录`)
    return
  }
  try {
    await ElMessageBox.confirm('确定删除此会话？', '提示', { type: 'warning' })
    await api.delete(`/agents/${agentId}/sessions/${sessionId}`)
    sessionDrafts.delete(String(sessionId))
    persistSessionDrafts()
    if (currentSessionId.value === sessionId) handleNewSession()
    fetchSessions()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// ---- Send / Stop ----
const handleSend = async (options = {}) => {
  if (historyMessagesLoading.value || historyMessagesLoadFailed.value) return
  const resumeRun = options?.resumeRun
  if (currentSessionReadOnly.value) {
    ElMessage.warning(readonlyWarning())
    return
  }
  if (pendingFileUploads.value) return
  const content = inputText.value.trim() || (selectedFiles.value.length ? '请分析所附文件。' : '')
  if (!content && !resumeRun) return
  if (findStreamForView()) {
    ElMessage.warning('当前已有会话正在响应，请等待完成后再发送')
    return
  }
  const sendSessionId = currentSessionId.value
  const sendViewKey = sessionViewKey.value
  const optimisticUserId = 'u-' + Date.now()
  const attachedFiles = [...selectedFiles.value]
  const referencedSkillId = selectedSkillId.value
  let submissionReported = false
  const reportSubmission = error => {
    if (submissionReported) return
    submissionReported = true
    options?.onSubmissionResult?.(error)
  }
  const selectedSkill = agentSkills.value.find(skill => skill.id === referencedSkillId)
  const skillReference = selectedSkill ? { id: selectedSkill.id, name: selectedSkill.name } : null
  const streamState = createStreamState({
    userContent: content,
    requestedSessionId: sendSessionId,
    viewKey: sendViewKey,
    startedAt: resumeRun
      ? parseBackendDateTime(resumeRun.active_run_started_at)?.getTime()
      : null,
  })
  if (resumeRun) {
    streamState.runId = resumeRun.active_run_id
    streamState.sessionId = sendSessionId
    streamState.phase = resumeRun.active_run_status || 'running'
    streamState.resuming = true
  } else {
    streamState.idempotencyKey = globalThis.crypto?.randomUUID?.()
      || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  }
  const runSequence = ++streamSequence
  streamState.sequence = runSequence
  streamState.abortController = new AbortController()
  streamStates.value = [...streamStates.value, streamState]
  let referencesCleared = false
  const clearSubmittedReferences = () => {
    if (referencesCleared || !isActiveStreamState(streamState) || !isStreamVisibleInCurrentView(streamState)
      || sessionViewKey.value !== sendViewKey) return
    // Only clear composer selections; the request and message retain their own attachments.
    selectedFiles.value = selectedFiles.value.filter(path => !attachedFiles.includes(path))
    if (selectedSkillId.value === referencedSkillId) selectedSkillId.value = null
    referencesCleared = true
  }

  lastRunFailure.value = null
  currentRunPhase.value = 'connecting'

  if (!resumeRun) {
    displayMessages.value = [...displayMessages.value, {
      id: optimisticUserId,
      role: 'user',
      created_at: new Date().toISOString(),
      content,
      attachedFiles,
      skill: skillReference,
      images: messageImages(attachedFiles),
      _html: renderMarkdown(content),
    }]
    inputText.value = ''
  }
  // 用户消息本身没有 runtime usage，待本轮完成后统一汇总真实指标。
  recomputeHistoryTokens()

  // 用户消息追加后立即平滑滚动到底，避免新消息被输入区遮挡
  chatMainRef.value?.scrollToBottom()

  currentBlocks.value = []
  currentRunId.value = null
  permissionQueue.value = []
  activeStreamState.value = streamState
  streamingSessionId.value = sendSessionId
  if (!resumeRun) touchStreamingSessionInList(sendSessionId, content)
  streamingViewKey.value = sendViewKey
  streaming.value = true
  syncStreamStateToView(streamState)

  try {
    const requestBody = JSON.stringify({
      content,
      session_id: sendSessionId,
      model_id: selectedModelId.value,
      skill_id: referencedSkillId,
      attached_files: attachedFiles,
      permission_mode: permissionMode.value,
      page_context: props.embedded ? props.pageContext : null,
    })
    const controller = streamState.abortController
    let reconnectAttempt = 0
    while (!chatDisposed && !controller.signal.aborted) {
      try {
        const reconnecting = !!streamState.runId
        const url = reconnecting
          ? `/aihub/api/agents/${agentId}/runs/${streamState.runId}/events?after=${streamState.lastEventId || 0}`
          : `/aihub/api/agents/${agentId}/messages`
        const request = token => fetch(url, {
          method: reconnecting ? 'GET' : 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
            ...(reconnecting || !streamState.idempotencyKey
              ? {}
              : { 'Idempotency-Key': streamState.idempotencyKey }),
          },
          ...(reconnecting ? {} : { body: requestBody }),
          signal: controller.signal,
        })
        let resp = await request(await getAccessTokenForRequest())
        if (resp.status === 401) resp = await request(await refreshAccessToken())
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}))
          const detail = body?.detail
          const error = new Error((typeof detail === 'string' ? detail : detail?.message) || `HTTP ${resp.status}`)
          error.httpStatus = resp.status
          throw error
        }
        await readAgentStream(resp, streamState, evt => {
          handleSseEvent(evt, streamState)
          if (evt.type === 'run_queued' || evt.type === 'run_start') {
            reportSubmission()
            if (!resumeRun) clearSubmittedReferences()
            if (streamState.stopRequested) {
              streamState.stopRequested = false
              streamState.phase = 'queued'
              void handleStop(streamState)
            }
          }
          reconnectAttempt = 0
        })
        // Older servers have no event IDs or stream_end; accept their terminal
        // event at EOF while new streams wait for durable settlement completion.
        if (streamState.streamEnded || (!streamState.lastEventId && streamState.terminalEventReceived)) break
        throw new Error('连接已断开，正在恢复响应')
      } catch (error) {
        if (chatDisposed || controller.signal.aborted) break
        if (error.httpStatus && error.httpStatus < 500) throw error
        if (!streamState.runId && reconnectAttempt >= 3) throw error
        // Before a run id is visible, retry the POST with the same
        // Idempotency-Key. Once a run id is known, retry only the read endpoint.
        streamState.contextNotice = streamState.runId
          ? '连接已断开，正在重新连接；任务仍在后台运行。'
          : '提交连接已断开，正在安全重试。'
        scheduleStreamStateSync(streamState)
        await new Promise(resolve => window.setTimeout(resolve, Math.min(5000, 500 * 2 ** Math.min(reconnectAttempt++, 4))))
        streamState.contextNotice = ''
      }
    }
  } catch (e) {
    const shouldNotify = isStreamVisibleInCurrentView(streamState)
    if (e.name === 'AbortError') {
      // Disposing the view closes only the observer; the task continues.
    } else {
      streamState.phase = 'failed'
      streamState.failed = true
      streamState.error = e?.message || '网络连接异常，请重试'
      if (streamState.blocks.length === 0) {
        if (shouldNotify) {
          displayMessages.value = displayMessages.value.filter(message => message.id !== optimisticUserId)
          inputText.value = content
          recomputeHistoryTokens()
        }
      }
      if (shouldNotify) ElMessage.error('发送失败：' + streamState.error)
    }
  } finally {
    reportSubmission(streamState.error || 'AI Hub 未确认接收任务，请检查边栏后重试')
    if (chatDisposed) return
    const shouldUpdateVisibleSession = isStreamVisibleInCurrentView(streamState)
    const wasStopped = streamState.phase === 'stopping' || streamState.cancelled
    if (!wasStopped && !streamState.failed && !streamState.terminalEventReceived) {
      streamState.phase = 'failed'
      streamState.failed = true
      streamState.error = '连接意外中断，请重试'
    }
    if (shouldUpdateVisibleSession && sessionViewKey.value === sendViewKey
      && !streamState.failed && (streamState.terminalEventReceived || streamState.runId)) {
      clearSubmittedReferences()
    }
    if (shouldUpdateVisibleSession && streamState.failed) {
      recordRunFailure(streamState)
    }
    _finalizeThinking(streamState)
    _finalizeToolUse(streamState)
    if (shouldUpdateVisibleSession) {
      pendingStreamState = streamState
      flushStreamStateToView()
    }
    if (shouldUpdateVisibleSession && streamState.blocks.length > 0) {
      currentBlocks.value = []
      upsertStreamAssistantMessage(streamState)
    }
    if (shouldUpdateVisibleSession && sendSessionId === null && !currentSessionId.value && streamState.sessionId) {
      currentSessionId.value = streamState.sessionId
    }
    streamState.finished = true
    streamStates.value = streamStates.value.filter(item => toRaw(item) !== toRaw(streamState))
    if (toRaw(activeStreamState.value) === toRaw(streamState)) activateStreamForCurrentView()
    if (wasStopped && shouldUpdateVisibleSession) ElMessage.info('已停止')
    if (shouldUpdateVisibleSession) chatMainRef.value?.followStream?.()
    if (shouldUpdateVisibleSession && !currentSessionReadOnly.value) {
      chatMainRef.value?.focusInput()
    }
    // 对话结束后刷新文件树（工具可能已写入文件）
    scheduleWorkspaceRefresh()
    await fetchSessions({ silent: true })
    await fetchCredits()
    if (resumeRun && !findStreamForView() && shouldUpdateVisibleSession && sameSessionId(currentSessionId.value, streamState.sessionId)) {
      await fetchMessages(streamState.sessionId)
    }
    if (shouldUpdateVisibleSession && sendSessionId === null && !currentSessionId.value) {
      currentSessionId.value = sessions.value[0]?.id || null
    }
    // 后端 run_agent_chat 已经保存 user/assistant；这里不能再 POST /messages，
    // 否则 DB 历史会重复，下一轮 prompt 会膨胀。
  }
}

const handleStop = async (targetStreamState = activeStreamState.value) => {
  const streamState = targetStreamState
  if (!streamState || streamState.phase === 'stopping') return

  const previousPhase = streamState.phase
  const runId = streamState.runId
    || (toRaw(streamState) === toRaw(activeStreamState.value) ? currentRunId.value : null)
  streamState.phase = 'stopping'
  syncStreamStateToView(streamState)

  if (!runId) {
    streamState.stopRequested = true
    return
  }

  try {
    await api.post(`/agents/${agentId}/runs/${runId}/cancel`)
    // Keep reading the SSE response so the backend can finish cancellation and
    // close the stream. Aborting here would make the final state ambiguous.
  } catch (e) {
    if (isActiveStreamState(streamState) && streamState.phase === 'stopping') {
      streamState.phase = previousPhase
      syncStreamStateToView(streamState)
    }
    ElMessage.error(e.response?.data?.detail || '停止失败，请重试')
  }
}

const handleRemoveChip = (chip) => {
  if (chip.type === 'skill') {
    selectedSkillId.value = null
  } else if (chip.type === 'file' && chip.path) {
    selectedFiles.value = selectedFiles.value.filter(f => f !== chip.path)
  }
}

const handleClearChips = () => {
  selectedSkillId.value = null
  selectedFiles.value = []
}

const handleFillInput = (text) => {
  if (currentSessionReadOnly.value) return
  inputText.value = text
  nextTick(() => chatMainRef.value?.focusInput())
}

// ---- Permission ----
const handlePermissionDecide = async (p, decision, remember) => {
  if (permissionSubmittingIds.value.includes(p.req_id)) return
  const runId = p.run_id || currentRunId.value
  if (!runId) {
    ElMessage.error('授权请求缺少运行标识')
    return
  }
  permissionSubmittingIds.value = [...permissionSubmittingIds.value, p.req_id]
  let resolved = false
  try {
    const result = await api.post(`/agents/${agentId}/permission/decide`, {
      run_id: runId,
      req_id: p.req_id,
      decision,
      remember,
      tool_key: p.tool_key,
    })
    if (!result?.ok) {
      if (result?.resolved) {
        resolved = true
        ElMessage.info(result.detail || '该授权请求已失效')
        return
      }
      ElMessage.error(result?.detail || '授权未生效，请重试')
      return
    }
    resolved = true
  } catch (e) {
    ElMessage.error('授权提交失败')
  } finally {
    permissionSubmittingIds.value = permissionSubmittingIds.value.filter(id => id !== p.req_id)
    if (!resolved) return
    const streamState = findStreamByRunId(runId)
    if (streamState) {
      streamState.resolvedPermissionIds.add(p.req_id)
      streamState.permissionQueue = streamState.permissionQueue.filter(item => item.req_id !== p.req_id)
      if (streamState.permissionQueue.length === 0 && streamState.phase === 'waiting_permission') {
        streamState.phase = 'running'
      }
      syncStreamStateToView(streamState)
    }
    if (streamState && isStreamVisibleInCurrentView(streamState)) {
      permissionQueue.value = permissionQueue.value.filter(item => item.req_id !== p.req_id)
    }
  }
}

// ---- Workspace context files ----
const handleAddWorkspaceFile = (file) => {
  if (!selectedFiles.value.includes(file.path)) {
    selectedFiles.value = [...selectedFiles.value, file.path]
  }
  nextTick(() => chatMainRef.value?.focusInput())
}

// ---- Message actions ----
const handleFeedbackChange = ({ messageId, feedback }) => {
  const message = displayMessages.value.find(item => item.messageId === messageId)
  if (message) message.feedback = feedback
}
const handleRegenerate = (assistantMsg) => {
  if (currentSessionReadOnly.value) {
    ElMessage.warning(readonlyWarning())
    return
  }
  const idx = displayMessages.value.findIndex(m => m.id === assistantMsg.id)
  if (idx < 0) return
  // 找到前面的用户消息
  let userMsg = null
  for (let i = idx - 1; i >= 0; i--) {
    if (displayMessages.value[i].role === 'user') {
      userMsg = displayMessages.value[i]
      break
    }
  }
  if (!userMsg) return
  // 不伪造历史分叉，只把原问题放回输入框，由用户确认后重新提问。
  inputText.value = userMsg.content
  nextTick(() => chatMainRef.value?.focusInput())
}

const handleRetryRun = () => {
  const failure = lastRunFailure.value
  if (!failure || currentSessionReadOnly.value) return
  inputText.value = failure.content || ''
  lastRunFailure.value = null
  nextTick(() => chatMainRef.value?.focusInput())
}

const handleNarrowRetry = () => {
  const failure = lastRunFailure.value
  if (!failure || currentSessionReadOnly.value) return
  inputText.value = `${failure.content || ''}\n\n请缩小读取和命令输出范围后重试：分段读取文件，限制搜索结果，并只返回必要内容。`
  lastRunFailure.value = null
  nextTick(() => chatMainRef.value?.focusInput())
}

const handleContinueRun = () => {
  const failure = lastRunFailure.value
  if (!failure || currentSessionReadOnly.value) return
  inputText.value = '请基于当前已经完成的步骤继续执行，先检查工作区现状，再完成剩余任务。'
  lastRunFailure.value = null
  nextTick(() => chatMainRef.value?.focusInput())
}

const handleUploadFile = async (file) => {
  if (currentSessionReadOnly.value) {
    ElMessage.warning(readonlyWarning())
    return
  }
  if (!file || !file.name) return
  if (file.type.startsWith('image/')) {
    if (!['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type)) {
      ElMessage.error('图片仅支持 PNG、JPEG、GIF 和 WebP 格式')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      ElMessage.error('单张图片不能超过 5 MB')
      return
    }
  }
  const uploadViewKey = sessionViewKey.value
  pendingFileUploads.value += 1
  const formData = new FormData()
  const isImage = file.type.startsWith('image/')
  formData.append(isImage ? 'file' : 'files', file)
  try {
    const res = await api.post(`/agents/${agentId}/${isImage ? 'images' : 'files'}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
    ElMessage.success(file.type.startsWith('image/') ? '图片已添加' : `已上传: ${file.name}`)
    if (!isImage) scheduleWorkspaceRefresh(0)
    // 上传成功后自动添加为引用 chip
    const uploaded = isImage ? (res?.url ? [{ name: res.name, path: res.url }] : []) : res?.uploaded || []
    if (chatDisposed || uploadViewKey !== sessionViewKey.value) return
    for (const u of uploaded) {
      if (isImage) {
        filePreviewUrls.value[u.path] = u.path
      }
      if (!selectedFiles.value.includes(u.path)) {
        selectedFiles.value = [...selectedFiles.value, u.path]
      }
    }
    if (uploaded.length) nextTick(() => chatMainRef.value?.focusInput())
  } catch {
    ElMessage.error(file.type.startsWith('image/') ? '图片上传失败，请重试' : `上传失败: ${file.name}`)
  } finally {
    pendingFileUploads.value -= 1
  }
}

// ---- Model switch ----
const handleSwitchModel = (modelId) => {
  if (currentSessionId.value && currentSessionMetadata.value?.model_id) {
    ElMessage.info('当前会话已固定模型，请新建会话后切换')
    return
  }
  selectedModelId.value = modelId
}

// ---- Skill switch ----
const handleSwitchSkill = (skillId) => {
  selectedSkillId.value = skillId
  nextTick(() => chatMainRef.value?.focusInput())
}

const handleUseWelcomeSuggestion = ({ skillId, prompt }) => {
  if (historyMessagesLoading.value || historyMessagesLoadFailed.value || currentSessionReadOnly.value
    || visibleStreaming.value || pendingFileUploads.value) return
  if (skillId != null) {
    const skill = agentSkills.value.find(item => Number(item.id) === skillId)
    if (!Array.isArray(skill?.conversation_examples)
      || !skill.conversation_examples.some(example => typeof example === 'string' && example.trim() === prompt)) {
      ElMessage.warning('该示例暂不可用，请重新选择')
      return
    }
  }
  inputText.value = inputText.value.trim() ? `${inputText.value}\n\n${prompt}` : prompt
  nextTick(() => chatMainRef.value?.focusInput())
}

const fetchUsableTemplates = async () => {
  try {
    // 与各自资源页使用同一列表：默认工作台 /assets/prompts，专家 /agents/:id。
    // 两者都实时引用作者模板，不能使用个人模板管理列表或历史快照。
    const res = props.personalChat
      ? await assetsApi.getWorkspacePrompts({ skip: 0, limit: 200 })
      : await api.get(`/agents/${agentId}`)
    usableTemplates.value = props.personalChat ? (res?.items || []) : (res?.prompt_templates || [])
  } catch {
    usableTemplates.value = []
  }
}

const fetchCredits = async () => {
  try {
    credit.value = await enterpriseApi.getCredits()
  } catch {
    // 刷新失败时保留已加载的账户及单位，避免消耗文案切换回默认名称。
  }
}

const claimCredits = async () => {
  if (credit.value?.claimed_today) return
  creditClaiming.value = true
  try {
    credit.value = await enterpriseApi.claimDailyCredits()
    window.dispatchEvent(new CustomEvent('aihub:credit-account-updated', { detail: credit.value }))
    ElMessage.success(`${credit.value.display_name}已领取`)
  } catch (error) {
    const detail = error.response?.data?.detail
    const code = detail?.data?.code || error.response?.data?.data?.code
    if (code === 'CREDIT_ALREADY_CLAIMED') await fetchCredits()
    else ElMessage.error(typeof detail === 'string' ? detail : (detail?.message || '领取失败'))
  } finally {
    creditClaiming.value = false
  }
}

const handleCreditAccountUpdated = event => {
  if (event.detail) credit.value = event.detail
}

if (props.embedded && embeddedPrompt) {
  watch([embeddedPrompt.pending, embeddedReady], async ([command, ready], _previous, onCleanup) => {
    if (!command || !ready) return
    let cancelled = false
    onCleanup(() => { cancelled = true })
    const viewKey = sessionViewKey.value
    const skillsLoaded = command.skill === null || await fetchPersonalSkills()
    if (cancelled || chatDisposed || command !== embeddedPrompt.pending.value) return
    const finish = error => embeddedPrompt.finish(command, error)
    if (command.expiresAt <= Date.now()) return finish('提示词提交已超时')
    if (!agent.value) return finish('AI 助手尚未就绪，请重试')
    if (!skillsLoaded) return finish('技能列表加载失败，请重试')

    const matches = command.skill === null ? [] : agentSkills.value.filter(skill =>
      typeof command.skill === 'number' ? skill.id === command.skill : skill.name === command.skill)
    if (command.skill !== null && !matches.length) return finish('指定技能不可用，请检查技能是否已安装')
    if (matches.length > 1) return finish('存在同名技能，请使用技能 ID')
    if (viewKey !== sessionViewKey.value || pendingFileUploads.value || selectedFiles.value.length ||
      (currentSessionId.value === null && (inputText.value.trim() || findStreamForView()))) {
      return finish('请先处理 AI Hub 边栏中当前的对话或草稿，再重试')
    }

    handleNewSession()
    selectedSkillId.value = matches[0]?.id ?? null
    inputText.value = command.prompt
    // Only acknowledge the server's run_queued/run_start event; HTTP 200 alone is insufficient.
    try {
      await handleSend({ onSubmissionResult: finish })
      finish('AI Hub 暂时无法发送，请检查边栏后重试')
    } catch (error) {
      finish(error?.message || 'AI Hub 发送失败，请检查边栏后重试')
    }
  }, { immediate: true })
}

// ---- Init ----
onMounted(async () => {
  window.addEventListener('aihub:credit-account-updated', handleCreditAccountUpdated)
  if (workspaceSidebar && isValidId) workspaceSidebar.newSession.value = handleSidebarNewSession
  if (!isValidId) return  // 路由 id 非法（如 new/null/undefined），不发请求避免 422
  if (!credit.value) fetchCredits()
  fetchRuntimes()
  fetchUsableTemplates()
  const requestedSessionId = chatRouteActive.value && route.query.session ? parseInt(route.query.session, 10) : null
  // Auxiliary lists must not delay the initial composer focus.
  fetchPersonalSkills()
  fetchIdentityMcpStatus()
  fetchSessions()
  syncInstalledSkills()
  await Promise.all([
    fetchAgent(),
    requestedSessionId ? handleSelectSession(requestedSessionId) : Promise.resolve(),
  ])
  await applySkillExample()
  embeddedReady.value = true
  await nextTick()
  if (chatRouteActive.value) chatMainRef.value?.focusInput()
})

onBeforeUnmount(() => {
  chatDisposed = true
  streamStates.value.forEach(streamState => streamState.abortController?.abort())
  window.clearTimeout(sessionStatusTimer)
  Object.values(filePreviewUrls.value).forEach(url => URL.revokeObjectURL(url))
  window.removeEventListener('aihub:credit-account-updated', handleCreditAccountUpdated)
  if (workspaceSidebar) workspaceSidebar.newSession.value = null
  window.clearTimeout(draftSaveTimer)
  if (currentSessionId.value !== null && !currentSessionReadOnly.value) {
    saveSessionDraft(currentSessionId.value, inputText.value)
  }
  window.clearTimeout(workspaceRefreshTimer)
  if (streamRenderTimer !== null) window.clearTimeout(streamRenderTimer)
  pendingStreamState = null
})
</script>

<style scoped>
.agent-chat-page {
  --workspace-panel-width: 0px;
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}

.agent-chat--embedded .mobile-chat-toolbar { display: flex; min-height: 44px; align-items: center; padding: 4px 12px; gap: 8px; border-bottom: 1px solid #eef0f3; box-sizing: border-box; }
.agent-chat--embedded .mobile-chat-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: center; font-size: 13px; font-weight: 500; }
.agent-chat--embedded .mobile-chat-toolbar { gap: 4px; flex-shrink: 0; }
.agent-chat--embedded .mobile-chat-toolbar > .el-button { width: 32px; min-width: 32px; height: 32px; margin: 0; }
.embed-chat-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.embed-chat-actions .header-tool-button.el-button { width: 32px; min-width: 32px; height: 32px; }
.agent-chat--embedded .mobile-chat-toolbar :deep(.el-icon) { font-size: 14px; }
.agent-chat--embedded .agent-chat-body { margin-right: 0; }
.agent-chat--embedded .workspace-panel.open { width: min(88%, 360px); box-shadow: -2px 0 8px #0002; z-index: 1050; }
.agent-chat--embedded .workspace-panel.open.expanded { width: 100%; }
.agent-chat--embedded :deep(.chat-sidebar) { display: none; }
.agent-chat--embedded :deep(.chat-sidebar.mobile-open) { display: flex; position: absolute; top: 0; bottom: 0; left: 0; width: min(280px, 85%); height: 100%; transform: none; z-index: 1101; }
.agent-chat--embedded .mobile-sidebar-backdrop { display: block; position: absolute; inset: 0; z-index: 1100; background: #0005; }
.agent-chat--embedded :deep(.welcome-title) { font-size: 22px; }

.agent-chat-page.workspace-open {
  --workspace-panel-width: 312px;
}

.agent-chat-page.workspace-open.workspace-expanded {
  --workspace-panel-width: min(48vw, 620px);
}

.agent-chat-body {
  margin-right: var(--workspace-panel-width);
  transition: margin-right 0.2s ease;
}

.agent-chat-body {
  position: relative;
  min-height: 0;
  flex: 1;
  display: flex;
  overflow: hidden;
}

.agent-chat-sidebar {
  display: flex;
  flex: 0 0 264px;
  flex-direction: column;
  width: 264px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--workspace-panel-bg, #fafafa);
}

.agent-chat-sidebar :deep(.agent-workspace-nav) {
  width: 100%;
  flex: 0 0 auto;
  border-right: 0;
  border-bottom: 1px solid var(--workspace-border, #e7e9ec);
}

.agent-history-sidebar {
  display: flex;
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.agent-chat-sidebar--plain,
.agent-chat-sidebar--plain .agent-history-sidebar {
  display: contents;
}

.chat-center {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
}

.mobile-chat-toolbar,
.mobile-sidebar-backdrop {
  display: none;
}

.chat-center :deep(.chat-main) {
  min-height: 0;
}

.chat-center.channel-readonly :deep(.input-area),
.chat-center.channel-readonly :deep(.context-chips-bar) {
  display: none;
}

.readonly-bar {
  width: min(840px, calc(100% - 40px));
  min-height: 50px;
  margin: 0 auto;
  padding: 8px 48px 8px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  color: #529b2e;
  background: #f0f9eb;
  border: 1px solid #c2e7b0;
  border-radius: 6px 6px 0 0;
  box-sizing: border-box;
}

.readonly-bar--dingtalk {
  color: #1677ff;
  background: #ecf5ff;
  border-color: #b3d8ff;
}

.readonly-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.agent-invalid {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: #fff;
}

/* 右侧工作区面板 */
.workspace-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 30;
  display: flex;
  flex: 0 0 0;
  height: auto;
  background: #fff;
  transition: width 0.2s ease, flex-basis 0.2s ease;
  width: 0;
  overflow: hidden;
  box-sizing: border-box;
}

.agent-chat-page :deep(.workspace-identity) {
  border-right: 0;
  background: #fff;
}

.header-tool-wrap {
  position: relative;
  display: inline-flex;
}

.header-tool-button.el-button {
  width: 34px;
  min-width: 34px;
  height: 34px;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 9px;
  color: #787878;
  font-size: 16px;
  background: transparent;
}

.header-tool-button.el-button:hover,
.header-tool-button.el-button:focus-visible,
.header-tool-button.el-button.is-active {
  color: #202329;
  background: #efefef;
}

.header-tool-button.el-button.is-disabled {
  color: #b7bbc2;
  background: transparent;
}

.header-tool-dot {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 6px;
  height: 6px;
  border: 1px solid #fff;
  border-radius: 50%;
  background: #f05252;
  box-sizing: border-box;
  pointer-events: none;
}

.share-dialog-description {
  margin: 0 0 14px;
  color: #606266;
  font-size: 13px;
  line-height: 20px;
}
.workspace-panel.open {
  width: 312px;
  flex-basis: 312px;
  border-left: 1px solid #e8eae8;
}
.workspace-panel.open.expanded {
  width: min(48vw, 620px);
  flex-basis: min(48vw, 620px);
}

.workspace-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.workspace-body :deep(.workspace-tree) {
  flex: 1;
  min-height: 0;
}

@media (max-width: 900px) {
  .agent-chat-page {
    --workspace-panel-width: 0px;
  }

  .mobile-sidebar-backdrop {
    position: fixed;
    inset: 102px 0 0;
    display: block;
    z-index: 1100;
    background: rgba(0, 0, 0, 0.32);
  }

  .agent-chat--expert .mobile-sidebar-backdrop {
    position: absolute;
    inset: 0;
  }

  .agent-chat--expert :deep(.chat-sidebar) {
    position: absolute;
    top: 0;
  }

  .mobile-chat-toolbar {
    min-height: 44px;
    padding: 4px 8px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
    background: #fff;
    border-bottom: 1px solid #eef0f3;
    box-sizing: border-box;
  }

  .mobile-chat-title {
    min-width: 0;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: center;
    font-size: 14px;
    font-weight: 600;
    color: #303133;
  }

  .workspace-panel {
    top: 0;
    right: 0;
    bottom: 0;
    height: auto;
    flex-basis: 0;
    z-index: 1050;
    box-shadow: -2px 0 8px rgba(0, 0, 0, 0.12);
  }

  .workspace-panel.open {
    width: min(88vw, 320px);
  }

  .workspace-panel.open.expanded {
    width: min(96vw, 620px);
  }

  .readonly-bar {
    min-height: auto;
    padding: 8px 40px 8px 12px;
    flex-wrap: wrap;
  }

  .readonly-status {
    flex: 1 1 160px;
  }

  .readonly-bar :deep(.el-button) {
    margin-left: auto;
  }
}

@media (max-width: 480px) {
  .readonly-bar {
    align-items: flex-start;
  }
}
@media (max-width: 720px) {
  .agent-chat-body { flex-direction: column; }
  .agent-chat-sidebar:not(.agent-chat-sidebar--plain) {
    width: 100%;
    flex: 0 0 auto;
  }
  .agent-chat-sidebar:not(.agent-chat-sidebar--plain) .agent-history-sidebar {
    display: contents;
  }
}
</style>
