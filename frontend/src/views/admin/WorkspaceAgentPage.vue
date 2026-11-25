<template>
  <router-view v-if="resolvedAgentId" v-slot="{ Component }">
    <component :is="Component" :key="resolvedAgentId" v-bind="isDefault ? { agentIdOverride: resolvedAgentId } : {}" />
  </router-view>
  <el-skeleton v-else-if="assistant?.loading.value" :rows="6" animated style="padding: 32px; box-sizing: border-box" />
  <el-result v-else icon="warning" title="默认助手暂不可用" sub-title="请返回对话页重试">
    <template #extra><el-button @click="router.push('/workspace/chat')">返回对话</el-button></template>
  </el-result>
</template>

<script setup>
import { computed, inject, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const assistant = inject('workbenchAssistant', null)
const isDefault = computed(() => route.meta.workbenchDefault === true)
const resolvedAgentId = computed(() => isDefault.value ? assistant?.agentId.value : route.params.id)
const emit = defineEmits(['agent-updated'])
const agent = ref(null)
const agentLoading = ref(false)
// Reuse the existing management pages inside the workbench's sidebar.
provide('expertWorkspace', { agent, agentLoading })
watch(agent, value => {
  if (value) emit('agent-updated', value)
})
</script>
