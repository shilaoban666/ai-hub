<template>
  <section class="usage-page">
    <div class="usage-heading"><h2>全局用量 / 知识库调用用量</h2></div>
    <div class="usage-filters">
      <el-segmented v-model="period" :options="periodOptions" @change="refresh" />
      <el-date-picker v-if="period === 'custom'" v-model="dateRange" type="daterange" value-format="YYYY-MM-DD"
        start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" @change="refresh" />
      <el-select v-model="granularity" aria-label="趋势粒度" class="compact-select" @change="loadSummary">
        <el-option label="按小时" value="hour" /><el-option label="按天" value="day" /><el-option label="按周" value="week" />
      </el-select>
      <el-select v-model="userId" class="user-select" filterable remote clearable :remote-method="searchUsers"
        :loading="userSearchLoading" placeholder="搜索姓名或用户名" aria-label="用户"
        @visible-change="visible => visible && searchUsers('')" @change="refresh">
        <el-option v-for="user in userOptions" :key="user.id" :value="Number(user.id)" :label="userName(user.id)" />
      </el-select>
      <el-checkbox v-model="includeTests" @change="refresh">含检索测试</el-checkbox>
      <el-tooltip content="刷新" placement="top">
        <el-button :icon="Refresh" circle aria-label="刷新" :loading="loading || tableLoading" @click="refresh" />
      </el-tooltip>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <dl v-loading="loading" class="usage-metrics">
      <div v-for="metric in metrics" :key="metric.label">
        <dt>
          {{ metric.label }}
          <el-tooltip v-if="metric.tip" :content="metric.tip" placement="top"><el-icon class="metric-tip"><QuestionFilled /></el-icon></el-tooltip>
        </dt>
        <dd :class="metric.tone">{{ metric.value }}</dd><span v-if="metric.note">{{ metric.note }}</span>
      </div>
    </dl>

    <div class="usage-charts" v-loading="loading">
      <div class="chart-column">
      <section>
        <div class="section-heading">
          <h3>使用趋势</h3>
          <el-segmented v-model="trendMetric" size="small" :options="trendOptions" />
        </div>
        <div v-show="hasTrend" ref="chartElement" class="trend-chart">
          <svg :viewBox="`0 0 ${chartWidth} 220`" role="img" aria-label="知识库调用趋势">
            <g v-for="tick in [0, 1, 2, 3, 4]" :key="tick">
              <line x1="68" :y1="20 + tick * 40" :x2="chartWidth - 18" :y2="20 + tick * 40" stroke="#e5e7eb" />
              <text x="60" :y="24 + tick * 40" text-anchor="end" fill="#6b7280" font-size="11">{{ axisNumber(chartMax * (4 - tick) / 4) }}</text>
            </g>
            <rect v-for="bar in bars" :key="bar.bucket" :x="bar.x" :y="bar.y" :width="bar.width" :height="bar.height" rx="2" fill="#3476bb">
              <title>{{ shortTime(bar.bucket) }}：{{ bar.value.toLocaleString('zh-CN') }}</title>
            </rect>
            <text x="68" y="208" fill="#6b7280" font-size="12">{{ shortTime(trend[0]?.bucket) }}</text>
            <text :x="chartWidth - 18" y="208" text-anchor="end" fill="#6b7280" font-size="12">{{ shortTime(trend.at(-1)?.bucket) }}</text>
          </svg>
        </div>
        <el-empty v-if="!hasTrend" description="当前周期暂无知识库调用" :image-size="64" />
      </section>
      <section>
        <div class="section-heading">
          <h3>问题解答情况</h3>
          <span class="stack-legend">
            <span v-for="part in answerParts" :key="part.key"><i :style="{ background: part.color }" />{{ part.label }}</span>
          </span>
        </div>
        <div v-show="hasAnswerTrend" class="trend-chart">
          <svg :viewBox="`0 0 ${chartWidth} 220`" role="img" aria-label="每期提问的已解答、未命中与失败数量">
            <g v-for="tick in [0, 1, 2, 3, 4]" :key="tick">
              <line x1="68" :y1="20 + tick * 40" :x2="chartWidth - 18" :y2="20 + tick * 40" stroke="#e5e7eb" />
              <text x="60" :y="24 + tick * 40" text-anchor="end" fill="#6b7280" font-size="11">{{ axisNumber(answerMax * (4 - tick) / 4) }}</text>
            </g>
            <g v-for="bar in answerBars" :key="bar.bucket">
              <rect v-for="seg in bar.segments" :key="seg.key" :x="bar.x" :y="seg.y" :width="bar.width" :height="seg.height" :fill="seg.color" />
              <rect :x="bar.x" y="20" :width="bar.width" height="160" fill="transparent">
                <title>{{ shortTime(bar.bucket) }}：提问 {{ bar.total }}，已解答 {{ bar.answered }}，未命中 {{ bar.unanswered }}，失败 {{ bar.failed }}，解答率 {{ bar.rate }}</title>
              </rect>
            </g>
            <text x="68" y="208" fill="#6b7280" font-size="12">{{ shortTime(trend[0]?.bucket) }}</text>
            <text :x="chartWidth - 18" y="208" text-anchor="end" fill="#6b7280" font-size="12">{{ shortTime(trend.at(-1)?.bucket) }}</text>
          </svg>
        </div>
        <el-empty v-if="!hasAnswerTrend" description="当前周期暂无提问" :image-size="64" />
      </section>
      </div>
      <section>
        <div class="section-heading">
          <h3>热门召回文档</h3>
          <el-tooltip content="命中率 = 召回了该文档的成功调用次数 ÷ 成功调用总次数" placement="top"><span>前 10 名 · 命中率</span></el-tooltip>
        </div>
        <ol v-if="data.top_documents?.length" class="doc-rank">
          <li v-for="(item, index) in data.top_documents" :key="item.doc_name" class="ratio-row">
            <div>
              <span class="doc-name"><em :class="{ top: index < 3 }">{{ index + 1 }}</em>{{ item.doc_name }}</span>
              <strong>{{ item.hits }} 次 · {{ item.hit_rate }}%</strong>
            </div>
            <el-progress :percentage="Math.min(100, item.hit_rate)" :show-text="false" :stroke-width="6" color="#3476bb" />
          </li>
        </ol>
        <el-empty v-else description="暂无召回文档" :image-size="64" />
        <div class="section-heading source-heading">
          <h3>使用渠道</h3>
          <el-tooltip content="小趣 = AI Hub 里的智能体对话；知识库管理里的检索测试不算任何渠道" placement="top"><span>提问次数 · 占比</span></el-tooltip>
        </div>
        <div v-for="item in channels" :key="item.source" class="ratio-row">
          <div><span>{{ sourceLabels[item.source] || item.source }}</span><strong>{{ item.calls }} 次 · {{ item.call_ratio }}%</strong></div>
          <el-progress :percentage="item.call_ratio" :show-text="false" :stroke-width="6" color="#29906b" />
          <small>{{ number(item.answered_calls) }} 个已解答 · 解答率 {{ item.answer_rate }}%</small>
        </div>
      </section>
    </div>

    <el-tabs v-model="detailTab" @tab-change="resetTable">
      <el-tab-pane label="调用总览" name="overview" />
      <el-tab-pane label="用户排行" name="users" />
      <el-tab-pane label="调用明细" name="calls" />
    </el-tabs>
    <template v-if="detailTab === 'overview'">
      <div class="overview-summary" v-loading="loading">
        <span>期间共 <strong>{{ number(stats.active_users) }}</strong> 人使用，其中新增 <strong>{{ number(stats.new_users) }}</strong> 人</span>
        <span>提问 <strong>{{ number(stats.total_calls) }}</strong> 次，已解答 <strong>{{ number(stats.answered_calls) }}</strong> 个</span>
        <span><strong>{{ number(stats.sessions) }}</strong> 个对话</span>
        <span>消耗 RAG Token <strong>{{ number(stats.rag_tokens) }}</strong></span>
        <span class="muted">对话数只统计调用时带了会话 ID 的请求（如智能体对话）</span>
      </div>
      <el-table v-loading="loading" :data="data.daily || []" row-key="date" empty-text="暂无调用">
        <el-table-column prop="date" label="日期" min-width="120" />
        <el-table-column label="调用次数" align="right" min-width="100"><template #default="{ row }">{{ number(row.calls) }}</template></el-table-column>
        <el-table-column label="已解答" align="right" min-width="80"><template #default="{ row }">{{ number(row.answered_calls) }}</template></el-table-column>
        <el-table-column label="未命中" align="right" min-width="80">
          <template #default="{ row }"><span :class="{ warn: row.unanswered_calls }">{{ number(row.unanswered_calls) }}</span></template>
        </el-table-column>
        <el-table-column label="失败" align="right" min-width="80">
          <template #default="{ row }"><span :class="{ danger: row.failed_calls }">{{ number(row.failed_calls) }}</span></template>
        </el-table-column>
        <el-table-column label="成功率" align="right" min-width="90"><template #default="{ row }">{{ row.success_rate }}%</template></el-table-column>
        <el-table-column label="RAG Token" align="right" min-width="120"><template #default="{ row }">{{ number(row.rag_tokens) }}</template></el-table-column>
        <el-table-column label="使用用户数" align="right" min-width="100"><template #default="{ row }">{{ number(row.users) }}</template></el-table-column>
        <el-table-column label="使用对话数" align="right" min-width="100"><template #default="{ row }">{{ number(row.sessions) }}</template></el-table-column>
        <el-table-column label="平均耗时" align="right" min-width="100"><template #default="{ row }">{{ number(row.avg_latency_ms) }} ms</template></el-table-column>
      </el-table>
    </template>
    <el-table v-else-if="detailTab === 'users'" v-loading="loading" :data="data.by_user || []" row-key="user_id" empty-text="暂无用户调用">
      <el-table-column label="姓名" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ userName(row.user_id) }} <el-tag v-if="row.is_new" size="small" type="success" effect="plain">新用户</el-tag></template>
      </el-table-column>
      <el-table-column label="提问次数" align="right" min-width="100"><template #default="{ row }">{{ number(row.calls) }}</template></el-table-column>
      <el-table-column label="调用占比" min-width="160">
        <template #default="{ row }"><div class="inline-ratio"><el-progress :percentage="row.call_ratio" :stroke-width="6" :show-text="false" /><span>{{ row.call_ratio }}%</span></div></template>
      </el-table-column>
      <el-table-column label="已解答" align="right" min-width="90"><template #default="{ row }">{{ number(row.answered_calls) }}</template></el-table-column>
      <el-table-column label="解答率" align="right" min-width="90"><template #default="{ row }">{{ row.answer_rate }}%</template></el-table-column>
      <el-table-column label="RAG Token" align="right" min-width="120"><template #default="{ row }">{{ number(row.rag_tokens) }}</template></el-table-column>
      <el-table-column label="最近使用" min-width="160"><template #default="{ row }">{{ time(row.last_used_at) }}</template></el-table-column>
      <el-table-column label="操作" width="100"><template #default="{ row }"><el-button link type="primary" @click="inspectUser(row.user_id)">查看明细</el-button></template></el-table-column>
    </el-table>
    <template v-else>
      <div class="detail-filters">
        <el-select v-model="callStatus" class="status-select" aria-label="调用结果" @change="resetTable">
          <el-option label="全部结果" value="all" /><el-option label="成功" value="success" /><el-option label="未命中（知识库缺内容）" value="unanswered" /><el-option label="失败" value="error" />
        </el-select>
        <span class="muted">北京时间 · RAG Token 为问题与召回片段的估算 Token 数</span>
      </div>
      <el-alert v-if="tableError" :title="tableError" type="error" :closable="false" show-icon />
      <el-table v-loading="tableLoading" :data="rows" row-key="id" empty-text="暂无调用记录">
        <el-table-column label="时间" min-width="165"><template #default="{ row }">{{ time(row.created_at) }}</template></el-table-column>
        <el-table-column label="姓名" min-width="110" show-overflow-tooltip><template #default="{ row }">{{ userName(row.user_id) }}</template></el-table-column>
        <el-table-column prop="index_name" label="知识库" min-width="130" show-overflow-tooltip />
        <el-table-column label="来源" min-width="100"><template #default="{ row }">{{ sourceLabels[row.source] || row.source }}</template></el-table-column>
        <el-table-column prop="query" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column label="召回" align="right" width="70">
          <template #default="{ row }"><span :class="{ danger: row.status === 'success' && !row.result_count }">{{ row.result_count }}</span></template>
        </el-table-column>
        <el-table-column label="RAG Token" align="right" width="105"><template #default="{ row }">{{ number(row.rag_tokens) }}</template></el-table-column>
        <el-table-column label="耗时" align="right" width="90"><template #default="{ row }">{{ row.latency_ms }} ms</template></el-table-column>
        <el-table-column label="结果" width="90">
          <template #default="{ row }">
            <el-tooltip :disabled="!row.error_message" :content="row.error_message || ''" placement="top">
              <el-tag :type="row.status === 'success' ? 'success' : 'danger'" effect="plain">{{ row.status === 'success' ? '成功' : '失败' }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
      <div class="usage-pagination">
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="loadTable" />
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { QuestionFilled, Refresh } from '@element-plus/icons-vue'
import { knowledgeApi, knowledgeErrorText } from '@/api/knowledge'
import { adminApi } from '@/api/admin'
import { formatBeijingDateTime } from '@/utils/date-time'

const periodOptions = [{ label: '今日', value: 'today' }, { label: '近 7 天', value: '7d' }, { label: '本月', value: 'month' }, { label: '自定义', value: 'custom' }]
const sourceLabels = {
  xiaoqu: '小趣（AI Hub）', workbuddy: 'WorkBuddy（MCP）', mcp: '其他 MCP', api: 'API / 访问令牌',
  agent: '小趣（AI Hub）', skill: '技能', console: '控制台检索测试',
}
// Channels leadership tracks are always listed, even at zero, so a channel that is not live yet shows up.
const mainChannels = ['xiaoqu', 'workbuddy', 'api']
const trendOptions = [
  { label: '提问次数', value: 'calls' }, { label: '已解答', value: 'answered_calls' },
  { label: '使用人数', value: 'users' }, { label: '新增用户', value: 'new_users' }, { label: 'RAG Token', value: 'rag_tokens' },
]
const period = ref('7d')
const dateRange = ref([])
const granularity = ref('day')
const userId = ref()
const includeTests = ref(false)
const trendMetric = ref('calls')
const data = ref({})
const loading = ref(false)
const error = ref('')
const detailTab = ref('overview')
const callStatus = ref('all')
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 16
const tableLoading = ref(false)
const tableError = ref('')
const chartElement = ref(null)
const chartWidth = ref(720)
const usersById = ref({})
const searchedUsers = ref([])
const userSearchLoading = ref(false)
let chartObserver
let summaryRequest = 0
let tableRequest = 0
let userSearchRequest = 0

const stats = computed(() => data.value.summary || {})
const trend = computed(() => data.value.trend || [])
const hasTrend = computed(() => trend.value.some(row => Number(row[trendMetric.value])))
const chartMax = computed(() => Math.max(1, ...trend.value.map(row => Number(row[trendMetric.value]) || 0)))
const bars = computed(() => {
  const count = Math.max(1, trend.value.length)
  const slot = (chartWidth.value - 86) / count
  const width = Math.max(2, Math.min(28, slot * 0.7))
  return trend.value.map((row, index) => {
    const value = Number(row[trendMetric.value]) || 0
    const height = value / chartMax.value * 160
    return { bucket: row.bucket, value, x: 68 + index * slot + (slot - width) / 2, y: 180 - height, width, height }
  })
})
const number = value => Number(value || 0).toLocaleString('zh-CN')
const metrics = computed(() => [
  { label: '使用人数', value: number(stats.value.active_users), note: `累计 ${number(stats.value.total_users)} 人用过`, tip: '本期内提过问的人数' },
  { label: '新增用户', value: number(stats.value.new_users), tone: 'good', tip: '第一次使用知识库的时间落在本期内的人数' },
  { label: '提问次数', value: number(stats.value.total_calls), note: `失败 ${number(stats.value.failed_calls)} 次` },
  { label: '已解答问题', value: number(stats.value.answered_calls), tone: 'good', note: `解答率 ${stats.value.answer_rate ?? 0}%`,
    tip: '检索成功且知识库召回到相关内容的提问；未召回到内容的不算' },
  { label: '未命中问题', value: number(stats.value.unanswered_calls), tone: stats.value.unanswered_calls ? 'warn' : '',
    note: '知识库缺内容，可在调用明细查看', tip: '检索成功但知识库里没有相关内容的提问' },
  { label: 'RAG Token', value: number(stats.value.rag_tokens), note: `平均每问 ${number(stats.value.avg_rag_tokens)}` },
  { label: '平均耗时', value: `${number(stats.value.avg_latency_ms)} ms` },
])
const answerParts = [
  { key: 'answered_calls', label: '已解答', color: '#3476bb' },
  { key: 'unanswered_calls', label: '未命中', color: '#e6a23c' },
  { key: 'failed_calls', label: '失败', color: '#d03050' },
]
const hasAnswerTrend = computed(() => trend.value.some(row => Number(row.calls)))
const answerMax = computed(() => Math.max(1, ...trend.value.map(row => Number(row.calls) || 0)))
const answerBars = computed(() => {
  const count = Math.max(1, trend.value.length)
  const slot = (chartWidth.value - 86) / count
  const width = Math.max(2, Math.min(28, slot * 0.7))
  return trend.value.map((row, index) => {
    let top = 180
    const segments = answerParts.map(part => {
      const height = (Number(row[part.key]) || 0) / answerMax.value * 160
      top -= height
      return { key: part.key, color: part.color, y: top, height }
    }).filter(seg => seg.height > 0)
    const total = Number(row.calls) || 0
    return {
      bucket: row.bucket, x: 68 + index * slot + (slot - width) / 2, width, segments, total,
      answered: row.answered_calls || 0, unanswered: row.unanswered_calls || 0, failed: row.failed_calls || 0,
      rate: total ? `${Math.round((row.answered_calls || 0) / total * 100)}%` : '无',
    }
  })
})
const channels = computed(() => {
  const rows = data.value.by_source || []
  const empty = source => ({ source, calls: 0, call_ratio: 0, answered_calls: 0, answer_rate: 0 })
  return [...mainChannels.map(source => rows.find(row => row.source === source) || empty(source)),
    ...rows.filter(row => !mainChannels.includes(row.source))]
})
const axisNumber = value => Number(value).toLocaleString('zh-CN', { notation: 'compact', maximumFractionDigits: 1 })
const time = value => value ? formatBeijingDateTime(value) : '无'
const shortTime = value => value ? time(value).slice(5, granularity.value === 'hour' ? 16 : 10) : ''
const userName = id => {
  const user = usersById.value[id]
  return user?.first_name?.trim() || user?.username?.trim() || `用户 ${id}`
}
const userOptions = computed(() => {
  const selected = userId.value && usersById.value[userId.value]
  return selected && !searchedUsers.value.some(user => Number(user.id) === Number(userId.value))
    ? [selected, ...searchedUsers.value] : searchedUsers.value
})
function rememberUsers(users) { for (const user of users || []) usersById.value[Number(user.id)] = user }
// Names the server attached, for viewers who cannot read the IAM user list themselves.
function rememberServerNames(rows) {
  for (const row of rows || []) {
    if (row.user_name && !usersById.value[row.user_id]) usersById.value[row.user_id] = { id: row.user_id, first_name: row.user_name }
  }
}
async function loadUserNames(items) {
  const ids = [...new Set((items || []).map(row => row.user_id))].filter(id => id && !usersById.value[id])
  if (!ids.length) return
  try {
    const result = await adminApi.getUsers({ ids: ids.join(','), limit: ids.length })
    rememberUsers(result.items || result)
  } catch { /* keep user ids */ }
}
async function searchUsers(search) {
  const requestId = ++userSearchRequest
  userSearchLoading.value = true
  try {
    const result = await adminApi.getUsers({ search: search.trim() || undefined, limit: 50 })
    if (requestId !== userSearchRequest) return
    searchedUsers.value = result.items || result
    rememberUsers(searchedUsers.value)
  } catch { if (requestId === userSearchRequest) searchedUsers.value = [] } finally {
    if (requestId === userSearchRequest) userSearchLoading.value = false
  }
}
function params() {
  if (period.value === 'custom' && dateRange.value?.length !== 2) return null
  return {
    period: period.value,
    ...(period.value === 'custom' ? { start_date: dateRange.value[0], end_date: dateRange.value[1] } : {}),
    ...(userId.value ? { user_id: userId.value } : {}),
    ...(includeTests.value ? { include_tests: true } : {}),
  }
}
async function loadSummary() {
  const requestId = ++summaryRequest
  const query = params()
  error.value = ''
  if (!query) { data.value = {}; return }
  loading.value = true
  try {
    const result = await knowledgeApi.getUsage({ ...query, granularity: granularity.value })
    if (requestId !== summaryRequest) return
    data.value = result
    rememberServerNames(result.by_user)
    loadUserNames(result.by_user)
  } catch (err) {
    if (requestId === summaryRequest) { error.value = knowledgeErrorText(err, '知识库调用用量加载失败'); data.value = {} }
  } finally { if (requestId === summaryRequest) loading.value = false }
}
async function loadTable() {
  if (detailTab.value !== 'calls') return
  const requestId = ++tableRequest
  const query = params()
  tableError.value = ''
  if (!query) { rows.value = []; total.value = 0; return }
  tableLoading.value = true
  try {
    const result = await knowledgeApi.getUsageCalls({ ...query, status: callStatus.value, skip: (page.value - 1) * pageSize, limit: pageSize })
    if (requestId !== tableRequest) return
    rememberServerNames(result.items)
    await loadUserNames(result.items)
    rows.value = result.items || []
    total.value = result.total || 0
  } catch (err) {
    if (requestId === tableRequest) { tableError.value = knowledgeErrorText(err, '调用明细加载失败'); rows.value = []; total.value = 0 }
  } finally { if (requestId === tableRequest) tableLoading.value = false }
}
function resetTable() { page.value = 1; return loadTable() }
function refresh() { loadSummary(); resetTable() }
function inspectUser(id) { userId.value = id; detailTab.value = 'calls'; refresh() }
onMounted(() => {
  refresh()
  chartObserver = new ResizeObserver(([entry]) => {
    if (entry.contentRect.width) chartWidth.value = Math.max(280, entry.contentRect.width)
  })
  if (chartElement.value) chartObserver.observe(chartElement.value)
})
onBeforeUnmount(() => chartObserver?.disconnect())
</script>

<style scoped>
.usage-page { min-width: 0; color: #30343b; }
.usage-heading { margin-bottom: 28px; }
.usage-heading h2 { margin: 0; font-size: 24px; line-height: 1.5; }
.usage-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 24px; }
.usage-filters :deep(.el-date-editor) { max-width: 100%; flex: 0 1 300px; }
.compact-select { width: 100px; }
.user-select { width: 220px; max-width: 100%; }
.status-select { width: 200px; }
.usage-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 22px; margin: 0 0 28px; padding: 10px 0 24px; border-bottom: 1px solid #e5e7eb; }
.usage-metrics dt { color: #747b86; font-size: 13px; }
.usage-metrics dd { margin: 10px 0 4px; font-size: 24px; font-weight: 600; overflow-wrap: anywhere; }
.usage-metrics span { color: #9aa0a8; font-size: 12px; }
.usage-charts { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 30px; margin-bottom: 28px; }
.usage-charts section { min-width: 0; }
.chart-column { min-width: 0; display: flex; flex-direction: column; gap: 24px; }
.stack-legend { display: inline-flex; gap: 12px; }
.stack-legend span { display: inline-flex; align-items: center; gap: 4px; }
.stack-legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
.warn { color: #c27c0e; }
.metric-tip { margin-left: 2px; vertical-align: -2px; color: #9aa0a8; cursor: help; }
.usage-metrics dd.good { color: #29906b; }
.usage-metrics dd.warn { color: #c27c0e; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.section-heading h3 { font-size: 15px; margin: 0; }
.section-heading > span { font-size: 12px; color: #747b86; }
.source-heading { margin-top: 24px; }
.trend-chart { min-height: 180px; display: flex; align-items: center; }
.trend-chart svg { width: 100%; height: 220px; }
.ratio-row { margin: 14px 0; }
.ratio-row > div:first-child { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 7px; font-size: 13px; }
.ratio-row span { overflow-wrap: anywhere; }
.ratio-row strong { flex-shrink: 0; font-weight: 500; }
.ratio-row small { display: block; margin-top: 5px; color: #9aa0a8; font-size: 12px; }
.doc-rank { margin: 0; padding: 0; list-style: none; }
.doc-name { display: inline-flex; align-items: baseline; gap: 8px; min-width: 0; }
.doc-name em { flex-shrink: 0; width: 18px; color: #9aa0a8; font-style: normal; font-weight: 600; text-align: right; }
.doc-name em.top { color: #3476bb; }
.overview-summary { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 22px; margin: 4px 0 14px; font-size: 13px; color: #606266; }
.overview-summary strong { margin: 0 3px; color: #30343b; font-size: 18px; font-weight: 600; }
.danger { color: #d03050; }
.inline-ratio { display: flex; align-items: center; gap: 8px; }
.inline-ratio .el-progress { flex: 1; }
.inline-ratio span { width: 52px; text-align: right; font-size: 12px; color: #606266; }
.detail-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 14px; }
.muted { color: #747b86; font-size: 12px; }
.usage-pagination { display: flex; justify-content: flex-end; margin-top: 20px; }
@media (max-width: 760px) {
  .usage-charts { grid-template-columns: 1fr; }
  .usage-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px 12px; }
}
</style>
