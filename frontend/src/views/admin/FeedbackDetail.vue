<template>
  <section class="feedback-detail-page" v-loading="loading && !selected">
    <header class="page-heading">
      <el-button link :icon="ArrowLeft" @click="goBack">返回</el-button>
      <div class="heading-title">
        <h2>反馈详情</h2>
        <p>{{ selected?.session_title?.trim() || '无' }}</p>
      </div>
      <FeedbackActions v-if="canProcess" :feedback="selected" :can-assign="canAssign" @saved="value => selected = value" />
    </header>

    <div v-if="error" class="detail-error">
      <el-alert :title="error" type="error" :closable="false" show-icon />
      <el-button @click="loadDetail(false)">重新加载</el-button>
    </div>

    <template v-if="selected">
      <section class="detail-summary">
        <div class="summary-heading">
          <h3>{{ selected.session_title?.trim() || '无' }}</h3>
          <el-tag :type="selected.rating === 'like' ? 'success' : 'danger'" effect="light" size="small">{{ ratingLabel(selected.rating) }}</el-tag>
        </div>
        <dl class="summary-fields">
          <div><dt>反馈人</dt><dd>{{ selected.display_name?.trim() || '无' }}</dd></div>
          <div><dt>反馈时间</dt><dd>{{ time(selected.created_at) }}</dd></div>
          <div><dt>智能体</dt><dd>{{ detailSession?.agent_name?.trim() || '无' }}</dd></div>
          <div><dt>处理状态</dt><dd><el-tag v-if="selected.rating === 'like'" class="processing-status-tag" type="success" effect="plain" size="small">无需处理</el-tag><el-tag v-else class="processing-status-tag" :type="statusTone(selected.processing_status)" effect="plain" size="small">{{ processingLabels[normalizeProcessingStatus(selected.processing_status)] }}</el-tag></dd></div>
          <div><dt>处理人</dt><dd>{{ selected.rating === 'dislike' ? selected.assignee_name?.trim() || selected.assignee_username?.trim() || '无' : '无' }}</dd></div>
        </dl>
        <dl class="summary-notes">
          <div><dt>反馈原因</dt><dd class="reason-tags"><span v-for="reason in reasonItems(selected.reasons)" :key="reason" class="reason-chip">{{ reason }}</span><span v-if="!reasonItems(selected.reasons).length" class="muted">无</span></dd></div>
          <div><dt>处理备注</dt><dd class="feedback-comment">{{ selected.processing_remark?.trim() || '无' }}</dd></div>
          <div><dt>处理截图</dt><dd><el-image v-for="(url, index) in selected.processing_images || []" :key="url" :src="url" :preview-src-list="selected.processing_images" :initial-index="index" preview-teleported style="width: 80px; height: 80px; margin-right: 8px" fit="cover" /><span v-if="!selected.processing_images?.length">无</span></dd></div>
          <div><dt>补充说明</dt><dd class="feedback-comment" :class="{ muted: !selected.comment?.trim() }">{{ selected.comment?.trim() || '无' }}</dd></div>
        </dl>
      </section>

      <div class="conversation-heading">
        <h3>反馈相关对话</h3>
        <span>{{ sessionDeleted ? '原对话已删除 · ' : '' }}截至被反馈回复的上下文</span>
      </div>
      <div class="feedback-conversation">
        <ChatMain ref="chat" :display-messages="messages" :history-has-more="hasMore"
          :older-history-loading="loading" :highlighted-message-id="selected.message_id"
          :agent-name="detailSession?.agent_name || ''" :agent-icon="detailSession?.agent_icon || 'H'"
          view-only @load-older="loadDetail(true)" />
      </div>
    </template>


  </section>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { feedbackApi } from '@/api/feedback'
import { useAuthStore } from '@/stores/auth'
import { formatBeijingDateTime } from '@/utils/date-time'
import { mergeToolBlocks } from '@/utils/agent-chat-blocks'
import { renderMarkdown } from '@/utils/markdown'
import { normalizeProcessingStatus, processingLabels, statusTone } from '@/utils/feedback-status'
import ChatMain from './components/ChatMain.vue'
import FeedbackActions from './components/FeedbackActions.vue'

const route = useRoute(), router = useRouter(), authStore = useAuthStore()
const selected = ref(null), detailSession = ref(null), messages = ref([]), hasMore = ref(false), sessionDeleted = ref(false)
const loading = ref(false), error = ref(''), canProcess = ref(false), canAssign = ref(false), chat = ref(null)
let detailRequest = 0
const ratingLabel = value => value === 'like' ? '点赞' : '点踩'
const time = value => value?.trim() ? formatBeijingDateTime(value) : '无'
const reasonItems = value => (value || []).map(reason => reason?.trim()).filter(Boolean)
const errorText = (err, fallback) => { const detail = err.response?.data?.detail; return typeof detail === 'string' ? detail : detail?.message || fallback }

function mapMessage(message) {
  const common = { id: message.id, messageId: message.id, role: message.role, created_at: message.created_at, _saved: true }
  if (message.role !== 'assistant') return { ...common, content: message.content, _html: renderMarkdown(message.content || ''), attachedFiles: message.attached_files || [], skill: message.skill }
  let payload
  try { payload = JSON.parse(message.content) } catch { payload = null }
  const blocks = Array.isArray(payload) ? payload : payload?.blocks
  return { ...common, blocks: mergeToolBlocks(Array.isArray(blocks) ? blocks : [{ type: 'text', content: message.content || '' }]) }
}

async function loadDetail(older = false) {
  const feedbackId = Number(route.params.id)
  if (!Number.isSafeInteger(feedbackId) || feedbackId < 1) { error.value = '反馈编号无效'; return }
  const request = ++detailRequest
  loading.value = true; error.value = ''
  if (!older) { selected.value = null; detailSession.value = null; messages.value = []; hasMore.value = false }
  try {
    const result = await feedbackApi.detail(feedbackId, { scope: 'context', limit: 50, ...(older && messages.value.length ? { before_id: messages.value[0].messageId } : {}) })
    if (request !== detailRequest) return
    selected.value = result.feedback; detailSession.value = result.session; sessionDeleted.value = result.session_deleted
    hasMore.value = result.has_more; canProcess.value = result.can_process === true; canAssign.value = result.can_assign === true
    const batch = result.items.map(mapMessage); messages.value = older ? [...batch, ...messages.value] : batch
    if (!older) { await nextTick(); chat.value?.scrollToBottom(false) }
  } catch (err) { if (request === detailRequest) error.value = errorText(err, '反馈详情加载失败') }
  finally { if (request === detailRequest) loading.value = false }
}

function goBack() {
  // Explicit list origin also survives a detail-page reload.
  if (route.query.from === 'mine') { router.push('/admin/dashboard/personal/feedback'); return }
  if (route.query.from === 'all' && authStore.user?.is_superuser) { router.push('/admin/dashboard/summary/feedback'); return }
  if (window.history.state?.back) { router.back(); return }
  router.push(authStore.user?.is_superuser ? '/admin/dashboard/summary/feedback' : '/admin/dashboard/personal/feedback')
}
watch(() => route.params.id, () => loadDetail(false), { immediate: true })
onBeforeUnmount(() => { ++detailRequest })
</script>

<style scoped>
.processing-status-tag { width: 76px; justify-content: center; box-sizing: border-box; }
.feedback-detail-page { min-width: 0; height: calc(100vh - 112px); min-height: 620px; display: flex; flex-direction: column; }
.page-heading { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid #dcdfe6; }
.heading-title { min-width: 0; }
.heading-title h2 { margin: 0; font-size: 22px; line-height: 30px; }
.heading-title p { margin: 2px 0 0; color: #909399; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-error { margin: 24px 0; }
.detail-error .el-button { margin-top: 12px; }
.detail-summary { padding: 20px 0; border-bottom: 1px solid #dcdfe6; flex-shrink: 0; }
.summary-heading { display: flex; align-items: center; gap: 10px; }
.summary-heading h3 { margin: 0; font-size: 17px; line-height: 1.5; overflow-wrap: anywhere; min-width: 0; }
.summary-fields { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 16px; margin: 18px 0 16px; }
dt { color: #909399; font-size: 12px; line-height: 22px; }
dd { margin: 5px 0 0; line-height: 22px; color: #454b54; overflow-wrap: anywhere; }
.summary-notes { border-top: 1px solid #ebeef5; padding-top: 14px; margin: 0; display: grid; gap: 12px; }
.summary-notes > div { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 12px; }
.reason-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.reason-chip { background: #eef0f3; border-radius: 4px; padding: 1px 8px; font-size: 12px; }
.feedback-comment { white-space: pre-wrap; }
.muted, small { color: #909399; }
.person-account { margin-left: 10px; }
.conversation-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 18px 0 12px; }
.conversation-heading h3 { margin: 0; font-size: 15px; }
.conversation-heading span { font-size: 12px; color: #909399; }
.feedback-conversation { flex: 1; min-height: 0; display: flex; border-top: 1px solid #ebeef5; }
.feedback-conversation :deep(.chat-main) { width: 100%; }
.feedback-conversation :deep(.messages) { padding: 20px 0; }
.feedback-conversation :deep(.feedback-target) { border-left: 2px solid #a0cfff; border-radius: 8px; background: #f5f9ff; padding: 16px; }
.feedback-conversation :deep(.feedback-target .assistant-identity > .el-tag) { order: 3; margin-left: auto; }
@media (max-width: 900px) {
  .feedback-detail-page { height: auto; min-height: calc(100vh - 96px); }
  .summary-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .feedback-conversation { min-height: 60vh; }
}
@media (max-width: 600px) {
  .page-heading { grid-template-columns: auto minmax(0, 1fr); }
  .page-heading > .el-button:last-child { grid-column: 1 / -1; width: 100%; }
  .summary-fields { grid-template-columns: 1fr; }
  .conversation-heading { align-items: flex-start; flex-direction: column; gap: 4px; }
}
</style>
