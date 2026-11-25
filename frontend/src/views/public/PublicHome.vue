<template>
  <div class="home">
    <section class="hero">
      <div class="hero-inner">
        <h1>AI Hub</h1>
        <p class="hero-title">把分散的 AI 能力，组合成你自己的智能体</p>
        <p class="hero-description">
          Skills、MCP、提示词、模型与 Runtime，在一个工作台统一配置与使用。
        </p>

        <div class="hero-actions">
          <a href="#resources" class="button button-secondary">
            探索公开资源
            <el-icon><ArrowDown /></el-icon>
          </a>
          <router-link to="/admin/agents/new" class="button button-primary">构建智能体</router-link>
        </div>

      </div>
    </section>

    <section id="resources" class="section resource-section">
      <div class="section-heading">
        <div>
          <span class="section-kicker">公开资源</span>
          <h2>从真实能力开始探索</h2>
          <p>查看团队已经沉淀的能力，找到合适的内容后再进入工作台组合使用。</p>
        </div>
        <router-link :to="activeResourceConfig.to" class="text-link">
          查看全部{{ activeResourceConfig.label }}
          <el-icon><ArrowRight /></el-icon>
        </router-link>
      </div>

      <div class="resource-tabs" role="tablist" aria-label="资源类型">
        <button
          v-for="resource in resourceConfigs"
          :id="`resource-tab-${resource.key}`"
          :key="resource.key"
          type="button"
          role="tab"
          :aria-selected="activeResource === resource.key"
          :aria-controls="`resource-panel-${resource.key}`"
          :class="['resource-tab', { active: activeResource === resource.key }]"
          :style="{ '--resource-accent': resource.accent, '--resource-soft': resource.soft }"
          @click="activeResource = resource.key"
        >
          <el-icon><component :is="resource.icon" /></el-icon>
          <span>{{ resource.label }}</span>
          <b>{{ resourcesLoading ? '--' : resourceTotals[resource.key] }}</b>
        </button>
      </div>

      <div
        :id="`resource-panel-${activeResource}`"
        class="resource-panel"
        role="tabpanel"
        :aria-labelledby="`resource-tab-${activeResource}`"
      >
        <div v-if="resourcesLoading" class="resource-grid" aria-label="资源加载中">
          <div v-for="index in 3" :key="index" class="resource-card skeleton-card">
            <span class="skeleton skeleton-icon"></span>
            <span class="skeleton skeleton-title"></span>
            <span class="skeleton skeleton-copy"></span>
            <span class="skeleton skeleton-copy short"></span>
          </div>
        </div>

        <div v-else-if="activeResourceItems.length" class="resource-grid">
          <router-link
            v-for="item in activeResourceItems"
            :key="item.id"
            :to="`${activeResourceConfig.to}/${item.id}`"
            class="resource-card"
            :style="{
              '--resource-accent': activeResourceConfig.accent,
              '--resource-soft': activeResourceConfig.soft,
            }"
          >
            <div class="resource-card-head">
              <span class="resource-card-icon">
                <el-icon><component :is="activeResourceConfig.icon" /></el-icon>
              </span>
              <span class="resource-type">{{ activeResourceConfig.singular }}</span>
              <el-icon class="resource-arrow"><TopRight /></el-icon>
            </div>
            <h3>{{ item.name }}</h3>
            <p>{{ resourceDescription(item) }}</p>
            <div class="resource-meta">
              <span>{{ item.author || '匿名' }}</span>
              <SkillMetadataTags v-if="activeResource === 'skills' && item.module" :model-value="item.module" />
              <span v-else>{{ resourceMeta(item) }}</span>
            </div>
          </router-link>
        </div>

        <div v-else class="resource-empty">
          <el-icon><Box /></el-icon>
          <p>暂时还没有公开的{{ activeResourceConfig.label }}</p>
        </div>
      </div>
    </section>

    <section id="build" class="build-band">
      <div class="section build-layout">
        <div class="build-copy">
          <span class="section-kicker">构建智能体</span>
          <h2>从配置到使用，一条清晰路径</h2>
          <p class="build-intro">
            不需要在多个系统间来回切换。选定运行环境后，把已有能力组合起来，边对话边验证，最后在自己的场景中持续使用。
          </p>

          <ol class="build-steps">
            <li v-for="(step, index) in buildSteps" :key="step.title">
              <span class="step-number">{{ index + 1 }}</span>
              <div>
                <h3>{{ step.title }}</h3>
                <p>{{ step.description }}</p>
              </div>
            </li>
          </ol>
        </div>

        <div class="orchestration" aria-label="智能体能力编排示意">
          <div class="orchestration-label">能力输入</div>
          <div class="orchestration-inputs">
            <div v-for="item in orchestrationInputs" :key="item.label" class="orchestration-node">
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </div>
          </div>

          <div class="orchestration-connector" aria-hidden="true">
            <span></span>
            <el-icon><ArrowDown /></el-icon>
          </div>

          <div class="agent-core">
            <div class="agent-core-icon"><el-icon><Cpu /></el-icon></div>
            <div>
              <strong>智能体工作台</strong>
              <span>身份 · 模型 · Runtime · 能力编排</span>
            </div>
          </div>

          <div class="orchestration-connector" aria-hidden="true">
            <span></span>
            <el-icon><ArrowDown /></el-icon>
          </div>

          <div class="orchestration-outputs">
            <span><el-icon><ChatDotRound /></el-icon>对话调试</span>
            <span><el-icon><Link /></el-icon>个人渠道</span>
            <span><el-icon><DataAnalysis /></el-icon>用量追踪</span>
          </div>
        </div>
      </div>
    </section>

    <section class="section trust-section">
      <div class="section-heading trust-heading">
        <div>
          <span class="section-kicker">平台保障</span>
          <h2>日常使用需要的可靠性，已经融入流程</h2>
        </div>
      </div>

      <div class="trust-grid">
        <article v-for="item in trustItems" :key="item.title" class="trust-item">
          <el-icon><component :is="item.icon" /></el-icon>
          <div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.description }}</p>
          </div>
        </article>
      </div>
    </section>

    <section class="cta-band">
      <div class="cta-inner">
        <div>
          <span class="cta-kicker">开始构建</span>
          <h2>把下一项 AI 能力，沉淀成团队可以复用的资产</h2>
          <p>直接创建智能体，或先浏览已有资源寻找灵感。</p>
        </div>
        <div class="cta-actions">
          <router-link to="/admin/agents/new" class="button button-light">
            创建智能体
            <el-icon><ArrowRight /></el-icon>
          </router-link>
          <router-link to="/skills" class="button button-dark-ghost">浏览技能中心</router-link>
        </div>
      </div>
    </section>

    <footer class="home-footer">
      <span>AI Hub</span>
      <span>AI 能力整合平台</span>
    </footer>
  </div>
</template>

<script setup>
import SkillMetadataTags from '@/components/SkillMetadataTags.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ArrowDown,
  ArrowRight,
  Box,
  ChatDotRound,
  Connection,
  Cpu,
  DataAnalysis,
  Document,
  Lock,
  Operation,
  Link,
  Refresh,
  Setting,
  TopRight,
} from '@element-plus/icons-vue'
import { publicSkillsApi } from '@/api/skills'
import SkillIcon from '@/components/icons/SkillIcon.vue'
import { publicMcpsApi } from '@/api/mcps'
import { publicPromptTemplatesApi } from '@/api/prompt-templates'

const resourceConfigs = [
  {
    key: 'skills',
    label: '技能',
    singular: 'SKILL.md',
    to: '/skills',
    icon: SkillIcon,
    accent: 'var(--brand-600)',
    soft: 'var(--brand-50)',
  },
  {
    key: 'mcps',
    label: 'MCP 服务',
    singular: 'MCP',
    to: '/mcps',
    icon: Connection,
    accent: '#0e7490',
    soft: '#ecfeff',
  },
  {
    key: 'templates',
    label: '提示词模板',
    singular: 'Prompt',
    to: '/prompt-templates',
    icon: Document,
    accent: '#be185d',
    soft: '#fdf2f8',
  },
]

const activeResource = ref('skills')
const resourcesLoading = ref(true)
const resourceGroups = reactive({ skills: [], mcps: [], templates: [] })
const resourceTotals = reactive({ skills: 0, mcps: 0, templates: 0 })

const activeResourceConfig = computed(
  () => resourceConfigs.find((resource) => resource.key === activeResource.value) || resourceConfigs[0]
)
const activeResourceItems = computed(() => resourceGroups[activeResource.value].slice(0, 3))

const orchestrationInputs = [
  { label: '模型', icon: Cpu },
  { label: 'Skills', icon: SkillIcon },
  { label: 'MCP', icon: Connection },
  { label: '提示词', icon: Document },
  { label: 'Runtime', icon: Setting },
  { label: '用量策略', icon: DataAnalysis },
]

const buildSteps = [
  { title: '创建智能体', description: '选择模型与 Runtime，设置清晰的身份和目标。' },
  { title: '绑定能力', description: '组合 Skills、MCP 和提示词模板，不重复造轮子。' },
  { title: '对话调试', description: '观察流式响应与工具调用，快速定位和修正问题。' },
  { title: '个人使用', description: '保存配置并按需绑定自己的渠道，智能体仅供创建者使用。' },
]

const trustItems = [
  { icon: Lock, title: '安全登录', description: '统一认证与权限校验，资源归属清晰。' },
  { icon: Refresh, title: 'Git 双向同步', description: '对接 GitLab 与 GitHub，保留团队原有协作方式。' },
  { icon: DataAnalysis, title: '用量透明', description: '个人与全局 Token 用量可追踪、可分析。' },
  { icon: Operation, title: '版本可控', description: '技能版本历史与软删除机制，调整和试错更安心。' },
]

const cleanText = (value) => {
  if (!value) return ''
  const text = String(value).replace(/\s+/g, ' ').trim()
  return ['|', '-', '无'].includes(text) ? '' : text
}

const resourceDescription = (item) => {
  const description = cleanText(item.description)
  const text = description || (activeResource.value === 'templates' ? cleanText(item.content) : '')
  if (!text) return '查看详情了解这项能力的配置和使用方式。'
  return text.length > 108 ? `${text.slice(0, 108)}...` : text
}

const resourceMeta = (item) => {
  if (activeResource.value === 'skills') return item.version || '通用能力'
  if (activeResource.value === 'mcps') {
    const typeMap = { stdio: 'STDIO', sse: 'SSE', streamable_http: 'HTTP', json: 'JSON' }
    return typeMap[item.type] || item.type || '工具服务'
  }
  return item.category || '通用模板'
}

const fetchResources = async () => {
  resourcesLoading.value = true
  const requests = [
    publicSkillsApi.getList({ skip: 0, limit: 3 }),
    publicMcpsApi.getList({ skip: 0, limit: 3 }),
    publicPromptTemplatesApi.getList({ skip: 0, limit: 3 }),
  ]

  const results = await Promise.allSettled(requests)
  const keys = ['skills', 'mcps', 'templates']
  results.forEach((result, index) => {
    const key = keys[index]
    if (result.status === 'fulfilled') {
      resourceGroups[key] = result.value?.items || []
      resourceTotals[key] = result.value?.total || 0
    }
  })
  resourcesLoading.value = false
}

onMounted(fetchResources)
</script>

<style scoped>
.home {
  margin: -24px;
  overflow: hidden;
  color: var(--ink);
  background: var(--bg);
}

.section {
  width: min(1180px, calc(100% - 48px));
  margin: 0 auto;
  padding: 76px 0;
}

.hero {
  position: relative;
  min-height: min(680px, calc(100vh - 96px));
  min-height: min(680px, calc(100svh - 96px));
  display: flex;
  align-items: center;
  background-color: #f8fafc;
  border-bottom: 1px solid var(--border);
}

.hero-inner {
  position: relative;
  width: min(980px, calc(100% - 48px));
  margin: 0 auto;
  padding: 72px 0 48px;
  text-align: center;
}

.section-kicker,
.cta-kicker {
  display: inline-block;
  color: var(--brand-600);
  font-size: 13px;
  font-weight: 800;
}

.hero h1 {
  margin: 0 0 18px;
  font-size: 64px;
  line-height: 1.04;
  font-weight: 850;
  letter-spacing: 0;
  color: #111827;
}

.hero-title {
  margin: 0;
  color: var(--brand-800);
  font-size: 25px;
  line-height: 1.45;
  font-weight: 750;
}

.hero-description {
  max-width: 660px;
  margin: 18px auto 0;
  color: var(--ink-soft);
  font-size: 16px;
  line-height: 1.8;
}

.hero-actions,
.cta-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
}

.hero-actions {
  margin-top: 34px;
}

.button {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 20px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: inherit;
  font-size: 15px;
  font-weight: 700;
  text-decoration: none;
  transition: transform 0.2s, border-color 0.2s, background-color 0.2s, box-shadow 0.2s;
}

.button:hover {
  transform: translateY(-2px);
}

.button-primary {
  color: #fff;
  background: var(--brand-600);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.24);
}

.button-primary:hover {
  background: var(--brand-700);
  box-shadow: 0 14px 28px rgba(37, 99, 235, 0.3);
}

.button-secondary {
  color: var(--ink);
  background: rgba(255, 255, 255, 0.9);
  border-color: var(--border);
}

.button-secondary:hover {
  color: var(--brand-600);
  border-color: var(--brand-300);
}

.section-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 32px;
  margin-bottom: 30px;
}

.section-heading h2,
.build-copy h2,
.cta-inner h2 {
  margin: 9px 0 0;
  color: #111827;
  font-size: 32px;
  line-height: 1.28;
  font-weight: 800;
  letter-spacing: 0;
}

.section-heading p {
  max-width: 690px;
  margin: 10px 0 0;
  color: var(--ink-soft);
  font-size: 15px;
  line-height: 1.7;
}

.text-link {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--brand-600);
  font-size: 14px;
  font-weight: 700;
  text-decoration: none;
}

.text-link:hover {
  color: var(--brand-700);
}

.resource-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 22px;
  overflow-x: auto;
  scrollbar-width: none;
}

.resource-tabs::-webkit-scrollbar {
  display: none;
}

.resource-tab {
  min-height: 42px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  color: var(--ink-soft);
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  font: inherit;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: color 0.2s, background-color 0.2s, border-color 0.2s;
}

.resource-tab b {
  min-width: 24px;
  padding: 2px 6px;
  color: var(--ink-soft);
  background: var(--border-soft);
  border-radius: 4px;
  font-size: 12px;
  text-align: center;
}

.resource-tab:hover,
.resource-tab.active {
  color: var(--resource-accent);
  background: var(--resource-soft);
  border-color: color-mix(in srgb, var(--resource-accent) 32%, white);
}

.resource-tab.active b {
  color: #fff;
  background: var(--resource-accent);
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.resource-card {
  min-height: 240px;
  display: flex;
  flex-direction: column;
  padding: 22px;
  color: inherit;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  text-decoration: none;
  transition: transform 0.22s, border-color 0.22s, box-shadow 0.22s;
}

.resource-card:hover {
  transform: translateY(-4px);
  border-color: color-mix(in srgb, var(--resource-accent) 38%, white);
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
}

.resource-card-head {
  display: flex;
  align-items: center;
}

.resource-card-icon {
  width: 38px;
  height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--resource-accent);
  background: var(--resource-soft);
  border-radius: 8px;
  font-size: 20px;
}

.resource-type {
  margin-left: 10px;
  color: var(--resource-accent);
  font-size: 12px;
  font-weight: 750;
}

.resource-arrow {
  margin-left: auto;
  color: #94a3b8;
  font-size: 17px;
}

.resource-card h3 {
  margin: 20px 0 9px;
  overflow: hidden;
  color: #111827;
  font-size: 18px;
  line-height: 1.35;
  font-weight: 780;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resource-card p {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: var(--ink-soft);
  font-size: 14px;
  line-height: 1.65;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.resource-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: auto;
  padding-top: 20px;
  color: var(--ink-faint);
  font-size: 12px;
}

.resource-meta > span:not(.skill-metadata-tags) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resource-empty {
  min-height: 240px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ink-faint);
  background: #fff;
  border: 1px dashed var(--border);
  border-radius: 8px;
}

.resource-empty .el-icon {
  font-size: 34px;
}

.skeleton-card {
  pointer-events: none;
}

.skeleton {
  display: block;
  background: #eef2f7;
  border-radius: 6px;
  animation: skeleton-pulse 1.4s ease-in-out infinite;
}

.skeleton-icon {
  width: 38px;
  height: 38px;
}

.skeleton-title {
  width: 62%;
  height: 20px;
  margin-top: 22px;
}

.skeleton-copy {
  width: 100%;
  height: 13px;
  margin-top: 15px;
}

.skeleton-copy.short {
  width: 74%;
  margin-top: 9px;
}

.build-band {
  background: var(--brand-50);
  border-top: 1px solid var(--brand-100);
  border-bottom: 1px solid var(--brand-100);
}

.build-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(420px, 1.1fr);
  align-items: center;
  gap: 76px;
}

.build-intro {
  margin: 16px 0 0;
  color: var(--ink-soft);
  font-size: 15px;
  line-height: 1.75;
}

.build-steps {
  margin: 32px 0 0;
  padding: 0;
  list-style: none;
}

.build-steps li {
  position: relative;
  display: grid;
  grid-template-columns: 36px 1fr;
  gap: 14px;
  padding-bottom: 24px;
}

.build-steps li:last-child {
  padding-bottom: 0;
}

.build-steps li:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 34px;
  bottom: 2px;
  left: 17px;
  width: 1px;
  background: var(--brand-200);
}

.step-number {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: var(--brand-600);
  border-radius: 50%;
  font-size: 13px;
  font-weight: 800;
}

.build-steps h3 {
  margin: 0;
  color: #111827;
  font-size: 16px;
  line-height: 1.4;
}

.build-steps p {
  margin: 5px 0 0;
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.6;
}

.orchestration {
  padding: 28px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid var(--brand-200);
  border-radius: 8px;
  box-shadow: 0 18px 44px rgba(37, 99, 235, 0.1);
}

.orchestration-label {
  margin-bottom: 14px;
  color: var(--ink-faint);
  font-size: 12px;
  font-weight: 750;
}

.orchestration-inputs {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.orchestration-node {
  min-height: 70px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: var(--ink-soft);
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
}

.orchestration-node .el-icon {
  color: var(--brand-600);
  font-size: 21px;
}

.orchestration-connector {
  width: 24px;
  height: 42px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  color: var(--brand-400);
}

.orchestration-connector span {
  width: 1px;
  flex: 1;
  background: var(--brand-300);
}

.agent-core {
  min-height: 86px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 14px 20px;
  color: #fff;
  background: var(--brand-800);
  border-radius: 8px;
  box-shadow: 0 12px 30px rgba(30, 64, 175, 0.24);
}

.agent-core-icon {
  width: 44px;
  height: 44px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.14);
  border-radius: 8px;
  font-size: 24px;
}

.agent-core strong,
.agent-core span {
  display: block;
}

.agent-core strong {
  font-size: 16px;
}

.agent-core span {
  margin-top: 4px;
  color: var(--brand-100);
  font-size: 12px;
}

.orchestration-outputs {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.orchestration-outputs span {
  min-height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #0f766e;
  background: #f0fdfa;
  border: 1px solid #99f6e4;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
}

.trust-heading {
  margin-bottom: 34px;
}

.trust-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.trust-item {
  display: grid;
  grid-template-columns: 34px 1fr;
  gap: 13px;
  padding: 28px 24px;
}

.trust-item + .trust-item {
  border-left: 1px solid var(--border);
}

.trust-item > .el-icon {
  width: 34px;
  height: 34px;
  color: var(--brand-600);
  background: var(--brand-50);
  border-radius: 8px;
  font-size: 18px;
}

.trust-item h3 {
  margin: 0;
  color: #111827;
  font-size: 15px;
}

.trust-item p {
  margin: 6px 0 0;
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.6;
}

.cta-band {
  margin: 0 24px 24px;
  color: #fff;
  background: var(--brand-900);
  border-radius: 8px;
}

.cta-inner {
  width: min(1120px, calc(100% - 48px));
  min-height: 250px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 56px;
}

.cta-kicker {
  color: #a7f3d0;
}

.cta-inner h2 {
  max-width: 700px;
  color: #fff;
}

.cta-inner p {
  margin: 12px 0 0;
  color: var(--brand-100);
  font-size: 14px;
}

.cta-actions {
  flex: 0 0 auto;
}

.button-light {
  color: var(--brand-900);
  background: #fff;
}

.button-dark-ghost {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.34);
}

.button-dark-ghost:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.6);
}

.home-footer {
  min-height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 0 max(24px, calc((100% - 1120px) / 2));
  color: var(--ink-faint);
  background: #fff;
  border-top: 1px solid var(--border);
  font-size: 13px;
}

.home-footer span:first-child {
  color: var(--ink);
  font-weight: 750;
}

@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}

@media (max-width: 980px) {
  .hero {
    min-height: auto;
  }

  .hero-inner {
    padding-top: 84px;
  }

  .build-layout {
    grid-template-columns: 1fr;
    gap: 48px;
  }

  .orchestration {
    max-width: 620px;
    width: 100%;
    margin: 0 auto;
    box-sizing: border-box;
  }

  .trust-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .trust-item:nth-child(3) {
    border-left: 0;
    border-top: 1px solid var(--border);
  }

  .trust-item:nth-child(4) {
    border-top: 1px solid var(--border);
  }

  .cta-inner {
    padding: 54px 0;
    flex-direction: column;
    align-items: flex-start;
    gap: 28px;
  }

  .cta-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .home {
    margin: -16px;
  }

  .section {
    width: calc(100% - 32px);
    padding: 56px 0;
  }

  .hero-inner {
    width: calc(100% - 32px);
    padding: 64px 0 34px;
  }

  .hero h1 {
    font-size: 42px;
  }

  .hero-title {
    font-size: 20px;
  }

  .hero-description {
    font-size: 15px;
  }

  .hero-actions .button {
    width: 100%;
    box-sizing: border-box;
  }

  .section-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 16px;
  }

  .section-heading h2,
  .build-copy h2,
  .cta-inner h2 {
    font-size: 27px;
  }

  .resource-grid {
    grid-template-columns: 1fr;
  }

  .resource-card {
    min-height: 220px;
  }

  .orchestration {
    padding: 18px;
  }

  .orchestration-inputs {
    grid-template-columns: repeat(2, 1fr);
  }

  .orchestration-outputs {
    grid-template-columns: 1fr;
  }

  .trust-grid {
    grid-template-columns: 1fr;
  }

  .trust-item + .trust-item,
  .trust-item:nth-child(3) {
    border-left: 0;
    border-top: 1px solid var(--border);
  }

  .cta-band {
    margin: 0 16px 16px;
  }

  .cta-inner {
    width: calc(100% - 36px);
    padding: 44px 0;
  }

  .cta-actions {
    width: 100%;
  }

  .cta-actions .button {
    width: 100%;
    box-sizing: border-box;
  }

  .home-footer {
    min-height: 88px;
    padding: 18px 16px;
    align-items: flex-start;
    flex-direction: column;
    justify-content: center;
    gap: 4px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .button,
  .resource-card,
  .skeleton {
    transition: none;
    animation: none;
  }
}
</style>
