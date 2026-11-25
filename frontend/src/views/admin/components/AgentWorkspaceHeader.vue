<template>
  <header class="agent-workspace-header" :class="{ 'agent-workspace-header--personal': personalChat, 'agent-workspace-header--minimal': !showIdentity && !showTabs }">
    <div v-if="showIdentity && !personalChat" class="workspace-identity">
      <el-tooltip :content="backLabel" placement="bottom">
        <el-button
          :icon="ArrowLeft"
          circle
          :aria-label="backLabel"
          @click="router.push(backTarget)"
        />
      </el-tooltip>
      <div class="identity-copy">
        <div class="identity-title">
          <strong>{{ displayName }}</strong>
        </div>
        <span v-if="runtimeLabel" class="runtime-tag">{{ runtimeLabel }}</span>
      </div>
    </div>

    <nav v-if="showTabs && tabs.length" class="workspace-tabs" aria-label="智能体工作台导航">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="workspace-tab"
        :class="{ active: active === tab.key }"
        :disabled="!hasAgent && tab.key !== 'config'"
        @click="navigate(tab.path)"
      >
        <el-icon><component :is="tab.icon" /></el-icon>
        <span>{{ tab.label }}</span>
      </button>
    </nav>

    <div class="workspace-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, ChatDotRound, Connection, DataAnalysis, Setting } from '@element-plus/icons-vue'

const props = defineProps({
  agent: { type: Object, default: null },
  agentId: { type: [Number, String], default: null },
  active: { type: String, default: 'config' },
  title: { type: String, default: '' },
  runtimeType: { type: String, default: '' },
  personalChat: { type: Boolean, default: false },
  showTabs: { type: Boolean, default: true },
  showIdentity: { type: Boolean, default: true },
})

const router = useRouter()
const hasAgent = computed(() => Number.isFinite(Number(props.agentId)) && Number(props.agentId) > 0)
const displayName = computed(() => {
  if (props.personalChat) return 'AI Hub 对话'
  return isDefaultAssistant.value ? 'AI Hub 工作台' : (props.agent?.name || props.title || '新建智能体')
})
const effectiveRuntimeType = computed(() => props.runtimeType || props.agent?.runtime_type || '')
const isDefaultAssistant = computed(() => props.agent?.kind === 'personal_default')
const backTarget = computed(() => isDefaultAssistant.value ? '/admin/skills' : '/admin/agents')
const backLabel = computed(() => isDefaultAssistant.value ? '返回管理后台' : '返回智能体列表')
const runtimeLabel = computed(() => ({
  claude_code: 'Claude Agent',
})[effectiveRuntimeType.value] || effectiveRuntimeType.value)
const tabs = computed(() => {
  if (props.personalChat) return []
  const items = [
    { key: 'chat', label: '对话', icon: ChatDotRound, path: `/admin/agents/${props.agentId}/chat` },
    { key: 'statistics', label: isDefaultAssistant.value ? '用量' : '统计', icon: DataAnalysis, path: `/admin/agents/${props.agentId}/statistics` },
  ]
  if (!isDefaultAssistant.value) {
    items.splice(1, 0, { key: 'config', label: '配置', icon: Setting, path: `/admin/agents/${props.agentId}` })
  }
  return items
})

const navigate = (path) => {
  if (hasAgent.value) router.push(path)
}
</script>

<style scoped>
.agent-workspace-header {
  height: 58px;
  flex: 0 0 58px;
  display: flex;
  align-items: center;
  padding: 0;
  background: #fff;
  box-sizing: border-box;
  z-index: 20;
}

.agent-workspace-header--personal {
  border-bottom: 0;
}

.workspace-identity,
.workspace-actions,
.workspace-tabs,
.workspace-tab {
  display: flex;
  align-items: center;
}

.workspace-identity {
  width: 264px;
  flex: 0 0 264px;
  min-width: 0;
  gap: 10px;
  align-self: stretch;
  padding: 0 14px;
  background: var(--workspace-panel-bg, #fafafa);
  box-sizing: border-box;
}

.identity-copy {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.identity-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.identity-copy strong {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--el-text-color-primary);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.identity-copy span {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.runtime-tag {
  padding: 2px;
  flex: 0 0 auto;
  border-radius: 4px;
  color: #909399;
  font-size: 11px;
  line-height: 16px;
  white-space: nowrap;
}

.workspace-tabs {
  height: 58px;
  flex: 0 0 auto;
  gap: 2px;
  padding: 0 12px;
}

.workspace-tab {
  position: relative;
  height: 34px;
  gap: 6px;
  padding: 0 12px;
  border: 0;
  border-radius: 7px;
  color: #6a7079;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 14px;
}

.workspace-tab:hover:not(:disabled),
.workspace-tab.active {
  color: #1f2329;
  background: #f0f1ef;
}

.workspace-tab:disabled {
  color: var(--el-text-color-placeholder);
  cursor: not-allowed;
}

.workspace-actions {
  flex: 0 0 auto;
  justify-content: flex-end;
  min-width: 0;
  gap: 4px;
  margin-left: auto;
  padding-right: 16px;
}
.agent-workspace-header--minimal .workspace-actions {
  gap: 2px;
  margin-right: 18px;
  padding: 3px;
  border: 0;
  background: transparent;
}

@media (max-width: 900px) {
  .agent-workspace-header {
    gap: 8px;
  }

  .identity-copy {
    display: none;
  }

  .workspace-identity {
    width: auto;
    flex: 0 0 auto;
    padding: 0 0 0 8px;
    border-right: 0;
    background: #fff;
  }

  .workspace-tab {
    gap: 4px;
    padding: 0 10px;
    font-size: 13px;
  }

  .workspace-actions {
    padding-right: 8px;
  }

  .runtime-tag {
    display: none;
  }
}

@media (max-width: 560px) {
  .workspace-tabs {
    gap: 0;
    padding: 0 4px;
  }

  .workspace-tab {
    width: 36px;
    justify-content: center;
    padding: 0;
  }

  .workspace-tab span {
    display: none;
  }

  .workspace-tab.active {
    width: auto;
    padding: 0 9px;
  }

  .workspace-tab.active span {
    display: inline;
  }

  .workspace-actions :deep(.el-button span) {
    display: none;
  }
}
</style>
