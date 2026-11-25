<template>
  <main v-loading="loading" class="open-call-page">
    <div class="open-call-content">
      <ResourcePageHeader title="开放调用" />
      <el-alert v-if="error" :title="error" type="error" :closable="false">
        <el-button link type="primary" @click="load">重新加载</el-button>
      </el-alert>
      <el-form v-else-if="canManage" label-width="120px" label-position="right">
        <AgentOpenCallSetting :agent-id="agentId" />
      </el-form>
    </div>
  </main>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import api from '@/api/request'
import AgentOpenCallSetting from '@/components/AgentOpenCallSetting.vue'
import ResourcePageHeader from './components/ResourcePageHeader.vue'

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
  agent.value = null
  try {
    const data = await api.get(`/agents/${agentId}`)
    if (current !== sequence) return
    agent.value = data
    if (workspace) workspace.agent.value = data
    if (!canManage.value) error.value = '仅智能体创建者可配置开放调用'
  } catch (e) {
    const detail = e.response?.data?.detail
    if (current === sequence) error.value = typeof detail === 'string' ? detail : '智能体信息加载失败'
  } finally {
    if (current === sequence) loading.value = false
  }
}
onMounted(load)
onBeforeUnmount(() => { sequence++ })
</script>

<style scoped>
.open-call-page { height: 100%; overflow: auto; box-sizing: border-box; }
.open-call-content { width: min(100%, 1304px); margin: 0 auto; padding: 28px 32px 48px; box-sizing: border-box; }
.open-call-content :deep(.open-call) { border: 0; border-radius: 0; }
.open-call-content :deep(.open-call > .el-card__header) { padding: 24px 0 16px; border-bottom: 0; }
.open-call-content :deep(.open-call > .el-card__body) { padding: 0 0 32px; }
@media (max-width: 900px) {
  .open-call-content { padding: 22px 16px 36px; }
}
</style>
