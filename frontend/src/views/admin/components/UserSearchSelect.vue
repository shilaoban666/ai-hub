<template>
  <el-select :model-value="modelValue" filterable remote clearable :remote-method="searchUsers"
    :loading="loading" :placeholder="placeholder" :aria-label="label"
    :no-data-text="error || '无'" @visible-change="visible => visible && searchUsers('')"
    @update:model-value="selectUser" @change="value => emit('change', value)">
    <el-option v-for="user in options" :key="user.id" :value="Number(user.id)" :label="userName(user)">
      <span>{{ userName(user) }}</span>
      <span v-if="user.first_name?.trim()" class="user-account">{{ user.username?.trim() || '无' }}</span>
      <el-tag v-if="user.is_active === false" class="departed-tag" size="small" type="info" effect="plain">已离职</el-tag>
    </el-option>
  </el-select>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { adminApi } from '@/api/admin'

const props = defineProps({
  modelValue: { type: Number, default: undefined },
  placeholder: { type: String, default: '搜索姓名或用户名' },
  label: { type: String, default: '用户' },
})
const emit = defineEmits(['update:modelValue', 'change'])
const results = ref([]), selected = ref(null), loading = ref(false), error = ref('')
let requestId = 0
const userName = user => user.first_name?.trim() || user.username?.trim() || '无'
const options = computed(() => {
  const current = results.value.find(user => Number(user.id) === props.modelValue)
  return selected.value && Number(selected.value.id) === props.modelValue && !current
    ? [selected.value, ...results.value] : results.value
})
function selectUser(value) {
  selected.value = options.value.find(user => Number(user.id) === value) || null
  emit('update:modelValue', value || undefined)
}
async function searchUsers(search) {
  const id = ++requestId
  loading.value = true
  error.value = ''
  try {
    const data = await adminApi.getUsers({ search: search.trim() || undefined, limit: 50, is_active: undefined })
    if (id === requestId) results.value = data.items || []
  } catch {
    if (id === requestId) {
      results.value = []
      error.value = '用户查询失败，请重新搜索'
    }
  } finally {
    if (id === requestId) loading.value = false
  }
}
onBeforeUnmount(() => { ++requestId })
</script>

<style scoped>
.user-account { margin-left: 12px; color: #909399; font-size: 12px; }
.departed-tag { margin-left: 8px; }
</style>
