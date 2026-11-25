<template>
  <div class="avatar-setting">
    <div class="avatar-setting-summary">
      <div class="icon-preview" :class="{ 'has-icon': hasIcon }">
        <span v-if="hasIcon" class="icon-emoji-large" :class="{ 'image-icon': getAssistantImage(modelValue) }"><AssistantIcon :icon="modelValue" /></span>
        <span v-else class="icon-placeholder">无</span>
      </div>
      <div class="avatar-setting-copy">
        <div class="avatar-setting-heading">
          <span class="avatar-setting-title">{{ hasIcon ? '已设置头像' : '无' }}</span>
          <el-button :disabled="disabled" text type="primary" :aria-expanded="pickerOpen" @click="pickerOpen = !pickerOpen">
            {{ pickerOpen ? '收起' : '更换头像' }}
          </el-button>
        </div>
        <span>列表名片会展示这个头像</span>
      </div>
    </div>
    <el-collapse-transition>
      <div v-show="pickerOpen" class="icon-picker">
        <fieldset :disabled="disabled || uploading" class="picker-controls">
          <div class="icon-grid">
            <button v-for="emoji in emojiOptions" :key="emoji" type="button" class="icon-option"
              :class="{ selected: modelValue === emoji }" :aria-pressed="modelValue === emoji"
              @click="$emit('update:modelValue', emoji)">{{ emoji }}</button>
          </div>
          <AssistantCharacterPicker :model-value="modelValue" :disabled="disabled || uploading" :show-characters="showCharacters"
            @update:model-value="value => $emit('update:modelValue', value)" @uploading="handleUploading" />
        </fieldset>
      </div>
    </el-collapse-transition>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import AssistantIcon from '@/components/AssistantIcon.vue'
import AssistantCharacterPicker from '@/components/AssistantCharacterPicker.vue'
import { getAssistantImage } from '@/config/assistant-characters'

const props = defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  showCharacters: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'uploading'])
const pickerOpen = ref(false)
const uploading = ref(false)
const hasIcon = computed(() => Boolean(props.modelValue?.trim()))
function handleUploading(value) {
  uploading.value = value
  emit('uploading', value)
}

const emojiOptions = [
  '🤖', '🧠', '💬', '✨', '🚀', '💡', '🔧', '🛠️', '📝', '💻',
  '🎯', '⚡', '🔍', '📊', '🗂️', '🔮', '🎨', '🏆', '💎', '🌟',
  '🔥', '⭐', '🦾', '💪', '🧩', '🎵', '📚', '🏥', '💰', '🛡️',
  '🔒', '🗣️', '🌐', '📡', '🧪', '🎮', '🏗️', '📋', '✅', '❤️',
  '🐱', '🐶', '🦊', '🐼', '🐙', '👾', '🎭', '🧭', '💊', '📦',
  '☁️', '🐳', '🔌', '🎪', '🧲', '🫧', '🧿', '🔆', '🎛️', '🪄',
]
</script>

<style scoped>
.avatar-setting {
  width: 100%;
}

.avatar-setting-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 58px;
}

.avatar-setting-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.avatar-setting-heading {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0 12px;
  line-height: 22px;
}

.avatar-setting-heading > .el-button {
  margin: 0;
  padding: 0;
  height: 22px;
}

.avatar-setting-title {
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 400;
}

.avatar-setting-copy > span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 18px;
}

.icon-picker {
  width: 100%;
  margin-top: 12px;
  padding-top: 14px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.icon-preview {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px dashed #dcdfe6;
  border-radius: 8px;
  margin-bottom: 10px;
  background: #fafafa;
  transition: all 0.2s;
}

.icon-preview.has-icon {
  border-style: solid;
  border-color: #7F77DD;
  background: #f5f3ff;
}

.icon-emoji-large.image-icon { display:block; width:48px; height:48px; }
.icon-preview:has(.image-icon) { background:transparent; border-color:transparent; }
.icon-emoji-large {
  font-size: 32px;
  line-height: 1;
}

.icon-placeholder {
  font-size: 20px;
  color: #c0c4cc;
}

.icon-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: 480px;
  margin-bottom: 16px;
}

.icon-option {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  transition: all 0.15s;
  padding: 0;
}

.icon-option:hover {
  border-color: #7F77DD;
  background: #f5f3ff;
  transform: scale(1.15);
}

.icon-option.selected {
  border-color: #7F77DD;
  background: #e8e4ff;
  box-shadow: 0 0 0 2px rgba(127, 119, 221, 0.3);
}

.picker-controls { min-width: 0; margin: 0; padding: 0; border: 0; }
.icon-option:disabled { cursor: not-allowed; opacity: 0.6; }
</style>
