<template>
  <div class="token-dashboard">
    <div class="page-head">
      <div>
        <h2>我的用量 / Token 用量</h2>
        <p>按照当前 AI Hub 登录用户匹配 sub2api 邮箱，展示个人 Token 使用情况。</p>
      </div>
    </div>

    <el-card class="source-card" shadow="never">
      <div class="source-grid">
        <div>
          <span>用户名</span>
          <strong>{{ displayUserName }}</strong>
        </div>
        <div>
          <span>邮箱</span>
          <strong>{{ user.email || '-' }}</strong>
        </div>
        <div>
          <span>匹配方式</span>
          <strong>AI Hub username -> sub2api users.email 前缀</strong>
        </div>
        <el-tag type="success" effect="plain" round>个人视图 · 当前用户可见</el-tag>
      </div>
    </el-card>

    <div class="metric-grid" v-loading="loading">
      <el-card v-for="item in metricCards" :key="item.label" shadow="never" class="metric-card">
        <div class="metric-icon" :class="item.type">{{ item.icon }}</div>
        <div>
          <div class="metric-label">{{ item.label }}</div>
          <div class="metric-value">{{ item.value }}</div>
          <div class="metric-sub">{{ item.sub }}</div>
        </div>
      </el-card>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="filter-row">
        <div class="filter-controls">
          <span class="filter-label">统计周期：</span>
          <el-segmented v-model="filters.period" :options="periodOptions" @change="handlePeriodChange" />
          <el-date-picker
            v-if="filters.period === 'custom'"
            v-model="customDateRange"
            class="custom-range"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            @change="loadDashboard"
          />
          <span class="filter-label">趋势粒度：</span>
          <el-segmented v-model="filters.granularity" :options="granularityOptions" @change="loadDashboard" />
          <el-button type="primary" :loading="loading" @click="loadDashboard">刷新数据</el-button>
        </div>
      </div>
    </el-card>

    <div class="top-grid">
      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="panel-head">
            <h3>我的 Token 趋势</h3>
            <div class="legend">
              <span><i class="dot total"></i>总 Token</span>
              <span><i class="dot input"></i>输入</span>
              <span><i class="dot output"></i>输出</span>
              <span><i class="dot cache"></i>缓存</span>
            </div>
          </div>
        </template>
        <div class="chart-box">
          <svg v-if="trend.length" viewBox="0 0 720 220" preserveAspectRatio="none">
            <g class="grid-lines">
              <line
                v-for="tick in trendYAxisTicks"
                :key="tick.index"
                x1="54"
                :y1="tick.y"
                x2="708"
                :y2="tick.y"
              />
            </g>
            <line class="axis-line" x1="54" y1="180" x2="708" y2="180" />
            <line class="axis-line" x1="54" y1="16" x2="54" y2="180" />
            <path :d="buildAxisPath('total_tokens')" class="line total" />
            <path :d="buildAxisPath('cache_tokens')" class="line cache" />
            <path :d="buildAxisPath('input_tokens')" class="line input" />
            <path :d="buildAxisPath('output_tokens')" class="line output" />
          </svg>
          <div v-if="trend.length" class="axis-label-layer">
            <span
              v-for="tick in trendYAxisTicks"
              :key="`trend-y-${tick.index}`"
              class="axis-label axis-label-y"
              :style="axisLabelStyle(tick, 'y', trendChart)"
            >{{ tick.label }}</span>
            <span
              v-for="tick in trendXAxisTicks"
              :key="`trend-x-${tick.index}`"
              class="axis-label axis-label-x"
              :style="axisLabelStyle(tick, 'x', trendChart)"
            >{{ tick.label }}</span>
          </div>
          <el-empty v-else description="暂无趋势数据" :image-size="80" />
        </div>
      </el-card>

      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="panel-head">
            <h3>Token 构成</h3>
            <span class="muted">{{ activePeriodLabel }}</span>
          </div>
        </template>
        <div class="split-list">
          <div v-for="item in tokenBreakdown" :key="item.label" class="split-row">
            <div class="split-main">
              <strong>{{ item.label }}</strong>
              <span>{{ item.value }} / {{ item.ratio }}</span>
            </div>
            <el-progress :percentage="item.percent" :show-text="false" />
          </div>
        </div>
      </el-card>
    </div>

    <div class="detail-grid">
      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="panel-head">
            <h3>模型分布</h3>
            <span class="muted">Top {{ models.length }}</span>
          </div>
        </template>
        <RankBars :items="models" />
      </el-card>

      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="panel-head">
            <h3>API Key 用量</h3>
            <span class="muted">Top {{ apiKeys.length }}</span>
          </div>
        </template>
        <RankBars :items="apiKeys" />
      </el-card>

      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="panel-head">
            <h3>Endpoint 分布</h3>
            <span class="muted">Top {{ endpoints.length }}</span>
          </div>
        </template>
        <RankBars :items="endpoints" />
      </el-card>
    </div>

    <el-card shadow="never" class="panel-card recent-card">
      <template #header>
        <div class="panel-head">
          <h3>最近请求明细</h3>
          <span class="muted">展示当前周期最近 20 条记录</span>
        </div>
      </template>
      <div class="request-filter">
        <span class="filter-label">搜索请求：</span>
        <el-input
          v-model="filters.requestSearch"
          clearable
          placeholder="输入 API Key 或模型名称"
          @clear="clearRequestSearch"
          @keyup.enter="confirmRequestSearch"
        />
        <el-button type="primary" @click="confirmRequestSearch">查询</el-button>
      </div>
      <el-table
        v-loading="loading"
        :data="pagedRecentRequests"
        :default-sort="{ prop: 'created_at', order: 'descending' }"
        row-key="created_at"
        empty-text="暂无请求明细"
        @sort-change="handleRecentSortChange"
      >
        <el-table-column prop="created_at" label="时间" min-width="130" sortable="custom">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="api_key_name" label="API Key" min-width="130" sortable="custom" />
        <el-table-column prop="model" label="模型" min-width="130" sortable="custom" />
        <el-table-column prop="input_tokens" label="输入" align="right" min-width="130" sortable="custom">
          <template #default="{ row }">{{ formatTokens(row.input_tokens) }}</template>
        </el-table-column>
        <el-table-column prop="output_tokens" label="输出" align="right" min-width="130" sortable="custom">
          <template #default="{ row }">{{ formatTokens(row.output_tokens) }}</template>
        </el-table-column>
        <el-table-column prop="cache_tokens" label="Cache" align="right" min-width="130" sortable="custom">
          <template #default="{ row }">{{ formatTokens(row.cache_tokens) }}</template>
        </el-table-column>
        <el-table-column prop="total_tokens" label="总 Token" align="right" min-width="130" sortable="custom">
          <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
        </el-table-column>
        <el-table-column prop="duration_ms" label="响应" align="right" min-width="130" sortable="custom">
          <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="filteredRecentRequests.length" class="pagination-container">
        <el-pagination
          v-model:current-page="recentPagination.currentPage"
          v-model:page-size="recentPagination.pageSize"
          :page-sizes="[10, 20, 50]"
          :total="filteredRecentRequests.length"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleRecentPageSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import { ElMessage, ElProgress } from 'element-plus'
import { dashboardApi } from '@/api/dashboard'
import { formatBeijingDateTime, getBeijingDateTimeParts } from '@/utils/date-time'

const periodOptions = [
  { label: '今日', value: 'today' },
  { label: '近 7 天', value: '7d' },
  { label: '本月', value: 'month' },
  { label: '自定义', value: 'custom' }
]

const granularityOptions = [
  { label: '按小时', value: 'hour' },
  { label: '按天', value: 'day' },
  { label: '按周', value: 'week' }
]

const trendChart = {
  width: 720,
  height: 220,
  padding: { left: 54, right: 12, top: 16, bottom: 40 }
}

const filters = ref({
  period: '7d',
  granularity: 'day',
  requestSearch: ''
})
const confirmedRequestSearch = ref('')
const customDateRange = ref([])
const loading = ref(false)
const user = ref({})
const summary = ref({})
const trend = ref([])
const models = ref([])
const apiKeys = ref([])
const endpoints = ref([])
const recentRequests = ref([])
const recentPagination = ref({
  currentPage: 1,
  pageSize: 10
})
const recentSort = ref({
  prop: 'created_at',
  order: 'descending'
})

const RankBars = defineComponent({
  props: {
    items: {
      type: Array,
      default: () => []
    }
  },
  setup(props) {
    return () => h('div', { class: 'rank-bars' },
      props.items?.length
        ? props.items.map(item => h('div', { class: 'detail-rank-row', key: item.name }, [
          h('div', { class: 'detail-rank-main' }, [
            h('span', item.name || '-'),
            h('strong', `${formatTokens(item.total_tokens)} / ${formatPercent(item.ratio)}`)
          ]),
          h(ElProgress, {
            percentage: Math.min(Number(item.ratio || 0), 100),
            showText: false
          })
        ]))
        : h('div', { class: 'empty-small' }, '暂无数据')
    )
  }
})

const activePeriodLabel = computed(() => {
  return periodOptions.find(item => item.value === filters.value.period)?.label || '近 7 天'
})

const displayUserName = computed(() => {
  return user.value.aihub_first_name || user.value.username || user.value.aihub_username || '-'
})
const trendYAxisTicks = computed(() => buildYAxisTicks(getRowsMax(trend.value), trendChart))
const trendXAxisTicks = computed(() => buildXAxisTicks(trend.value, trendChart))

const metricCards = computed(() => [
  {
    label: '我的总 Token',
    value: formatTokens(summary.value.total_tokens),
    sub: `输入 ${formatTokens(summary.value.input_tokens)} / 输出 ${formatTokens(summary.value.output_tokens)}`,
    type: 'blue',
    icon: 'T'
  },
  {
    label: '请求数',
    value: String(summary.value.request_count || 0),
    sub: `平均 ${formatTokens(avgTokensPerRequest.value)} / 请求`,
    type: 'green',
    icon: '次'
  },
  {
    label: '缓存占比',
    value: formatPercent(summary.value.cache_ratio),
    sub: `缓存 ${formatTokens(summary.value.cache_tokens)}`,
    type: 'purple',
    icon: '%'
  },
  {
    label: '平均响应',
    value: formatDuration(summary.value.avg_duration_ms),
    sub: `首 Token ${formatDuration(summary.value.avg_first_token_ms)}`,
    type: 'yellow',
    icon: 'ms'
  }
])

const avgTokensPerRequest = computed(() => {
  const count = Number(summary.value.request_count || 0)
  if (!count) return 0
  return Number(summary.value.total_tokens || 0) / count
})

const tokenBreakdown = computed(() => {
  const total = Number(summary.value.total_tokens || 0)
  const items = [
    { label: '输入 Token', value: Number(summary.value.input_tokens || 0) },
    { label: '输出 Token', value: Number(summary.value.output_tokens || 0) },
    { label: 'Cache Token', value: Number(summary.value.cache_tokens || 0) },
    { label: '图片输出 Token', value: Number(summary.value.image_output_tokens || 0) }
  ]
  return items.map(item => ({
    ...item,
    value: formatTokens(item.value),
    ratio: formatPercent(total ? (Number(summary.value[itemKey(item.label)] || 0) / total) * 100 : 0),
    percent: Math.round(total ? (Number(summary.value[itemKey(item.label)] || 0) / total) * 100 : 0)
  }))
})

const filteredRecentRequests = computed(() => {
  const keyword = confirmedRequestSearch.value
  if (!keyword) return recentRequests.value
  return recentRequests.value.filter(row => {
    return [row.api_key_name, row.model]
      .some(value => String(value || '').toLowerCase().includes(keyword))
  })
})
const sortedRecentRequests = computed(() => sortRows(filteredRecentRequests.value, recentSort.value))
const pagedRecentRequests = computed(() => paginateRows(sortedRecentRequests.value, recentPagination.value))

onMounted(() => {
  loadDashboard()
})

function itemKey(label) {
  if (label === '输入 Token') return 'input_tokens'
  if (label === '输出 Token') return 'output_tokens'
  if (label === 'Cache Token') return 'cache_tokens'
  return 'image_output_tokens'
}

function buildParams() {
  const params = {
    period: filters.value.period,
    granularity: filters.value.granularity
  }
  if (filters.value.period === 'custom' && customDateRange.value?.length === 2) {
    params.start_date = customDateRange.value[0]
    params.end_date = customDateRange.value[1]
  }
  return params
}

async function loadDashboard() {
  if (filters.value.period === 'custom' && customDateRange.value?.length !== 2) {
    clearDashboard()
    return
  }

  loading.value = true
  try {
    const data = await dashboardApi.getPersonalTokenUsage(buildParams())
    user.value = data.user || {}
    summary.value = data.summary || {}
    trend.value = data.trend || []
    models.value = data.models || []
    apiKeys.value = data.api_keys || []
    endpoints.value = data.endpoints || []
    recentRequests.value = data.recent_requests || []
    resetRecentPagination()
  } catch (error) {
    console.error('加载个人 Token 看板失败:', error)
    ElMessage.error(error.response?.data?.detail || '加载个人 Token 看板失败')
    clearDashboard()
  } finally {
    loading.value = false
  }
}

function clearDashboard() {
  user.value = {}
  summary.value = {}
  trend.value = []
  models.value = []
  apiKeys.value = []
  endpoints.value = []
  recentRequests.value = []
}

function handlePeriodChange() {
  if (filters.value.period !== 'custom') {
    loadDashboard()
  }
}

function confirmRequestSearch() {
  confirmedRequestSearch.value = (filters.value.requestSearch || '').trim().toLowerCase()
  resetRecentPagination()
}

function clearRequestSearch() {
  filters.value.requestSearch = ''
  confirmedRequestSearch.value = ''
  resetRecentPagination()
}

function paginateRows(rows, pagination) {
  const currentPage = Number(pagination.currentPage || 1)
  const pageSize = Number(pagination.pageSize || 10)
  const start = (currentPage - 1) * pageSize
  return rows.slice(start, start + pageSize)
}

function sortRows(rows, sortState) {
  if (!sortState?.prop || !sortState?.order) return rows
  const direction = sortState.order === 'ascending' ? 1 : -1
  return [...rows].sort((a, b) => compareValue(a?.[sortState.prop], b?.[sortState.prop]) * direction)
}

function compareValue(a, b) {
  if (a === b) return 0
  if (a === null || a === undefined || a === '') return -1
  if (b === null || b === undefined || b === '') return 1
  const dateA = Date.parse(a)
  const dateB = Date.parse(b)
  if (!Number.isNaN(dateA) && !Number.isNaN(dateB)) {
    return dateA - dateB
  }
  const numA = Number(a)
  const numB = Number(b)
  if (!Number.isNaN(numA) && !Number.isNaN(numB)) {
    return numA - numB
  }
  return String(a).localeCompare(String(b), 'zh-CN')
}

function resetRecentPagination() {
  recentPagination.value.currentPage = 1
}

function handleRecentPageSizeChange() {
  resetRecentPagination()
}

function handleRecentSortChange({ prop, order }) {
  recentSort.value = { prop, order }
  resetRecentPagination()
}

function buildAxisPath(field, rows = trend.value, chart = trendChart) {
  return buildLinePath(rows, row => Number(row[field] || 0), chart, getRowsMax(rows))
}

function buildLinePath(rows, valueGetter, chart, maxValue) {
  if (!rows?.length) return ''
  const { width, height, padding } = chart
  const innerWidth = width - padding.left - padding.right
  const innerHeight = height - padding.top - padding.bottom
  const max = Math.max(Number(maxValue || 0), 1)
  return rows.map((row, index) => {
    const x = rows.length === 1
      ? padding.left + innerWidth / 2
      : padding.left + (index / (rows.length - 1)) * innerWidth
    const y = padding.top + innerHeight - (Number(valueGetter(row) || 0) / max) * innerHeight
    return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
  }).join(' ')
}

function buildYAxisTicks(maxValue, chart) {
  const { height, padding } = chart
  const innerHeight = height - padding.top - padding.bottom
  return [1, 0.75, 0.5, 0.25, 0].map((ratio, index) => ({
    index,
    label: formatTokens(Number(maxValue || 0) * ratio),
    y: Number((padding.top + (1 - ratio) * innerHeight).toFixed(2))
  }))
}

function buildXAxisTicks(rows, chart) {
  if (!rows?.length) return []
  const { width, padding } = chart
  const innerWidth = width - padding.left - padding.right
  const maxTicks = 5
  const step = Math.max(1, Math.ceil(rows.length / maxTicks))
  const lastIndex = rows.length - 1
  const ticks = []
  rows.forEach((row, index) => {
    if (index % step !== 0 && index !== lastIndex) return
    const x = rows.length === 1
      ? padding.left + innerWidth / 2
      : padding.left + (index / (rows.length - 1)) * innerWidth
    ticks.push({
      index,
      x: Number(x.toFixed(2)),
      label: formatBucket(row.bucket)
    })
  })
  return ticks
}

function getRowsMax(rows) {
  return Math.max(...(rows || []).map(row => Number(row.total_tokens || 0)), 1)
}

function axisLabelStyle(tick, type, chart) {
  const rawX = type === 'y' ? chart.padding.left - 8 : tick.x
  const x = type === 'x'
    ? Math.min(Math.max(rawX, 58), chart.width - 34)
    : rawX
  const y = type === 'y' ? tick.y : 211
  return {
    left: `${(x / chart.width) * 100}%`,
    top: `${(y / chart.height) * 100}%`
  }
}

function formatTokens(value) {
  const num = Number(value || 0)
  if (num >= 1000000000) return `${(num / 1000000000).toFixed(2)}B`
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
  return String(Math.round(num))
}

function formatPercent(value) {
  return `${Number(value || 0).toFixed(1)}%`
}

function formatDuration(value) {
  const num = Number(value || 0)
  if (!num) return '-'
  if (num >= 1000) return `${(num / 1000).toFixed(1)}s`
  return `${Math.round(num)}ms`
}

function formatTime(value) {
  if (!value) return '-'
  return formatBeijingDateTime(value, {
    year: undefined,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: undefined,
  })
}

function formatBucket(value) {
  const parts = getBeijingDateTimeParts(value)
  if (!parts) return '-'
  if (filters.value.granularity === 'hour') {
    return `${parts.month}/${parts.day} ${parts.hour}时`
  }
  return `${parts.month}/${parts.day}`
}
</script>

<style scoped>
.token-dashboard {
  min-width: 980px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;
}

.page-head h2 {
  margin: 0 0 8px;
  color: #111827;
  font-size: 24px;
}

.page-head p {
  margin: 0;
  color: #6b7280;
  font-size: 13px;
}

.source-card,
.metric-card,
.panel-card,
.filter-card {
  border-radius: 8px;
  border-color: #e4eaf2;
}

.source-card {
  margin-bottom: 18px;
}

.source-grid {
  display: grid;
  grid-template-columns: minmax(160px, .8fr) minmax(300px, 1.1fr) minmax(360px, 1.4fr) auto;
  align-items: center;
  gap: 28px;
}

.source-grid > div {
  min-width: 0;
}

.source-grid span,
.metric-label,
.metric-sub,
.muted {
  color: #8290a3;
  font-size: 12px;
}

.source-grid strong {
  display: block;
  margin-top: 4px;
  color: #172033;
  overflow-wrap: anywhere;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.metric-card :deep(.el-card__body) {
  display: grid;
  grid-template-columns: 42px 1fr;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
}

.metric-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  font-weight: 700;
}

.metric-icon.blue { color: #2f7cf6; background: #eef6ff; }
.metric-icon.green { color: #10b981; background: #ecfdf5; }
.metric-icon.purple { color: #8b5cf6; background: #f5f3ff; }
.metric-icon.yellow { color: #ca8a04; background: #fefce8; }

.metric-value {
  margin-top: 3px;
  color: #111827;
  font-size: 22px;
  line-height: 1;
  font-weight: 700;
}

.metric-sub {
  margin-top: 6px;
}

.filter-card {
  margin-bottom: 16px;
}

.filter-row,
.request-filter {
  display: flex;
  align-items: center;
  gap: 12px;
}

.filter-row {
  justify-content: flex-end;
  overflow-x: auto;
  padding-bottom: 2px;
}

.filter-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: nowrap;
  gap: 12px;
}

.filter-controls :deep(.el-segmented),
.filter-controls :deep(.el-button) {
  flex: 0 0 auto;
}

.request-filter {
  margin-bottom: 14px;
}

.request-filter .el-input {
  max-width: 360px;
}

.pagination-container {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.filter-label {
  flex: 0 0 auto;
  color: #4b5563;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
}

.custom-range {
  flex: 0 0 300px;
  width: 300px;
  margin-top: 0;
}

.top-grid {
  display: grid;
  grid-template-columns: 1.1fr .9fr;
  gap: 16px;
  margin-bottom: 16px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.recent-card {
  margin-bottom: 8px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-head h3 {
  margin: 0;
  color: #111827;
  font-size: 16px;
}

.legend {
  display: flex;
  gap: 14px;
  color: #64748b;
  font-size: 12px;
}

.dot {
  width: 8px;
  height: 8px;
  display: inline-block;
  margin-right: 5px;
  border-radius: 50%;
}

.dot.total { background: #8b5cf6; }
.dot.input { background: #3b82f6; }
.dot.output { background: #10b981; }
.dot.cache { background: #06b6d4; }

.chart-box {
  position: relative;
  height: 235px;
  overflow: hidden;
}

svg {
  width: 100%;
  height: 100%;
}

.grid-lines line {
  stroke: #e7edf5;
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.axis-line {
  stroke: #d8e0eb;
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.axis-label-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.axis-label {
  position: absolute;
  color: #8491a5;
  font-family: Arial, "Microsoft YaHei", sans-serif;
  font-size: 10.5px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
}

.axis-label-y {
  transform: translate(-100%, -50%);
  text-align: right;
}

.axis-label-x {
  transform: translate(-50%, -50%) rotate(-24deg);
  transform-origin: center;
}

.line {
  fill: none;
  stroke-width: 4;
  vector-effect: non-scaling-stroke;
}

.line.total { stroke: #8b5cf6; }
.line.input { stroke: #3b82f6; stroke-width: 3; }
.line.output { stroke: #10b981; stroke-width: 3; }
.line.cache { stroke: #06b6d4; }

.split-list,
.rank-bars,
:deep(.rank-bars) {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.detail-rank-row,
:deep(.detail-rank-row) {
  padding: 10px 0 6px;
}

.split-main,
.detail-rank-main,
:deep(.detail-rank-main) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 36px;
  margin-bottom: 16px;
  color: #334155;
  font-size: 13px;
}

.detail-rank-main span,
:deep(.detail-rank-main span) {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-rank-main strong,
:deep(.detail-rank-main strong) {
  flex: 0 0 auto;
  min-width: 112px;
  padding-left: 20px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.split-main span,
.detail-rank-main strong,
:deep(.detail-rank-main strong) {
  color: #2563eb;
  font-weight: 700;
}

.detail-rank-row :deep(.el-progress),
:deep(.detail-rank-row .el-progress) {
  margin-top: 10px;
}

.empty-small {
  color: #8a94a6;
  font-size: 13px;
  text-align: center;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .top-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .source-grid,
  .filter-row,
  .request-filter {
    align-items: stretch;
    flex-direction: column;
  }

  .filter-controls {
    align-items: stretch;
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .custom-range {
    flex: 1 1 300px;
    width: 300px;
  }

  .source-grid {
    display: flex;
  }
}
</style>
