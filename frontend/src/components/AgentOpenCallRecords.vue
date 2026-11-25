<template>
  <section class="call-records" aria-label="API 调用记录">
    <div class="records-heading">
      <h1>API 调用记录</h1>
      <el-button
        :icon="Refresh"
        text
        circle
        :loading="loading"
        aria-label="刷新记录"
        title="刷新记录"
        @click="refresh"
      />
    </div>
    <p class="hint">查看开放调用的请求和结果，每 5 秒自动刷新。关闭调用或重置密钥不会清除历史记录，重新开启后可从左侧菜单查看。</p>
    <div class="records-search">
      <el-input v-model="search" clearable placeholder="按完整运行 ID 查询" aria-label="按运行 ID 查询" @keyup.enter="searchRuns" @clear="searchRuns" />
      <el-button @click="searchRuns">查询</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table v-loading="loading" :data="items" empty-text="无" row-key="run_id" @row-click="showDetail">
      <el-table-column prop="created_at" label="请求时间" width="175"><template #default="{ row }">{{ time(row.created_at) }}</template></el-table-column>
      <el-table-column prop="run_id" label="运行 ID" min-width="190" show-overflow-tooltip />
      <el-table-column label="请求内容" min-width="190" show-overflow-tooltip><template #default="{ row }">{{ display(row.prompt) }}</template></el-table-column>
      <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="耗时" width="95"><template #default="{ row }">{{ duration(row.duration_ms) }}</template></el-table-column>
      <el-table-column label="操作" width="104"><template #default="{ row }"><el-button link type="primary" @click.stop="showDetail(row)">查看详情</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-if="total > pageSize" v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="load" />
    <el-drawer v-model="drawer" title="API 调用详情" size="min(760px, 95vw)" append-to-body>
      <div v-loading="detailLoading" class="call-detail">
        <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
        <template v-if="detail">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="运行 ID">{{ detail.run_id }}</el-descriptions-item>
            <el-descriptions-item label="状态"><el-tag :type="statusType(detail.status)">{{ statusLabel(detail.status) }}</el-tag></el-descriptions-item>
            <el-descriptions-item label="请求时间">{{ time(detail.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="开始时间">{{ time(detail.started_at) }}</el-descriptions-item>
            <el-descriptions-item label="完成时间">{{ time(detail.finished_at) }}</el-descriptions-item>
            <el-descriptions-item label="耗时">{{ duration(detail.duration_ms) }}</el-descriptions-item>
            <el-descriptions-item label="指定技能">{{ display(detail.skill) }}</el-descriptions-item>
            <el-descriptions-item label="Token">{{ display(detail.total_tokens) }}</el-descriptions-item>
            <el-descriptions-item label="消耗积分">{{ display(detail.charged_points) }}</el-descriptions-item>
          </el-descriptions>
          <h4>请求内容</h4><pre>{{ display(detail.prompt) }}</pre>
          <p v-if="!detail.prompt" class="hint">未传入 prompt 时按智能体已保存的主提示词和职责执行。</p>
          <h4>返回结果</h4><pre>{{ display(detail.result) }}</pre>
          <h4>错误代码</h4><pre>{{ display(detail.error_code) }}</pre>
          <h4>失败原因</h4><pre>{{ display(detail.error_message) }}</pre>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import api from '@/api/request'

const props = defineProps({ agentId: { type: [Number, String], required: true } })
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const search = ref('')
const filter = ref('')
const loading = ref(false)
const error = ref('')
const drawer = ref(false)
const detail = ref(null)
const detailId = ref('')
const detailLoading = ref(false)
const detailError = ref('')
let sequence = 0
let detailSequence = 0
let timer
const path = () => '/agents/' + props.agentId + '/open-call/runs'
const display = value => value == null || (typeof value === 'string' && !value.trim()) ? '无' : value
const time = value => {
  if (!value) return '无'
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z')
  return Number.isNaN(date.getTime()) ? '无' : date.toLocaleString('zh-CN', { hour12: false })
}
const duration = value => value == null ? '无' : (value / 1000).toFixed(1) + ' 秒'
const statusLabel = value => ({ queued: '排队中', running: '执行中', succeeded: '成功', failed: '失败', timed_out: '已超时', cancelled: '已取消', unknown: '执行中断' }[value] || display(value))
const statusType = value => ({ succeeded: 'success', failed: 'danger', timed_out: 'danger', unknown: 'warning', cancelled: 'info' }[value] || 'primary')
const active = value => ['queued', 'running'].includes(value)
const load = async () => {
  const current = ++sequence
  loading.value = true
  try {
    const data = await api.get(path(), { params: { skip: (page.value - 1) * pageSize, limit: pageSize, ...(filter.value ? { run_id: filter.value } : {}) } })
    if (current !== sequence) return
    items.value = data.items
    total.value = data.total
    error.value = ''
  } catch (e) {
    if (current === sequence) error.value = e.response?.data?.detail || '调用记录加载失败'
  } finally {
    if (current === sequence) loading.value = false
  }
}
const loadDetail = async () => {
  const current = ++detailSequence
  detailLoading.value = true
  try {
    const data = await api.get(path() + '/' + detailId.value)
    if (current !== detailSequence) return
    detail.value = data
    detailError.value = ''
  } catch (e) {
    if (current === detailSequence) detailError.value = e.response?.data?.detail || '调用详情加载失败'
  } finally {
    if (current === detailSequence) detailLoading.value = false
  }
}
const showDetail = row => {
  detail.value = null
  detailError.value = ''
  detailId.value = row.run_id
  drawer.value = true
  loadDetail()
}
const searchRuns = () => {
  filter.value = search.value.trim()
  page.value = 1
  load()
}
const refresh = () => {
  load()
  if (drawer.value && detailId.value) loadDetail()
}
watch(() => props.agentId, () => {
  detailSequence++
  drawer.value = false
  detail.value = null
  search.value = filter.value = ''
  page.value = 1
  items.value = []
  load()
})
onMounted(() => {
  load()
  timer = setInterval(() => {
    if (document.hidden) return
    if (!loading.value) load()
    if (!detailLoading.value && drawer.value && active(detail.value?.status)) loadDetail()
  }, 5000)
})
onBeforeUnmount(() => { clearInterval(timer); sequence++; detailSequence++ })
</script>

<style scoped>
.call-records { width: 100%; min-width: 0; }
.records-heading, .records-search { display: flex; align-items: center; gap: 12px; }
.records-heading { justify-content: space-between; min-height: 44px; padding-bottom: 18px; border-bottom: 1px solid #eceef1; }
.records-heading h1 { margin: 0; color: #202328; font-size: 20px; font-weight: 650; }
.records-heading + .hint { margin-top: 20px; }
.records-search { margin: 12px 0; }
.records-search .el-input { max-width: 380px; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.65; }
.el-pagination { margin-top: 16px; justify-content: flex-end; }
.call-detail pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px; background: var(--el-fill-color-light); border-radius: 6px; }
.call-detail h4 { margin-bottom: 8px; }
</style>
