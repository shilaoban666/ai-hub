<template>
  <main class="conversation-share-page">
    <header v-if="share" class="share-header">
      <div class="share-heading">
        <span class="agent-name">{{ share.agent_name }}</span>
        <h1>{{ share.title || '对话分享' }}</h1>
      </div>
      <time v-if="share.shared_at" :datetime="share.shared_at">
        分享于 {{ formatDate(share.shared_at) }}
      </time>
    </header>

    <section v-if="error" class="share-state">
      <el-result icon="warning" title="无法查看该对话" :sub-title="error" />
    </section>

    <section v-else class="conversation-view" v-loading="loading">
      <ChatMain
        ref="chatMainRef"
        :display-messages="displayMessages"
        :history-loading="loading"
        :agent-name="share?.agent_name || ''"
        :agent-icon="share?.agent_icon || 'H'"
        :scrollbar-right-offset="5"
        view-only
        allow-reply-copy
      />
    </section>
  </main>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import api from '@/api/request'
import { mergeToolBlocks } from '@/utils/agent-chat-blocks'
import { formatBeijingDateTime, parseBackendDateTime } from '@/utils/date-time'
import { renderMarkdown } from '@/utils/markdown'
import ChatMain from '@/views/admin/components/ChatMain.vue'

const route = useRoute()
const token = String(route.params.token || '')
const chatMainRef = ref(null)
const share = ref(null)
const displayMessages = ref([])
const loading = ref(true)
const error = ref('')

const usageNumber = (usage, ...keys) => {
  for (const key of keys) {
    const value = Number(usage?.[key])
    if (Number.isFinite(value)) return value
  }
  return null
}

const buildTurnMetrics = (usage, durationMs) => {
  const inputTokens = usageNumber(usage, 'input_tokens', 'prompt_tokens')
  const outputTokens = usageNumber(usage, 'output_tokens', 'completion_tokens')
  const cacheReadTokens = usageNumber(usage, 'cache_read_input_tokens', 'cache_read_tokens')
  const cacheCreationTokens = usageNumber(usage, 'cache_creation_input_tokens', 'cache_creation_tokens')
  const reportedTotal = usageNumber(usage, 'total_tokens')
  const tokenParts = [inputTokens, outputTokens, cacheReadTokens, cacheCreationTokens]
  const hasTokenBreakdown = tokenParts.some(value => value !== null)
  const numericDuration = durationMs === null || durationMs === undefined ? null : Number(durationMs)

  return {
    durationMs: Number.isFinite(numericDuration) && numericDuration >= 0 ? numericDuration : null,
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
  }
}

const mapMessages = items => items.map((message, index) => {
  if (message.role === 'assistant') {
    let payload = null
    let blocks
    try {
      payload = JSON.parse(message.content)
      blocks = payload
    } catch {
      blocks = [{ type: 'text', content: message.content }]
    }
    if (blocks && typeof blocks === 'object' && blocks.blocks) blocks = blocks.blocks
    if (!Array.isArray(blocks)) blocks = [{ type: 'text', content: String(message.content || '') }]
    const previous = items[index - 1]
    const previousCreatedAt = parseBackendDateTime(previous?.created_at)
    const messageCreatedAt = parseBackendDateTime(message.created_at)
    const legacyDuration = previous?.role === 'user' && previous.created_at && message.created_at
      && previousCreatedAt && messageCreatedAt
      ? Math.max(0, messageCreatedAt.getTime() - previousCreatedAt.getTime())
      : null
    return {
      id: `a-${message.id}`,
      messageId: message.id,
      role: 'assistant',
      blocks: mergeToolBlocks(blocks),
      metrics: buildTurnMetrics(payload?.usage, payload?.duration_ms ?? legacyDuration),
      _saved: true,
    }
  }
  return {
    id: `u-${message.id}`,
    messageId: message.id,
    role: message.role,
    content: message.content,
    created_at: message.created_at,
    _html: renderMarkdown(message.content || ''),
    _saved: true,
  }
})

const loadShare = async () => {
  let beforeId = null
  let allItems = []
  try {
    do {
      const response = await api.get(`/public/conversation-shares/${encodeURIComponent(token)}`, {
        params: { limit: 100, ...(beforeId ? { before_id: beforeId } : {}) },
      })
      share.value = {
        title: response.title,
        agent_name: response.agent_name,
        shared_at: response.shared_at,
      }
      allItems = [...(response.items || []), ...allItems]
      beforeId = response.has_more ? response.items?.[0]?.id : null
      if (!beforeId) break
    } while (true)

    displayMessages.value = mapMessages(allItems)
    document.title = `${share.value.title || '对话分享'} - AI Hub`
    await nextTick()
    chatMainRef.value?.scrollToBottom(false)
  } catch (requestError) {
    const detail = requestError.response?.data?.detail
    error.value = detail || '该分享链接不存在或已被取消'
  } finally {
    loading.value = false
  }
}

const formatDate = value => formatBeijingDateTime(value, { second: undefined })

onMounted(async () => {
  await loadShare()
})
</script>

<style scoped>
.conversation-share-page {
  width: 100%;
  height: 100%;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: #303133;
  background: #fff;
  text-align: left;
}

.share-header {
  min-height: 64px;
  padding: 10px max(20px, calc((100% - 960px) / 2));
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex: 0 0 auto;
  border-bottom: 1px solid #e8eaed;
  background: #fff;
  box-sizing: border-box;
}

.share-heading {
  min-width: 0;
}

.agent-name {
  display: block;
  margin-bottom: 2px;
  color: #6b7280;
  font-size: 12px;
  line-height: 18px;
}

.share-header h1 {
  margin: 0;
  overflow: hidden;
  color: #202124;
  font-size: 17px;
  font-weight: 600;
  line-height: 24px;
  text-overflow: ellipsis;
  white-space: nowrap;
  letter-spacing: 0;
}

.share-header time {
  flex: 0 0 auto;
  color: #909399;
  font-size: 12px;
  white-space: nowrap;
}

.conversation-view,
.share-state {
  min-height: 0;
  flex: 1;
  display: flex;
}

.conversation-view :deep(.chat-main) {
  min-height: 0;
}

.share-state {
  align-items: center;
  justify-content: center;
}

@media (max-width: 640px) {
  .share-header {
    min-height: 58px;
    padding: 8px 14px;
  }

  .share-header time {
    display: none;
  }

  .share-header h1 {
    font-size: 15px;
  }

  .conversation-view :deep(.messages) {
    padding: 18px 14px;
  }

  .conversation-view :deep(.user-message-stack) {
    max-width: 88%;
  }
}
</style>
