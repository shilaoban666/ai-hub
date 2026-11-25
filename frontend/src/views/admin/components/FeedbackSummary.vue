<template>
  <dl class="feedback-summary" :aria-busy="loading" aria-label="反馈汇总">
    <div v-for="metric in metrics" :key="metric.key" class="feedback-summary-item" :class="metric.tone">
      <dt>{{ metric.label }}</dt>
      <dd>{{ displayValue(metric.key) }}</dd>
    </div>
  </dl>
</template>

<script setup>
const props = defineProps({ summary: Object, loading: Boolean })
const metrics = [
  { key: 'likes', label: '点赞数量', tone: 'positive' },
  { key: 'dislikes', label: '点踩数量', tone: 'negative' },
  { key: 'resolved', label: '点踩已处理', tone: 'positive' },
  { key: 'pending', label: '点踩待处理', tone: 'pending' },
  { key: 'resolution_rate', label: '点踩处理率', tone: '' },
]
function displayValue(key) {
  const value = props.summary?.[key]
  if (value === null || value === undefined) return '无'
  return key === 'resolution_rate' ? `${(value * 100).toFixed(1)}%` : value.toLocaleString('zh-CN')
}
</script>

<style scoped>
.feedback-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin: 0 0 20px; }
.feedback-summary-item { min-width: 0; padding: 18px 20px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; background: var(--el-bg-color); }
dt { color: var(--el-text-color-secondary); font-size: 13px; line-height: 20px; }
dd { margin: 10px 0 0; color: var(--el-text-color-primary); font-size: 26px; font-weight: 600; line-height: 34px; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.positive dd { color: var(--el-color-success); }
.negative dd { color: var(--el-color-danger); }
.pending dd { color: var(--el-color-warning); }
@media (max-width: 1000px) { .feedback-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 600px) { .feedback-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .feedback-summary-item { padding: 14px; } }
</style>
