<template>
  <div class="skill-selector">
    <el-dropdown trigger="click" @command="handleSelect">
      <span class="trigger">
        <span class="dot skill"></span>
        <span class="label">{{ currentLabel }}</span>
        <el-icon class="arrow"><ArrowDown /></el-icon>
      </span>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="s in skills"
            :key="s.id"
            :command="s.id"
            :class="{ active: s.id === selectedId }"
          >
            <div class="skill-option">
              <span class="dot skill"></span>
              <div>
                <div class="name">{{ s.name }}</div>
              </div>
            </div>
          </el-dropdown-item>
          <el-dropdown-item v-if="skills.length === 0" disabled>
            <span class="empty">无可用技能</span>
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
  skills: { type: Array, default: () => [] },
  selectedId: { type: Number, default: null },
})

const emit = defineEmits(['select'])

const currentLabel = computed(() => {
  const found = props.skills.find(s => s.id === props.selectedId)
  return found?.name || '请选择'
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
.dot.skill { background: #67c23a; }

.label { color: #303133; font-weight: 500; }
.arrow { font-size: 12px; color: #909399; }

.skill-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 4px 0;
}
.skill-option .name { font-weight: 600; font-size: 14px; }
.skill-option .desc { font-size: 12px; color: #909399; margin-top: 2px; }

.empty {
  color: #c0c4cc;
  font-size: 13px;
}
</style>
