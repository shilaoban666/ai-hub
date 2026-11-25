<template>
  <div
    class="app-shell"
    :class="{
      'app-shell--collapsed': effectiveCollapsed,
      'app-shell--workspace': isAgentWorkspace,
    }"
  >
    <button v-if="mainSidebarOpen" class="workspace-backdrop" type="button" aria-label="关闭主菜单" @click="mainSidebarOpen = false" />
    <aside class="product-sidebar" :class="{ compact: effectiveCollapsed, 'mobile-open': mainSidebarOpen }" aria-label="主菜单" @keydown.esc="mainSidebarOpen = false">
      <div class="brand-row">
        <ShellBrand v-if="!effectiveCollapsed" />
        <ProductModeSwitch :compact="effectiveCollapsed" @navigate="mainSidebarOpen = false" />
      </div>

      <div class="navigation-scroll">
        <div id="management-navigation">
          <ManagementNavigation :active-menu="activeMenu" :default-openeds="defaultOpeneds" :collapsed="effectiveCollapsed" />
        </div>
      </div>

      <div class="sidebar-footer">
        <ShellAccount :compact="effectiveCollapsed" :is-mobile-viewport="isMobileViewport" @navigate="mainSidebarOpen = false" />
        <el-tooltip :disabled="isMobileViewport" :enterable="false" :trigger-keys="[]" :content="effectiveCollapsed ? '展开主菜单' : '收起主菜单'" placement="right">
          <button
            class="collapse-button"
            type="button"
            :aria-label="effectiveCollapsed ? '展开主菜单' : '收起主菜单'"
            :aria-expanded="!effectiveCollapsed"
            @click="toggleSidebar"
          >
            <el-icon><Fold v-if="!effectiveCollapsed" /><Expand v-else /></el-icon>
          </button>
        </el-tooltip>
      </div>
    </aside>

    <section class="shell-content" :class="{ 'shell-content--workspace': isAgentWorkspace }">
      <div class="workspace-mobile-nav">
        <el-button :icon="Menu" text aria-label="打开主菜单" :aria-expanded="mainSidebarOpen" @click="mainSidebarOpen = true" />
        <span>AI Hub 管理后台</span>
      </div>
      <router-view />
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Expand, Fold, Menu,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import ShellBrand from './ShellBrand.vue'
import ManagementNavigation from './ManagementNavigation.vue'
import ShellAccount from './ShellAccount.vue'
import ProductModeSwitch from './ProductModeSwitch.vue'

const authStore = useAuthStore()
const appStore = useAppStore()
const route = useRoute()
const mobileViewport = window.matchMedia('(max-width: 900px)')
const isMobileViewport = ref(mobileViewport.matches)
const mainSidebarOpen = ref(false)
const updateMobileViewport = event => {
  isMobileViewport.value = event.matches
  mainSidebarOpen.value = false
}
const isAgentWorkspace = computed(() => route.path.startsWith('/admin/agents/'))
const effectiveCollapsed = computed(() => !isMobileViewport.value && appStore.collapsed)
watch(() => route.path, () => { mainSidebarOpen.value = false })

const activeMenu = computed(() => {
  const mappings = [
    ['/admin/dashboard/summary/token-usage', '/admin/dashboard/summary/token-usage'],
    ['/admin/dashboard/summary/credit-usage', '/admin/dashboard/summary/credit-usage'],
    ['/admin/dashboard/summary/knowledge-usage', '/admin/dashboard/summary/knowledge-usage'],
    ['/admin/dashboard/summary/service', '/admin/dashboard/summary/service'],
    ['/admin/dashboard/summary/feedback', '/admin/dashboard/summary/feedback'],
    ['/admin/dashboard/summary/principal', '/admin/dashboard/summary/principal'],
    ['/admin/dashboard/personal/token-usage', '/admin/dashboard/personal/token-usage'],
    ['/admin/dashboard/personal/credit-usage', '/admin/dashboard/personal/credit-usage'],
    ['/admin/dashboard/personal/feedback', '/admin/dashboard/personal/feedback'],
    // Keep the originating feedback menu selected while viewing details.
    ['/admin/feedback', route.query.from === 'mine' || authStore.user?.is_superuser !== true ? '/admin/dashboard/personal/feedback' : '/admin/dashboard/summary/feedback'],
    ['/admin/global-settings', '/admin/global-settings'], ['/admin/knowledge-settings', '/admin/knowledge-settings'], ['/admin/assistant-settings', '/admin/assistant-settings'], ['/admin/workbench-settings', '/admin/workbench-settings'], ['/admin/services', '/admin/services'],
    ['/admin/endpoints', '/admin/endpoints'], ['/admin/permissions', '/admin/permissions'],
    ['/admin/roles', '/admin/roles'], ['/admin/users', '/admin/users'], ['/admin/clients', '/admin/clients'],
    ['/admin/prompt-templates', '/admin/prompt-templates'],
    ['/admin/skills', '/admin/skills'], ['/admin/mcp', '/admin/mcp'], ['/admin/models', '/admin/models'],
    ['/admin/agents', '/admin/agents'], ['/admin/tokens', '/admin/tokens'],
    ['/admin/knowledge', '/admin/knowledge'],
  ]
  return mappings.find(([prefix]) => route.path.startsWith(prefix))?.[1] || route.path
})
const defaultOpeneds = computed(() => {
  const opened = []
  if (['/admin/dashboard/personal/feedback', '/admin/dashboard/summary/feedback'].includes(activeMenu.value)) opened.push('/admin/feedback')
  if (['/admin/dashboard/personal/credit-usage', '/admin/dashboard/personal/token-usage'].includes(activeMenu.value)) opened.push('/admin/dashboard/personal')
  if (['/admin/dashboard/summary/token-usage', '/admin/dashboard/summary/credit-usage', '/admin/dashboard/summary/knowledge-usage'].includes(route.path)) {
    opened.push('/admin/dashboard/summary/usage')
  } else if (['/admin/dashboard/summary/service', '/admin/dashboard/summary/principal', '/admin/dashboard/summary/xiaoqu'].includes(activeMenu.value)) opened.push('/admin/dashboard/summary')
  if (['/admin/services', '/admin/endpoints'].includes(activeMenu.value)) opened.push('/admin/service-management')
  if (['/admin/global-settings', '/admin/knowledge-settings', '/admin/assistant-settings', '/admin/workbench-settings', '/admin/clients'].includes(activeMenu.value)) opened.push('/admin/system')
  if (['/admin/permissions', '/admin/roles', '/admin/users'].includes(activeMenu.value)) opened.push('/admin/access-control')
  return opened
})

onMounted(() => mobileViewport.addEventListener('change', updateMobileViewport))
onBeforeUnmount(() => mobileViewport.removeEventListener('change', updateMobileViewport))
const toggleSidebar = () => {
  if (isMobileViewport.value) { mainSidebarOpen.value = false; return }
  appStore.toggleSidebar()
}
</script>

<style scoped>
.app-shell { --sidebar-width: 260px; --shell-accent: #292d33; --shell-accent-soft: #ebebeb; width: 100%; height: 100vh; display: grid; grid-template-columns: var(--sidebar-width) minmax(0, 1fr); overflow: hidden; color: #202329; background: #f7f7f6; }
.app-shell--collapsed { --sidebar-width: 58px; }
.app-shell--workspace { --workspace-rail-bg: #f7f7f7; }
.product-sidebar { min-width: 0; display: flex; flex-direction: column; overflow: hidden; border-right: 1px solid #efefef; background: #f7f7f7; box-sizing: border-box; }
.app-shell--workspace .product-sidebar { border-right-color: var(--workspace-border); background: var(--workspace-rail-bg); }
.product-sidebar.compact { width: 58px; }
.brand-row { height: 58px; display: flex; flex: 0 0 58px; align-items: center; justify-content: space-between; gap: 8px; padding: 0 12px 0 26px; box-sizing: border-box; }
.collapse-button { width: 28px; height: 28px; display: grid; flex: 0 0 28px; place-items: center; border: 0; border-radius: 5px; color: #777b81; background: transparent; cursor: pointer; }
.collapse-button:hover { color: #202329; background: #e4e4e1; }
.sidebar-footer { display: flex; align-items: center; flex-shrink: 0; min-height: 58px; padding-right: 8px; border-top: 1px solid #e9e9e9; box-sizing: border-box; }
.sidebar-footer :deep(.account-row) { flex: 1; }
.product-sidebar.compact .sidebar-footer { flex-direction: column-reverse; padding: 4px 0 0; }
.product-sidebar.compact .sidebar-footer :deep(.account-row) { width: 100%; flex: 0 0 58px; }
.collapse-button:focus-visible { outline: 2px solid #858585; outline-offset: -2px; }
.navigation-scroll { min-height: 0; flex: 1; overflow-x: hidden; overflow-y: auto; padding-bottom: 10px; }
.nav-label { display: block; padding: 13px 17px 5px; color: #96999d; font-size: 10px; font-weight: 650; text-transform: uppercase; }
.product-sidebar :deep(.el-menu) { width: 100%; border: 0; background: transparent; }
.product-sidebar :deep(.el-menu-item), .product-sidebar :deep(.el-sub-menu__title) { height: 38px; margin: 1px 16px; padding: 0 10px !important; border-radius: 6px; color: #555a61; line-height: 38px; }
.product-sidebar:not(.compact) :deep(.el-sub-menu .el-menu-item) { padding-left: 37px !important; }
.product-sidebar :deep(.el-menu-item:hover), .product-sidebar :deep(.el-sub-menu__title:hover) { color: #23262b; background: #f1f2f4; }
.product-sidebar :deep(.el-menu-item.is-active) { color: var(--shell-accent); background: var(--shell-accent-soft); font-weight: 600; }
.product-sidebar :deep(.el-menu-item .el-icon), .product-sidebar :deep(.el-sub-menu__title .el-icon:not(.el-sub-menu__icon-arrow)) { color: inherit; font-size: 17px; }
.product-sidebar.compact .brand-row { height: auto; flex: 0 0 auto; justify-content: center; padding: 0; border-bottom: 1px solid #e9e9e9; }
.product-sidebar.compact .nav-label { display: none; }
.product-sidebar.compact .collapse-button { width: 38px; height: 38px; }
.product-sidebar.compact :deep(.management-navigation), .product-sidebar.compact :deep(.el-menu--collapse) { display: flex; flex-direction: column; gap: 2px; width: 100%; }
.product-sidebar.compact :deep(.el-menu-item), .product-sidebar.compact :deep(.el-sub-menu__title) { width: 42px; justify-content: center; margin: 0 auto; padding: 0 !important; box-sizing: border-box; }
.app-shell--workspace .product-sidebar.compact :deep(.el-menu-item:hover), .app-shell--workspace .product-sidebar.compact :deep(.el-sub-menu__title:hover) { background: var(--workspace-hover-bg); }
.app-shell--workspace .product-sidebar.compact :deep(.el-menu-item.is-active) { color: #25282d; background: var(--workspace-active-bg); }
.product-sidebar.compact :deep(.el-menu-item .el-menu-tooltip__trigger) { width: 100%; justify-content: center; padding: 0 !important; }
.product-sidebar.compact :deep(.el-menu-item .el-icon), .product-sidebar.compact :deep(.el-sub-menu__title .el-icon) { margin: 0 !important; }
.shell-content { min-width: 0; min-height: 0; overflow: auto; padding: 32px 36px 48px; background: #fafafa; box-sizing: border-box; }
.shell-content--workspace { overflow: hidden; padding: 0; background: #fff; }
.app-shell--workspace { --shell-accent: #292d33; --shell-accent-soft: #e9ebee; --workspace-panel-bg: #f7f8fa; --workspace-border: #eceef1; --workspace-control-bg: #eceef2; --workspace-hover-bg: #eceef2; --workspace-active-bg: #e4e7ec; }
#management-navigation { margin-top: 6px; }
.product-sidebar.compact #management-navigation { margin-top: 10px; }
.workspace-mobile-nav, .workspace-backdrop { display: none; }
@media (max-width: 860px) {
  .app-shell, .app-shell--workspace { display: block; }
  .product-sidebar { display: none; }
  .shell-content { width: 100%; height: 100vh; padding: 22px 16px 36px; }
  .shell-content--workspace { padding: 0; }
}
@media (max-width: 900px) {
  .app-shell { display: block; }
  .shell-content { display: flex; flex-direction: column; width: 100%; height: 100dvh; }
  .shell-content--workspace > :last-child { flex: 1; min-height: 0; height: auto; }
  .product-sidebar { display: none; position: fixed; inset: 0 auto 0 0; width: min(300px, 86vw); z-index: 1400; box-shadow: 4px 0 20px #20232918; }
  .product-sidebar.mobile-open { display: flex; }
  .workspace-mobile-nav { display: flex; align-items: center; gap: 8px; min-height: 44px; flex: 0 0 44px; font-size: 13px; background: #fff; border-bottom: 1px solid #eceef1; }
  .workspace-mobile-nav .el-button { width: 36px; height: 36px; margin: 0 0 0 4px; padding: 0; }
  .workspace-backdrop { display: block; position: fixed; inset: 0; z-index: 1350; border: 0; background: #20232955; }
}
</style>
