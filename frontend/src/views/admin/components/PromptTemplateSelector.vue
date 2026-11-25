<template>
  <div class="template-selector">
    <el-dropdown trigger="click" @command="handleSelect">
      <span class="trigger">
        <span class="dot template"></span>
        <span class="label">{{ currentLabel }}</span>
        <el-icon class="arrow"><ArrowDown /></el-icon>
      </span>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item
            v-for="t in templates"
            :key="t.id"
            :command="t"
          >
            <div class="template-option">
              <div>
                <div class="name">{{ t.name }}</div>
                <div class="desc">{{ t.category }}<span v-if="t.author"> · {{ t.author }}</span></div>
              </div>
            </div>
          </el-dropdown-item>
          <el-dropdown-item v-if="templates.length === 0" disabled>
            <span class="empty">无可用提示词模板</span>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup>
import { ArrowDown } from '@element-plus/icons-vue'

const emit = defineEmits(['select'])

defineProps({
  templates: { type: Array, default: () => [] },
})

// 选完即填入输入框，选择器本身不保持选中态，统一显示"请选择"，与模型/技能选择器一致
const currentLabel = '请选择'

const handleSelect = (template) => {
  emit('select', template)
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
.dot.template { background: #b37feb; }

.label { color: #303133; font-weight: 500; }
.arrow { font-size: 12px; color: #909399; }

.template-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 4px 0;
}
.template-option .name { font-weight: 600; font-size: 14px; }
.template-option .desc { font-size: 12px; color: #909399; margin-top: 2px; }

.empty {
  color: #c0c4cc;
  font-size: 13px;
}
</style>
