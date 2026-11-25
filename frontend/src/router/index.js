import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AdminLayout from '@/components/AdminLayout.vue'
import PublicLayout from '@/components/PublicLayout.vue'

const routes = [
  // === 独立路由（无布局） ===
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue')
  },
  {
    path: '/share/:token',
    name: 'ConversationShareView',
    component: () => import('@/views/public/ShareView.vue')
  },
  // === 公开路由（无需认证） ===
  {
    path: '/',
    component: PublicLayout,
    children: [
      {
        path: '',
        redirect: '/home'
      },
      {
        path: 'home',
        name: 'PublicHome',
        component: () => import('@/views/public/PublicHome.vue')
      },
      {
        path: 'skills',
        name: 'PublicSkillList',
        component: () => import('@/views/public/PublicSkillList.vue')
      },
      {
        path: 'skills/:id',
        name: 'PublicSkillDetail',
        component: () => import('@/views/public/PublicSkillDetail.vue')
      },
      {
        path: 'mcps',
        name: 'PublicMcpList',
        component: () => import('@/views/public/PublicMcpList.vue')
      },
      {
        path: 'mcps/:id',
        name: 'PublicMcpDetail',
        component: () => import('@/views/public/PublicMcpDetail.vue')
      },
      {
        path: 'prompt-templates',
        name: 'PublicPromptTemplateList',
        component: () => import('@/views/public/PublicPromptTemplateList.vue')
      },
      {
        path: 'prompt-templates/:id',
        name: 'PublicPromptTemplateDetail',
        component: () => import('@/views/public/PublicPromptTemplateDetail.vue')
      }
    ]
  },
  // === 独立工作台（需要认证） ===
  {
    path: '/workspace',
    component: () => import('@/views/admin/WorkspaceLayout.vue'),
    redirect: '/workspace/chat',
    meta: { requiresAuth: true },
    children: [
      {
        path: 'chat',
        name: 'WorkspaceChat',
        component: () => import('@/views/admin/ChatBootstrap.vue'),
      },
      {
        path: 'feedback',
        name: 'WorkspaceFeedback',
        redirect: '/admin/dashboard/personal/feedback',
      },
      ...[
        { path: 'skills', view: 'skills', title: '技能市场' },
        { path: 'prompts', view: 'prompts', title: '提示词库' },
        { path: 'connectors', view: 'mcp', title: '连接器' },
      ].map(({ path, view, title }) => ({
        path,
        name: `Workspace-${path}`,
        component: () => import('@/views/admin/AgentResourceAccess.vue'),
        props: route => {
          const agentId = Number(route.query.agent)
          return {
            workspaceView: view,
            workspaceTitle: title,
            agentId: Number.isSafeInteger(agentId) && agentId > 0 ? agentId : null,
          }
        },
      })),
      {
        path: 'agents/:id(\\d+)',
        component: () => import('@/views/admin/WorkspaceAgentPage.vue'),
        meta: { workbenchExpert: true },
        children: [
          { path: '', name: 'WorkspaceAgentDetail', component: () => import('@/views/admin/AgentDetail.vue') },
          { path: 'open-call', name: 'WorkspaceAgentOpenCall', component: () => import('@/views/admin/AgentOpenCall.vue') },
          { path: 'statistics', name: 'WorkspaceAgentStatistics', component: () => import('@/views/admin/AgentStatistics.vue') },
          { path: 'api-calls', name: 'WorkspaceAgentOpenCalls', component: () => import('@/views/admin/AgentOpenCalls.vue') },
        ],
      },
      {
        path: 'assistant',
        component: () => import('@/views/admin/WorkspaceAgentPage.vue'),
        meta: { workbenchDefault: true },
        children: [
          { path: 'statistics', name: 'WorkspaceAssistantStatistics', component: () => import('@/views/admin/AgentStatistics.vue') },
        ],
      },
    ],
  },
  {
    path: '/admin/chat',
    redirect: '/workspace/chat',
  },
  {
    path: '/admin/workspace/:legacyPath(.*)*',
    redirect: to => ({ path: to.path.slice('/admin'.length), query: to.query, hash: to.hash }),
  },
  // === 管理后台路由（需要认证） ===
  {
    path: '/admin',
    component: AdminLayout,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        redirect: '/admin/skills'
      },
      {
        path: 'assets',
        name: 'AdminAssetCenter',
        redirect: '/workspace/skills',
      },
      {
        path: 'skills',
        name: 'AdminSkillList',
        component: () => import('@/views/admin/AdminSkillList.vue')
      },
      {
        path: 'skills/:id',
        name: 'AdminSkillDetail',
        component: () => import('@/views/admin/AdminSkillDetail.vue')
      },
      {
        path: 'mcp',
        name: 'AdminMcpList',
        component: () => import('@/views/admin/McpList.vue')
      },
      {
        path: 'mcp/:id',
        name: 'AdminMcpDetail',
        component: () => import('@/views/admin/McpDetail.vue')
      },
      {
        path: 'models',
        name: 'AdminModelList',
        component: () => import('@/views/admin/ModelList.vue')
      },
      {
        path: 'models/:id',
        name: 'AdminModelDetail',
        component: () => import('@/views/admin/ModelDetail.vue')
      },
      {
        path: 'prompt-templates',
        name: 'AdminPromptTemplateList',
        component: () => import('@/views/admin/PromptTemplateList.vue')
      },
      {
        path: 'prompt-templates/:id',
        name: 'AdminPromptTemplateDetail',
        component: () => import('@/views/admin/PromptTemplateDetail.vue')
      },
      {
        path: 'agents',
        name: 'AdminAgentList',
        component: () => import('@/views/admin/AgentList.vue'),
      },
      {
        path: 'agents/new',
        name: 'AdminAgentCreate',
        component: () => import('@/views/admin/AgentDetail.vue'),
      },
      {
        path: 'agents/:id',
        component: () => import('@/views/admin/AgentWorkspaceLayout.vue'),
        children: [
          { path: '', name: 'AdminAgentDetail', component: () => import('@/views/admin/AgentDetail.vue') },
          { path: 'open-call', name: 'AdminAgentOpenCall', component: () => import('@/views/admin/AgentOpenCall.vue') },
          { path: 'chat', name: 'AdminAgentChat', redirect: to => ({ path: '/workspace/chat', query: { ...to.query, agent: to.params.id }, hash: to.hash }) },
          { path: 'statistics', name: 'AdminAgentStatistics', component: () => import('@/views/admin/AgentStatistics.vue') },
          { path: 'api-calls', name: 'AdminAgentOpenCalls', component: () => import('@/views/admin/AgentOpenCalls.vue') },
        ],
      },
      {
        path: 'dashboard/personal/credit-usage',
        name: 'AdminPersonalCreditUsage',
        component: () => import('@/views/admin/PersonalCreditUsage.vue'),
      },
      {
        path: 'dashboard/personal/token-usage',
        name: 'AdminPersonalTokenUsage',
        component: () => import('@/views/admin/PersonalTokenUsage.vue')
      },
      {
        path: 'dashboard/personal/feedback',
        name: 'AdminPersonalFeedback',
        component: () => import('@/views/admin/MyFeedback.vue')
      },
      {
        path: 'feedback/:id(\\d+)',
        name: 'FeedbackDetail',
        component: () => import('@/views/admin/FeedbackDetail.vue')
      },
      {
        path: 'dashboard/summary/credit-usage',
        name: 'AdminSummaryCreditUsage',
        component: () => import('@/views/admin/SummaryCreditUsage.vue'),
        meta: { requiresSuperuser: true },
      },
      {
        path: 'dashboard/summary/token-usage',
        name: 'AdminSummaryTokenUsage',
        component: () => import('@/views/admin/SummaryTokenUsage.vue'),
        meta: { requiresSuperuser: true }
      },
      {
        path: 'dashboard/summary/knowledge-usage',
        name: 'AdminSummaryKnowledgeUsage',
        // Opened to configured departments too; the page shows the server's answer when not allowed.
        component: () => import('@/views/admin/SummaryKnowledgeUsage.vue')
      },
      {
        path: 'dashboard/summary/feedback',
        name: 'UserFeedback',
        component: () => import('@/views/admin/UserFeedback.vue'),
        meta: { requiresSuperuser: true },
      },
      // 系统管理
      {
        path: 'global-settings',
        name: 'AdminGlobalSettings',
        component: () => import('@/views/admin/GlobalSettings.vue'),
        meta: { requiresSuperuser: true }
      },
      {
        path: 'knowledge-settings',
        name: 'AdminKnowledgeSettings',
        component: () => import('@/views/admin/KnowledgeSettings.vue'),
        meta: { requiresSuperuser: true }
      },
      {
        path: 'assistant-settings',
        name: 'AdminAssistantSettings',
        component: () => import('@/views/admin/AssistantSettings.vue'),
        meta: { requiresSuperuser: true }
      },
      {
        path: 'workbench-settings',
        name: 'AdminWorkbenchSettings',
        component: () => import('@/views/admin/WorkbenchSettings.vue'),
        meta: { requiresSuperuser: true }
      },
      {
        path: 'system-resources',
        redirect: { path: '/admin/workbench-settings', query: { tab: 'resources' } }
      },
      {
        path: 'users',
        name: 'AdminUserList',
        component: () => import('@/views/admin/UserList.vue'),
        meta: { requiresSuperuser: true }
      },
      {
        path: 'knowledge',
        name: 'AdminKnowledgeManagement',
        component: () => import('@/views/admin/KnowledgeManagement.vue')
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 全局前置守卫
router.beforeEach(async (to, from, next) => {
  if (to.query.tab === 'credits' && [
    '/admin/dashboard/personal/token-usage', '/admin/dashboard/summary/token-usage',
  ].includes(to.path)) {
    const { tab, ...query } = to.query
    next({ path: to.path.replace('/token-usage', '/credit-usage'), query, hash: to.hash, replace: true })
    return
  }
  const authStore = useAuthStore()

  // 已登录时访问登录页，直接进入工作台
  if (to.path === '/login' && authStore.isAuthenticated) {
    next('/workspace/chat')
    return
  }

  // 如果路由需要认证
  if (to.meta.requiresAuth) {
    if (!authStore.isAuthenticated) {
      // 保存原目标路径
      sessionStorage.setItem('auth_redirect', to.fullPath)
      // 跳转到登录页
      next('/login')
      return
    }

    if (!authStore.user) {
      try {
        await authStore.fetchUserInfo()
      } catch (error) {
        console.error('获取用户信息失败:', error)
        if (!authStore.isAuthenticated) {
          next('/login')
          return
        }
      }
    }

    if (to.meta.requiresSuperuser && authStore.user?.is_superuser !== true) {
      next('/admin/dashboard/personal/token-usage')
      return
    }

    if (to.meta.permission && !authStore.hasPermission(to.meta.permission)) {
      next('/admin')
      return
    }
  }

  next()
})

export default router
