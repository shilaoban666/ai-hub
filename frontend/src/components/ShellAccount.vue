<template>
  <div v-if="authStore.isAuthenticated" class="account-row" :class="{ compact }">
    <el-popover v-model:visible="accountMenuOpen" :placement="isMobileViewport ? 'top-start' : 'right-end'" :width="280" :popper-style="{ maxWidth: 'calc(100vw - 24px)' }" trigger="click" @show="loadCredit">
      <template #reference>
        <button class="account-trigger" type="button" aria-label="打开账户信息">
          <el-avatar :size="30" :src="authStore.user?.avatar">{{ headerDisplayName.charAt(0) }}</el-avatar>
          <span class="account-copy"><strong>{{ headerDisplayName }}</strong><small>{{ authStore.user?.email?.trim() || '本地账号' }}</small></span>
        </button>
      </template>
      <div class="account-panel">
        <div class="account-panel__identity">
          <el-avatar :size="38" :src="authStore.user?.avatar">{{ headerDisplayName.charAt(0) }}</el-avatar>
          <div><strong>{{ headerDisplayName }}</strong><span>{{ authStore.user?.email?.trim() || authStore.user?.username?.trim() || '无' }}</span></div>
        </div>
        <div class="account-balance">
          <span><el-icon><Coin /></el-icon>{{ creditDisplayName(credit?.display_name) }}余额</span>
          <div class="account-balance__actions">
            <strong>{{ formatCreditPoints(credit?.available_balance, '无') }}</strong>
            <el-button
              v-if="!credit?.claimed_today"
              class="account-claim-button"
              type="primary"
              size="small"
              link
              :loading="creditClaiming"
              :disabled="!credit"
              @click.stop="claimDailyCredit"
            >
              领取
            </el-button>
            <small v-else class="account-claimed-status">今日已领取</small>
          </div>
        </div>
        <button class="account-menu-item" type="button" @click="goTo('/admin/dashboard/personal/credit-usage')">
          <el-icon><Coin /></el-icon><span>积分用量</span>
        </button>
        <button class="account-menu-item" type="button" @click="goTo('/admin/dashboard/personal/token-usage')">
          <el-icon><TrendCharts /></el-icon><span>Token 用量（sub2api）</span>
        </button>
        <button v-if="!inWorkspace" class="account-menu-item" type="button" @click="goTo('/workspace/chat')">
          <el-icon><Monitor /></el-icon><span>AI 工作台</span>
        </button>
        <button class="account-menu-item account-menu-item--danger" type="button" @click="handleLogout">
          <el-icon><SwitchButton /></el-icon><span>退出登录</span>
        </button>
      </div>
    </el-popover>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Coin, Monitor, SwitchButton, TrendCharts } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { enterpriseApi } from '@/api/enterprise'
import { creditDisplayName, formatCreditPoints } from '@/utils/credit-points'

defineProps({ compact: Boolean, isMobileViewport: Boolean, inWorkspace: Boolean })
const emit = defineEmits(['navigate'])
const router = useRouter()
const authStore = useAuthStore()
const accountMenuOpen = ref(false)
const credit = ref(null)
const creditClaiming = ref(false)
const headerDisplayName = computed(() => authStore.user?.first_name?.trim() || authStore.user?.username || '用户')
const loadCredit = async () => {
  try { credit.value = await enterpriseApi.getCredits() } catch { credit.value = null }
}
const handleCreditAccountUpdated = event => {
  if (event.detail) credit.value = event.detail
}
onMounted(() => {
  window.addEventListener('aihub:credit-account-updated', handleCreditAccountUpdated)
  loadCredit()
})
onBeforeUnmount(() => window.removeEventListener('aihub:credit-account-updated', handleCreditAccountUpdated))
const goTo = path => {
  accountMenuOpen.value = false
  emit('navigate')
  router.push(path)
}
const claimDailyCredit = async () => {
  if (!credit.value || credit.value.claimed_today || creditClaiming.value) return
  creditClaiming.value = true
  try {
    credit.value = await enterpriseApi.claimDailyCredits()
    window.dispatchEvent(new CustomEvent('aihub:credit-account-updated', { detail: credit.value }))
    ElMessage.success(`今日${credit.value.display_name}已领取`)
  } catch (error) {
    const detail = error.response?.data?.detail
    const code = detail?.data?.code || error.response?.data?.data?.code
    if (code === 'CREDIT_ALREADY_CLAIMED') {
      await loadCredit()
      if (credit.value) {
        window.dispatchEvent(new CustomEvent('aihub:credit-account-updated', { detail: credit.value }))
      }
    } else {
      ElMessage.error(typeof detail === 'string' ? detail : (detail?.message || '领取失败'))
    }
  } finally {
    creditClaiming.value = false
  }
}
const handleLogout = async () => {
  try {
    await ElMessageBox.confirm('确定退出当前账号？', '退出登录', { type: 'warning' })
  } catch {
    return
  }
  accountMenuOpen.value = false
  try {
    await authStore.logout()
  } catch {
    ElMessage.warning({ message: 'AI Hub 本地登录已清除，但统一认证退出未完成，请稍后重试。', duration: 8000 })
    router.push('/login')
  }
}
</script>

<style scoped>
.account-row { min-width: 0; height: 58px; display: flex; flex: 0 0 58px; align-items: center; padding: 0 8px; box-sizing: border-box; }
.account-row :deep(.el-popover__reference) { width: 100%; }
.account-trigger { width: 100%; min-width: 0; height: 42px; display: flex; align-items: center; gap: 9px; padding: 0 4px; border: 0; border-radius: 6px; color: #202329; background: transparent; cursor: pointer; font: inherit; text-align: left; box-sizing: border-box; }
.account-trigger:hover, .account-trigger:focus-visible { background: #f1f2f4; outline: none; }
.account-row :deep(.el-avatar) { flex: 0 0 auto; color: #333; background: #ececec; border: 1px solid #dedede; box-sizing: border-box; font-size: 12px; }
.account-copy { display: flex; flex: 1; flex-direction: column; min-width: 0; line-height: 1.2; }
.account-copy strong, .account-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-copy strong { font-size: 12px; font-weight: 600; }
.account-copy small { margin-top: 2px; color: #919499; font-size: 10px; }
.account-panel { display: flex; flex-direction: column; gap: 4px; }
.account-panel__identity { display: flex; min-width: 0; align-items: center; gap: 10px; padding: 4px 4px 12px; border-bottom: 1px solid #eceef1; }
.account-panel__identity > div { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.account-panel__identity strong, .account-panel__identity span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-panel__identity strong { color: #202329; font-size: 14px; }
.account-panel__identity span { color: #81868e; font-size: 12px; }
.account-balance { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 8px 0 4px; padding: 10px 12px; border-radius: 6px; background: #f4f6f8; }
.account-balance > span { min-width: 0; display: inline-flex; flex: 1; align-items: center; gap: 6px; overflow: hidden; color: #646a73; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.account-balance strong { color: #20242a; font-size: 16px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.account-balance__actions { min-width: 0; display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.account-claim-button.el-button { flex: 0 0 auto; margin: 0; padding: 2px 0; font-size: 12px; }
.account-claimed-status { flex: 0 0 auto; color: #777d85; font-size: 11px; white-space: nowrap; }
.account-menu-item { width: 100%; height: 36px; display: flex; align-items: center; gap: 9px; padding: 0 10px; border: 0; border-radius: 5px; color: #3f444b; background: transparent; cursor: pointer; font: inherit; font-size: 13px; text-align: left; }
.account-menu-item:hover { background: #f1f2f4; }
.account-menu-item--danger { color: #c33f3f; }
.account-row.compact .account-copy { display: none; }
.account-row.compact { justify-content: center; padding: 0 8px; }
.account-row.compact .account-trigger { justify-content: center; padding: 0; }
</style>
