<template>
  <!-- 右侧上下文面板：Token 用量 + Runtime 信息 + 会话信息 -->
  <div class="context-panel">
    <div class="panel-section">
      <div class="section-title">上下文用量</div>
      <TokenUsage
        :used="tokenUsed"
        :input-tokens="inputTokens"
        :output-tokens="outputTokens"
        :cache-tokens="cacheTokens"
        :available="tokenAvailable"
        :complete="tokenComplete"
        :has-replies="tokenHasReplies"
      />
    </div>

    <div class="panel-section">
      <div class="section-title">Runtime</div>
      <div class="runtime-info">
        <span class="dot" :class="runtimeType"></span>
        <span>{{ runtimeLabel }}</span>
      </div>
      <div class="runtime-meta" v-if="model">
        <span class="label">模型:</span> {{ model }}
      </div>
    </div>

    <div class="panel-section" v-if="sessionInfo">
      <div class="section-title">会话</div>
      <div class="session-stats">
        <div class="stat">
          <span class="stat-value">{{ sessionInfo.messageCount || 0 }}</span>
          <span class="stat-label">条消息</span>
        </div>
        <div class="stat" v-if="sessionInfo.duration">
          <span class="stat-value">{{ sessionInfo.duration }}</span>
          <span class="stat-label">耗时</span>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { computed } from 'vue'
import TokenUsage from './TokenUsage.vue'
import { RUNTIME_INFO } from '@/config/runtimes'

const props = defineProps({
  runtimeType: { type: String, default: 'claude_code' },
  model: { type: String, default: '' },
  agentId: { type: Number, default: 0 },
  tokenUsed: { type: Number, default: null },
  inputTokens: { type: Number, default: 0 },
  outputTokens: { type: Number, default: 0 },
  cacheTokens: { type: Number, default: 0 },
  tokenAvailable: { type: Boolean, default: false },
  tokenComplete: { type: Boolean, default: false },
  tokenHasReplies: { type: Boolean, default: false },
  sessionInfo: { type: Object, default: null },
})

defineEmits(['file-click'])

const runtimeLabel = computed(() => {
  const info = RUNTIME_INFO[props.runtimeType]
  return info?.label || 'Claude Agent'
})
</script>

<style scoped>
.context-panel {
  width: 240px;
  background: #fafafa;
  border-left: 1px solid #e4e7ed;
  overflow-y: auto;
}
.panel-section {
  padding: 12px 0;
  border-bottom: 1px solid #f0f0f0;
}
.panel-section:last-child {
  border-bottom: none;
}
.section-title {
  padding: 0 12px 6px;
  font-size: 11px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.runtime-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  font-size: 13px;
  color: #303133;
}
.dot {
  width: 8px; height: 8px;
  border-radius: 50%;
}
.dot.claude_code { background: #d97706; }

.runtime-meta {
  padding: 2px 12px;
  font-size: 11px;
  color: #909399;
  font-family: 'SF Mono', monospace;
}
.runtime-meta .label { color: #c0c4cc; }

.session-stats {
  display: flex;
  gap: 16px;
  padding: 4px 12px;
}
.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.stat-value {
  font-size: 18px;
  font-weight: 700;
  color: #303133;
}
.stat-label {
  font-size: 10px;
  color: #c0c4cc;
}
</style>
