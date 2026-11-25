<template>
  <div class="character-picker">
    <div class="character-options" role="group" aria-label="头像选择">
      <button v-for="item in characters" :key="item.id" type="button"
        class="character-choice" :class="{ selected: modelValue === item.id }"
        :disabled="disabled" :aria-pressed="modelValue === item.id" @click="$emit('update:modelValue', item.id)">
        <img :src="item.src" alt="" /><span>{{ item.name }}</span>
      </button>
      <button v-if="allowText" type="button" class="character-choice custom-choice" :class="{ selected: !image }"
        :disabled="disabled" :aria-pressed="!image" @click="useCustom">
        <span class="custom-symbol">Aa</span><span>文字 / Emoji</span>
      </button>
      <button type="button" class="character-choice" :class="{ selected: image && !character }"
        :disabled="disabled || uploading" :aria-pressed="!!image && !character" @click="fileInput.click()">
        <img v-if="image && !character" :src="image" alt="" /><span v-else class="custom-symbol">＋</span>
        <span>{{ uploading ? '上传中…' : '上传图片' }}</span>
      </button>
    </div>
    <input ref="fileInput" type="file" :disabled="disabled || uploading" accept=".png,.jpg,.jpeg,.gif,.webp,.ico,.svg" hidden @change="upload" />
    <span class="upload-hint">建议使用透明背景，图片尽量控制在 100KB 以内，最大 200KB，请勿上传过大的图片或动图。支持 PNG、JPG、GIF、WebP、ICO、SVG。</span>
    <el-input v-if="allowText && !image" :disabled="disabled" :model-value="modelValue" maxlength="8"
      placeholder="输入字母、文字或 emoji" @update:model-value="value => $emit('update:modelValue', value)" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadImage } from '@/api/upload'
import { ASSISTANT_CHARACTERS, getAssistantCharacter, getAssistantImage } from '@/config/assistant-characters'
const props = defineProps({
  modelValue: { type: String, default: 'H' },
  allowText: { type: Boolean, default: true },
  showCharacters: { type: Boolean, default: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'uploading'])
const characters = computed(() => props.showCharacters ? ASSISTANT_CHARACTERS : [])
const character = computed(() => getAssistantCharacter(props.modelValue))
const image = computed(() => getAssistantImage(props.modelValue))
const fileInput = ref(null)
const uploading = ref(false)
const customIcon = ref('H')
watch(() => props.modelValue, value => {
  if (!getAssistantImage(value)) customIcon.value = value
}, { immediate: true })
function useCustom() { emit('update:modelValue', customIcon.value) }
async function upload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || props.disabled) return
  if (file.size > 200 * 1024) {
    ElMessage.warning('图片不能超过 200KB，请压缩后再上传'); return
  }
  if (!/\.(png|jpe?g|gif|webp|ico|svg)$/i.test(file.name)) {
    ElMessage.warning('请选择 PNG、JPG、GIF、WebP、ICO 或 SVG 图片'); return
  }
  uploading.value = true
  emit('uploading', true)
  try {
    const result = await uploadImage(file, 'assistant')
    if (!getAssistantImage(result.url)) throw new Error('图片地址无效')
    emit('update:modelValue', result.url)
  } catch (error) { ElMessage.error(error.message || '上传失败，请重试') }
  finally { uploading.value = false; emit('uploading', false) }
}
</script>

<style scoped>
.character-picker { width: 100%; display: flex; flex-direction: column; gap: 10px; }
.character-options { display: flex; flex-wrap: wrap; gap: 10px; }
.character-choice { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; width: 100px; min-height: 96px; padding: 10px; border: 1px solid #dce3ec; border-radius: 10px; background: transparent; color: #536579; font: inherit; font-size: 12px; cursor: pointer; }
.character-choice img { width: 48px; height: 48px; object-fit: contain; }
.character-choice:hover, .character-choice.selected { border-color: #72afe1; background: #f1f7fe; }
.character-choice:focus-visible { outline: 2px solid #5799d4; outline-offset: 2px; }
.character-choice:disabled { cursor: not-allowed; opacity: 0.6; }
.custom-symbol { display: grid; place-items: center; width: 48px; height: 48px; font-size: 24px; color: #64748b; }
.upload-hint { color: #8a96a5; font-size: 12px; line-height: 1.5; }
</style>
