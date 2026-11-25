<template>
  <div class="workspace-layout">
    <header class="workspace-mobile-header">
      <button ref="menuButton" type="button" class="workspace-icon-button" aria-label="打开工作台导航" aria-controls="workspace-sidebar" :aria-expanded="mobileSidebarOpen" @click="openMobileSidebar"><el-icon><Expand /></el-icon></button>
      <span>AI Hub 工作台</span>
    </header>
    <button v-if="mobileSidebarOpen" type="button" class="workspace-backdrop" aria-label="关闭侧栏遮罩" tabindex="-1" @click="closeMobileSidebar" />
    <aside id="workspace-sidebar" class="workspace-sidebar" :class="{ compact: effectiveCollapsed, 'mobile-open': mobileSidebarOpen }" aria-label="工作台侧栏" @keydown.esc="handleSidebarEscape">
      <div class="workspace-brand">
        <ShellBrand v-if="!effectiveCollapsed" />
        <div class="workspace-brand-actions">
          <ProductModeSwitch :compact="effectiveCollapsed" @navigate="mobileSidebarOpen = false" />
          <button ref="closeButton" type="button" class="workspace-icon-button workspace-close" aria-label="关闭工作台导航" @click="closeMobileSidebar"><el-icon><Close /></el-icon></button>
        </div>
      </div>
      <nav v-show="!effectiveCollapsed" class="workspace-primary" aria-label="工作台导航">
        <div class="workspace-heading">
          <AgentSwitcher
            allow-switch compact-trigger
            :current-agent="currentAgent" :default-assistant="defaultAssistant" :selected-id="selectedAgentId"
            :agents="agents" :loading="agentsLoading" :load-failed="agentsLoadFailed"
            :identity-loading="selectedAgentId ? agentsLoading : assistantLoading" :switching="switchingAgent"
            @reload="loadAgents" @select="switchAgent"
          />
        </div>
      </nav>
      <nav class="workspace-resources" aria-label="资源与工具">
        <button type="button" class="workspace-action" aria-label="新建对话" :title="effectiveCollapsed ? '新建对话' : undefined"
          :aria-current="isChat && !route.query.session ? 'page' : undefined" @click="startChat">
          <el-icon><EditPen /></el-icon><span>新建对话</span>
        </button>
        <router-link v-for="item in resourceItems" :key="item.key" class="workspace-action" :to="item.to"
          :aria-label="item.label" :title="effectiveCollapsed ? item.label : undefined"
          :aria-current="activeMenu === item.key ? 'page' : undefined" @click="navigateResource">
          <el-icon><component :is="item.icon" /></el-icon><span>{{ item.label }}</span>
        </router-link>
        <el-popover v-model:visible="resourceMenuOpen" :placement="isMobileViewport ? 'bottom-start' : 'right-start'" :width="188" :offset="6"
          popper-class="workspace-resource-popover"
          :popper-style="{ padding: '6px', borderRadius: '12px', maxWidth: 'calc(100vw - 24px)' }"
          :show-arrow="false" trigger="click" @show="focusActiveResource">
          <template #reference>
            <button ref="resourceButton" type="button" class="workspace-action"
              :class="{ 'is-active': resourceMenuOpen || agentPageActive }" :aria-expanded="resourceMenuOpen"
              aria-label="更多" :title="effectiveCollapsed ? '更多' : undefined"><el-icon><MoreFilled /></el-icon><span>更多</span></button>
          </template>
          <nav ref="resourceMenu" class="workspace-resource-menu" aria-label="更多" @keydown.esc.stop="closeResourceMenu">
            <router-link v-for="item in agentItems" :key="item.key" class="workspace-resource-link" :to="item.to"
              :aria-current="activeMenu === item.key ? 'page' : undefined" @click="navigateResource">
              <el-icon><component :is="item.icon" /></el-icon><span>{{ item.label }}</span>
            </router-link>
          </nav>
        </el-popover>
      </nav>
      <div v-show="!effectiveCollapsed" id="workspace-history" class="workspace-history" />
      <footer class="workspace-footer">
        <ShellAccount in-workspace :compact="effectiveCollapsed" :is-mobile-viewport="isMobileViewport" @navigate="mobileSidebarOpen = false" />
        <el-tooltip :disabled="isMobileViewport" :enterable="false" :trigger-keys="[]" :content="effectiveCollapsed ? '展开主菜单' : '收起主菜单'" placement="right">
          <button class="collapse-button" type="button" :aria-label="effectiveCollapsed ? '展开主菜单' : '收起主菜单'" :aria-expanded="!effectiveCollapsed" aria-controls="workspace-sidebar" @click="toggleSidebar">
            <el-icon><Fold v-if="!effectiveCollapsed" /><Expand v-else /></el-icon>
          </button>
        </el-tooltip>
      </footer>
    </aside>
    <section class="workspace-content">
      <!-- 保留对话页实例，使历史列表、搜索状态和生成中的回复不随资源页切换而卸载。 -->
      <div v-show="isChat" class="workspace-chat"><ChatBootstrap :selected-agent-id="selectedAgentId" @ready="assistantId = $event" @identity="defaultAssistant = $event" @loading="assistantLoading = $event" /></div>
      <div v-if="!isChat" class="workspace-resource" :class="{ 'workspace-resource--agent': isExpertSettings || route.meta.workbenchDefault }">
        <router-view :key="selectedAgentId" @agent-updated="updateAgent" />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatDotSquare, Close, Connection, DataAnalysis, EditPen, Expand, Fold, MoreFilled } from '@element-plus/icons-vue'
import ChatBootstrap from './ChatBootstrap.vue'
import AgentSwitcher from './components/AgentSwitcher.vue'
import ProductModeSwitch from '@/components/ProductModeSwitch.vue'
import SkillIcon from '@/components/icons/SkillIcon.vue'
import ShellAccount from '@/components/ShellAccount.vue'
import ShellBrand from '@/components/ShellBrand.vue'
import { useAgentOptions } from '@/composables/useAgentOptions'
import { provideAgentOpenCall } from '@/composables/useAgentOpenCall'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const mobileViewport = window.matchMedia('(max-width: 900px)')
const isMobileViewport = ref(mobileViewport.matches)
const mobileSidebarOpen = ref(false)
const effectiveCollapsed = computed(() => !isMobileViewport.value && appStore.collapsed)
const menuButton = ref(null)
const closeButton = ref(null)
const newSession = shallowRef(null)
provide('workspaceSidebar', { enabled: ref(true), mobileSidebarOpen, newSession })

const openMobileSidebar = async () => {
  mobileSidebarOpen.value = true
  await nextTick()
  closeButton.value?.focus()
}
const closeMobileSidebar = () => {
  if (!mobileSidebarOpen.value) return
  resourceMenuOpen.value = false
  mobileSidebarOpen.value = false
  menuButton.value?.focus()
}
const toggleSidebar = () => {
  resourceMenuOpen.value = false
  if (isMobileViewport.value) { closeMobileSidebar(); return }
  appStore.toggleSidebar()
}
const handleSidebarEscape = () => {
  if (resourceMenuOpen.value) closeResourceMenu()
  else closeMobileSidebar()
}
const updateMobileViewport = event => {
  isMobileViewport.value = event.matches
  mobileSidebarOpen.value = false
  resourceMenuOpen.value = false
}
const defaultAssistant = ref(null)
const assistantLoading = ref(true)
const assistantId = ref(null)
provide('workbenchAssistant', { agentId: assistantId, loading: assistantLoading })
const { agents, agentsLoading, agentsLoadFailed, loadAgents, updateAgent } = useAgentOptions()
const switchingAgent = ref(false)
const resourceMenuOpen = ref(false)
const resourceButton = ref(null)
const resourceMenu = ref(null)
const isExpertSettings = computed(() => route.meta.workbenchExpert === true)
const selectedAgentId = computed(() => {
  if (route.meta.workbenchDefault) return 0
  const id = Number(isExpertSettings.value ? route.params.id : route.query.agent)
  return Number.isSafeInteger(id) && id > 0 ? id : 0
})
const currentAgent = computed(() => selectedAgentId.value
  ? agents.value.find(agent => agent.id === selectedAgentId.value) : defaultAssistant.value)
provideAgentOpenCall(selectedAgentId, currentAgent)
const expertQuery = computed(() => ({
  agent: selectedAgentId.value,
  ...(route.query.session ? { session: route.query.session } : {}),
}))
const expertMenus = computed(() => [
  { key: 'channels', path: '/channels', label: '渠道配置', icon: Connection },
  { key: 'statistics', path: '/statistics', label: '统计信息', icon: DataAnalysis },
])
const assistantMenus = [
  { key: 'channels', label: '渠道配置', icon: Connection },
  { key: 'statistics', label: '统计信息', icon: DataAnalysis },
]
const agentItems = computed(() => selectedAgentId.value
    ? expertMenus.value.map(item => ({ ...item, to: { path: `/workspace/agents/${selectedAgentId.value}${item.path}`, query: expertQuery.value } }))
    : assistantMenus.map(item => ({ ...item, to: { path: `/workspace/assistant/${item.key}`, query: route.query.session ? { session: route.query.session } : {} } }))
)
const agentPageActive = computed(() => agentItems.value.some(item => item.key === activeMenu.value))
const switchAgent = async id => {
  if (id === selectedAgentId.value) return
  switchingAgent.value = true
  try {
    await router.push({ path: '/workspace/chat', query: id ? { agent: id } : {} })
    mobileSidebarOpen.value = false
  } catch {
    ElMessage.error('切换失败，请稍后重试')
  } finally {
    switchingAgent.value = false
  }
}
onMounted(() => {
  mobileViewport.addEventListener('change', updateMobileViewport)
  loadAgents()
})
onBeforeUnmount(() => mobileViewport.removeEventListener('change', updateMobileViewport))
watch(() => route.path, () => {
  resourceMenuOpen.value = false
  mobileSidebarOpen.value = false
})
const isChat = computed(() => route.name === 'WorkspaceChat')
const activeMenu = computed(() => {
  if (isChat.value) return ''
  if (route.name === 'WorkspaceAgentDetail') return 'basic'
  return route.path.split('/').pop()
})
const resources = [
  { path: 'skills', label: '技能市场', icon: SkillIcon },
  { path: 'connectors', label: '连接器', icon: Connection },
  { path: 'prompts', label: '提示词库', icon: ChatDotSquare },
]
const resourceItems = computed(() => resources.map(({ path, ...resource }) => ({
  ...resource,
  key: path,
  to: { path: `/workspace/${path}`, query: selectedAgentId.value ? expertQuery.value : route.query },
})))
const startChat = () => {
  mobileSidebarOpen.value = false
  if (newSession.value) newSession.value()
  else router.push({ path: '/workspace/chat', query: selectedAgentId.value ? { agent: selectedAgentId.value } : {} })
}
const navigateResource = () => {
  if (resourceMenuOpen.value && !isMobileViewport.value) resourceButton.value?.focus()
  resourceMenuOpen.value = false
  mobileSidebarOpen.value = false
}
const closeResourceMenu = () => {
  resourceMenuOpen.value = false
  resourceButton.value?.focus()
}
const focusActiveResource = () => {
  const menu = resourceMenu.value
  const item = menu?.querySelector('[aria-current="page"]') || menu?.querySelector('a')
  item?.focus({ preventScroll: true })
}
</script>

<style scoped>
.workspace-layout {
  --workspace-panel-bg: #f7f7f7;
  --workspace-row-height: 34px;
  /* Shared chat components retain their original sizes outside the workspace. */
  --workspace-font-size-offset: 1px;
  --el-font-size-extra-large: 21px;
  --el-font-size-large: 19px;
  --el-font-size-medium: 17px;
  --el-font-size-base: 15px;
  --el-font-size-small: 14px;
  --el-font-size-extra-small: 13px;
  --workspace-border: #e9e9e9;
  --workspace-control-bg: #fff;
  --workspace-hover-bg: #f0f0f0;
  --workspace-active-bg: #ebebeb;
  --workspace-strong: #000;
  --workspace-ink: #181818;
  --workspace-muted: #888;
  --workspace-subtle: #999;
  --workspace-focus: #858585;
  --shell-accent: #2d2d2d;
  display: flex;
  width: 100%;
  height: 100dvh;
  min-height: 0;
  overflow: hidden;
  color: var(--workspace-ink);
  background: #fff;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.workspace-sidebar {
  display: flex;
  flex-direction: column;
  flex: 0 0 260px;
  min-width: 0;
  min-height: 0;
  box-sizing: border-box;
  overflow: auto;
  scrollbar-width: thin;
  background: var(--workspace-panel-bg);
  border-right: 1px solid #efefef;
}
.workspace-brand { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex: 0 0 58px; padding: 0 12px 0 26px; }
.workspace-brand-actions { display: flex; align-items: center; flex-shrink: 0; gap: 2px; }
.workspace-primary { display: grid; gap: 12px; flex-shrink: 0; padding: 0 16px; }
.workspace-action {
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  min-height: var(--workspace-row-height);
  padding: 0 12px;
  box-sizing: border-box;
  border: 0;
  border-radius: 9px;
  color: var(--workspace-strong);
  background: transparent;
  font: inherit;
  font-size: 14px;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
  transition: background .15s, color .15s;
}
.workspace-action > .el-icon, .workspace-resource-link > .el-icon { flex: 0 0 17px; font-size: 17px; color: var(--workspace-strong); }
.workspace-action:hover { background: var(--workspace-hover-bg); color: var(--workspace-strong); }
.workspace-action.is-active, .workspace-action[aria-current="page"] { color: var(--workspace-strong); background: var(--workspace-active-bg); font-weight: 500; }
.workspace-heading { display: flex; align-items: center; min-width: 0; }
.workspace-resources { display: grid; gap: 3px; flex-shrink: 0; margin: 4px 16px 0; }
.workspace-history { flex: 1; min-height: 110px; margin: 18px 0 0; overflow: hidden; }
.workspace-footer { display: flex; align-items: center; flex-shrink: 0; min-height: 58px; margin-top: auto; padding-right: 8px; border-top: 1px solid #e9e9e9; box-sizing: border-box; }
.workspace-footer :deep(.account-row) { flex: 1; }
.collapse-button { width: 28px; height: 28px; display: grid; flex: 0 0 28px; place-items: center; border: 0; border-radius: 5px; color: #777b81; background: transparent; cursor: pointer; }
.collapse-button:hover { color: #202329; background: #e4e4e1; }
.collapse-button:focus-visible { outline: 2px solid #858585; outline-offset: -2px; }
.workspace-sidebar.compact { flex-basis: 58px; }
.workspace-sidebar.compact .workspace-brand { flex: 0 0 auto; justify-content: center; padding: 0; border-bottom: 1px solid #e9e9e9; }
.workspace-sidebar.compact .workspace-resources { width: 42px; gap: 2px; margin: 10px auto 0; padding-top: 0; }
.workspace-sidebar.compact .workspace-action { height: 38px; min-height: 38px; justify-content: center; padding: 0; }
.workspace-sidebar.compact .workspace-action > span { display: none; }
.workspace-sidebar.compact .workspace-footer { flex-direction: column-reverse; padding: 4px 0 0; }
.workspace-sidebar.compact .workspace-footer :deep(.account-row) { width: 100%; flex: 0 0 58px; }
.workspace-sidebar.compact .collapse-button { width: 38px; height: 38px; }
.workspace-resource-menu { display: grid; gap: 2px; }
.workspace-resource-link { display: flex; align-items: center; gap: 10px; min-height: 32px; padding: 0 10px; border-radius: 7px; color: #000; font-size: 14px; text-decoration: none; }
.workspace-resource-link:hover { background: #f0f0f0; }
.workspace-resource-link[aria-current="page"] { background: #ebebeb; font-weight: 500; }
.workspace-icon-button { display: grid; place-items: center; flex-shrink: 0; width: 30px; height: 30px; padding: 0; border: 0; border-radius: 8px; color: #444; background: transparent; cursor: pointer; font-size: 17px; }
.workspace-icon-button:hover, .workspace-icon-button.is-active { background: var(--workspace-active-bg); color: #242424; }
.workspace-action:focus-visible, .workspace-icon-button:focus-visible, .workspace-resource-link:focus-visible { outline: 2px solid var(--workspace-focus); outline-offset: -2px; }
.workspace-close { display: none; }
.workspace-content { flex: 1; min-width: 0; min-height: 0; overflow: hidden; background: #fff; }
.workspace-chat { height: 100%; min-height: 0; }
.workspace-resource { height: 100%; overflow: auto; padding: 28px 32px 48px; box-sizing: border-box; }
.workspace-resource.workspace-resource--agent { padding: 0; overflow: hidden; }
.workspace-mobile-header, .workspace-backdrop { display: none; }
@media (max-width: 900px), (hover: none), (pointer: coarse) {
  .workspace-layout { --workspace-row-height: 42px; }
  .workspace-resource-link { min-height: 42px; }
}
@media (max-width: 900px) {
  .workspace-layout { flex-direction: column; }
  .workspace-mobile-header { display: flex; flex: 0 0 48px; align-items: center; gap: 8px; padding: 0 10px; border-bottom: 1px solid var(--workspace-border); font-size: 14px; font-weight: 500; }
  .workspace-sidebar { display: none; position: fixed; inset: 0 auto 0 0; width: min(300px, 86vw); z-index: 1200; box-shadow: 8px 0 32px #0000001a; }
  .workspace-sidebar.mobile-open { display: flex; }
  .workspace-brand { flex-basis: 58px; }
  .workspace-brand-actions .workspace-icon-button { width: 36px; height: 36px; }
  .workspace-close { display: grid; }
  .workspace-backdrop { display: block; position: fixed; inset: 0; z-index: 1150; border: 0; background: #00000040; }
  .workspace-resource { padding: 22px 16px 36px; }
  .workspace-history { margin-top: 22px; }
}
@media (prefers-reduced-motion: reduce) { .workspace-action { transition: none; } }
</style>
