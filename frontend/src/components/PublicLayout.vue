<template>
  <div class="public-layout">
    <header class="public-header">
      <div class="header-inner">
        <router-link to="/home" class="header-logo" aria-label="AI Hub 首页">
          <span class="logo-mark" aria-hidden="true"><span></span></span>
          <span class="brand-full">AI Hub</span>
          <span class="brand-short">AI Hub</span>
        </router-link>

        <nav class="header-nav" aria-label="公共导航">
          <router-link
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            :class="{ active: isActive(item.to) }"
          >
            {{ item.label }}
          </router-link>
        </nav>

        <div class="header-actions">
          <router-link :to="workspaceLink" class="workspace-link">
            {{ workspaceLabel }}
          </router-link>
          <button
            type="button"
            class="menu-button"
            :aria-expanded="mobileMenuOpen"
            aria-controls="mobile-navigation"
            :aria-label="mobileMenuOpen ? '关闭导航菜单' : '打开导航菜单'"
            :title="mobileMenuOpen ? '关闭导航菜单' : '打开导航菜单'"
            @click="mobileMenuOpen = !mobileMenuOpen"
          >
            <el-icon><Close v-if="mobileMenuOpen" /><Menu v-else /></el-icon>
          </button>
        </div>
      </div>

      <transition name="mobile-nav">
        <nav v-if="mobileMenuOpen" id="mobile-navigation" class="mobile-navigation" aria-label="移动端导航">
          <router-link
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="mobile-nav-item"
            :class="{ active: isActive(item.to) }"
            @click="mobileMenuOpen = false"
          >
            <span>{{ item.label }}</span>
            <el-icon><ArrowRight /></el-icon>
          </router-link>
        </nav>
      </transition>
    </header>

    <main class="public-content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight, Close, Menu } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const authStore = useAuthStore()
const mobileMenuOpen = ref(false)

const navItems = [
  { to: '/home', label: '首页' },
  { to: '/skills', label: '技能中心' },
  { to: '/mcps', label: 'MCP 服务' },
  { to: '/prompt-templates', label: '提示词模板' },
]

const isActive = (path) => route.path.startsWith(path)
const workspaceLink = computed(() => (authStore.isAuthenticated ? '/workspace/chat' : '/login'))
const workspaceLabel = '进入工作台'

watch(
  () => route.path,
  () => {
    mobileMenuOpen.value = false
  }
)
</script>

<style scoped>
.public-layout {
  --brand-50: #eff6ff;
  --brand-100: #dbeafe;
  --brand-200: #bfdbfe;
  --brand-300: #93c5fd;
  --brand-400: #60a5fa;
  --brand-500: #3b82f6;
  --brand-600: #2563eb;
  --brand-700: #1d4ed8;
  --brand-800: #1e40af;
  --brand-900: #1e3a8a;
  --ink: #1e293b;
  --ink-soft: #64748b;
  --ink-faint: #94a3b8;
  --bg: #f8fafc;
  --card: #ffffff;
  --border: #e2e8f0;
  --border-soft: #f1f5f9;
  --shadow: 0 10px 30px rgba(37, 99, 235, 0.1);
  --shadow-hover: 0 16px 36px rgba(37, 99, 235, 0.18);

  --el-color-primary: var(--brand-600);
  --el-color-primary-light-3: var(--brand-400);
  --el-color-primary-light-5: var(--brand-300);
  --el-color-primary-light-7: var(--brand-200);
  --el-color-primary-light-8: var(--brand-100);
  --el-color-primary-light-9: var(--brand-50);
  --el-color-primary-dark-2: var(--brand-700);
  --el-color-success: #8fdcc0;
  --el-color-success-light-9: #eafaf3;
  --el-border-radius-base: 8px;
  --el-border-radius-small: 6px;
  --el-card-border-radius: 8px;
  --el-card-border-color: var(--border-soft);
  --el-font-family: "Quicksand", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;

  min-height: 100vh;
  display: flex;
  flex-direction: column;
  color: var(--ink);
  background: var(--bg);
  font-family: var(--el-font-family);
}

.public-header {
  position: sticky;
  top: 0;
  z-index: 50;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.header-inner {
  width: min(1440px, 100%);
  height: 60px;
  margin: 0 auto;
  padding: 0 24px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  box-sizing: border-box;
}

.header-logo {
  width: fit-content;
  display: inline-flex;
  align-items: center;
  color: var(--ink);
  font-size: 18px;
  font-weight: 800;
  text-decoration: none;
}

.brand-short {
  display: none;
}

.logo-mark {
  width: 28px;
  height: 28px;
  margin-right: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  background: var(--brand-600);
  border-radius: 8px;
  box-shadow: 0 5px 12px rgba(37, 99, 235, 0.25);
}

.logo-mark span {
  width: 9px;
  height: 9px;
  background: #fff;
  border-radius: 3px;
  box-shadow: 7px 0 0 rgba(255, 255, 255, 0.45), 0 7px 0 rgba(255, 255, 255, 0.45);
}

.header-nav {
  display: flex;
  align-items: center;
  gap: 2px;
}

.nav-item {
  position: relative;
  padding: 20px 14px 18px;
  color: var(--ink-soft);
  font-size: 14px;
  font-weight: 650;
  text-decoration: none;
  transition: color 0.2s;
}

.nav-item::after {
  content: '';
  position: absolute;
  right: 14px;
  bottom: -1px;
  left: 14px;
  height: 2px;
  background: var(--brand-600);
  transform: scaleX(0);
  transition: transform 0.2s;
}

.nav-item:hover,
.nav-item.active {
  color: var(--brand-600);
}

.nav-item.active::after {
  transform: scaleX(1);
}

.header-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.workspace-link {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  padding: 0 14px;
  color: #fff;
  background: var(--brand-600);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
  transition: background-color 0.2s, transform 0.2s;
}

.workspace-link:hover {
  background: var(--brand-700);
  transform: translateY(-1px);
}

.menu-button {
  width: 38px;
  height: 38px;
  display: none;
  align-items: center;
  justify-content: center;
  padding: 0;
  color: var(--ink);
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  font-size: 20px;
}

.mobile-navigation {
  position: absolute;
  top: 60px;
  right: 0;
  left: 0;
  padding: 8px 16px 16px;
  background: #fff;
  border-bottom: 1px solid var(--border);
  box-shadow: 0 18px 30px rgba(15, 23, 42, 0.1);
}

.mobile-nav-item {
  min-height: 46px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  color: var(--ink-soft);
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  text-decoration: none;
}

.mobile-nav-item:hover,
.mobile-nav-item.active {
  color: var(--brand-600);
  background: var(--brand-50);
}

.mobile-nav-enter-active,
.mobile-nav-leave-active {
  transition: opacity 0.16s, transform 0.16s;
  transform-origin: top;
}

.mobile-nav-enter-from,
.mobile-nav-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.public-content {
  flex: 1;
  padding: 24px;
}

@media (max-width: 900px) {
  .header-inner {
    grid-template-columns: 1fr auto;
  }

  .header-nav {
    display: none;
  }

  .menu-button {
    display: inline-flex;
  }
}

@media (max-width: 760px) {
  .header-inner {
    padding: 0 16px;
  }

  .public-content {
    padding: 16px;
  }
}

@media (max-width: 430px) {
  .brand-full {
    display: none;
  }

  .brand-short {
    display: inline;
  }

  .workspace-link {
    padding: 0 11px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .nav-item::after,
  .workspace-link,
  .mobile-nav-enter-active,
  .mobile-nav-leave-active {
    transition: none;
  }
}
</style>
