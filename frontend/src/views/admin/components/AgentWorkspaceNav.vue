<template>
  <aside class="agent-workspace-nav" aria-label="智能体配置导航">
    <RouterLink class="agent-workspace-nav__back" to="/admin/agents">
      <el-icon><ArrowLeft /></el-icon><span>自定义 Agent</span>
    </RouterLink>

    <div class="agent-workspace-nav__identity">
      <AgentSwitcher :current-agent="loadFailed ? { name: '加载失败' } : agent" :identity-loading="loading" />
      <button v-if="loadFailed" type="button" class="agent-workspace-nav__retry" @click="$emit('retry')">重新加载</button>
    </div>

    <nav class="agent-workspace-nav__groups" aria-label="配置菜单">
      <div v-for="group in menuGroups" :key="group.label" class="agent-workspace-nav__group" role="group" :aria-label="group.label">
        <div class="agent-workspace-nav__group-label" aria-hidden="true">{{ group.label }}</div>
        <button
          v-for="item in group.items"
          :key="item.key"
          type="button"
          class="agent-workspace-nav__item"
          :class="{ 'is-active': active === item.key }"
          :aria-current="active === item.key ? 'page' : undefined"
          :disabled="!hasAgent"
          @click="go(item.path, item.section)"
        >
          <el-icon><component :is="item.icon" /></el-icon><span>{{ item.label }}</span>
        </button>
      </div>
    </nav>

    <div class="agent-workspace-nav__footer">
      <a v-if="hasAgent" class="agent-workspace-nav__chat" :href="chatHref" target="_blank" rel="noopener noreferrer" aria-label="开始对话（新窗口打开工作台）">
        <el-icon><ChatLineRound /></el-icon><span>开始对话</span><el-icon class="agent-workspace-nav__external"><TopRight /></el-icon>
      </a>
      <button v-else type="button" class="agent-workspace-nav__chat" disabled>
        <el-icon><ChatLineRound /></el-icon><span>开始对话</span>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import AgentSwitcher from './AgentSwitcher.vue'
import SkillIcon from '@/components/icons/SkillIcon.vue'
import { ArrowLeft, ChatDotSquare, ChatLineRound, Connection, MagicStick, Tickets, TopRight, User } from '@element-plus/icons-vue'
import { useAgentOpenCall } from '@/composables/useAgentOpenCall'

const props = defineProps({
  agent: { type: Object, default: null },
  agentId: { type: [Number, String], default: null },
  loading: { type: Boolean, default: false },
  loadFailed: { type: Boolean, default: false },
  active: { type: String, default: 'config' },
})
defineEmits(['retry'])

const router = useRouter()
const hasAgent = computed(() => Number.isSafeInteger(Number(props.agentId)) && Number(props.agentId) > 0)
const chatHref = computed(() => hasAgent.value
  ? router.resolve({ name: 'WorkspaceChat', query: { agent: props.agentId } }).href : '')
const openCall = useAgentOpenCall()
const menuGroups = computed(() => [
  { label: '智能体设置', items: [
    { key: 'config', label: '基本信息', icon: User, section: 'basic' },
    ...(props.agent?.kind === 'expert' && props.agent.can_edit !== false
      ? [{ key: 'open-call', label: '开放调用', icon: MagicStick, path: '/open-call' }] : []),
    ...(openCall?.enabled.value ? [{ key: 'api-calls', label: 'API 调用记录', icon: Tickets, path: '/api-calls' }] : []),
  ] },
  { label: '能力资源', items: [
    { key: 'skills', label: '技能市场', icon: SkillIcon, section: 'skills' },
    { key: 'mcp', label: '连接器', icon: Connection, section: 'mcp' },
    { key: 'prompts', label: '提示词库', icon: ChatDotSquare, section: 'prompts' },
  ] },
])

const go = (path = '', section = '') => {
  if (!hasAgent.value) return
  const base = `/admin/agents/${props.agentId}`
  if (path) {
    router.push(`${base}${path}`)
    return
  }
  router.push({ path: base, query: section && section !== 'basic' ? { section } : {} })
}
</script>

<style scoped>
.agent-workspace-nav {
  display: flex;
  flex: 0 0 248px;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border-right: 1px solid var(--workspace-border, #e7e9ec);
  background: #fff;
}
.agent-workspace-nav__back { display: flex; flex-shrink: 0; align-items: center; gap: 8px; margin: 16px 16px 0; padding: 6px 4px; border-radius: 6px; color: #737983; font-size: 12px; text-decoration: none; }
.agent-workspace-nav__back:hover { color: #272c33; }
.agent-workspace-nav__identity { display: grid; flex-shrink: 0; gap: 9px; margin: 18px 20px 22px; min-width: 0; }
.agent-workspace-nav__retry { justify-self: start; padding: 0; border: 0; background: transparent; color: var(--el-color-primary); font: inherit; font-size: 12px; cursor: pointer; }
.agent-workspace-nav__groups { flex: 1; min-height: 0; overflow-y: auto; padding: 0 12px 16px; }
.agent-workspace-nav__group + .agent-workspace-nav__group { margin-top: 22px; }
.agent-workspace-nav__group-label { padding: 0 12px 8px; color: #9298a1; font-size: 11px; line-height: 18px; }
.agent-workspace-nav__item { display: flex; align-items: center; gap: 11px; width: 100%; min-height: 40px; margin: 2px 0; padding: 0 12px; border: 0; border-radius: 7px; color: #555b63; background: transparent; font: inherit; font-size: 13px; text-align: left; cursor: pointer; }
.agent-workspace-nav__item > .el-icon { width: 17px; flex: 0 0 17px; font-size: 17px; }
.agent-workspace-nav__item:hover:not(:disabled) { background: var(--workspace-hover-bg, #eceef2); }
.agent-workspace-nav__item.is-active { color: #272c33; background: var(--workspace-active-bg, #e4e7ec); font-weight: 600; }
.agent-workspace-nav__item:disabled { color: var(--el-text-color-placeholder); cursor: not-allowed; }
.agent-workspace-nav__footer { display: grid; flex-shrink: 0; gap: 9px; padding: 16px; }
.agent-workspace-nav__chat { display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 40px; box-sizing: border-box; padding: 0 12px; border: 1px solid #343941; border-radius: 8px; background: #343941; color: #fff; font: inherit; font-size: 13px; text-decoration: none; cursor: pointer; }
.agent-workspace-nav__chat:hover:not(:disabled) { background: #484e57; border-color: #484e57; }
.agent-workspace-nav__chat:disabled { opacity: .4; cursor: not-allowed; }
.agent-workspace-nav__external { margin-left: auto; opacity: .65; font-size: 13px; }
.agent-workspace-nav__chat > .el-icon:first-child { margin-right: auto; font-size: 17px; }
.agent-workspace-nav__item:focus-visible, .agent-workspace-nav__chat:focus-visible, .agent-workspace-nav__back:focus-visible { outline: 2px solid #7899be; outline-offset: -2px; }
@media (max-width: 900px) {
  .agent-workspace-nav { flex-basis: 212px; }
}
@media (max-width: 720px) {
  .agent-workspace-nav { display: grid; grid-template-columns: minmax(0, 1fr) auto; width: 100%; flex: 0 0 auto; border-right: 0; border-bottom: 1px solid var(--workspace-border, #e7e9ec); }
  .agent-workspace-nav__back { grid-column: 1; margin: 8px 12px 0; }
  .agent-workspace-nav__identity { grid-column: 1; gap: 0; margin: 4px 16px 12px; }
  .agent-workspace-nav__group-label { display: none; }
  .agent-workspace-nav__groups { grid-column: 1 / -1; grid-row: 3; display: flex; gap: 8px; min-width: 0; overflow-x: auto; padding: 0 8px 8px; }
  .agent-workspace-nav__group { display: flex; flex: 0 0 auto; gap: 2px; }
  .agent-workspace-nav__group + .agent-workspace-nav__group { margin: 0; padding-left: 8px; border-left: 1px solid var(--workspace-border, #e7e9ec); }
  .agent-workspace-nav__item { width: auto; min-height: 36px; padding: 0 9px; white-space: nowrap; }
  .agent-workspace-nav__footer { grid-column: 2; grid-row: 1 / 3; align-self: center; padding: 12px; border: 0; }
  .agent-workspace-nav__chat { min-height: 36px; }
}
</style>
