<template>
  <!-- Token 用量指示器：真实用量构成 + 详细统计 -->
  <div class="token-usage" :class="{ compact, unavailable: !available }">
    <el-popover placement="top-end" trigger="hover" :width="220">
      <template #reference>
        <div class="usage-chart" :style="chartStyle" aria-hidden="true"></div>
      </template>
      <div v-if="available" class="token-details">
        <div class="token-detail-row total">
          <span><span class="legend-dot total"></span>全部</span>
          <strong>{{ formatExactTokens(used) }} Token</strong>
        </div>
        <div class="token-detail-row">
          <span><span class="legend-dot input"></span>普通输入</span>
          <strong>{{ formatExactTokens(inputTokens) }} Token</strong>
        </div>
        <div class="token-detail-row">
          <span><span class="legend-dot cache"></span>缓存输入</span>
          <strong>{{ formatExactTokens(cacheTokens) }} Token</strong>
        </div>
        <div class="token-detail-row">
          <span><span class="legend-dot output"></span>输出</span>
          <strong>{{ formatExactTokens(outputTokens) }} Token</strong>
        </div>
        <div v-if="!complete" class="token-detail-note">部分历史回复未返回 usage</div>
      </div>
      <div v-else class="token-detail-empty">
        {{ hasReplies ? '当前 Runtime 未返回真实 Token usage' : '当前对话还没有 Token 用量' }}
      </div>
    </el-popover>
    <div class="usage-text">
      <span v-if="available">{{ complete ? '累计' : '已记录' }} {{ formatTokens(used) }} Token</span>
      <span v-else>{{ hasReplies ? 'Token 用量不可用' : '未产生用量' }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  used: { type: Number, default: null },
  inputTokens: { type: Number, default: 0 },
  outputTokens: { type: Number, default: 0 },
  cacheTokens: { type: Number, default: 0 },
  available: { type: Boolean, default: false },
  complete: { type: Boolean, default: false },
  hasReplies: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
})

const chartStyle = computed(() => {
  if (!props.available || !props.used) return {}
  const inputEnd = (props.inputTokens / props.used) * 100
  const cacheEnd = inputEnd + (props.cacheTokens / props.used) * 100
  return {
    background: `conic-gradient(#6d5bd0 0 ${inputEnd}%, #16a36a ${inputEnd}% ${cacheEnd}%, #2f80ed ${cacheEnd}% 100%)`,
  }
})

const formatTokens = (n) => {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(0) + 'K'
  return String(n)
}

const formatExactTokens = n => Math.round(Number(n) || 0).toLocaleString()
</script>

<style scoped>
.token-usage {
  padding: 8px 12px;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
}
.usage-chart {
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border-radius: 50%;
  background: #e4e7ed;
  position: relative;
  cursor: pointer;
}
.usage-chart::after {
  content: '';
  position: absolute;
  inset: 4px;
  border-radius: 50%;
  background: #fff;
}
.token-usage.unavailable .usage-chart {
  background: #e4e7ed;
}

.usage-text {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #909399;
  font-family: 'SF Mono', 'Courier New', monospace;
}
.token-details {
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
}
.token-detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 28px;
  color: #606266;
}
.token-detail-row.total {
  padding-bottom: 4px;
  margin-bottom: 4px;
  border-bottom: 1px solid #ebeef5;
  color: #303133;
}
.token-detail-row strong {
  margin-left: 18px;
  color: #303133;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.token-detail-note,
.token-detail-empty {
  margin-top: 6px;
  color: #909399;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  line-height: 1.5;
}
.legend-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 6px;
  border-radius: 50%;
}
.legend-dot.total { background: #606266; }
.legend-dot.input { background: #6d5bd0; }
.legend-dot.cache { background: #16a36a; }
.legend-dot.output { background: #2f80ed; }

/* compact 模式：内联在操作栏中 */
.token-usage.compact {
  padding: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}
.token-usage.compact .usage-chart {
  width: 20px;
  height: 20px;
  flex-basis: 20px;
}
.token-usage.compact .usage-chart::after {
  inset: 4px;
}
.token-usage.compact .usage-text {
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  font-family: inherit;
  color: #41464d;
  white-space: nowrap;
  gap: 2px;
}
</style>
