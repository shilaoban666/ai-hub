<template>
  <div class="model-selector">
    <el-dropdown trigger="click" @command="handleSelect">
      <span class="trigger">
        <span class="dot model"></span>
        <span class="label">{{ currentLabel }}</span>
        <el-icon class="arrow"><ArrowDown /></el-icon>
      </span>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="m in visibleModels"
            :key="m.id"
            :command="m.id"
            :class="{ active: m.id === selectedId }"
          >
            <div class="model-option">
              <span class="dot model"></span>
              <div>
                <div class="name">{{ m.name }}</div>
                <div class="desc">{{ getModelOptionMeta(m) }}</div>
              </div>
            </div>
          </el-dropdown-item>
          <el-dropdown-item v-if="visibleModels.length === 0" disabled>
            <span class="empty">无可用模型</span>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import {
  getCompatibleModelsForRuntime,
  getModelOptionMeta,
} from '@/config/models'

const props = defineProps({
  models: { type: Array, default: () => [] },
  selectedId: { type: Number, default: null },
  runtimeType: { type: String, default: 'claude_code' },
})

const emit = defineEmits(['select'])

const visibleModels = computed(() => getCompatibleModelsForRuntime(
  props.models,
  props.runtimeType,
))

const currentLabel = computed(() => {
  const found = visibleModels.value.find(m => m.id === props.selectedId)
  if (!found) return '请选择'
  return found.remarks ? `${found.name} · ${found.remarks}` : found.name
})

const handleSelect = (id) => {
  emit('select', id)
}
</script>

<style scoped>
.trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  background: #f0f0f0;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.2s;
  user-select: none;
}
.trigger:hover {
  background: #e0e0e0;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.dot.model { background: #409eff; }

.label {
  max-width: 180px;
  overflow: hidden;
  color: #303133;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.arrow { font-size: 12px; color: #909399; }

.model-option {
  min-width: 260px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 4px 0;
}
.model-option .name { font-weight: 600; font-size: 14px; }
.model-option .desc { font-size: 12px; color: #909399; margin-top: 2px; }

.empty {
  color: #c0c4cc;
  font-size: 13px;
}
</style>
