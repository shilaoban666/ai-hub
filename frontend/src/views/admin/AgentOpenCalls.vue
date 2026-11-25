<template>
  <main v-loading="loading" class="api-calls-page">
    <div class="api-calls-content">
      <el-alert v-if="error" :title="error" type="error" :closable="false">
        <el-button link type="primary" @click="load">重新加载</el-button>
      </el-alert>
      <AgentOpenCallRecords v-else-if="canManage" :agent-id="agentId" />
    </div>
  </main>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import api from '@/api/request'
import AgentOpenCallRecords from '@/components/AgentOpenCallRecords.vue'

const route = useRoute()
const workspace = inject('expertWorkspace', null)
const agentId = Number(route.params.id)
const loading = ref(false)
const error = ref('')
const agent = ref(null)
const canManage = computed(() => agent.value?.kind === 'expert' && agent.value.can_edit !== false)
let sequence = 0
const load = async () => {
  const current = ++sequence
  loading.value = true
  error.value = ''
  try {
    const data = await api.get(`/agents/${agentId}`)
    if (current !== sequence) return
    agent.value = data
    if (workspace) workspace.agent.value = data
    if (!canManage.value) error.value = '仅智能体创建者可查看 API 调用记录'
  } catch (e) {
    if (current === sequence) error.value = e.response?.data?.detail || '智能体信息加载失败'
  } finally {
    if (current === sequence) loading.value = false
  }
}
onMounted(load)
onBeforeUnmount(() => { sequence++ })
</script>

<style scoped>
.api-calls-page { height: 100%; overflow: auto; box-sizing: border-box; }
.api-calls-content { width: min(100%, 1304px); margin: 0 auto; padding: 28px 32px 48px; box-sizing: border-box; }
@media (max-width: 900px) {
  .api-calls-content { padding: 22px 16px 36px; }
}
</style>
