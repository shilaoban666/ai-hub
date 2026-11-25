import { computed, inject, onBeforeUnmount, provide, ref, watch } from 'vue'
import api from '@/api/request'

const openCallKey = Symbol('agentOpenCall')

// Keep navigation state within the current workspace and never retain raw keys.
export function provideAgentOpenCall(agentId, agent) {
  const enabled = ref(false)
  let sequence = 0
  const ownerId = computed(() => {
    const id = Number(agentId.value)
    const current = agent.value
    return id > 0 && Number(current?.id) === id && current.kind === 'expert' && current.can_edit !== false ? id : 0
  })
  const update = (id, value) => {
    if (Number(id) !== ownerId.value) return
    sequence++
    enabled.value = value === true
  }
  watch(ownerId, async id => {
    const current = ++sequence
    enabled.value = false
    if (!id) return
    try {
      const data = await api.get(`/agents/${id}/open-call`)
      if (current === sequence) enabled.value = data.enabled === true
    } catch {
      // A failed settings lookup must not expose an owner-only menu.
      if (current === sequence) enabled.value = false
    }
  }, { immediate: true })
  onBeforeUnmount(() => { sequence++ })
  const state = { enabled: computed(() => ownerId.value > 0 && enabled.value), update }
  provide(openCallKey, state)
  return state
}

export const useAgentOpenCall = () => inject(openCallKey, null)
