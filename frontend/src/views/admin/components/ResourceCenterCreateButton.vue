<template>
  <el-button
    class="resource-create-button"
    tag="a"
    type="primary"
    :icon="Plus"
    :href="router.resolve({ name: destination.route }).href"
    target="_blank"
    rel="noopener noreferrer"
  >{{ destination.label }}</el-button>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'

const props = defineProps({ resource: { type: String, required: true } })
const router = useRouter()
const destinations = {
  skills: { route: 'AdminSkillList', label: '新建技能' },
  prompts: { route: 'AdminPromptTemplateList', label: '新建提示词' },
  mcp: { route: 'AdminMcpList', label: '新建连接器' },
}
const destination = computed(() => destinations[props.resource])
</script>

<style scoped>
.resource-create-button,
.resource-create-button:hover,
.resource-create-button:focus,
.resource-create-button:active {
  text-decoration: none;
}
</style>
