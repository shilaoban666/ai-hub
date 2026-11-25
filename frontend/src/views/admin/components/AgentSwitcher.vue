<template>
  <div class="agent-switcher" :class="{ 'agent-switcher--compact': compactTrigger }">
    <div v-if="!compactTrigger && identityLoading && !currentAgent" class="agent-switcher-identity agent-switcher-skeleton" role="status" aria-label="正在加载智能体信息" aria-busy="true">
      <span class="agent-switcher-avatar skeleton-avatar" aria-hidden="true" />
      <span class="skeleton-name" aria-hidden="true" />
    </div>
    <el-popover
      v-else
      :visible="profileVisible"
      placement="bottom-start"
      :trigger="compactTrigger ? [] : 'hover'"
      :trigger-keys="[]"
      :virtual-triggering="compactTrigger"
      :virtual-ref="compactTriggerElement"
      :show-after="250"
      :hide-after="180"
      :width="420"
      :disabled="!profileAgent || visible"
      :enterable="true"
      :persistent="false"
      popper-class="agent-profile-popover"
      :popper-style="{ maxWidth: 'calc(100vw - 24px)', padding: '0', borderRadius: '14px', boxSizing: 'border-box' }"
    >
      <template v-if="!compactTrigger" #reference>
        <button v-click-outside="closeProfileOutside" type="button" class="agent-switcher-identity agent-profile-trigger"
          :disabled="!profileAgent" :aria-label="`查看${displayName}的智能体名片`" :aria-expanded="profileVisible"
          @mouseenter="openProfile(250)" @mouseleave="closeProfile(180)"
          @click="openProfile()" @blur="closeProfileOnBlur" @keydown.esc.stop="closeProfile()">
          <span v-if="currentAgent?.icon?.trim()" class="agent-switcher-avatar" :class="{ 'image-avatar': getAssistantImage(currentAgent.icon) }"><AssistantIcon :icon="currentAgent.icon" /></span>
          <strong class="agent-switcher-name">{{ displayName }}</strong>
        </button>
      </template>
      <AgentProfileCard v-if="profileAgent" :agent="profileAgent" @mouseenter="openProfile()" @mouseleave="closeProfile(180)"
        @focusout="closeProfileOnBlur" @keydown.esc.stop="closeProfile()" />
    </el-popover>
    <el-popover
      v-if="allowSwitch"
      v-model:visible="visible"
      placement="bottom-start"
      trigger="click"
      :trigger-keys="[]"
      :width="640"
      popper-class="agent-switcher-popover"
      :popper-style="{ maxWidth: 'calc(100vw - 24px)', padding: '16px', boxSizing: 'border-box' }"
    >
      <template #reference>
        <button
          v-if="compactTrigger"
          v-click-outside="closeProfileOutside"
          ref="compactTriggerElement"
          type="button"
          class="agent-switcher-identity agent-switcher-row"
          :class="{ 'is-open': visible }"
          aria-label="召唤智能体"
          :aria-expanded="visible"
          :disabled="switching"
          @mouseenter="openProfile(500)" @mouseleave="closeProfile(180)"
          @blur="closeProfileOnBlur" @keydown.esc.stop="closePopovers"
        >
          <span v-if="identityLoading && !currentAgent" class="agent-switcher-row-loading agent-switcher-skeleton" role="status" aria-label="正在加载智能体信息" aria-busy="true">
            <span class="agent-switcher-avatar skeleton-avatar" aria-hidden="true" />
            <span class="skeleton-name" aria-hidden="true" />
          </span>
          <template v-else>
            <span class="agent-switcher-avatar" :class="{ 'image-avatar': getAssistantImage(currentAgent?.icon) }"><AssistantIcon :icon="currentAgent?.icon || 'H'" /></span>
            <strong class="agent-switcher-name" :title="displayName">{{ displayName }}</strong>
          </template>
          <el-icon v-if="switching" class="agent-switcher-chevron is-loading" aria-hidden="true"><Loading /></el-icon>
          <el-icon v-else class="agent-switcher-chevron" aria-hidden="true"><ArrowDown /></el-icon>
        </button>
        <el-button
          v-else
          text
          class="agent-switcher-trigger"
          :class="{ 'is-open': visible }"
          aria-label="召唤智能体"
          title="召唤智能体"
          :disabled="switching"
          :aria-expanded="visible"
        >
          <span>召唤</span>
          <el-icon class="agent-switcher-trigger-icon"><ExpertIcon /></el-icon>
        </el-button>
      </template>
      <div @keydown.esc.stop="closePopovers">
        <el-input v-model="search" :prefix-icon="Search" placeholder="搜索名称、作者、描述或技能" clearable aria-label="搜索智能体">
          <template #suffix>
            <span class="agent-switcher-loading" :class="{ 'is-visible': loading }" role="status" aria-label="正在加载智能体">
              <el-icon v-if="loading" class="is-loading"><Loading /></el-icon>
            </span>
          </template>
        </el-input>
        <button v-if="loadFailed" type="button" class="agent-switcher-retry" @click="$emit('reload')">专家列表加载失败，点击重试</button>
        <div class="agent-switcher-options" role="listbox" aria-label="选择智能体">
          <button
            v-for="item in filteredOptions"
            :key="item.id"
            type="button"
            role="option"
            class="agent-switcher-option"
            :class="{ 'is-selected': item.id === selectedId }"
            :aria-label="item.name"
            :aria-selected="item.id === selectedId"
            :disabled="switching"
            @click="select(item.id)"
          >
            <span class="agent-card-profile">
              <span v-if="item.icon?.trim()" class="agent-switcher-avatar agent-card-avatar" :class="{ 'image-avatar': getAssistantImage(item.icon) }"><AssistantIcon :icon="item.icon" /></span>
              <span class="agent-card-identity">
                <span class="agent-switcher-option-name" :title="item.name">{{ item.name }}</span>
                <span class="agent-card-author" :title="textOrNone(item.author)">作者：{{ textOrNone(item.author) }}</span>
              </span>
              <span v-for="origin in item.origins" :key="origin" class="origin-badge" :class="`origin-badge--${origin}`">{{ originLabel(origin) }}</span>
            </span>
            <span class="agent-card-description" :title="textOrNone(item.description)">{{ textOrNone(item.description) }}</span>
            <span class="agent-card-expertise">
              <span class="expertise-label">技能<span v-if="skillNames(item).length" class="expertise-count">{{ skillNames(item).length }}</span></span>
              <span class="expertise-tags" :title="skillNames(item).join('、') || '无'">
                <span v-for="name in skillNames(item).slice(0, 3)" :key="name" class="expertise-tag">{{ name }}</span>
                <span v-if="skillNames(item).length > 3" class="expertise-tag">+{{ skillNames(item).length - 3 }}</span>
                <span v-if="!skillNames(item).length" class="expertise-empty">无</span>
              </span>
            </span>
          </button>
          <div v-if="!loading && !filteredOptions.length" class="agent-switcher-status">无匹配智能体</div>
        </div>
        <div class="agent-switcher-footer">
          <button v-if="compactTrigger && profileAgent" type="button" class="agent-switcher-profile-link" @click="showCurrentProfile">查看当前智能体名片</button>
          <el-button
            class="agent-switcher-create"
            type="primary"
            tag="a"
            :icon="Plus"
            :href="router.resolve({ name: 'AdminAgentList' }).href"
            target="_blank"
            rel="noopener noreferrer"
          >新建自定义 Agent</el-button>
        </div>
      </div>
    </el-popover>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDown, Loading, Plus, Search } from '@element-plus/icons-vue'
import { ClickOutside as vClickOutside } from 'element-plus'
import AssistantIcon from '@/components/AssistantIcon.vue'
import AgentProfileCard from '@/components/AgentProfileCard.vue'
import ExpertIcon from '@/components/icons/ExpertIcon.vue'
import { getAssistantImage } from '@/config/assistant-characters'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({
  allowSwitch: Boolean,
  compactTrigger: Boolean,
  currentAgent: { type: Object, default: null },
  defaultAssistant: { type: Object, default: null },
  selectedId: { type: Number, default: 0 },
  agents: { type: Array, default: () => [] },
  loading: Boolean,
  loadFailed: Boolean,
  identityLoading: Boolean,
  switching: Boolean,
})
const emit = defineEmits(['select', 'reload'])
const visible = ref(false)
const profileVisible = ref(false)
const compactTriggerElement = ref(null)
const search = ref('')
const auth = useAuthStore()
const router = useRouter()
const textOrNone = value => String(value ?? '').trim() || '无'
const skillNames = item => [...new Set((item.skills || []).map(skill => skill.name?.trim()).filter(Boolean))]
const originLabel = origin => ({ default: '默认', mine: '我的', public: '公开' })[origin] || origin
const displayName = computed(() => props.currentAgent?.name?.trim() || '无')
let profileTimer
const openProfile = (delay = 0) => {
  clearTimeout(profileTimer)
  if (!profileAgent.value || visible.value) return
  if (delay) profileTimer = setTimeout(() => { profileVisible.value = true }, delay)
  else profileVisible.value = true
}
const closeProfile = (delay = 0) => {
  clearTimeout(profileTimer)
  if (delay) profileTimer = setTimeout(() => { profileVisible.value = false }, delay)
  else profileVisible.value = false
}
const closeProfileOutside = event => {
  if (!event.target?.closest('.agent-profile-popover')) closeProfile()
}
const closeProfileOnBlur = event => {
  if (!event.relatedTarget?.closest('.agent-profile-popover, .agent-profile-trigger, .agent-switcher-row')) closeProfile()
  else clearTimeout(profileTimer)
}
const closePopovers = () => {
  visible.value = false
  closeProfile()
  if (props.compactTrigger) compactTriggerElement.value?.focus({ preventScroll: true })
}
const showCurrentProfile = async () => {
  visible.value = false
  await nextTick()
  compactTriggerElement.value?.focus({ preventScroll: true })
  openProfile()
}
onBeforeUnmount(() => clearTimeout(profileTimer))
const normalizeAgent = item => {
  const isDefault = item.id === 0 || item.kind === 'personal_default'
  const isPublicVisitor = item.origin === 'public' || item.can_edit === false
  return {
    ...item,
    name: item.name?.trim() || '无',
    origins: isDefault ? ['default'] : [
      ...(!isPublicVisitor ? ['mine'] : []),
      ...(item.is_public || isPublicVisitor ? ['public'] : []),
    ],
    author: isDefault ? '平台' : (item.author?.trim() || (!isPublicVisitor ? (auth.user?.first_name?.trim() || auth.user?.username?.trim()) : '')),
  }
}
const profileAgent = computed(() => props.currentAgent ? normalizeAgent({
  ...props.currentAgent,
  ...(props.allowSwitch && props.selectedId === 0 ? { id: 0 } : {}),
}) : null)
const filteredOptions = computed(() => [
  { ...props.defaultAssistant, id: 0, name: props.defaultAssistant?.name?.trim() || '默认助手', icon: props.defaultAssistant?.icon || 'H', author: '平台' },
  ...props.agents.map(agent => ({ ...agent, name: agent.name?.trim() || '无' })),
].map(normalizeAgent)
  .filter(item => [item.name, item.author, item.description, ...skillNames(item)].some(value =>
    String(value || '').toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()))))
const select = id => { visible.value = false; emit('select', id) }
watch(visible, value => {
  if (value) { closeProfile(); search.value = ''; emit('reload') }
})
watch(() => props.currentAgent?.id, () => { closeProfile() })
watch(() => props.selectedId, () => { visible.value = false; closeProfile() })
</script>

<style scoped>
.agent-switcher { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.agent-switcher-identity { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; height: 36px; }
.agent-profile-trigger { margin: 0; padding: 0; border: 0; border-radius: 7px; background: transparent; font: inherit; text-align: left; cursor: pointer; }
.agent-profile-trigger:hover:not(:disabled) { background: #e9edf366; }
.agent-profile-trigger:focus-visible { outline: 2px solid #7899be; outline-offset: 3px; }
.agent-profile-trigger:disabled { cursor: default; }
.agent-switcher-skeleton { animation: identity-breathe 1.8s ease-in-out infinite; }
.agent-switcher-skeleton .skeleton-avatar { background: #e3e7ec; }
.skeleton-name { width: 84px; max-width: calc(100% - 42px); height: 12px; border-radius: 3px; background: #e8ebef; }
@keyframes identity-breathe { 0%, 100% { opacity: 1; } 50% { opacity: .55; } }
@media (prefers-reduced-motion: reduce) { .agent-switcher-skeleton { animation: none; } }
.agent-switcher-avatar { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; flex: 0 0 32px; overflow: hidden; border-radius: 50%; background: #30343a; color: #fff; font-size: 16px; font-weight: 700; line-height: 1; white-space: nowrap; }
.agent-switcher-avatar.image-avatar { background: transparent; }
.agent-switcher-name { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; flex: 1; min-width: 0; max-height: 36px; overflow: hidden; overflow-wrap: anywhere; color: #2d3137; font-size: 14px; font-weight: 400; line-height: 18px; }
.agent-switcher-trigger.el-button { flex: 0 0 auto; height: 28px; margin: 0; padding: 0 10px; border: 1px solid #e3e8f0; border-radius: 8px; background: #f1f4f9; color: #4d6483; font-size: 12px; font-weight: 500; transition: background .15s, border-color .15s, color .15s; }
.agent-switcher-trigger :deep(> span) { gap: 5px; }
.agent-switcher-trigger :deep(.agent-switcher-trigger-icon) { display: inline-flex; align-items: center; justify-content: center; width: 15px; height: 15px; flex: 0 0 15px; font-size: 15px; line-height: 1; vertical-align: middle; transform: translateY(-1px); }
.agent-switcher-trigger.el-button:hover:not(:disabled) { border-color: #cfd9e7; background: #e9eef6; color: #35506f; }
.agent-switcher-trigger.el-button.is-open { border-color: #cfd9e7; background: #e3eaf4; color: #2f4a6b; }
.agent-switcher-trigger.el-button:focus-visible { outline: 2px solid #7899be; outline-offset: 2px; }
.agent-switcher-trigger.el-button:disabled { opacity: .55; }
@media (prefers-reduced-motion: reduce) { .agent-switcher-trigger.el-button { transition: none; } }
.agent-switcher-loading { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; flex: 0 0 16px; visibility: hidden; color: #8b929d; }
.agent-switcher-loading.is-visible { visibility: visible; }
.agent-switcher-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; max-height: min(520px, 65vh); overflow-y: auto; margin-top: 12px; padding: 2px; }
.agent-switcher-footer { display: flex; justify-content: flex-end; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--el-border-color-lighter); }
.agent-switcher-create, .agent-switcher-create:hover, .agent-switcher-create:focus, .agent-switcher-create:active { text-decoration: none; }
.agent-switcher-option { display: flex; flex-direction: column; gap: 8px; min-width: 0; width: 100%; padding: 16px; border: 1px solid #e4e8ee; border-radius: 12px; background: #fff; color: #2d3137; font: inherit; font-size: 13px; text-align: left; cursor: pointer; transition: border-color .15s, background .15s; }
.agent-switcher-option:hover, .agent-switcher-option:focus-visible { border-color: #aabed5; background: #f8fafc; }
.agent-switcher-option:focus-visible { outline: 2px solid #7899be; outline-offset: -2px; }
.agent-switcher-option.is-selected { border-color: #b6c8dd; background: #edf3f9; color: #2d3137; }
.agent-switcher-option:disabled { cursor: wait; opacity: .65; }
.agent-card-profile { display: flex; align-items: center; gap: 10px; width: 100%; min-width: 0; }
.agent-card-avatar { width: 44px; height: 44px; flex-basis: 44px; font-size: 24px; }
.agent-card-identity { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 0; }
.agent-switcher-option-name { display: block; font-size: 14px; font-weight: 400; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-card-author { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #728096; font-size: 12px; }
.agent-card-description { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 21px; color: #5f6977; overflow-wrap: anywhere; }
.agent-card-expertise { display: flex; align-items: flex-start; gap: 8px; width: 100%; }
.expertise-label, .expertise-empty { color: #8a96a5; font-size: 11px; font-weight: 400; line-height: 24px; }
.expertise-label { display: inline-flex; align-items: center; gap: 7px; flex-shrink: 0; }
.expertise-count { padding: 0 6px; border-radius: 4px; background: #f2f5f8; color: #66788b; font-size: 11px; line-height: 20px; }
.expertise-tags { display: flex; flex-wrap: wrap; gap: 5px; min-width: 0; }
.expertise-tag { max-width: 100%; overflow-wrap: anywhere; padding: 3px 8px; border: 1px solid #dce8f4; border-radius: 999px; color: #4d7197; background: #f5f9fd; font-size: 11px; line-height: 16px; box-sizing: border-box; }
@media (max-width: 600px) { .agent-switcher-options { grid-template-columns: minmax(0, 1fr); max-height: 60vh; } }
.agent-switcher-option.is-selected .agent-switcher-option-name { font-weight: 400; }
.origin-badge { flex: 0 0 auto; padding: 1px 6px; border-radius: 4px; color: #5f6672; background: #f0f2f5; font-size: 11px; font-weight: 400; line-height: 18px; white-space: nowrap; }
.origin-badge--mine { color: #285886; background: #eaf2fa; }
.agent-switcher-status { grid-column: 1 / -1; padding: 10px 8px; color: #8b929d; font-size: 12px; }
.agent-switcher-retry { padding: 10px 8px; border: 0; background: transparent; color: #c45656; font: inherit; font-size: 12px; cursor: pointer; }
.agent-switcher--compact { width: 100%; }
.agent-switcher-row { width: 100%; height: 48px; gap: 9px; margin: 0; padding: 0 10px; border: 0; border-radius: 10px; background: transparent; color: #2d3137; font: inherit; text-align: left; cursor: pointer; box-sizing: border-box; transition: background .15s; }
.agent-switcher-row:hover:not(:disabled), .agent-switcher-row.is-open { background: #ebebeb; }
.agent-switcher-row:focus-visible { outline: 2px solid #409eff; outline-offset: -2px; }
.agent-switcher-row:disabled { cursor: wait; opacity: .6; }
.agent-switcher-row .agent-switcher-avatar { width: 22px; height: 22px; flex-basis: 22px; border-radius: 50%; background: #30343a; color: #fff; font-size: calc(11px + var(--workspace-font-size-offset, 0px)); font-weight: 700; }
.agent-switcher-row .agent-switcher-avatar.image-avatar { background: transparent; }
.agent-switcher-row .agent-switcher-name { display: block; max-height: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: inherit; font-size: calc(14px + var(--workspace-font-size-offset, 0px)); font-weight: 600; line-height: 20px; }
.agent-switcher-chevron { flex: 0 0 12px; margin-left: auto; color: #929292; font-size: 12px; transition: transform .15s, color .15s; }
.agent-switcher-row.is-open .agent-switcher-chevron:not(.is-loading) { color: #409eff; transform: rotate(180deg); }
.agent-switcher-row-loading { display: flex; align-items: center; flex: 1; min-width: 0; gap: 9px; }
.agent-switcher-profile-link { margin-right: auto; padding: 4px 0; border: 0; border-radius: 4px; background: transparent; color: #777; font: inherit; font-size: 12px; cursor: pointer; }
.agent-switcher-profile-link:hover { color: #409eff; }
.agent-switcher-profile-link:focus-visible { outline: 2px solid #409eff; outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .agent-switcher-row, .agent-switcher-chevron { transition: none; } }
</style>
