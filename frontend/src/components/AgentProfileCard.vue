<template>
  <article class="agent-profile-card" aria-label="智能体名片" tabindex="0">
    <div class="profile-heading">
      <span v-if="agent.icon?.trim()" class="profile-avatar" :class="{ 'image-avatar': getAssistantImage(agent.icon) }">
        <AssistantIcon :icon="agent.icon" />
      </span>
      <div class="profile-identity">
        <h3 class="profile-name">{{ textOrNone(agent.name) }}</h3>
        <div class="profile-author-line">
          <span class="profile-author-label">作者</span>
          <span class="profile-author">{{ textOrNone(agent.author) }}</span>
        </div>
      </div>
      <div v-if="agent.origins?.length" class="profile-origins">
        <span v-for="origin in agent.origins" :key="origin" class="profile-origin" :class="`profile-origin--${origin}`">{{ originLabel(origin) }}</span>
      </div>
    </div>
    <dl class="profile-details">
      <div class="profile-field">
        <dt>描述</dt>
        <dd class="profile-description">{{ textOrNone(agent.description) }}</dd>
      </div>
      <div class="profile-field profile-field--skills">
        <dt>技能<span v-if="skills.length" class="profile-count">{{ skills.length }}</span></dt>
        <dd class="profile-skills">
          <span v-for="(skill, index) in skills" :key="skill.id ?? index" class="profile-skill">{{ skill.name }}</span>
          <span v-if="!skills.length" class="profile-empty">无</span>
        </dd>
      </div>
    </dl>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import AssistantIcon from '@/components/AssistantIcon.vue'
import { getAssistantImage } from '@/config/assistant-characters'

const props = defineProps({ agent: { type: Object, required: true } })
const textOrNone = value => String(value ?? '').trim() || '无'
const originLabel = origin => ({ default: '默认', mine: '我的', public: '公开' })[origin] || origin
const skills = computed(() => (props.agent.skills || [])
  .filter(skill => skill.name?.trim())
  .map(skill => ({ ...skill, name: skill.name.trim() })))
</script>

<style scoped>
.agent-profile-card { max-height: min(640px, calc(100dvh - 120px)); overflow-y: auto; overscroll-behavior: contain; padding: 20px; color: #303741; font-size: 13px; line-height: 1.65; scrollbar-width: thin; box-sizing: border-box; }
.agent-profile-card:focus-visible { outline: 2px solid #7899be; outline-offset: -3px; border-radius: 12px; }
.profile-heading { display: flex; align-items: flex-start; gap: 14px; }
.profile-avatar { display: grid; place-items: center; flex: 0 0 52px; width: 52px; height: 52px; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 14px; background: #f1f5fa; color: #53657d; font-size: 28px; font-weight: 600; line-height: 1; }
.profile-avatar.image-avatar { background: transparent; border-color: transparent; }
.profile-identity { min-width: 0; flex: 1; }
.profile-name { margin: 0; color: #242b35; font-size: 17px; font-weight: 600; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.profile-author-line { display: flex; align-items: baseline; gap: 7px; min-width: 0; margin-top: 3px; color: #818b99; font-size: 12px; line-height: 1.65; }
.profile-author-label { flex: 0 0 auto; }
.profile-author { min-width: 0; color: #596575; white-space: pre-wrap; overflow-wrap: anywhere; }
.profile-origins { display: flex; flex: 0 0 auto; flex-wrap: wrap; justify-content: flex-end; gap: 6px; max-width: 45%; margin: 4px 0 0 auto; }
.profile-origin { padding: 1px 7px; border-radius: 5px; background: #f0f2f5; color: #667180; font-size: 11px; }
.profile-origin--mine { background: #eaf2fa; color: #285886; }
.profile-origin--public { background: #edf6f0; color: #3f7755; }
.profile-details { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 10px 12px; margin: 18px 0 0; padding-top: 16px; padding-left: 18px; border-top: 1px solid #edf0f4; }
.profile-field { display: grid; grid-column: 1 / -1; grid-template-columns: subgrid; align-items: start; column-gap: 8px; min-width: 0; }
.profile-field--skills { align-items: center; }
.profile-field dt { display: flex; align-items: center; gap: 7px; color: #818b99; font-size: 12px; line-height: 21.45px; }
.profile-field dd { margin: 0; min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.profile-count { padding: 0 6px; border-radius: 4px; background: #f2f5f8; color: #66788b; font-size: 11px; }
.profile-skills { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 7px; }
.profile-skill { min-width: 0; max-width: 100%; padding: 4px 9px; border: 1px solid #dce8f4; border-radius: 7px; background: #f5f9fd; color: #4d7197; font-size: 12px; line-height: 1.6; box-sizing: border-box; }
.profile-empty { color: #818b99; }
@media (max-width: 600px) { .agent-profile-card { padding: 16px; } }
</style>
