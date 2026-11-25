<template>
  <div class="agent-statistics" v-loading="loading">
    <template v-if="isValidId">
      <div class="statistics-body">
        <AgentWorkspaceNav v-if="!expertWorkspace" :agent="agent" :agent-id="agentId" active="statistics" />
        <main class="statistics-scroll">
          <div class="statistics-content">
          <ResourcePageHeader title="统计信息">
            <template #actions>
              <el-tooltip content="刷新统计" placement="bottom">
                <el-button
                  :icon="Refresh"
                  circle
                  text
                  :loading="refreshing"
                  aria-label="刷新统计"
                  @click="loadStatistics(true)"
                />
              </el-tooltip>
            </template>
          </ResourcePageHeader>
          <div class="statistics-tabs" role="tablist" aria-label="统计视图">
            <button
              v-for="view in statisticsViews"
              :key="view.value"
              type="button"
              role="tab"
              class="statistics-tab"
              :class="{ active: activeView === view.value }"
              :aria-selected="activeView === view.value"
              @click="selectView(view.value)"
            >
              {{ view.label }}
            </button>
          </div>

          <div class="page-heading">
            <div>
              <h1>{{ viewTitle }}</h1>
              <span class="period-text">{{ periodText }}</span>
            </div>
            <el-segmented v-model="days" :options="periodOptions" @change="loadStatistics()" />
          </div>

          <el-alert
            v-if="loadError"
            :title="loadError"
            type="error"
            :closable="false"
            show-icon
            class="load-alert"
          />

          <template v-if="activeView === 'runtime'">
          <section class="metric-grid" aria-label="运行概览">
            <div v-for="item in runtimeMetrics" :key="item.label" class="metric-item">
              <div class="metric-topline">
                <span class="metric-label">{{ item.label }}</span>
                <el-icon :class="`is-${item.tone}`"><component :is="item.icon" /></el-icon>
              </div>
              <strong>{{ item.value }}</strong>
              <span class="metric-detail">{{ item.detail }}</span>
            </div>
          </section>

          <section class="overview-grid">
            <div class="panel trend-panel">
              <div class="panel-heading">
                <h2>运行趋势</h2>
                <div class="legend" aria-label="图例">
                  <span><i class="is-success"></i>成功</span>
                  <span><i class="is-failed"></i>失败</span>
                  <span><i class="is-cancelled"></i>取消</span>
                  <span><i class="is-abnormal"></i>异常</span>
                </div>
              </div>
              <div v-if="hasTrendData" class="trend-chart" role="img" :aria-label="trendAriaLabel">
                <div class="chart-grid" aria-hidden="true">
                  <span></span><span></span><span></span><span></span>
                </div>
                <div class="trend-columns">
                  <div
                    v-for="(item, index) in trend"
                    :key="item.date"
                    class="trend-column"
                    :title="trendTooltip(item)"
                  >
                    <div class="bar-track">
                      <div class="bar-stack" :style="trendBarStyle(item)">
                        <span class="bar-success" :style="trendSegmentStyle(item.succeeded_runs, item.total_runs)"></span>
                        <span class="bar-failed" :style="trendSegmentStyle(item.failed_runs, item.total_runs)"></span>
                        <span class="bar-cancelled" :style="trendSegmentStyle(item.cancelled_runs, item.total_runs)"></span>
                        <span class="bar-abnormal" :style="trendSegmentStyle(item.abnormal_runs, item.total_runs)"></span>
                        <span class="bar-active" :style="trendSegmentStyle(item.active_runs, item.total_runs)"></span>
                      </div>
                    </div>
                    <span class="trend-label">{{ showTrendLabel(index) ? shortDate(item.date) : '' }}</span>
                  </div>
                </div>
              </div>
              <el-empty v-else description="当前周期暂无运行记录" :image-size="72" />
            </div>

            <div class="panel source-panel">
              <div class="panel-heading">
                <h2>渠道表现</h2>
                <span class="panel-meta">{{ statistics?.sources?.length || 0 }} 个来源</span>
              </div>
              <div v-if="statistics?.sources?.length" class="source-list">
                <div v-for="item in statistics.sources" :key="item.source" class="source-row">
                  <div class="source-main">
                    <span>{{ sourceLabel(item.source) }}</span>
                    <strong>{{ formatPercent(item.success_rate) }}</strong>
                  </div>
                  <div class="source-track">
                    <span :style="{ width: `${sourceShare(item)}%` }"></span>
                  </div>
                  <div class="source-detail">
                    <span>{{ item.total_runs }} 轮</span>
                    <span>{{ item.failed_runs }} 失败</span>
                    <span v-if="item.cancelled_runs">{{ item.cancelled_runs }} 取消</span>
                    <span v-if="item.abnormal_runs" class="danger-text">{{ item.abnormal_runs }} 异常</span>
                  </div>
                </div>
              </div>
              <el-empty v-else description="暂无渠道数据" :image-size="64" />
            </div>
          </section>

          <section class="detail-grid">
            <div class="panel error-panel">
              <div class="panel-heading">
                <h2>失败原因</h2>
                <span class="panel-meta">按发生次数排序</span>
              </div>
              <div v-if="statistics?.errors?.length" class="error-list">
                <div v-for="item in statistics.errors" :key="item.error_code" class="error-row">
                  <div class="error-rank">{{ item.count }}</div>
                  <div class="error-copy">
                    <strong>{{ errorLabel(item.error_code) }}</strong>
                    <span>{{ item.latest_message || item.error_code }}</span>
                  </div>
                  <time>{{ formatCompactTime(item.last_occurred_at) }}</time>
                </div>
              </div>
              <el-empty v-else description="当前周期没有失败记录" :image-size="64" />
            </div>

            <div class="panel health-panel">
              <div class="panel-heading"><h2>运行状态</h2></div>
              <div class="health-list">
                <div v-for="item in healthBreakdown" :key="item.label" class="health-row">
                  <span><i :class="`is-${item.tone}`"></i>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
            </div>

          </section>

          <section class="panel failures-panel">
            <div class="panel-heading">
              <h2>最近失败</h2>
              <span class="panel-meta">最近 10 条</span>
            </div>
            <el-table
              v-if="statistics?.recent_failures?.length"
              :data="statistics.recent_failures"
              class="failures-table"
              table-layout="fixed"
            >
              <el-table-column label="时间" width="150">
                <template #default="{ row }">{{ formatCompactTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="渠道" width="110">
                <template #default="{ row }">{{ sourceLabel(row.source) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'failed' ? 'danger' : 'warning'" effect="plain" size="small">
                    {{ row.status === 'failed' ? '失败' : '异常' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="耗时" width="100">
                <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
              </el-table-column>
              <el-table-column label="原因" min-width="260">
                <template #default="{ row }">
                  <div class="failure-reason">
                    <strong>{{ errorLabel(row.error_code) }}</strong>
                    <span>{{ row.error_message || row.error_code || '未记录错误信息' }}</span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="当前周期没有失败记录" :image-size="72" />
          </section>
          </template>

          <template v-else-if="activeView === 'credits'">
            <section class="metric-grid credit-metric-grid" :aria-label="`${creditName}概览`">
              <div v-for="item in creditMetrics" :key="item.label" class="metric-item">
                <div class="metric-topline">
                  <span class="metric-label">{{ item.label }}</span>
                  <el-icon :class="`is-${item.tone}`"><component :is="item.icon" /></el-icon>
                </div>
                <strong>{{ item.value }}</strong>
                <span class="metric-detail">{{ item.detail }}</span>
              </div>
            </section>
            <section class="overview-grid">
              <div class="panel trend-panel">
                <div class="panel-heading">
                  <h2>{{ creditName }}消耗趋势</h2>
                  <span class="panel-meta">按运行日期汇总实际扣费</span>
                </div>
                <div v-if="hasCreditTrendData" class="trend-chart" role="img" :aria-label="`${periodText}共消耗 ${formatPoints(summary.charged_points)} ${creditName}`">
                  <div class="chart-grid" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
                  <div class="trend-columns">
                    <div v-for="(item, index) in trend" :key="item.date" class="trend-column" :title="`${item.date} · ${formatPoints(item.charged_points)} ${creditName}`">
                      <div class="bar-track">
                        <div class="bar-stack bar-credit" :style="{ height: `${Number(item.charged_points) > 0 ? Math.max(2, Number(item.charged_points) * 100 / peakDailyPoints) : 0}%` }" />
                      </div>
                      <span class="trend-label">{{ showTrendLabel(index) ? shortDate(item.date) : '' }}</span>
                    </div>
                  </div>
                </div>
                <el-empty v-else :description="`当前周期暂无${creditName}消耗`" :image-size="72" />
              </div>
              <div class="panel credit-source-panel">
                <div class="panel-heading"><h2>渠道消耗</h2><span class="panel-meta">单位：{{ creditName }}</span></div>
                <div v-if="creditSources.length" class="source-list">
                  <div v-for="item in creditSources" :key="item.source" class="source-row">
                    <div class="source-main"><span>{{ sourceLabel(item.source) }}</span><strong>{{ formatPoints(item.charged_points) }}</strong></div>
                    <div class="source-track"><span :style="{ width: `${item.share}%` }" /></div>
                    <div class="source-detail"><span>占比 {{ formatPercent(item.share) }}</span><span>{{ formatNumber(item.total_runs) }} 轮运行</span></div>
                  </div>
                </div>
                <el-empty v-else description="当前周期暂无渠道消耗" :image-size="64" />
              </div>
            </section>
          </template>
          <template v-else>
            <section class="metric-grid token-metric-grid" aria-label="Token 概览">
              <div v-for="item in tokenMetrics" :key="item.label" class="metric-item">
                <div class="metric-topline">
                  <span class="metric-label">{{ item.label }}</span>
                  <el-icon :class="`is-${item.tone}`"><component :is="item.icon" /></el-icon>
                </div>
                <strong>{{ item.value }}</strong>
                <span class="metric-detail">{{ item.detail }}</span>
              </div>
            </section>

            <section class="overview-grid token-overview-grid">
              <div class="panel trend-panel">
                <div class="panel-heading">
                  <h2>Token 趋势</h2>
                  <div class="legend" aria-label="图例">
                    <span><i class="is-token-input"></i>输入</span>
                    <span><i class="is-token-output"></i>输出</span>
                    <span><i class="is-token-cache"></i>缓存</span>
                  </div>
                </div>
                <div v-if="hasTokenTrendData" class="trend-chart" role="img" :aria-label="tokenTrendAriaLabel">
                  <div class="chart-grid" aria-hidden="true">
                    <span></span><span></span><span></span><span></span>
                  </div>
                  <div class="trend-columns">
                    <div
                      v-for="(item, index) in trend"
                      :key="item.date"
                      class="trend-column"
                      :title="tokenTrendTooltip(item)"
                    >
                      <div class="bar-track">
                        <div class="bar-stack" :style="tokenTrendBarStyle(item)">
                          <span class="bar-token-input" :style="trendSegmentStyle(item.input_tokens, item.total_tokens)"></span>
                          <span class="bar-token-output" :style="trendSegmentStyle(item.output_tokens, item.total_tokens)"></span>
                          <span class="bar-token-cache" :style="trendSegmentStyle(item.cache_read_tokens + item.cache_creation_tokens, item.total_tokens)"></span>
                        </div>
                      </div>
                      <span class="trend-label">{{ showTrendLabel(index) ? shortDate(item.date) : '' }}</span>
                    </div>
                  </div>
                </div>
                <el-empty v-else description="当前周期暂无 Token 记录" :image-size="72" />
              </div>

              <div class="panel token-panel">
                <div class="panel-heading"><h2>Token 明细</h2></div>
                <div class="token-list">
                  <div v-for="item in tokenBreakdown" :key="item.label" class="token-row">
                    <div>
                      <span>{{ item.label }}</span>
                      <strong>{{ formatNumber(item.value) }}</strong>
                    </div>
                    <div class="token-track"><span :style="{ width: `${item.percent}%` }"></span></div>
                  </div>
                </div>
                <div class="token-total-row">
                  <span>总计</span>
                  <strong>{{ formatNumber(summary.total_tokens) }}</strong>
                </div>
              </div>
            </section>
          </template>
          </div>
        </main>
      </div>
    </template>

    <el-result v-else icon="error" title="智能体不存在" sub-title="请返回列表重新选择">
      <template #extra>
        <el-button type="primary" @click="router.push('/admin/agents')">返回列表</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleCheckFilled, Coin, DataLine, Refresh, Timer, WarningFilled } from '@element-plus/icons-vue'
import api from '@/api/request'
import { formatBeijingDate, formatBeijingDateTime } from '@/utils/date-time'
import ResourcePageHeader from './components/ResourcePageHeader.vue'
import AgentWorkspaceNav from './components/AgentWorkspaceNav.vue'

const route = useRoute()
const expertWorkspace = inject('expertWorkspace', null)
const router = useRouter()
const props = defineProps({ agentIdOverride: { type: Number, default: null } })
const agentId = props.agentIdOverride || Number.parseInt(route.params.id, 10)
const isValidId = Number.isFinite(agentId) && agentId > 0
const periodOptions = [
  { label: '今天', value: 1 },
  { label: '近 7 天', value: 7 },
  { label: '近 30 天', value: 30 },
]
const statisticsViews = computed(() => [
  { label: '运行质量', value: 'runtime' },
  { label: `${creditName.value}用量`, value: 'credits' },
  { label: 'Token 用量', value: 'tokens' },
])

const days = ref(7)
const normalizeView = view => ['tokens', 'credits'].includes(view) ? view : 'runtime'
const activeView = ref(normalizeView(route.query.view))
const agent = ref(null)
const statistics = ref(null)
const loading = ref(false)
const refreshing = ref(false)
const loadError = ref('')
const creditName = computed(() => statistics.value?.credit_display_name?.trim() || '趣点')

const summary = computed(() => statistics.value?.summary || {
  total_runs: 0,
  succeeded_runs: 0,
  failed_runs: 0,
  cancelled_runs: 0,
  active_runs: 0,
  abnormal_runs: 0,
  success_rate: 0,
  failure_rate: 0,
  median_duration_ms: null,
  p95_duration_ms: null,
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  cache_creation_tokens: 0,
  total_tokens: 0,
  average_tokens_per_run: 0,
  charged_points: 0,
})
const trend = computed(() => statistics.value?.trend || [])
const maxTrendTotal = computed(() => Math.max(1, ...trend.value.map(item => item.total_runs || 0)))
const maxTokenTrendTotal = computed(() => Math.max(1, ...trend.value.map(item => item.total_tokens || 0)))
const hasTrendData = computed(() => trend.value.some(item => item.total_runs > 0))
const hasTokenTrendData = computed(() => trend.value.some(item => item.total_tokens > 0))
const viewTitle = computed(() => statisticsViews.value.find(view => view.value === activeView.value).label)
const periodText = computed(() => {
  if (!statistics.value) return days.value === 1 ? '今天' : `最近 ${days.value} 天`
  const start = formatBeijingDate(statistics.value.start_at)
  const end = formatBeijingDate(statistics.value.end_at)
  if (days.value === 1) return `今天 · ${end}`
  return `${start} - ${end}`
})
const trendAriaLabel = computed(() => (
  `${days.value === 1 ? '今天' : `最近 ${days.value} 天`}共运行 ${summary.value.total_runs} 轮，成功率 ${formatPercent(summary.value.success_rate)}`
))
const tokenTrendAriaLabel = computed(() => (
  `${days.value === 1 ? '今天' : `最近 ${days.value} 天`}共消耗 ${formatNumber(summary.value.total_tokens)} Token`
))
const runtimeMetrics = computed(() => [
  {
    label: '运行轮次',
    value: formatNumber(summary.value.total_runs),
    detail: `${summary.value.active_runs} 轮执行中`,
    icon: DataLine,
    tone: 'primary',
  },
  {
    label: '成功率',
    value: formatPercent(summary.value.success_rate),
    detail: `${summary.value.succeeded_runs} 成功 / ${summary.value.failed_runs} 失败`,
    icon: CircleCheckFilled,
    tone: 'success',
  },
  {
    label: '典型耗时',
    value: formatDuration(summary.value.median_duration_ms),
    detail: '完成轮次中位数',
    icon: Timer,
    tone: 'regular',
  },
  {
    label: '慢请求 P95',
    value: formatDuration(summary.value.p95_duration_ms),
    detail: '95% 的完成轮次不超过此值',
    icon: WarningFilled,
    tone: 'warning',
  },
])
const peakDailyPoints = computed(() => Math.max(0, ...trend.value.map(item => Number(item.charged_points || 0))))
const hasCreditTrendData = computed(() => peakDailyPoints.value > 0)
const creditSources = computed(() => (statistics.value?.sources || [])
  .filter(item => Number(item.charged_points) > 0)
  .map(item => ({ ...item, share: summary.value.charged_points > 0 ? Number(item.charged_points) * 100 / Number(summary.value.charged_points) : 0 }))
  .sort((a, b) => Number(b.charged_points) - Number(a.charged_points)))
const creditMetrics = computed(() => [
  {
    label: '消耗总量',
    value: formatPoints(summary.value.charged_points),
    detail: `实际扣费 · ${creditName.value}`,
    icon: Coin,
    tone: 'warning',
  },
  {
    label: '平均每轮消耗',
    value: formatPoints(summary.value.total_runs ? Number(summary.value.charged_points || 0) / summary.value.total_runs : 0),
    detail: `${formatNumber(summary.value.total_runs)} 轮运行（含未扣费轮次）`,
    icon: DataLine,
    tone: 'primary',
  },
  {
    label: '日均消耗',
    value: formatPoints(Number(summary.value.charged_points || 0) / (statistics.value?.days || days.value)),
    detail: `按所选 ${statistics.value?.days || days.value} 个自然日计算`,
    icon: Timer,
    tone: 'success',
  },
  {
    label: '单日最高消耗',
    value: formatPoints(peakDailyPoints.value),
    detail: `所选周期内单日峰值 · ${creditName.value}`,
    icon: DataLine,
    tone: 'token',
  },
])
const tokenMetrics = computed(() => [
  {
    label: 'Token 总量',
    value: formatTokenCount(summary.value.total_tokens),
    detail: `${formatNumber(summary.value.total_tokens)} Token`,
    icon: Coin,
    tone: 'token',
  },
  {
    label: '平均每轮',
    value: formatTokenCount(summary.value.average_tokens_per_run),
    detail: `${formatNumber(summary.value.total_runs)} 轮运行`,
    icon: DataLine,
    tone: 'primary',
  },
  {
    label: '输入 Token',
    value: formatTokenCount(summary.value.input_tokens),
    detail: `${formatNumber(summary.value.input_tokens)} Token`,
    icon: DataLine,
    tone: 'regular',
  },
  {
    label: '输出 Token',
    value: formatTokenCount(summary.value.output_tokens),
    detail: `${formatNumber(summary.value.output_tokens)} Token`,
    icon: DataLine,
    tone: 'success',
  },
])
const healthBreakdown = computed(() => [
  { label: '成功', value: summary.value.succeeded_runs, tone: 'success' },
  { label: '失败', value: summary.value.failed_runs, tone: 'failed' },
  { label: '主动取消', value: summary.value.cancelled_runs, tone: 'cancelled' },
  { label: '状态异常', value: summary.value.abnormal_runs, tone: 'abnormal' },
  { label: '执行中', value: summary.value.active_runs, tone: 'active' },
])
const tokenBreakdown = computed(() => {
  const items = [
    { label: '输入', value: summary.value.input_tokens },
    { label: '输出', value: summary.value.output_tokens },
    { label: '缓存读取', value: summary.value.cache_read_tokens },
    { label: '缓存创建', value: summary.value.cache_creation_tokens },
  ]
  const max = Math.max(1, ...items.map(item => Number(item.value || 0)))
  return items.map(item => ({
    ...item,
    percent: Math.max(item.value ? 3 : 0, Number(item.value || 0) * 100 / max),
  }))
})

const sourceNames = {
  api: '开放调用',
  web: 'Web 对话',
  weixin_clawbot: '微信',
  dingtalk_clawbot: '钉钉',
}
const errorNames = {
  cancelled: '运行已取消',
  runtime_error: 'Runtime 执行失败',
  runtime_timeout: '运行超时',
  runtime_unavailable: 'Runtime 不可用',
  workspace_error: '工作区异常',
  credential_decryption_failed: '凭据读取失败',
  unknown_status: '运行状态异常',
}

const formatNumber = value => new Intl.NumberFormat('zh-CN').format(Number(value || 0))
const formatPoints = value => Number(value || 0).toFixed(2)
const formatTokenCount = value => new Intl.NumberFormat('zh-CN', {
  notation: 'compact',
  maximumFractionDigits: 1,
}).format(Number(value || 0))
const formatPercent = value => `${Number(value || 0).toFixed(1)}%`
const formatDuration = value => {
  if (!Number.isFinite(Number(value))) return '-'
  const ms = Math.max(0, Number(value))
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return `${minutes}m ${seconds}s`
}
const formatCompactTime = value => formatBeijingDateTime(value, {
  year: undefined,
  second: undefined,
  fallback: '-',
})
const sourceLabel = source => sourceNames[source] || source || '未知来源'
const errorLabel = code => errorNames[code] || code || '未分类错误'
const shortDate = date => date?.slice(5).replace('-', '/') || ''
const showTrendLabel = index => days.value === 7 || index === 0 || index === trend.value.length - 1 || index % 5 === 0
const trendBarStyle = item => ({
  height: `${item.total_runs ? Math.max(6, item.total_runs * 100 / maxTrendTotal.value) : 2}%`,
})
const tokenTrendBarStyle = item => ({
  height: `${item.total_tokens ? Math.max(6, item.total_tokens * 100 / maxTokenTrendTotal.value) : 2}%`,
})
const trendSegmentStyle = (value, total) => ({
  height: `${total ? Math.max(0, Number(value || 0) * 100 / total) : 0}%`,
})
const trendTooltip = item => (
  `${item.date} · ${item.total_runs} 轮 · 成功 ${item.succeeded_runs} · 失败 ${item.failed_runs}`
)
const tokenTrendTooltip = item => (
  `${item.date} · ${formatNumber(item.total_tokens)} Token · 输入 ${formatNumber(item.input_tokens)} · 输出 ${formatNumber(item.output_tokens)}`
)
const sourceShare = item => {
  const max = Math.max(1, ...(statistics.value?.sources || []).map(source => source.total_runs || 0))
  return Math.max(3, item.total_runs * 100 / max)
}

const getErrorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback

const selectView = name => {
  activeView.value = normalizeView(name)
  router.replace({
    query: {
      ...route.query,
      view: activeView.value === 'runtime' ? undefined : activeView.value,
    },
  })
}

watch(() => route.query.view, view => {
  activeView.value = normalizeView(view)
})

const loadStatistics = async (manual = false) => {
  if (!isValidId) return
  if (manual) refreshing.value = true
  else loading.value = true
  loadError.value = ''
  try {
    statistics.value = await api.get(`/agents/${agentId}/statistics`, { params: { days: days.value } })
  } catch (error) {
    loadError.value = getErrorMessage(error, '统计数据加载失败')
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

onMounted(async () => {
  if (!isValidId) return
  loading.value = true
  try {
    const [agentResult] = await Promise.all([
      api.get(`/agents/${agentId}`),
      loadStatistics(),
    ])
    agent.value = agentResult
  } catch (error) {
    loadError.value = getErrorMessage(error, '智能体信息加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.agent-statistics {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
}

.statistics-body {
  min-height: 0;
  flex: 1;
  display: flex;
}

.statistics-scroll {
  min-width: 0;
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.statistics-content {
  width: min(100%, 1304px);
  margin: 0 auto;
  padding: 28px 32px 48px;
  box-sizing: border-box;
}

.statistics-tabs {
  margin-top: 20px;
  display: flex;
  align-items: center;
  gap: 24px;
  margin-bottom: 22px;
  border-bottom: 1px solid #ebeef5;
}

.statistics-tab {
  position: relative;
  min-height: 38px;
  padding: 0 2px;
  border: 0;
  color: #606266;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 14px;
  transition: color 0.15s;
}

.statistics-tab::after {
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  background: var(--el-color-primary);
  content: '';
  opacity: 0;
  transition: opacity 0.15s;
}

.statistics-tab:hover,
.statistics-tab.active {
  color: var(--el-color-primary);
}

.statistics-tab.active::after { opacity: 1; }

.page-heading,
.panel-heading,
.metric-topline,
.source-main,
.source-detail,
.health-row,
.token-row > div:first-child {
  display: flex;
  align-items: center;
}

.page-heading {
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
}

.page-heading h1 {
  margin: 0 0 5px;
  color: #20242a;
  font-size: 22px;
  line-height: 1.3;
  letter-spacing: 0;
}

.period-text,
.panel-meta,
.metric-detail,
.source-detail,
.error-copy span,
.error-row time {
  color: #8a919c;
  font-size: 12px;
}

.load-alert { margin-bottom: 16px; }

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.metric-item,
.panel {
  border: 1px solid #e3e6ea;
  border-radius: 6px;
  background: #fff;
  box-sizing: border-box;
}

.metric-item {
  min-height: 126px;
  display: flex;
  flex-direction: column;
  padding: 18px;
}

.metric-topline {
  justify-content: space-between;
  color: #656d78;
}

.metric-topline .el-icon { font-size: 18px; }
.metric-topline .is-primary { color: #337ecc; }
.metric-topline .is-success { color: #27845a; }
.metric-topline .is-regular { color: #687384; }
.metric-topline .is-warning { color: #b7791f; }
.metric-topline .is-token { color: #7b61a8; }
.metric-label { font-size: 13px; }

.metric-item > strong {
  margin-top: 13px;
  color: #20242a;
  font-size: 27px;
  line-height: 1.1;
  letter-spacing: 0;
}

.metric-detail { margin-top: auto; padding-top: 8px; }

.overview-grid,
.detail-grid {
  display: grid;
  gap: 12px;
  margin-bottom: 12px;
}

.overview-grid { grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); }
.detail-grid { grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr); }
.panel { min-width: 0; padding: 18px; }

.panel-heading {
  min-height: 28px;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.panel-heading h2 {
  margin: 0;
  color: #30343a;
  font-size: 15px;
  line-height: 22px;
  letter-spacing: 0;
}

.legend { display: flex; flex-wrap: wrap; gap: 12px; color: #7a828d; font-size: 12px; }
.legend span,
.health-row > span { display: inline-flex; align-items: center; gap: 5px; }
.legend i,
.health-row i {
  width: 7px;
  height: 7px;
  display: inline-block;
  border-radius: 2px;
}
.legend i.is-success,
.health-row i.is-success { background: #38a169; }
.legend i.is-failed,
.health-row i.is-failed { background: #d65c5c; }
.legend i.is-cancelled,
.health-row i.is-cancelled { background: #a7adb6; }
.legend i.is-abnormal,
.health-row i.is-abnormal { background: #d49436; }
.health-row i.is-active { background: #4b8ed6; }
.legend i.is-token-input { background: #5c7cba; }
.legend i.is-token-output { background: #2f9d78; }
.legend i.is-token-cache { background: #7b61a8; }

.trend-chart { position: relative; height: 230px; padding: 8px 4px 0; box-sizing: border-box; }
.chart-grid {
  position: absolute;
  inset: 8px 4px 29px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
}
.chart-grid span { border-top: 1px dashed #edf0f3; }
.trend-columns {
  position: relative;
  height: 100%;
  display: flex;
  align-items: stretch;
  gap: 5px;
}
.trend-column { min-width: 0; flex: 1; display: flex; flex-direction: column; align-items: center; }
.bar-track { width: 100%; flex: 1; display: flex; align-items: flex-end; justify-content: center; }
.bar-stack {
  width: min(18px, 72%);
  min-width: 4px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  overflow: hidden;
  border-radius: 3px 3px 1px 1px;
  background: #eef1f4;
}
.bar-stack span { width: 100%; min-height: 0; }
.bar-success { background: #38a169; }
.bar-failed { background: #d65c5c; }
.bar-cancelled { background: #a7adb6; }
.bar-abnormal { background: #d49436; }
.bar-active { background: #4b8ed6; }
.bar-token-input { background: #5c7cba; }
.bar-token-output { background: #2f9d78; }
.bar-token-cache { background: #7b61a8; }
.bar-credit, .credit-source-panel .source-track span { background: #b98a45; }
.trend-label { height: 20px; margin-top: 8px; color: #8a919c; font-size: 10px; white-space: nowrap; }

.source-list,
.error-list,
.health-list { display: flex; flex-direction: column; }
.source-list { gap: 18px; }
.source-main { justify-content: space-between; gap: 12px; color: #4a515b; font-size: 13px; }
.source-main strong { color: #30343a; font-size: 13px; }
.source-track { height: 5px; margin: 8px 0 6px; overflow: hidden; border-radius: 2px; background: #eef1f4; }
.source-track span { height: 100%; display: block; border-radius: inherit; background: #4b8ed6; }
.source-detail { flex-wrap: wrap; gap: 8px; }
.danger-text { color: #b45353; }

.error-list { gap: 0; }
.error-row {
  min-height: 54px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  border-top: 1px solid #eff1f4;
}
.error-row:first-child { border-top: 0; }
.error-rank {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: 4px;
  color: #b84e4e;
  background: #fff1f1;
  font-size: 12px;
  font-weight: 600;
}
.error-copy { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.error-copy strong { color: #3f454d; font-size: 13px; }
.error-copy span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.error-row time { white-space: nowrap; }

.health-list,
.token-list { gap: 0; }
.health-row { min-height: 38px; justify-content: space-between; border-bottom: 1px solid #f0f2f4; color: #5d6570; font-size: 13px; }
.health-row strong { color: #30343a; }
.token-list { display: flex; flex-direction: column; gap: 13px; }
.token-row > div:first-child { justify-content: space-between; gap: 10px; color: #5d6570; font-size: 12px; }
.token-row strong { color: #30343a; font-size: 12px; }
.token-track { height: 4px; margin-top: 6px; overflow: hidden; border-radius: 2px; background: #eef1f4; }
.token-track span { height: 100%; display: block; border-radius: inherit; background: #7b61a8; }
.token-total-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid #eceff2;
  color: #5d6570;
  font-size: 13px;
}
.token-total-row strong { color: #30343a; }

.failures-panel { padding-bottom: 10px; }
.failures-table { width: 100%; }
.failure-reason { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.failure-reason strong { color: #454b54; font-size: 13px; }
.failure-reason span { overflow: hidden; color: #8a919c; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 920px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .overview-grid,
  .detail-grid { grid-template-columns: 1fr; }
}

@media (max-width: 900px) {
  .statistics-content { padding: 22px 16px 36px; }
}

@media (max-width: 720px) {
  .statistics-tabs { gap: 20px; margin-bottom: 18px; overflow-x: auto; }
  .statistics-tab { flex: 0 0 auto; }
  .page-heading { align-items: flex-start; }
  .page-heading h1 { font-size: 19px; }
  .metric-grid { gap: 8px; }
  .metric-item { min-height: 116px; padding: 14px; }
  .metric-item > strong { font-size: 22px; }
  .panel { padding: 14px; }
  .trend-panel { overflow-x: auto; }
  .trend-chart { min-width: 520px; }
  .legend { gap: 8px; }
  .error-row { grid-template-columns: 32px minmax(0, 1fr); }
  .error-row time { display: none; }
  .failures-panel { overflow: hidden; }
  .failures-table { min-width: 720px; }
  .failures-panel :deep(.el-table__body-wrapper),
  .failures-panel :deep(.el-table__header-wrapper) { overflow-x: auto; }
}
</style>
