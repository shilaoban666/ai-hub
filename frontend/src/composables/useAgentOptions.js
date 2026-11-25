import { ref } from 'vue'
import api from '@/api/request'
import { adminApi } from '@/api/admin'

export function useAgentOptions() {
  const agents = ref([])
  const agentsLoading = ref(false)
  const agentsLoadFailed = ref(false)
  const loadAgents = async () => {
    if (agentsLoading.value) return
    agentsLoading.value = true
    agentsLoadFailed.value = false
    try {
      const loadPages = async path => {
        const items = []
        let total = 0
        do {
          const page = await api.get(path, { params: { skip: items.length, limit: 100 } })
          const batch = page.items || []
          items.push(...batch)
          total = page.total || 0
          if (!batch.length) break
        } while (items.length < total)
        return items
      }
      const [mine, shared] = await Promise.all([loadPages('/agents'), loadPages('/public/agents')])
      const authorIds = [...new Set(shared.map(agent => agent.user_id).filter(id => Number(id) > 0))]
      const authorNames = new Map()
      // Reuse IAM's batch lookup; missing profile access must not block switching.
      const batches = []
      for (let offset = 0; offset < authorIds.length; offset += 100) {
        const ids = authorIds.slice(offset, offset + 100)
        batches.push(adminApi.getUsers({ ids: ids.join(','), limit: ids.length }))
      }
      for (const result of await Promise.allSettled(batches)) {
        if (result.status !== 'fulfilled') continue
        const users = result.value?.items || result.value
        if (!Array.isArray(users)) continue
        for (const user of users) authorNames.set(Number(user.id), user.first_name?.trim() || user.username?.trim() || '')
      }
      const ownIds = new Set(mine.map(agent => agent.id))
      agents.value = [
        ...mine.map(agent => ({ ...agent, origin: 'mine' })),
        ...shared.filter(agent => !ownIds.has(agent.id)).map(agent => ({ ...agent, author: agent.author || authorNames.get(Number(agent.user_id)), origin: 'public', can_edit: false })),
      ]
    } catch {
      agentsLoadFailed.value = true
    } finally {
      agentsLoading.value = false
    }
  }
  const updateAgent = value => {
    agents.value = agents.value.map(agent => agent.id === value.id ? { ...agent, ...value } : agent)
  }
  return { agents, agentsLoading, agentsLoadFailed, loadAgents, updateAgent }
}
