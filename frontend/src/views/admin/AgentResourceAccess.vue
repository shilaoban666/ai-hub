<template>
  <el-skeleton v-if="loading" :rows="6" animated />
  <el-result v-else-if="error" icon="warning" :title="error">
    <template #extra><el-button @click="load">重新加载</el-button></template>
  </el-result>
  <AssetCenter v-else v-bind="$attrs" :agent-id="agentId" :workspace-view="workspaceView" :read-only="agent?.can_edit === false" />
</template>

<script setup>
import { ref, watch } from 'vue'
import api from '@/api/request'
import AssetCenter from './AssetCenter.vue'
defineOptions({ inheritAttrs: false })
const props = defineProps({ agentId: { type: [Number, String], default: null }, workspaceView: { type: String, default: 'skills' } })
const agent = ref(null)
const loading = ref(false)
const error = ref('')
let revision = 0
const load = async () => {
  const request = ++revision
  agent.value = null
  error.value = ''
  loading.value = Boolean(props.agentId)
  if (!props.agentId) return
  try {
    const result = await api.get(`/agents/${props.agentId}`)
    if (request === revision) agent.value = result
  } catch (e) {
    if (request === revision) error.value = typeof e.response?.data?.detail === 'string' ? e.response.data.detail : '智能体加载失败'
  } finally {
    if (request === revision) loading.value = false
  }
}
watch(() => props.agentId, load, { immediate: true })
</script>
