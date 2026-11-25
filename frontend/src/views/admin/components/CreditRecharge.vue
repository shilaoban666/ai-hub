<template>
  <div class="recharge-panel">
    <el-alert v-if="!publishedSettings" title="请先保存并生效智能体设置，再为用户充值积分" type="warning" :closable="false" show-icon />
    <p class="recharge-hint">选择指定用户进行充值，确认后立即到账，无需保存草稿或再次生效。</p>
    <el-form v-if="publishedSettings" :model="form" :disabled="submitting" label-position="top" @submit.prevent="submit">
      <el-form-item label="充值用户" required>
        <el-select
          v-model="form.userId"
          filterable remote clearable :remote-method="searchUsers" :loading="usersLoading"
          placeholder="搜索姓名、用户名或邮箱" aria-label="充值用户"
          no-data-text="无" no-match-text="无"
          @visible-change="visible => visible && searchUsers('')"
          @change="selectUser"
        >
          <el-option v-for="user in userOptions" :key="user.id" :value="user.id" :label="userLabel(user)" />
        </el-select>
        <div v-if="usersError" class="search-error" role="alert">{{ usersError }}</div>
      </el-form-item>
      <div v-if="selectedUser" class="balance-section" aria-live="polite" :aria-busy="balanceLoading">
        <div class="balance-heading">
          <span>用户积分余额</span>
          <el-button :icon="Refresh" circle plain size="small" aria-label="刷新积分余额" title="刷新积分余额" :loading="balanceLoading" :disabled="balanceLoading || submitting" @click="loadBalance" />
        </div>
        <p v-if="balanceLoading" class="balance-loading">余额查询中...</p>
        <p v-else-if="balanceError" class="search-error" role="alert">{{ balanceError }}</p>
        <template v-else>
          <p>当前可用余额：{{ formatBalance(balance?.available_balance) }} {{ balanceUnit }}</p>
          <p>冻结积分：{{ formatBalance(balance?.reserved_balance) }} {{ balanceUnit }}</p>
        </template>
      </div>
      <el-form-item :label="`充值金额（${unitLabel}）`" required>
        <el-input-number v-model="form.amount" :min="0.01" :max="1000000000" :precision="2" :step="0.01" :controls="false" placeholder="请输入充值金额" aria-label="充值金额" />
      </el-form-item>
      <el-form-item label="充值备注">
        <el-input v-model="form.reason" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="选填，用于记录充值原因" aria-label="充值备注" />
      </el-form-item>
      <el-button type="primary" native-type="submit" :loading="submitting" :disabled="!canSubmit">确认充值</el-button>
    </el-form>
    <el-alert v-if="lastRecharge" class="recharge-result" title="充值成功" type="success" :closable="false" show-icon>
      <p>充值用户：{{ lastRecharge.userLabel }}</p>
      <p>本次充值：{{ formatCreditPoints(lastRecharge.amount, '无') }} {{ lastRecharge.unitLabel }}</p>
      <p>当前可用余额：{{ formatCreditPoints(lastRecharge.balance, '无') }} {{ lastRecharge.unitLabel }}</p>
    </el-alert>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { adminApi } from '@/api/admin'
import { enterpriseApi } from '@/api/enterprise'
import { creditDisplayName, formatCreditPoints } from '@/utils/credit-points'

const props = defineProps({ publishedSettings: { type: Object, default: null } })
const form = reactive({ userId: null, amount: undefined, reason: '' })
const users = ref([])
const selectedUser = ref(null)
const usersLoading = ref(false)
const usersError = ref('')
const submitting = ref(false)
const lastRecharge = ref(null)
const balance = ref(null)
const balanceLoading = ref(false)
const balanceError = ref('')
let searchVersion = 0
let balanceVersion = 0
const unitLabel = computed(() => creditDisplayName(props.publishedSettings?.credit_display_name))
const balanceUnit = computed(() => creditDisplayName(balance.value?.display_name || unitLabel.value))
const formatBalance = value => (
  typeof value === 'string' && !value.trim() ? '无' : formatCreditPoints(value, '无')
)
const userOptions = computed(() => {
  if (selectedUser.value && !users.value.some(user => user.id === selectedUser.value.id)) {
    return [selectedUser.value, ...users.value]
  }
  return users.value
})
const canSubmit = computed(() => Boolean(props.publishedSettings && selectedUser.value)
  && Number.isFinite(form.amount) && form.amount >= 0.01 && form.amount <= 1000000000 && !submitting.value)
const userLabel = user => {
  const name = [user.first_name?.trim(), user.username?.trim()].filter(Boolean).join(' · ') || '无'
  return `${name}（ID：${user.id}）`
}
const errorText = (error, fallback) => {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : (detail?.message || fallback)
}
const searchUsers = async (query = '') => {
  const version = ++searchVersion
  usersLoading.value = true
  usersError.value = ''
  try {
    const result = await adminApi.getUsers({ search: query.trim() || undefined, limit: 50 })
    if (version === searchVersion) users.value = result.items || []
  } catch (error) {
    if (version === searchVersion) {
      users.value = []
      usersError.value = errorText(error, '用户加载失败，请重新搜索')
    }
  } finally {
    if (version === searchVersion) usersLoading.value = false
  }
}
const loadBalance = async () => {
  const version = ++balanceVersion
  const userId = selectedUser.value?.id
  balance.value = null
  balanceError.value = ''
  balanceLoading.value = Boolean(userId)
  if (!userId) return
  try {
    const account = await enterpriseApi.getUserCreditBalance(userId)
    if (version === balanceVersion) balance.value = account
  } catch (error) {
    if (version === balanceVersion) balanceError.value = errorText(error, '余额查询失败，请刷新重试')
  } finally {
    if (version === balanceVersion) balanceLoading.value = false
  }
}
const selectUser = id => {
  selectedUser.value = userOptions.value.find(user => user.id === id) || null
  lastRecharge.value = null
  loadBalance()
}
onBeforeUnmount(() => {
  searchVersion++
  balanceVersion++
})
const submit = async () => {
  if (!canSubmit.value) return
  const user = selectedUser.value
  const amount = form.amount.toFixed(2)
  const label = userLabel(user)
  const unit = unitLabel.value
  const reason = form.reason.trim() || '管理员充值'
  submitting.value = true
  try {
    await ElMessageBox.confirm(
      `将为 ${label} 充值 ${formatCreditPoints(amount)} ${unit}，确认后立即到账。`,
      '确认积分充值',
      { type: 'warning', confirmButtonText: '确认充值', cancelButtonText: '取消' },
    )
  } catch {
    submitting.value = false
    return
  }
  try {
    const account = await enterpriseApi.rechargeUserCredits(user.id, { amount, reason })
    ++balanceVersion
    balance.value = account
    balanceLoading.value = false
    balanceError.value = ''
    lastRecharge.value = { userLabel: label, amount, balance: account.available_balance, unitLabel: unit }
    form.amount = undefined
    form.reason = ''
    ElMessage.success('充值成功')
  } catch (error) {
    ElMessage.error(errorText(error, '充值失败，请稍后重试'))
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.recharge-panel { max-width: 560px; padding: 12px 0; }
.recharge-hint { margin: 0 0 24px; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.6; }
.el-alert + .recharge-hint { margin-top: 16px; }
.el-select, .el-input-number { width: 100%; }
.search-error { margin-top: 8px; color: var(--el-color-danger); font-size: 12px; }
.balance-section { margin: 0 0 22px; padding: 12px 0; border-top: 1px solid var(--el-border-color-lighter); border-bottom: 1px solid var(--el-border-color-lighter); }
.balance-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--el-text-color-regular); font-size: 14px; }
.balance-section p { margin: 8px 0 0; overflow-wrap: anywhere; }
.balance-loading { color: var(--el-text-color-secondary); font-size: 13px; }
.recharge-result { margin-top: 24px; }
.recharge-result p { margin: 4px 0; overflow-wrap: anywhere; }
</style>
