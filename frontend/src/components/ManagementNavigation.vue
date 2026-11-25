<template>
  <div class="management-navigation" :class="{ compact: collapsed }" aria-label="管理导航">
    <span class="nav-label">个人资源管理</span>
    <el-menu :default-active="activeMenu" :collapse="collapsed" :collapse-transition="false" router @select="$emit('navigate')">
      <el-menu-item index="/admin/skills"><el-icon><SkillIcon /></el-icon><template #title>技能管理</template></el-menu-item>
      <el-menu-item index="/admin/mcp"><el-icon><Connection /></el-icon><template #title>MCP 管理</template></el-menu-item>
      <el-menu-item index="/admin/prompt-templates"><el-icon><ChatDotSquare /></el-icon><template #title>提示词管理</template></el-menu-item>
      <el-menu-item index="/admin/agents"><el-icon><ExpertIcon /></el-icon><template #title>自定义 Agent</template></el-menu-item>
      <el-menu-item index="/admin/models"><el-icon><Box /></el-icon><template #title>自定义模型</template></el-menu-item>
      <el-menu-item index="/admin/knowledge"><el-icon><Collection /></el-icon><template #title>知识库管理</template></el-menu-item>
    </el-menu>
    <span class="nav-label">统计与看板</span>
    <el-menu :default-active="activeMenu" :default-openeds="defaultOpeneds" :collapse="collapsed" :collapse-transition="false" router @select="$emit('navigate')">
      <el-sub-menu index="/admin/dashboard/personal">
        <template #title><el-icon><TrendCharts /></el-icon><span>我的用量</span></template>
        <el-menu-item index="/admin/dashboard/personal/credit-usage">积分用量</el-menu-item>
        <el-menu-item index="/admin/dashboard/personal/token-usage"><span class="usage-menu-label">Token 用量（sub2api）</span></el-menu-item>
      </el-sub-menu>
      <el-sub-menu v-if="authStore.user?.is_superuser === true" index="/admin/dashboard/summary/usage">
        <template #title><el-icon><TrendCharts /></el-icon><span>全局用量</span></template>
        <el-menu-item index="/admin/dashboard/summary/credit-usage">积分用量</el-menu-item>
        <el-menu-item index="/admin/dashboard/summary/token-usage"><span class="usage-menu-label">Token 用量（sub2api）</span></el-menu-item>
        <el-menu-item index="/admin/dashboard/summary/knowledge-usage">知识库调用用量</el-menu-item>
      </el-sub-menu>
      <el-menu-item v-if="authStore.user?.is_superuser !== true && knowledgeAccess.can_view_usage" index="/admin/dashboard/summary/knowledge-usage">
        <el-icon><TrendCharts /></el-icon><template #title>知识库调用用量</template>
      </el-menu-item>
      <el-sub-menu index="/admin/feedback">
        <template #title><el-icon><ChatDotSquare /></el-icon><span>用户反馈</span></template>
        <el-menu-item index="/admin/dashboard/personal/feedback">我的反馈</el-menu-item>
        <el-menu-item v-if="authStore.user?.is_superuser === true" index="/admin/dashboard/summary/feedback">所有反馈</el-menu-item>
      </el-sub-menu>
    </el-menu>
    <span v-if="authStore.user?.is_superuser === true" class="nav-label">配置与管理</span>
    <el-menu v-if="authStore.user?.is_superuser === true" :default-active="activeMenu" :default-openeds="defaultOpeneds" :collapse="collapsed" :collapse-transition="false" router @select="$emit('navigate')">
      <el-menu-item index="/admin/users"><el-icon><Lock /></el-icon><template #title>用户管理</template></el-menu-item>
      <el-sub-menu index="/admin/system">
        <template #title><el-icon><Setting /></el-icon><span>系统设置</span></template>
        <el-menu-item index="/admin/global-settings">全局设置</el-menu-item>
        <el-menu-item index="/admin/knowledge-settings">知识库设置</el-menu-item>
        <el-menu-item index="/admin/assistant-settings">智能体设置</el-menu-item>
        <el-menu-item index="/admin/workbench-settings">默认助手设置</el-menu-item>
      </el-sub-menu>
    </el-menu>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Box, ChatDotSquare, Collection, Connection, DataAnalysis, Key, Lock, Setting, SetUp, TrendCharts } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { knowledgeApi } from '@/api/knowledge'
import ExpertIcon from '@/components/icons/ExpertIcon.vue'
import SkillIcon from '@/components/icons/SkillIcon.vue'

defineProps({
  collapsed: { type: Boolean, default: false },
  activeMenu: { type: String, default: '' },
  defaultOpeneds: { type: Array, default: () => [] },
})
defineEmits(['navigate'])
const authStore = useAuthStore()
// Department access to the knowledge usage board (superusers see it under 全局用量).
const knowledgeAccess = ref({})
onMounted(async () => {
  if (authStore.user?.is_superuser === true) return
  try { knowledgeAccess.value = await knowledgeApi.getAccess() } catch { knowledgeAccess.value = {} }
})
const showPermissionMenu = computed(() => (
  authStore.hasPermission('auth:permission:view') ||
  authStore.hasPermission('auth:role:view') ||
  authStore.hasPermission('auth:user:view')
))
</script>

<style scoped>
.nav-label { display: block; padding: 13px 17px 5px 26px; color: #96999d; font-size: 10px; font-weight: 650; }
.compact .nav-label { display: none; }
.usage-menu-label { white-space: normal; line-height: 17px; font-size: 13px; overflow-wrap: anywhere; }
.management-navigation :deep(.el-menu) { width: 100%; border: 0; background: transparent; }
.management-navigation :deep(.el-menu-item), .management-navigation :deep(.el-sub-menu__title) { height: 38px; margin: 1px 16px; padding: 0 10px !important; border-radius: 6px; color: #555a61; line-height: 38px; }
.management-navigation:not(.compact) :deep(.el-sub-menu .el-menu-item) { padding-left: 37px !important; }
.management-navigation :deep(.el-menu-item:hover), .management-navigation :deep(.el-sub-menu__title:hover) { color: #23262b; background: #f1f2f4; }
.management-navigation :deep(.el-menu-item.is-active),
.management-navigation.compact :deep(.el-sub-menu.is-active > .el-sub-menu__title) { color: var(--shell-accent, #292d33); background: var(--shell-accent-soft, #ebebeb); font-weight: 600; }
.management-navigation :deep(.el-menu-item .el-icon), .management-navigation :deep(.el-sub-menu__title .el-icon:not(.el-sub-menu__icon-arrow)) { color: inherit; font-size: 17px; }
</style>
