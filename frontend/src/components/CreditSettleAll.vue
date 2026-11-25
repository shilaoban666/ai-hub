<template>
  <el-button type="primary" :loading="busy" @click="settleAll">全量结算</el-button>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { dashboardApi } from '@/api/dashboard'

const props = defineProps({ scope: { type: String, required: true }, userId: Number })
const emit = defineEmits(['settled'])
const busy = ref(false)

async function settleAll() {
  if (busy.value) return
  busy.value = true
  const userId = props.userId
  const scope = props.scope
  const target = scope === 'personal' ? '我的' : userId ? '当前所选用户的' : '全部用户的'
  try {
    await ElMessageBox.confirm(
      `将强制结算${target}全部历史未结算且已结束的任务，不受日期、状态筛选和分页限制，运行中或失联的任务会跳过。立即按已记录用量结算，历史预占返还剩余积分，实时扣费不重复扣款；缺失用量由平台承担。`,
      '全量结算',
      { confirmButtonText: '确认全量结算', cancelButtonText: '取消', type: 'warning' },
    )
    const result = await dashboardApi.settleAllCreditRuns(scope, userId ? { user_id: userId } : {})
    const message = `全量结算完成：已结算 ${result.settled} 条，跳过 ${result.skipped} 条，失败 ${result.failed} 条`
    ElMessage({ type: result.failed ? 'warning' : 'success', message, duration: 6000 })
    emit('settled')
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    const detail = err.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : detail?.message || '全量结算失败，请刷新查看结果后重试')
    emit('settled')
  } finally {
    busy.value = false
  }
}
</script>
