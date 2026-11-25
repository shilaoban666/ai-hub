<template>
  <aside v-if="visible" class="service-availability-notice" role="status" aria-live="polite">
    <el-icon :size="20" :class="{ 'is-loading': recovering }"><Loading v-if="recovering" /><WarningFilled v-else /></el-icon>
    <div class="service-availability-copy">
      <strong>{{ recovering ? '服务暂时不可用，正在自动重连' : '服务暂未恢复' }}</strong>
      <span>{{ recovering ? '可能正在升级或重启，恢复后将自动加载数据，请保留当前页面。' : '等待时间较长，请稍后重新加载页面。编辑中的内容请先保留。' }}</span>
    </div>
    <el-button
      v-if="recovering"
      class="retry-button"
      size="small"
      plain
      :loading="retrying"
      :disabled="retrying"
      @click="handleRetry"
    >
      <el-icon v-if="!retrying"><Refresh /></el-icon>
      {{ retrying ? '正在重连' : '立即重试' }}
    </el-button>
    <el-button v-else class="retry-button" size="small" plain @click="reload">
      <el-icon><Refresh /></el-icon>
      重新加载
    </el-button>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Loading, Refresh, WarningFilled } from '@element-plus/icons-vue'
import { serviceAvailability, retryUnavailableServices } from '@/utils/service-availability'

const recovering = computed(() => Object.values(serviceAvailability).some(state => state.active > 0))
const visible = computed(() => recovering.value || Object.values(serviceAvailability).some(state => state.unavailable))
const retrying = ref(false)
const reload = () => window.location.reload()
const handleRetry = () => {
  if (retrying.value) return
  retrying.value = true
  retryUnavailableServices()
  window.setTimeout(() => { retrying.value = false }, 900)
}
</script>

<style scoped>
.service-availability-notice {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 4000;
  display: flex;
  align-items: center;
  gap: 12px;
  width: min(640px, calc(100vw - 32px));
  box-sizing: border-box;
  padding: 14px 18px;
  color: #8a5a17;
  background: #fff9eb;
  border: 1px solid #eed7a5;
  border-radius: 12px;
  box-shadow: 0 6px 24px #392b151a;
}
.service-availability-notice > .el-icon { flex-shrink: 0; }
.service-availability-copy { display: flex; flex: 1; flex-direction: column; gap: 4px; min-width: 0; }
.service-availability-copy strong { font-size: 14px; }
.service-availability-copy span { font-size: 12px; line-height: 1.6; }
.retry-button {
  flex: 0 0 auto;
  min-width: 88px;
  color: #8a5a17;
  border-color: #dcae58;
  background: #fffdf7;
  font-weight: 600;
}
.retry-button:hover,
.retry-button:focus-visible {
  color: #70470b;
  border-color: #c28a2f;
  background: #fff5d8;
}
.retry-button :deep(.el-icon) { margin-right: 4px; }
@media (max-width: 480px) {
  .service-availability-notice { top: 8px; padding: 12px; gap: 8px; flex-wrap: wrap; }
  .service-availability-copy { flex-basis: calc(100% - 40px); }
  .service-availability-notice > .retry-button { margin-left: 28px; }
}
</style>
