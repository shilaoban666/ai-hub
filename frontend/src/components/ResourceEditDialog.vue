<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    :width="width"
    top="6vh"
    append-to-body
    destroy-on-close
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    @update:model-value="handleVisibility"
  >
    <div class="resource-edit-body"><slot /></div>
    <template #footer>
      <el-button :disabled="saving" @click="handleVisibility(false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="$emit('save')">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
const props = defineProps({
  modelValue: Boolean,
  title: { type: String, required: true },
  width: { type: String, default: 'min(760px, calc(100vw - 32px))' },
  saving: Boolean,
})
const emit = defineEmits(['update:modelValue', 'cancel', 'save'])
const handleVisibility = (visible) => {
  if (!visible && props.saving) return
  if (!visible) emit('cancel')
  emit('update:modelValue', visible)
}
</script>

<style scoped>
.resource-edit-body {
  max-height: calc(88dvh - 140px);
  overflow-y: auto;
  padding: 4px 12px 4px 2px;
}
</style>
