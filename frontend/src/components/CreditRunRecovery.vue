<template>
  <div class="credit-run-actions">
    <el-button v-if="canRecover" link type="primary" :loading="busy" @click="recover">
      {{ active ? '恢复对话' : '重试结算' }}
    </el-button>
    <el-button v-if="canForceSettle" link type="warning" :loading="busy" @click="forceSettle">
      强制结算
    </el-button>
    <el-button v-if="canForceRelease" link type="danger" :loading="busy" @click="forceRelease">
      强制返还
    </el-button>
    <span v-if="!canRecover && !canForceRelease && !canForceSettle">无</span>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { dashboardApi } from '@/api/dashboard'
import { formatBeijingDateTime } from '@/utils/date-time'

const props = defineProps({ row: { type: Object, required: true }, scope: { type: String, required: true } })
const emit = defineEmits(['recovered'])
const busy = ref(false)
const active = computed(() => ['queued', 'running', 'unknown'].includes(props.row.status))
const canRecover = computed(() => props.row.source === 'web' && (
  active.value || ['reserved', 'metering', 'pending_reconciliation'].includes(props.row.settlement_status)
))
const canForceRelease = computed(() => props.row.billing_mode !== 'realtime' && props.row.source === 'web' && !active.value && (
  ['reserved', 'pending_reconciliation'].includes(props.row.settlement_status)
))
const canForceSettle = computed(() => props.row.source === 'web'
  && ['succeeded', 'failed', 'cancelled', 'timed_out'].includes(props.row.status)
  && ['reserved', 'metering', 'pending_reconciliation'].includes(props.row.settlement_status))

async function forceSettle() {
  if (busy.value) return
  busy.value = true
  try {
    await ElMessageBox.confirm(
      '立即按已记录用量结算，不再等待对账期限。历史预占返还剩余积分，实时扣费不重复扣款；缺失用量由平台承担。',
      '强制结算',
      { confirmButtonText: '确认结算', cancelButtonText: '取消', type: 'warning' },
    )
    const result = await dashboardApi.recoverCreditRun(props.scope, props.row.run_id, { forceSettle: true })
    if (result.settlement_status === 'settled') ElMessage.success('已按记录用量强制结算')
    else ElMessage.warning('该任务尚未结算，请刷新后重试')
    emit('recovered')
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    const detail = err.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : detail?.message || '强制结算失败，请刷新后重试')
    emit('recovered')
  } finally {
    busy.value = false
  }
}

async function forceRelease() {
  if (busy.value) return
  busy.value = true
  try {
    await ElMessageBox.confirm(
      `将直接返还“${props.row.session_title}”的全部预占积分（${props.row.reserved_points ?? '无'}），本次运行按 0 积分结算，不再等待用量对账。聊天记录会保留，任务不会重新执行。`,
      '强制返还预占积分',
      { confirmButtonText: '确认返还', cancelButtonText: '取消', type: 'warning' },
    )
    await dashboardApi.recoverCreditRun(props.scope, props.row.run_id, { forceRelease: true })
    ElMessage.success('已强制返还全部预占积分')
    emit('recovered')
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    const detail = err.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : detail?.message || '强制返还失败，请刷新后重试')
    emit('recovered')
  } finally {
    busy.value = false
  }
}

async function recover() {
  if (busy.value) return
  busy.value = true
  try {
    await ElMessageBox.confirm(
      active.value
        ? `恢复“${props.row.session_title}”会结束失联任务，保留聊天记录。按已记录用量结算；在对账期限内用量不完整时保留待对账，超时后按已记录用量结算。任务不会自动重跑。`
        : '重新核对该任务的用量并尝试结算；在对账期限内用量不完整时继续保留待对账，超时后按已记录用量结算。',
      active.value ? '恢复对话' : '重试结算',
      { confirmButtonText: active.value ? '确认恢复' : '重试结算', cancelButtonText: '取消', type: 'warning' },
    )
    const result = await dashboardApi.recoverCreditRun(props.scope, props.row.run_id)
    if (result.settlement_status === 'pending_reconciliation') {
      const deadline = result.reconciliation_deadline
      ElMessage.warning(
        deadline
          ? `对话已结束，用量记录尚不完整，用量保留待对账；${formatBeijingDateTime(deadline)} 后可按已记录用量结算`
          : '对话已结束，用量记录尚不完整，用量保留待对账',
      )
    } else {
      ElMessage.success('处理完成，已结算实际用量')
    }
    emit('recovered')
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    const detail = err.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : detail?.message || '恢复失败，请刷新后重试')
    emit('recovered')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.credit-run-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.credit-run-actions > .el-button {
  margin: 0;
}
</style>
