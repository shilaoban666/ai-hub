<template>
  <AgentChat
    v-if="selectedAgentId || assistantId"
    :key="selectedAgentId || assistantId"
    :agent-id-override="selectedAgentId || assistantId"
    :personal-chat="!selectedAgentId"
    :workbench-chat="!embedded"
    :embedded="embedded"
    :page-context="pageContext"
    :initial-bootstrap="bootstrapData"
  />
  <template v-else-if="loading">
    <Teleport v-if="workspaceSidebar?.enabled.value" to="#workspace-history" defer>
      <ChatSidebar class="chat-sidebar--integrated" integrated compact-history sessions-loading inert />
    </Teleport>
    <div class="bootstrap-loading" aria-busy="true" aria-label="正在加载工作台">
      <AgentWorkspaceHeader personal-chat />
      <ChatMain inert send-locked :history-loading="!!route.query.session" />
      <p v-if="slowLoading" class="bootstrap-progress" role="status">正在准备工作台，首次加载或网络较慢时可能需要一点时间…</p>
    </div>
  </template>
  <div v-else class="bootstrap-page">
    <el-result
      icon="warning"
      title="AI 工作台暂不可用"
      :sub-title="errorMessage"
    >
      <template #extra>
        <el-button :icon="Refresh" @click="bootstrap">重试</el-button>
        <el-button
          v-if="authStore.user?.is_superuser && errorSettings"
          type="primary"
          :icon="Setting"
          @click="router.push(errorSettings.path)"
        >
          {{ errorSettings.label }}
        </el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup>
import { inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh, Setting } from '@element-plus/icons-vue'
import { enterpriseApi } from '@/api/enterprise'
import { useAuthStore } from '@/stores/auth'
import { bootstrapFailure } from '@/utils/bootstrap-error'
import AgentChat from './AgentChat.vue'
import AgentWorkspaceHeader from './components/AgentWorkspaceHeader.vue'
import ChatMain from './components/ChatMain.vue'
import ChatSidebar from './components/ChatSidebar.vue'

const router = useRouter()
defineProps({
  selectedAgentId: { type: Number, default: 0 },
  embedded: { type: Boolean, default: false },
  pageContext: { type: Object, default: null },
})
const emit = defineEmits(['ready', 'identity', 'loading'])
const route = useRoute()
const workspaceSidebar = inject('workspaceSidebar', null)
const authStore = useAuthStore()
const loading = ref(true)
const errorMessage = ref('')
const errorSettings = ref(null)
const slowLoading = ref(false)
let bootstrapController = null
let disposed = false
const assistantId = ref(null)
const bootstrapData = ref(null)
const handleCreditAccountUpdated = event => {
  if (bootstrapData.value && event.detail) bootstrapData.value.credit = event.detail
}

const bootstrap = async () => {
  if (bootstrapController || disposed) return
  bootstrapController = new AbortController()
  const signal = bootstrapController.signal
  const slowTimer = window.setTimeout(() => { slowLoading.value = true }, 5000)
  loading.value = true
  emit('loading', true)
  errorMessage.value = ''
  errorSettings.value = null
  slowLoading.value = false
  assistantId.value = null
  bootstrapData.value = null
  try {
    const result = await enterpriseApi.bootstrap({ signal })
    if (disposed) return
    const resolvedAssistantId = Number(result.assistant_id)
    if (!Number.isInteger(resolvedAssistantId) || resolvedAssistantId <= 0) {
      throw new Error('默认助手配置无效')
    }
    bootstrapData.value = result
    assistantId.value = resolvedAssistantId
    emit('ready', resolvedAssistantId)
    emit('identity', result.assistant || {
      id: resolvedAssistantId, name: result.assistant_name || '默认助手', icon: result.assistant_icon || 'H',
    })
  } catch (error) {
    if (disposed || error.code === 'ERR_CANCELED') return
    const failure = bootstrapFailure(error)
    errorMessage.value = failure.message
    errorSettings.value = failure.settings
  } finally {
    window.clearTimeout(slowTimer)
    bootstrapController = null
    slowLoading.value = false
    if (!disposed) {
      loading.value = false
      emit('loading', false)
    }
  }
}

onMounted(() => {
  window.addEventListener('aihub:credit-account-updated', handleCreditAccountUpdated)
  bootstrap()
})
onBeforeUnmount(() => {
  disposed = true
  bootstrapController?.abort()
  window.removeEventListener('aihub:credit-account-updated', handleCreditAccountUpdated)
})
</script>

<style scoped>
.bootstrap-loading {
  position: relative;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}
.bootstrap-progress {
  position: absolute;
  top: 35%;
  align-self: center;
  max-width: calc(100% - 48px);
  color: #727780;
  font-size: 14px;
  line-height: 1.6;
  text-align: center;
}
.bootstrap-page {
  height: 100%;
  min-height: 100%;
  display: grid;
  place-items: center;
  background: #fafafa;
}
</style>
