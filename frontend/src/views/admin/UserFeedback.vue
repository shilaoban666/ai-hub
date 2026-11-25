<template>
  <section class="user-feedback">
    <h2>所有反馈</h2>
    <FeedbackSummary :summary="summary" :loading="loading" />
    <el-alert v-if="xiaoquOnly" :title="`小趣反馈${departmentName ? ' · ' + departmentName : ''}`" type="info" :closable="false" class="dashboard-scope">
      <template #default><el-button link type="primary" @click="clearDashboardScope">清除看板筛选</el-button></template>
    </el-alert>
    <div class="feedback-filters">
      <el-select v-model="rating" aria-label="反馈类型" placeholder="反馈类型" clearable @change="refresh">
        <el-option label="点赞" value="like" /><el-option label="点踩" value="dislike" />
      </el-select>
      <el-select v-model="processingStatus" aria-label="处理状态筛选" placeholder="处理状态" clearable @change="refresh">
        <el-option v-for="(label, value) in processingLabels" :key="value" :label="label" :value="value" />
      </el-select>
      <el-select v-model="assigned" aria-label="是否分配处理人" placeholder="是否分配处理人" clearable @change="refresh">
        <el-option label="已分配" value="true" /><el-option label="未分配" value="false" />
      </el-select>
      <UserSearchSelect v-model="creatorId" placeholder="反馈人姓名 / 账号" label="检索反馈人" @change="refresh" />
      <UserSearchSelect v-model="assigneeId" placeholder="处理人姓名 / 账号" label="检索处理人" @change="refresh" />
      <el-input v-model="search" clearable placeholder="对话标题、反馈原因、补充说明" aria-label="搜索所有反馈" @keyup.enter="refresh" @clear="refresh" />
      <el-date-picker v-model="feedbackDates" class="feedback-date-range" type="daterange"
        value-format="YYYY-MM-DD" range-separator="至" start-placeholder="反馈开始日期" end-placeholder="反馈结束日期"
        :shortcuts="dateShortcuts" popper-class="xiaoqu-date-picker"
        aria-label="反馈时间范围（北京时间）" clearable @change="refresh" />
      <el-button type="primary" @click="refresh">搜索</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-table :data="rows" v-loading="loading" row-key="id" empty-text="暂无用户反馈">
      <el-table-column label="反馈时间" width="170"><template #default="{ row }">{{ time(row.created_at) }}</template></el-table-column>
      <el-table-column label="反馈人" width="170" show-overflow-tooltip><template #default="{ row }">{{ row.display_name?.trim() || '无' }}</template></el-table-column>
      <el-table-column label="反馈类型" width="170"><template #default="{ row }"><el-tag :type="row.rating === 'like' ? 'success' : 'danger'" effect="plain">{{ ratingLabel(row.rating) }}</el-tag></template></el-table-column>
      <el-table-column label="处理状态" width="170"><template #default="{ row }"><el-tag v-if="row.rating === 'like'" class="processing-status-tag" type="success" effect="plain">无需处理</el-tag><el-tag v-else class="processing-status-tag" :type="statusTone(row.processing_status)" effect="plain">{{ processingLabels[normalizeProcessingStatus(row.processing_status)] }}</el-tag></template></el-table-column>
      <el-table-column label="处理人" width="170" show-overflow-tooltip><template #default="{ row }">{{ row.rating === 'dislike' ? row.assignee_name?.trim() || '无' : '无' }}</template></el-table-column>
      <el-table-column label="对话标题" min-width="200" show-overflow-tooltip><template #default="{ row }"><el-button class="conversation-title-link" link type="primary" :title="row.session_title?.trim() || '无'" @click="openConversation(row)"><span class="feedback-cell-text">{{ row.session_title?.trim() || '无' }}</span></el-button></template></el-table-column>
      <el-table-column label="反馈原因" min-width="200" show-overflow-tooltip><template #default="{ row }"><span class="feedback-cell-text" :title="reasonItems(row.reasons).join('、') || '无'">{{ reasonItems(row.reasons).join('、') || '无' }}</span></template></el-table-column>
      <el-table-column label="补充说明" min-width="220" show-overflow-tooltip><template #default="{ row }"><span class="feedback-cell-text" :title="row.comment?.trim() || '无'">{{ row.comment?.trim() || '无' }}</span></template></el-table-column>
      <el-table-column label="操作" width="300" fixed="right"><template #default="{ row }"><div class="feedback-row-actions"><router-link class="feedback-detail-link" :to="{ name: 'FeedbackDetail', params: { id: row.id }, query: { from: 'all' } }" target="_blank" rel="noopener">查看反馈</router-link><FeedbackActions :feedback="row" link @saved="load" /></div></template></el-table-column>
    </el-table>
    <div class="feedback-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @size-change="refresh" @current-change="load" /></div>

    <el-drawer v-model="conversationOpen" class="feedback-full-conversation" title="完整会话" size="min(960px, 100%)" destroy-on-close @close="closeConversation">
      <template #header="{ titleId }">
        <div class="full-conversation-heading"><small :id="titleId">完整会话</small><small v-if="conversationDeleted"> · 原对话已删除</small><h3>{{ conversationTitle?.trim() || '无' }}</h3></div>
      </template>
      <div class="full-conversation-content">
        <div v-if="conversationError" class="conversation-error"><el-alert :title="conversationError" type="error" :closable="false" show-icon /><el-button @click="loadConversation">重新加载</el-button></div>
        <ChatMain v-else ref="conversationChat" :display-messages="conversationMessages" :history-loading="conversationLoading"
          :agent-name="conversationSession?.agent_name || ''" :agent-icon="conversationSession?.agent_icon || 'H'" view-only />
      </div>
    </el-drawer>

  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { feedbackApi } from '@/api/feedback'
import { formatBeijingDateTime } from '@/utils/date-time'
import { createDateRangeShortcuts } from '@/utils/date-range-shortcuts'
import { mergeToolBlocks } from '@/utils/agent-chat-blocks'
import { renderMarkdown } from '@/utils/markdown'
import { normalizeProcessingStatus, processingLabels, statusTone } from '@/utils/feedback-status'
import ChatMain from './components/ChatMain.vue'
import FeedbackActions from './components/FeedbackActions.vue'
import FeedbackSummary from './components/FeedbackSummary.vue'
import UserSearchSelect from './components/UserSearchSelect.vue'

const pageSize = ref(20)
const dateShortcuts = createDateRangeShortcuts()
const route = useRoute(), router = useRouter()
const xiaoquOnly = computed(() => route.query.xiaoqu_only === 'true')
const dashboardDepartment = computed(() => typeof route.query.department === 'string' ? route.query.department : undefined)
const departmentName = computed(() => typeof route.query.department_name === 'string' ? route.query.department_name.trim() : '')
const feedbackDates = ref(typeof route.query.start_date === 'string' && typeof route.query.end_date === 'string' ? [route.query.start_date, route.query.end_date] : [])
function clearDashboardScope() {
  const { xiaoqu_only, department, department_name, ...query } = route.query
  router.replace({ query })
}
const rows = ref([]), rating = ref(''), search = ref(''), page = ref(1), total = ref(0)
const assigned = ref('')
const processingStatus = ref(''), creatorId = ref(), assigneeId = ref()
const summary = ref(null)
const loading = ref(false), error = ref('')
const conversationOpen = ref(false), conversationLoading = ref(false), conversationError = ref('')
const conversationMessages = ref([]), conversationTitle = ref(''), conversationDeleted = ref(false)
const conversationSession = ref(null), conversationChat = ref(null), conversationFeedbackId = ref(null)
let conversationRequest = 0
let listRequest = 0
const time = value => value?.trim() ? formatBeijingDateTime(value) : '无'
const ratingLabel = value => value === 'like' ? '点赞' : '点踩'
const reasonItems = value => (value || []).map(reason => reason?.trim()).filter(Boolean)
const errorText = (err, fallback) => {
  const detail = err.response?.data?.detail
  return typeof detail === 'string' ? detail : detail?.message || fallback
}
async function load() {
  const request = ++listRequest
  loading.value = true; error.value = ''
  try {
    const result = await feedbackApi.list({ rating: rating.value || undefined, processing_status: processingStatus.value || undefined,
      xiaoqu_only: xiaoquOnly.value || undefined, department: dashboardDepartment.value,
      assigned: assigned.value || undefined, creator_user_id: creatorId.value, assignee_user_id: assigneeId.value, search: search.value.trim(), start_date: feedbackDates.value?.[0], end_date: feedbackDates.value?.[1], skip: (page.value - 1) * pageSize.value, limit: pageSize.value })
    if (request !== listRequest) return
    total.value = result.total
    summary.value = result.summary ?? null
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize.value))
    if (page.value > lastPage) { page.value = lastPage; return load() }
    rows.value = result.items
  } catch (err) { if (request === listRequest) { error.value = errorText(err, '反馈加载失败'); rows.value = []; summary.value = null; total.value = 0 } }
  finally { if (request === listRequest) loading.value = false }
}
function refresh() { page.value = 1; load() }
function mapMessage(message) {
  const common = { id: message.id, messageId: message.id, role: message.role, created_at: message.created_at, _saved: true }
  if (message.role !== 'assistant') return { ...common, content: message.content, _html: renderMarkdown(message.content || ''), attachedFiles: message.attached_files || [], skill: message.skill }
  let payload
  try { payload = JSON.parse(message.content) } catch { payload = null }
  const blocks = Array.isArray(payload) ? payload : payload?.blocks
  return { ...common, blocks: mergeToolBlocks(Array.isArray(blocks) ? blocks : [{ type: 'text', content: message.content || '' }]) }
}
function openConversation(row) {
  conversationFeedbackId.value = row.id; conversationTitle.value = row.session_title
  conversationSession.value = null; conversationDeleted.value = false
  conversationOpen.value = true; loadConversation()
}
function closeConversation() { ++conversationRequest; conversationMessages.value = []; conversationLoading.value = false }
async function loadConversation() {
  const request = ++conversationRequest
  const feedbackId = conversationFeedbackId.value
  conversationLoading.value = true; conversationError.value = ''; conversationMessages.value = []
  try {
    let beforeId = null
    const batches = []
    do {
      const result = await feedbackApi.detail(feedbackId, { scope: 'conversation', limit: 100, ...(beforeId ? { before_id: beforeId } : {}) })
      if (request !== conversationRequest || !conversationOpen.value) return
      conversationSession.value = result.session; conversationDeleted.value = result.session_deleted
      conversationTitle.value = result.session?.title || result.feedback.session_title
      batches.push(result.items)
      if (!result.has_more) break
      const nextId = result.items[0]?.id
      if (!nextId || (beforeId && nextId >= beforeId)) throw new Error('Invalid message cursor')
      beforeId = nextId
    } while (true)
    conversationMessages.value = batches.reverse().flat().map(mapMessage)
    conversationLoading.value = false
    await nextTick()
    if (request === conversationRequest) conversationChat.value?.scrollToTop(false)
  } catch (err) {
    if (request === conversationRequest) conversationError.value = errorText(err, '完整会话加载失败，请重试')
  } finally { if (request === conversationRequest) conversationLoading.value = false }
}
onBeforeUnmount(() => { ++conversationRequest; ++listRequest })
onMounted(load)
watch(() => [route.query.start_date, route.query.end_date, route.query.xiaoqu_only, route.query.department], () => {
  feedbackDates.value = typeof route.query.start_date === 'string' && typeof route.query.end_date === 'string' ? [route.query.start_date, route.query.end_date] : []
  refresh()
})
</script>

<style scoped>
.processing-status-tag { width: 76px; justify-content: center; box-sizing: border-box; }
.dashboard-scope { margin-bottom: 16px; }
.feedback-row-actions { display: flex; align-items: center; gap: 16px; white-space: nowrap; }
.feedback-row-actions :deep(.feedback-actions) { gap: 16px; }
.feedback-row-actions :deep(.el-button.is-link) { padding: 0; margin: 0; font-weight: 400; }
.feedback-detail-link { color: var(--el-color-primary); text-decoration: none; font-size: 14px; }
.feedback-detail-link:hover { color: var(--el-color-primary-light-3); }
.user-feedback { min-width: 0; }
.feedback-cell-text { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conversation-title-link { max-width: 100%; min-width: 0; vertical-align: middle; }
.conversation-title-link :deep(> span) { display: block; min-width: 0; overflow: hidden; }
h2 { margin: 0 0 24px; font-size: 24px; }
.feedback-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 20px; }
.feedback-filters .el-select, .feedback-filters .el-input { width: 240px; max-width: 100%; flex: 0 0 auto; }
.muted { color: #909399; }
.person-account { margin-left: 10px; }
.feedback-filters :deep(.feedback-date-range) { width: 320px; max-width: 100%; flex: 0 1 320px; box-sizing: border-box; }
.feedback-pagination { display: flex; justify-content: flex-end; margin-top: 20px; }
small { color: #909399; font-size: 12px; }
:global(.feedback-detail-drawer .el-drawer__header) { margin-bottom: 0; padding: 20px 24px; border-bottom: 1px solid #ebeef5; }
:global(.feedback-detail-drawer .el-drawer__title) { font-size: 16px; font-weight: 600; color: #303133; }
:global(.feedback-detail-drawer .el-drawer__body) { padding: 20px 24px 0; overflow: hidden; }
.feedback-detail { height: 100%; min-height: 0; display: flex; flex-direction: column; font-size: 14px; }
.detail-summary { padding: 18px 20px; border: 1px solid #ebeef5; border-radius: 10px; background: #fafbfc; max-height: 45%; overflow: auto; flex-shrink: 0; }
.summary-heading { display: flex; align-items: center; gap: 10px; }
.summary-heading h3 { margin: 0; font-size: 17px; line-height: 1.5; color: #303133; overflow-wrap: anywhere; min-width: 0; }
.summary-heading .el-tag { flex-shrink: 0; }
.process-feedback { margin-left: auto; flex-shrink: 0; }
.summary-fields { display: grid; grid-template-columns: 1fr 1.5fr 1fr 1fr; gap: 16px; margin: 18px 0 16px; }
.detail-summary dt { color: #909399; font-size: 12px; line-height: 22px; }
.detail-summary dd { margin: 0; line-height: 22px; color: #454b54; overflow-wrap: anywhere; }
.summary-fields dd { margin-top: 5px; }
.summary-notes { border-top: 1px solid #e8ebef; padding-top: 14px; margin: 0; display: grid; gap: 12px; }
.summary-notes > div { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 12px; }
.reason-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.reason-chip { background: #eef0f3; border-radius: 4px; padding: 1px 8px; font-size: 12px; }
.feedback-comment { white-space: pre-wrap; overflow-wrap: anywhere; }
.detail-summary dd.muted { color: #909399; }
.conversation-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 20px 0 12px; }
.conversation-heading h4 { margin: 0; font-size: 14px; font-weight: 600; color: #303133; }
.conversation-heading span { font-size: 12px; color: #909399; }
.feedback-conversation { flex: 1; min-height: 0; display: flex; border-top: 1px solid #ebeef5; }
.feedback-conversation :deep(.chat-main) { width: 100%; }
.feedback-conversation :deep(.messages) { padding: 20px 0; }
.feedback-conversation :deep(.feedback-target) { border-left: 2px solid #a0cfff; border-radius: 8px; background: #f5f9ff; padding: 16px; }
.feedback-conversation :deep(.feedback-target .assistant-identity > .el-tag) { order: 3; margin-left: auto; }
:global(.feedback-full-conversation .el-drawer__header) { padding: 16px 24px; margin: 0; border-bottom: 1px solid #ebeef5; }
:global(.feedback-full-conversation .el-drawer__body) { min-height: 0; padding: 0; display: flex; overflow: hidden; }
.full-conversation-heading { padding-right: 32px; }
.full-conversation-heading h3 { margin: 4px 0 0; font-size: 17px; line-height: 24px; overflow-wrap: anywhere; }
.full-conversation-content { display: flex; flex: 1; min-width: 0; min-height: 0; }
.conversation-error { margin: 24px auto; width: min(840px, 90%); }
.conversation-error .el-button { margin-top: 12px; }
@media (max-width: 600px) {
  :global(.feedback-detail-drawer .el-drawer__header) { padding: 16px; }
  :global(.feedback-detail-drawer .el-drawer__body) { padding: 12px 12px 0; }
  .detail-summary { padding: 14px; max-height: 50%; }
  .summary-heading { flex-wrap: wrap; }
  .summary-heading h3 { font-size: 16px; }
  .summary-fields { grid-template-columns: 1fr 1.5fr; gap: 12px; }
  .conversation-heading { flex-wrap: wrap; gap: 4px; padding-top: 14px; }
}
</style>
