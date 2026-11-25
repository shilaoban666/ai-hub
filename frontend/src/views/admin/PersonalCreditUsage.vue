<template>
  <section class="credit-usage">
    <div class="credit-heading">
      <h2>我的用量 / 积分用量</h2>
    </div>
    <div class="credit-filters">
      <el-segmented v-model="period" :options="periodOptions" @change="refresh" />
      <el-date-picker v-if="period === 'custom'" v-model="dateRange" type="daterange"
        value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期"
        range-separator="至" @change="refresh" />
      <el-select v-model="granularity" aria-label="趋势粒度" class="compact-select" @change="loadSummary">
        <el-option label="按小时" value="hour" /><el-option label="按天" value="day" /><el-option label="按周" value="week" />
      </el-select>
      <el-tooltip content="刷新" placement="top">
        <el-button :icon="Refresh" circle aria-label="刷新" :loading="loading || tableLoading" @click="refresh" />
      </el-tooltip>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <dl v-loading="loading" class="credit-metrics">
      <div v-for="metric in metrics" :key="metric.label">
        <dt>{{ metric.label }}</dt><dd>{{ metric.value }}</dd>
      </div>
    </dl>
    <div class="credit-totals">
      <span>期间赠送 <strong>{{ points(stats.initial_claim_points) }}</strong></span>
      <span>期间每日领取 <strong>{{ points(stats.daily_claim_points) }}</strong></span>
      <span>管理员增加 <strong>{{ points(stats.adjustment_added) }}</strong></span>
      <span>管理员扣减 <strong>{{ points(stats.adjustment_deducted) }}</strong></span>
      <span>当前运行中 <strong>{{ stats.reserved_runs || 0 }}</strong></span>
      <span>当前待结算 <strong>{{ stats.pending_runs || 0 }}</strong></span>
    </div>

    <div class="credit-charts" v-loading="loading">
      <section>
        <div class="section-heading"><h3>积分趋势</h3><span><i class="legend consumed" />消耗 <i class="legend claimed" />领取</span></div>
        <div v-show="hasTrend" ref="chartElement" class="trend-chart">
          <svg :viewBox="`0 0 ${chartWidth} 220`" role="img" aria-label="积分消耗与领取趋势">
            <g v-for="tick in [0, 1, 2, 3, 4]" :key="tick">
              <line x1="68" :y1="20 + tick * 40" :x2="chartWidth - 18" :y2="20 + tick * 40" stroke="#e5e7eb" />
              <text x="60" :y="24 + tick * 40" text-anchor="end" fill="#6b7280" font-size="11">{{ axisNumber(chartMax * (4 - tick) / 4) }}</text>
            </g>
            <path :d="trendPath('consumed_points')" fill="none" stroke="#3476bb" stroke-width="2" />
            <path :d="trendPath('claimed_points')" fill="none" stroke="#29906b" stroke-width="2" />
            <text x="68" y="208" fill="#6b7280" font-size="12">{{ shortTime(trend[0]?.bucket) }}</text>
            <text :x="chartWidth - 18" y="208" text-anchor="end" fill="#6b7280" font-size="12">{{ shortTime(trend.at(-1)?.bucket) }}</text>
          </svg>
        </div>
        <el-empty v-if="!hasTrend" description="当前周期暂无积分变动" :image-size="64" />
      </section>
      <section>
        <div class="section-heading"><h3>模型消耗</h3><span>前 10 名</span></div>
        <div v-for="model in data.models || []" :key="model.model_id ?? 'unknown'" class="model-row">
          <div><span>{{ model.model_name }}</span><strong>{{ points(model.consumed_points) }}</strong></div>
          <el-progress :percentage="ratio(model.consumed_points)" :show-text="false" :stroke-width="6" color="#3476bb" />
        </div>
        <el-empty v-if="!data.models?.length" description="暂无已结算用量" :image-size="64" />
      </section>
    </div>

    <div class="credit-detail-heading" :class="{ 'has-settle-action': detailTab === 'runs' }">
      <el-tabs v-model="detailTab" @tab-change="resetTable">
        <el-tab-pane label="消费明细" name="runs" />
        <el-tab-pane label="收支流水" name="ledger" />
      </el-tabs>
      <CreditSettleAll v-if="detailTab === 'runs'" scope="personal" @settled="refresh" />
    </div>
    <div class="detail-filters">
      <el-select v-if="detailTab === 'runs'" v-model="settlementStatus" aria-label="结算状态" class="status-select" @change="resetTable">
        <el-option v-for="item in statuses" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-if="detailTab === 'ledger'" v-model="entryType" aria-label="流水类型" class="status-select" @change="resetTable">
        <el-option label="全部类型" value="all" />
        <el-option v-for="(label, value) in entryLabels" :key="value" :label="label" :value="value" />
      </el-select>
      <span v-if="detailTab === 'runs'" class="muted">已结算按结算时间，未结算按发起时间 · 北京时间</span>
      <span v-else class="muted">北京时间</span>
    </div>
    <el-alert v-if="tableError" :title="tableError" type="error" :closable="false" show-icon />
    <el-table v-if="detailTab === 'runs'" v-loading="tableLoading" :data="rows" row-key="run_id" empty-text="暂无消费记录">
      <el-table-column label="时间" min-width="165"><template #default="{ row }">{{ time(row.recorded_at) }}</template></el-table-column>
      <el-table-column prop="session_title" label="会话" min-width="160" show-overflow-tooltip />
      <el-table-column prop="model_name" label="模型" min-width="130" show-overflow-tooltip />
      <el-table-column label="实际消耗" align="right" width="115"><template #default="{ row }">{{ row.charged_points == null ? '无' : points(row.charged_points) }}</template></el-table-column>
      <el-table-column label="计费方式" width="115"><template #default="{ row }">{{ row.billing_mode === 'realtime' ? '实时扣费' : '历史预占' }}</template></el-table-column>
      <el-table-column label="结算状态" width="115"><template #default="{ row }"><el-tag :type="row.settlement_status === 'settled' ? 'success' : 'warning'" effect="plain">{{ statusLabel(row.settlement_status) }}</el-tag></template></el-table-column>
      <el-table-column label="运行结果" width="100"><template #default="{ row }">{{ runLabels[row.status] || row.status }}</template></el-table-column>
      <el-table-column label="操作" width="115" fixed="right"><template #default="{ row }"><CreditRunRecovery :row="row" scope="personal" @recovered="refresh" /></template></el-table-column>
    </el-table>
    <el-table v-else-if="detailTab === 'ledger'" v-loading="tableLoading" :data="rows" row-key="id" empty-text="暂无收支流水">
      <el-table-column label="时间" min-width="165"><template #default="{ row }">{{ time(row.created_at) }}</template></el-table-column>
      <el-table-column label="类型" min-width="120"><template #default="{ row }">{{ entryLabels[row.entry_type] || row.entry_type }}</template></el-table-column>
      <el-table-column label="可用余额变动" align="right" min-width="130"><template #default="{ row }"><span :class="Number(row.amount) > 0 ? 'positive' : ''">{{ Number(row.amount) > 0 ? '+' : '' }}{{ points(row.amount) }}</span></template></el-table-column>
      <el-table-column label="变动后可用" align="right" min-width="115"><template #default="{ row }">{{ points(row.available_after) }}</template></el-table-column>
      <el-table-column label="变动后冻结" align="right" min-width="115"><template #default="{ row }">{{ points(row.reserved_after) }}</template></el-table-column>
      <el-table-column label="备注" min-width="180" show-overflow-tooltip><template #default="{ row }">{{ row.entry_type === 'admin_adjustment' ? row.reason : (entryLabels[row.entry_type] || '无') }}</template></el-table-column>
    </el-table>
    <div class="credit-pagination">
      <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" :pager-count="5"
        layout="total, prev, pager, next" @current-change="loadTable" />
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { dashboardApi } from '@/api/dashboard'
import CreditRunRecovery from '@/components/CreditRunRecovery.vue'
import CreditSettleAll from '@/components/CreditSettleAll.vue'
import { formatBeijingDateTime } from '@/utils/date-time'

const period = ref('7d')
const dateRange = ref([])
const granularity = ref('day')
const data = ref({})
const loading = ref(false)
const error = ref('')
const detailTab = ref('runs')
const settlementStatus = ref('all')
const entryType = ref('all')
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 16
const tableLoading = ref(false)
const tableError = ref('')
const chartElement = ref(null)
const chartWidth = ref(720)
let chartObserver
let summaryRequest = 0
let tableRequest = 0
const periodOptions = [{ label: '今日', value: 'today' }, { label: '近 7 天', value: '7d' }, { label: '本月', value: 'month' }, { label: '自定义', value: 'custom' }]
const statuses = [{ label: '全部状态', value: 'all' }, { label: '已结算', value: 'settled' }, { label: '运行中', value: 'reserved' }, { label: '实时计费中', value: 'metering' }, { label: '待结算', value: 'pending_reconciliation' }]
const entryLabels = { initial_claim: '新用户赠送', daily_claim: '每日领取', admin_adjustment: '管理员调整', model_usage: '模型用量扣费', run_reservation: '历史运行预占', run_settlement: '运行结算' }
const runLabels = { queued: '排队中', running: '运行中', unknown: '已失联', succeeded: '成功', failed: '失败', cancelled: '已取消', timed_out: '已超时' }
const stats = computed(() => data.value.summary || {})
const trend = computed(() => data.value.trend || [])
const hasTrend = computed(() => trend.value.some(row => Number(row.consumed_points) || Number(row.claimed_points)))
const chartMax = computed(() => Math.max(1, ...trend.value.map(row => Math.max(Number(row.consumed_points), Number(row.claimed_points)))))
const metrics = computed(() => [
  { label: '期间消耗积分', value: points(stats.value.consumed_points) },
  { label: '期间领取积分', value: points(stats.value.claimed_points) },
  { label: '当前可用积分', value: points(stats.value.available_balance) },
  { label: '当前冻结积分', value: points(stats.value.reserved_balance) },
  { label: '已结算运行', value: stats.value.run_count || 0 },
])
const points = value => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const axisNumber = value => Number(value).toLocaleString('zh-CN', { notation: 'compact', maximumFractionDigits: 2 })
const time = value => value ? formatBeijingDateTime(value) : '无'
const shortTime = value => time(value).slice(5, granularity.value === 'hour' ? 16 : 10)
const statusLabel = value => statuses.find(item => item.value === value)?.label || value
const ratio = value => stats.value.consumed_points ? Math.min(100, Number(value) / Number(stats.value.consumed_points) * 100) : 0
const trendPath = field => {
  const values = trend.value.length === 1 ? [trend.value[0], trend.value[0]] : trend.value
  return values.map((row, index) => `${index ? 'L' : 'M'}${68 + index / Math.max(1, values.length - 1) * (chartWidth.value - 86)},${180 - Number(row[field]) / chartMax.value * 160}`).join(' ')
}
function params() {
  if (period.value === 'custom' && dateRange.value?.length !== 2) return null
  return {
    period: period.value, granularity: granularity.value,
    ...(period.value === 'custom' ? { start_date: dateRange.value[0], end_date: dateRange.value[1] } : {}),
  }
}
function errorText(err) {
  const detail = err.response?.data?.detail
  return typeof detail === 'string' ? detail : detail?.message || '积分用量加载失败，请重试'
}
async function loadSummary() {
  const requestId = ++summaryRequest
  const query = params()
  error.value = ''
  if (!query) { data.value = {}; loading.value = false; return }
  loading.value = true
  try {
    const result = await dashboardApi.getPersonalCreditUsage('', query)
    if (requestId === summaryRequest) data.value = result
  } catch (err) {
    if (requestId === summaryRequest) { error.value = errorText(err); data.value = {} }
  } finally { if (requestId === summaryRequest) loading.value = false }
}
async function loadTable() {
  const requestId = ++tableRequest
  const query = params()
  tableError.value = ''
  rows.value = []
  if (!query) { total.value = 0; tableLoading.value = false; return }
  tableLoading.value = true
  try {
    const result = await dashboardApi.getPersonalCreditUsage(detailTab.value, {
      ...query, skip: (page.value - 1) * pageSize, limit: pageSize,
      ...(detailTab.value === 'runs' ? { status: settlementStatus.value } : {}),
      ...(detailTab.value === 'ledger' ? { entry_type: entryType.value } : {}),
    })
    if (requestId !== tableRequest) return
    total.value = result.total
    const lastPage = Math.max(1, Math.ceil(total.value / pageSize))
    if (page.value > lastPage) { page.value = lastPage; return loadTable() }
    rows.value = result.items
  } catch (err) {
    if (requestId === tableRequest) { tableError.value = errorText(err); total.value = 0 }
  } finally { if (requestId === tableRequest) tableLoading.value = false }
}
function resetTable() { page.value = 1; return loadTable() }
function refresh() { loadSummary(); resetTable() }
onMounted(() => {
  refresh()
  chartObserver = new ResizeObserver(([entry]) => {
    if (entry.contentRect.width) chartWidth.value = Math.max(280, entry.contentRect.width)
  })
  chartObserver.observe(chartElement.value)
})
onBeforeUnmount(() => chartObserver?.disconnect())
</script>

<style scoped>
.credit-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 28px; }
.credit-heading h2 { margin: 0; font-size: 24px; line-height: 1.5; overflow-wrap: anywhere; }
.credit-usage { min-width: 0; color: #30343b; }
.credit-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 24px; }
.credit-filters :deep(.el-date-editor) { max-width: 100%; flex: 0 1 300px; }
.compact-select { width: 100px; }
.status-select { width: 160px; }
.credit-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 22px; margin: 0; padding: 10px 0 24px; border-bottom: 1px solid #e5e7eb; }
.credit-metrics dt { color: #747b86; font-size: 13px; }
.credit-metrics dd { margin: 10px 0 0; font-size: 24px; font-weight: 600; overflow-wrap: anywhere; }
.credit-totals { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 16px 0 28px; font-size: 12px; color: #747b86; }
.credit-totals strong { margin-left: 5px; color: #414751; font-weight: 500; }
.credit-charts { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 30px; margin-bottom: 28px; }
.credit-charts section { min-width: 0; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.section-heading h3 { font-size: 15px; margin: 0 0 12px; }
.section-heading > span { font-size: 12px; color: #747b86; }
.legend { display: inline-block; width: 8px; height: 8px; margin: 0 4px 0 10px; }
.consumed { background: #3476bb; }.claimed { background: #29906b; }
.trend-chart { min-height: 180px; display: flex; align-items: center; }
.trend-chart svg { width: 100%; height: 220px; }
.model-row { margin: 16px 0; }
.model-row > div:first-child { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 7px; font-size: 13px; }
.model-row span { overflow-wrap: anywhere; }.model-row strong { flex-shrink: 0; font-weight: 500; }
.credit-detail-heading { position: relative; }
.credit-detail-heading > .el-tabs { width: 100%; min-width: 0; }
.credit-detail-heading > .el-button { position: absolute; top: 4px; right: 0; z-index: 1; }
.credit-detail-heading.has-settle-action :deep(.el-tabs__nav-scroll) { margin-right: 104px; }
.detail-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 14px; }
.muted { color: #747b86; font-size: 12px; }.positive { color: #258664; }
.credit-pagination { display: flex; justify-content: flex-end; margin-top: 20px; }
.credit-pagination :deep(.el-pagination) { flex-wrap: wrap; row-gap: 8px; }
@media (max-width: 760px) {
  .credit-charts { grid-template-columns: 1fr; }
  .credit-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px 12px; }
  .credit-metrics dd { font-size: 21px; }
  .credit-filters :deep(.el-segmented) { max-width: 100%; }
}
</style>
