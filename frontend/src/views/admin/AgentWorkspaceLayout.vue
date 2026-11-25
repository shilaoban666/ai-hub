<template>
  <div class="expert-workspace">
    <AgentWorkspaceNav :agent="agent" :agent-id="agentId" :loading="!agent && agentLoading" :load-failed="!agent && !agentLoading" :active="activeMenu" @retry="loadAgent" />
    <section class="expert-workspace-content">
      <div class="expert-workspace-page">
        <router-view v-slot="{ Component }"><component :is="Component" :key="agentId" /></router-view>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import api from '@/api/request'
import AgentWorkspaceNav from './components/AgentWorkspaceNav.vue'
import { provideAgentOpenCall } from '@/composables/useAgentOpenCall'

const route = useRoute()
const agentId = computed(() => Number(route.params.id))
const agent = ref(null)
const agentLoading = ref(true)
provideAgentOpenCall(agentId, agent)
const activeMenu = computed(() => {
  if (route.name === 'AdminAgentStatistics') return 'statistics'
  if (route.name === 'AdminAgentOpenCalls') return 'api-calls'
  if (route.name === 'AdminAgentOpenCall') return 'open-call'
  return ['skills', 'prompts', 'mcp'].includes(route.query.section) ? route.query.section : 'config'
})
provide('expertWorkspace', { agent, agentLoading })
let sequence = 0
const loadAgent = async () => {
  const current = ++sequence
  agent.value = null
  agentLoading.value = true
  try {
    const data = await api.get(`/agents/${agentId.value}`)
    if (current === sequence) agent.value = data
  } catch {
    // The sidebar exposes a retry; the current page owns its error details.
  } finally {
    if (current === sequence) agentLoading.value = false
  }
}
watch(agentId, loadAgent, { immediate: true })
onBeforeUnmount(() => { sequence++ })
</script>

<style scoped>
.expert-workspace { display: flex; height: 100%; min-height: 0; overflow: hidden; }
.expert-workspace-content { flex: 1; min-width: 0; height: 100%; overflow: hidden; }
.expert-workspace-page { height: 100%; min-height: 0; }
@media (max-width: 720px) {
  .expert-workspace { flex-direction: column; }
  .expert-workspace-content { min-height: 0; }
}
</style>
