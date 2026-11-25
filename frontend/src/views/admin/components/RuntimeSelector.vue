<template>
  <div class="runtime-selector">
    <el-dropdown trigger="click" @command="handleSwitch">
      <span class="trigger">
        <span class="dot" :class="current"></span>
        <span class="label">{{ currentLabel }}</span>
        <el-icon class="arrow"><ArrowDown /></el-icon>
      </span>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="rt in runtimes"
            :key="rt.type"
            :command="rt.type"
            :class="{ active: rt.type === current }"
            :disabled="rt.disabled"
          >
            <div class="runtime-option">
              <span class="dot" :class="rt.type"></span>
              <div>
                <div class="name">{{ rt.label }}</div>
                <div class="desc">{{ rt.description }}</div>
              </div>
            </div>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'

const props = defineProps({
  current: { type: String, default: 'claude_code' },
  runtimes: { type: Array, default: () => [] },
})

const emit = defineEmits(['switch'])

const currentLabel = computed(() => {
  const found = props.runtimes.find(r => r.type === props.current)
  return found?.label || 'Claude Agent'
})

const handleSwitch = (type) => {
  emit('switch', type)
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
.dot.claude_code { background: #d97706; }

.label { color: #303133; font-weight: 500; }
.arrow { font-size: 12px; color: #909399; }

.runtime-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 4px 0;
}
.runtime-option .name { font-weight: 600; font-size: 14px; }
.runtime-option .desc { font-size: 12px; color: #909399; margin-top: 2px; }
</style>
