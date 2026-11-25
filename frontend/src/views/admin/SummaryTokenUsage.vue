<template>
  <div class="token-dashboard">
    <div class="page-head">
      <div>
        <h2>全局用量 / Token 用量</h2>
        <p>统计所有 sub2api 用户的 Token 使用情况，点击用户行查看单个用户明细。</p>
      </div>
    </div>

    <el-card class="source-card" shadow="never">
      <div class="source-grid">
        <div>
          <span>统计范围</span>
          <strong>全部用户</strong>
        </div>
        <div>
          <span>活跃用户</span>
          <strong>{{ summary.active_users || 0 }} 人</strong>
        </div>
        <div>
          <span>数据源</span>
          <strong>sub2api users.email / usage_logs</strong>
        </div>
        <el-tag type="primary" effect="plain" round>汇总视图 · 管理员可见</el-tag>
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

    <div class="top-grid">
      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="panel-head">
            <h3>全平台 Token 趋势</h3>
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
                v-for="tick in platformYAxisTicks"
                :key="tick.index"
                x1="54"
                :y1="tick.y"
                x2="708"
                :y2="tick.y"
              />
            </g>
            <line class="axis-line" x1="54" y1="186" x2="708" y2="186" />
            <line class="axis-line" x1="54" y1="16" x2="54" y2="186" />
            <path :d="buildAxisPath('total_tokens')" class="line total" />
            <path :d="buildAxisPath('cache_tokens')" class="line cache" />
            <path :d="buildAxisPath('input_tokens')" class="line input" />
            <path :d="buildAxisPath('output_tokens')" class="line output" />
          </svg>
          <div v-if="trend.length" class="axis-label-layer">
            <span
              v-for="tick in platformYAxisTicks"
              :key="`platform-y-${tick.index}`"
              class="axis-label axis-label-y"
              :style="axisLabelStyle(tick, 'y', platformChart)"
            >{{ tick.label }}</span>
            <span
              v-for="tick in platformXAxisTicks"
              :key="`platform-x-${tick.index}`"
              class="axis-label axis-label-x"
              :style="axisLabelStyle(tick, 'x', platformChart)"
            >{{ tick.label }}</span>
          </div>
          <el-empty v-else description="暂无趋势数据" :image-size="80" />
        </div>
      </el-card>

      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="panel-head">
            <h3>用户名 Token 排行</h3>
            <span class="muted">Top {{ rankUsers.length }}</span>
          </div>
        </template>
        <div class="rank-list">
          <div v-for="user in rankUsers" :key="user.user_id" class="rank-row">
            <div class="rank-main">
              <strong>{{ user.username || '-' }}</strong>
              <span>{{ formatTokens(user.total_tokens) }} / {{ platformRatio(user.total_tokens) }}%</span>
            </div>
            <el-progress :percentage="rankPercent(user.total_tokens)" :show-text="false" />
          </div>
          <el-empty v-if="!rankUsers.length" description="暂无用户数据" :image-size="80" />
        </div>
      </el-card>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="filter-row">
        <div class="filter-search">
          <span class="filter-label">搜索用户</span>
          <el-input
            v-model="filters.search"
            class="search-input"
            clearable
            placeholder="输入用户名、邮箱或 API Key 名称"
            @clear="loadDashboard"
            @keyup.enter="loadDashboard"
          />
          <el-button type="primary" @click="loadDashboard">查询</el-button>
        </div>
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

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="panel-head">
          <h3>用户 Token 明细列表</h3>
          <span class="muted">点击用户行查看用量明细弹窗</span>
        </div>
      </template>
      <el-table
        v-loading="loading"
        class="usage-table"
        table-layout="fixed"
        :data="pagedUsers"
        row-key="user_id"
        :default-sort="{ prop: 'total_tokens', order: 'descending' }"
        empty-text="暂无用户 Token 数据"
        @row-click="openUserDetail"
        @sort-change="handleUserSortChange"
      >
        <el-table-column prop="username" label="用户名" min-width="160" show-overflow-tooltip sortable="custom">
          <template #default="{ row }">
            <strong class="clickable-name">{{ row.username || '-' }}</strong>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="220" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="total_tokens" label="总 Token" align="right" min-width="160" sortable="custom">
          <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
        </el-table-column>
        <el-table-column prop="request_count" label="请求数" align="right" min-width="160" sortable="custom" />
        <el-table-column prop="cache_ratio" label="Cache 占比" align="right" min-width="160" sortable="custom">
          <template #default="{ row }">{{ formatPercent(row.cache_ratio) }}</template>
        </el-table-column>
        <el-table-column prop="peak_tpm" label="高峰 TPM" align="right" min-width="160" sortable="custom">
          <template #default="{ row }">{{ formatTokens(row.peak_tpm) }}</template>
        </el-table-column>
        <el-table-column prop="trend_rate" label="趋势" align="right" min-width="170" class-name="trend-column" sortable="custom">
          <template #default="{ row }">
            <span :class="row.trend_rate >= 0 ? 'trend-up' : 'trend-down'">
              {{ formatTrend(row.trend_rate) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" align="center" min-width="150" class-name="status-column" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="row.status === 'growth' ? 'warning' : 'success'" round>
              {{ row.status === 'growth' ? '增长' : '正常' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="users.length" class="pagination-container">
        <el-pagination
          v-model:current-page="userPagination.currentPage"
          v-model:page-size="userPagination.pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="users.length"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleUserPageSizeChange"
        />
      </div>
    </el-card>

    <el-dialog
      v-model="detailVisible"
      width="860px"
      class="usage-detail-dialog"
      :title="detailTitle"
    >
      <div v-loading="detailLoading">
        <div v-if="userDetail" class="detail-content">
          <p class="detail-subtitle">
            {{ userDetail.user.email }} · 统计周期：{{ activePeriodLabel }}
          </p>

          <div class="detail-metrics">
            <div v-for="item in detailMetricCards" :key="item.label" class="detail-metric">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <small>{{ item.sub }}</small>
            </div>
          </div>

          <div class="detail-grid">
            <div class="detail-panel">
              <h4>该用户 Token 趋势</h4>
              <div class="detail-chart-box">
                <svg
                  v-if="userDetail.trend?.length"
                  :viewBox="`0 0 ${detailChart.width} ${detailChart.height}`"
                  preserveAspectRatio="none"
                >
                  <g class="grid-lines">
                    <line
                      v-for="tick in detailYAxisTicks"
                      :key="`detail-grid-${tick.index}`"
                      :x1="detailChart.padding.left"
                      :y1="tick.y"
                      :x2="detailChart.width - detailChart.padding.right"
                      :y2="tick.y"
                    />
                  </g>
                  <line
                    class="axis-line"
                    :x1="detailChart.padding.left"
                    :y1="detailChart.height - detailChart.padding.bottom"
                    :x2="detailChart.width - detailChart.padding.right"
                    :y2="detailChart.height - detailChart.padding.bottom"
                  />
                  <line
                    class="axis-line"
                    :x1="detailChart.padding.left"
                    :y1="detailChart.padding.top"
                    :x2="detailChart.padding.left"
                    :y2="detailChart.height - detailChart.padding.bottom"
                  />
                  <path :d="buildAxisPath('total_tokens', userDetail.trend, detailChart)" class="line total" />
                  <path :d="buildAxisPath('cache_tokens', userDetail.trend, detailChart)" class="line cache" />
                  <path :d="buildAxisPath('input_tokens', userDetail.trend, detailChart)" class="line input" />
                </svg>
                <div v-if="userDetail.trend?.length" class="axis-label-layer">
                  <span
                    v-for="tick in detailYAxisTicks"
                    :key="`detail-y-${tick.index}`"
                    class="axis-label axis-label-y"
                    :style="axisLabelStyle(tick, 'y', detailChart)"
                  >{{ tick.label }}</span>
                  <span
                    v-for="tick in detailXAxisTicks"
                    :key="`detail-x-${tick.index}`"
                    class="axis-label axis-label-x"
                    :style="axisLabelStyle(tick, 'x', detailChart)"
                  >{{ tick.label }}</span>
                </div>
                <el-empty v-else description="暂无趋势数据" :image-size="60" />
              </div>
            </div>
            <div class="detail-panel">
              <h4>模型分布</h4>
              <RankBars :items="userDetail.models" />
            </div>
            <div class="detail-panel">
              <h4>API Key 用量</h4>
              <RankBars :items="userDetail.api_keys" />
            </div>
            <div class="detail-panel">
              <h4>Endpoint 分布</h4>
              <RankBars :items="userDetail.endpoints" />
            </div>
          </div>

          <div class="recent-panel">
            <h4>最近请求摘要</h4>
            <el-table
              class="detail-recent-table"
              :data="pagedDetailRecentRequests"
              size="small"
              max-height="260"
              table-layout="fixed"
              @sort-change="handleDetailSortChange"
            >
              <el-table-column prop="created_at" label="时间" min-width="150" sortable="custom">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column prop="api_key_name" label="API Key" min-width="170" show-overflow-tooltip sortable="custom" />
              <el-table-column prop="model" label="模型" min-width="150" show-overflow-tooltip sortable="custom" />
              <el-table-column prop="total_tokens" label="总 Token" align="right" min-width="150" sortable="custom">
                <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
              </el-table-column>
              <el-table-column prop="duration_ms" label="耗时" align="right" min-width="130" sortable="custom">
                <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
              </el-table-column>
            </el-table>
            <div v-if="detailRecentRequests.length" class="pagination-container compact">
              <el-pagination
                v-model:current-page="detailPagination.currentPage"
                v-model:page-size="detailPagination.pageSize"
                :page-sizes="[5, 10, 20]"
                :total="detailRecentRequests.length"
                layout="total, sizes, prev, pager, next"
                @size-change="handleDetailPageSizeChange"
              />
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
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

const platformChart = {
  width: 720,
  height: 220,
  padding: { left: 54, right: 12, top: 16, bottom: 34 }
}

const detailChart = {
  width: 360,
  height: 170,
  padding: { left: 50, right: 8, top: 16, bottom: 34 }
}

const filters = ref({
  period: '7d',
  granularity: 'day',
  search: ''
})
const customDateRange = ref([])
const loading = ref(false)
const detailLoading = ref(false)
const detailVisible = ref(false)
const summary = ref({})
const trend = ref([])
const users = ref([])
const userDetail = ref(null)
const userPagination = ref({
  currentPage: 1,
  pageSize: 10
})
const detailPagination = ref({
  currentPage: 1,
  pageSize: 5
})
const userSort = ref({
  prop: 'total_tokens',
  order: 'descending'
})
const detailSort = ref({
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
            h('span', { class: 'detail-rank-name' }, item.name || '-'),
            h('strong', { class: 'detail-rank-value' }, `${formatTokens(item.total_tokens)} / ${formatPercent(item.ratio)}`)
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

const rankUsers = computed(() => users.value.slice(0, 5))
const maxUserTokens = computed(() => Math.max(...rankUsers.value.map(item => item.total_tokens || 0), 1))
const platformYAxisTicks = computed(() => buildYAxisTicks(getRowsMax(trend.value), platformChart))
const platformXAxisTicks = computed(() => buildXAxisTicks(trend.value, platformChart))
const detailYAxisTicks = computed(() => buildYAxisTicks(getRowsMax(userDetail.value?.trend || []), detailChart))
const detailXAxisTicks = computed(() => buildXAxisTicks(userDetail.value?.trend || [], detailChart))
const sortedUsers = computed(() => sortRows(users.value, userSort.value))
const pagedUsers = computed(() => paginateRows(sortedUsers.value, userPagination.value))
const detailRecentRequests = computed(() => userDetail.value?.recent_requests || [])
const sortedDetailRecentRequests = computed(() => sortRows(detailRecentRequests.value, detailSort.value))
const pagedDetailRecentRequests = computed(() => paginateRows(sortedDetailRecentRequests.value, detailPagination.value))

const metricCards = computed(() => [
  {
    label: '全平台总 Token',
    value: formatTokens(summary.value.total_tokens),
    sub: `输入 ${formatTokens(summary.value.input_tokens)} / 输出 ${formatTokens(summary.value.output_tokens)}`,
    type: 'blue',
    icon: 'T'
  },
  {
    label: '活跃用户',
    value: String(summary.value.active_users || 0),
    sub: '当前周期有调用记录',
    type: 'green',
    icon: '人'
  },
  {
    label: '缓存占比',
    value: formatPercent(summary.value.cache_ratio),
    sub: `缓存 ${formatTokens(summary.value.cache_tokens)}`,
    type: 'purple',
    icon: '%'
  },
  {
    label: '异常增长用户',
    value: String(summary.value.anomaly_users || 0),
    sub: '较上一周期增长超过 200%',
    type: 'yellow',
    icon: '!'
  }
])

const detailTitle = computed(() => {
  return userDetail.value ? `${userDetail.value.user.username} Token 用量明细` : 'Token 用量明细'
})

const detailMetricCards = computed(() => {
  const detail = userDetail.value
  if (!detail) return []
  return [
    {
      label: '总 Token',
      value: formatTokens(detail.summary.total_tokens),
      sub: `占全平台 ${formatPercent(detail.summary.platform_ratio)}`
    },
    {
      label: '请求数',
      value: String(detail.summary.request_count || 0),
      sub: `趋势 ${formatTrend(detail.summary.trend_rate)}`
    },
    {
      label: 'Cache 占比',
      value: formatPercent(detail.summary.cache_ratio),
      sub: `Cache ${formatTokens(detail.summary.cache_tokens)}`
    },
    {
      label: '平均响应',
      value: formatDuration(detail.summary.avg_duration_ms),
      sub: `首 Token ${formatDuration(detail.summary.avg_first_token_ms)}`
    }
  ]
})

onMounted(() => {
  loadDashboard()
})

function buildParams() {
  const params = {
    period: filters.value.period,
    granularity: filters.value.granularity,
    search: filters.value.search || '',
    limit: 200
  }
  if (filters.value.period === 'custom' && customDateRange.value?.length === 2) {
    params.start_date = customDateRange.value[0]
    params.end_date = customDateRange.value[1]
  }
  return params
}

async function loadDashboard() {
  if (filters.value.period === 'custom' && customDateRange.value?.length !== 2) {
    users.value = []
    trend.value = []
    summary.value = {}
    return
  }

  loading.value = true
  try {
    const data = await dashboardApi.getSummaryTokenUsage(buildParams())
    summary.value = data.summary || {}
    trend.value = data.trend || []
    users.value = data.users || []
    resetUserPagination()
  } catch (error) {
    console.error('加载汇总 Token 看板失败:', error)
    ElMessage.error(error.response?.data?.detail || '加载汇总 Token 看板失败')
    summary.value = {}
    trend.value = []
    users.value = []
  } finally {
    loading.value = false
  }
}

function handlePeriodChange() {
  if (filters.value.period !== 'custom') {
    loadDashboard()
  }
}

async function openUserDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  userDetail.value = null
  resetDetailPagination()
  try {
    userDetail.value = await dashboardApi.getSummaryTokenUsageUserDetail(row.user_id, buildParams())
  } catch (error) {
    console.error('加载用户 Token 明细失败:', error)
    ElMessage.error(error.response?.data?.detail || '加载用户 Token 明细失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

function buildAxisPath(field, rows = trend.value, chart = platformChart) {
  return buildLinePath(rows, row => Number(row[field] || 0), chart, getRowsMax(rows))
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

function resetUserPagination() {
  userPagination.value.currentPage = 1
}

function resetDetailPagination() {
  detailPagination.value.currentPage = 1
}

function handleUserPageSizeChange() {
  resetUserPagination()
}

function handleDetailPageSizeChange() {
  resetDetailPagination()
}

function handleUserSortChange({ prop, order }) {
  userSort.value = { prop, order }
  resetUserPagination()
}

function handleDetailSortChange({ prop, order }) {
  detailSort.value = { prop, order }
  resetDetailPagination()
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
    value: Math.round(Number(maxValue || 0) * ratio),
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
  const y = type === 'y' ? tick.y : chart.height - 9
  return {
    left: `${(x / chart.width) * 100}%`,
    top: `${(y / chart.height) * 100}%`
  }
}

function rankPercent(value) {
  return Math.round((Number(value || 0) / maxUserTokens.value) * 100)
}

function platformRatio(value) {
  const total = Number(summary.value.total_tokens || 0)
  if (!total) return '0.0'
  return ((Number(value || 0) / total) * 100).toFixed(1)
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

function formatTrend(value) {
  const num = Number(value || 0)
  return `${num >= 0 ? '+' : ''}${num.toFixed(1)}%`
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

.top-grid {
  display: grid;
  grid-template-columns: 1.1fr .9fr;
  gap: 16px;
  margin-bottom: 16px;
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

.detail-chart-box {
  position: relative;
  height: 170px;
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

.rank-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.rank-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 6px;
  color: #334155;
  font-size: 13px;
}

.rank-main strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rank-main span {
  flex: 0 0 auto;
  color: #2563eb;
  font-weight: 700;
  white-space: nowrap;
}

.filter-card {
  margin-bottom: 16px;
}

.filter-row {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  justify-content: space-between;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.filter-search,
.filter-controls {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 12px;
}

.filter-controls {
  justify-content: flex-end;
  margin-left: auto;
}

.filter-label {
  flex: 0 0 auto;
  color: #4b5563;
  font-size: 13px;
  font-weight: 700;
}

.search-input {
  flex: 0 0 360px;
  max-width: 360px;
}

.filter-search :deep(.el-button),
.filter-controls :deep(.el-segmented),
.filter-controls :deep(.el-button) {
  flex: 0 0 auto;
}

.custom-range {
  flex: 0 0 300px;
  width: 300px;
  margin-top: 0;
}

.clickable-name {
  color: #172033;
  cursor: pointer;
}

.usage-table :deep(.el-table__cell) {
  padding-left: 14px;
  padding-right: 14px;
}

.usage-table :deep(.trend-column .cell),
.usage-table :deep(.status-column .cell) {
  white-space: nowrap;
}

.usage-table :deep(.status-column .cell) {
  display: flex;
  justify-content: center;
}

.pagination-container {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.pagination-container.compact {
  margin-top: 10px;
}

.trend-up {
  color: #f59e0b;
  font-weight: 700;
}

.trend-down {
  color: #64748b;
  font-weight: 700;
}

.usage-detail-dialog :deep(.el-dialog) {
  border-radius: 10px;
}

.detail-subtitle {
  margin: -8px 0 16px;
  color: #7a8798;
  font-size: 13px;
}

.detail-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.detail-metric {
  padding: 14px;
  border: 1px solid #e4eaf2;
  border-radius: 8px;
}

.detail-metric span,
.detail-metric small {
  display: block;
  color: #8290a3;
  font-size: 12px;
}

.detail-metric strong {
  display: block;
  margin: 5px 0;
  color: #111827;
  font-size: 20px;
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.detail-panel,
.recent-panel {
  padding: 16px;
  border: 1px solid #e4eaf2;
  border-radius: 8px;
}

.detail-panel h4,
.recent-panel h4 {
  margin: 0 0 14px;
  color: #111827;
  font-size: 15px;
}

.rank-bars {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.detail-rank-row,
:deep(.detail-rank-row) {
  padding: 4px 0 8px;
}

.detail-rank-main,
:deep(.detail-rank-main) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  margin-bottom: 10px;
  color: #334155;
  font-size: 13px;
}

.detail-rank-name,
:deep(.detail-rank-name) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-rank-value,
:deep(.detail-rank-value) {
  color: #2563eb;
  font-weight: 700;
  text-align: right;
  white-space: nowrap;
}

.detail-rank-row :deep(.el-progress),
:deep(.detail-rank-row .el-progress) {
  margin-top: 4px;
}

.detail-recent-table :deep(.el-table__cell) {
  padding-left: 12px;
  padding-right: 12px;
}

.detail-recent-table :deep(.cell) {
  line-height: 1.45;
}

.empty-small {
  color: #8a94a6;
  font-size: 13px;
  text-align: center;
}

.recent-panel {
  margin-top: 16px;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .top-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .filter-row {
    flex-wrap: wrap;
    justify-content: flex-start;
    overflow-x: visible;
  }

  .filter-search,
  .filter-controls {
    flex-wrap: wrap;
  }

  .filter-controls {
    justify-content: flex-start;
    margin-left: 0;
  }

  .search-input {
    flex: 1 1 280px;
    max-width: none;
  }

  .custom-range {
    flex: 1 1 300px;
    width: 300px;
  }
}
</style>
