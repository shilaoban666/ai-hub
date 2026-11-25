<template>
  <span class="message-feedback" aria-label="回复评价">
    <el-tooltip :content="!messageId ? '回复保存后可反馈' : value?.rating === 'like' ? '撤回点赞' : '点赞'" placement="bottom">
      <el-button text circle class="msg-action-btn feedback-button" :class="{ selected: value?.rating === 'like' }"
        :disabled="busy || !messageId" :aria-pressed="value?.rating === 'like'" aria-label="点赞" @click="like">
        <el-icon><svg viewBox="1 1 22 22" aria-hidden="true"><path d="M7 10H3v11h4V10Zm0 0 5-7c2 0 3 1 2 4l-1 3h6c2 0 2 2 1.5 3.5l-2 6c-.3 1-1 1.5-2 1.5H7" /><path v-if="value?.rating === 'like'" class="wrist-divider" d="M7 10v11" /></svg></el-icon>
      </el-button>
    </el-tooltip>
    <el-popover :visible="open" placement="top" :width="380" :popper-style="{ maxWidth: 'calc(100vw - 24px)' }">
      <template #reference>
        <span class="feedback-trigger">
          <el-tooltip :content="!messageId ? '回复保存后可反馈' : value?.rating === 'dislike' ? '撤回点踩' : '点踩'" placement="bottom" :disabled="open">
            <el-button text circle class="msg-action-btn feedback-button" :class="{ selected: value?.rating === 'dislike' }"
              :disabled="busy || !messageId" :aria-pressed="value?.rating === 'dislike'" aria-label="点踩" @click="dislike">
              <el-icon><svg viewBox="1 1 22 22" class="thumb-down" aria-hidden="true"><path d="M7 10H3v11h4V10Zm0 0 5-7c2 0 3 1 2 4l-1 3h6c2 0 2 2 1.5 3.5l-2 6c-.3 1-1 1.5-2 1.5H7" /><path v-if="value?.rating === 'dislike'" class="wrist-divider" d="M7 10v11" /></svg></el-icon>
            </el-button>
          </el-tooltip>
        </span>
      </template>
      <section class="feedback-form" aria-label="不满意原因">
        <header><strong>不满意的原因（可选）</strong><el-button text :icon="Close" aria-label="关闭反馈" :disabled="busy" @click="open = false" /></header>
        <div class="reason-options">
          <button v-for="reason in options" :key="reason" type="button" :class="{ selected: reasons.includes(reason) }"
            :aria-pressed="reasons.includes(reason)" :disabled="busy" @click="toggle(reason)">{{ reason }}</button>
        </div>
        <el-input v-model="comment" type="textarea" :rows="3" maxlength="2000" show-word-limit
          :disabled="busy" placeholder="补充说明（可选）" aria-label="反馈补充说明" />
        <el-button class="submit-feedback" type="primary" :loading="busy" :disabled="busy"
          @click="submit({ rating: 'dislike', reasons, comment })">提交反馈</el-button>
      </section>
    </el-popover>
  </span>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { feedbackApi } from '@/api/feedback'

const props = defineProps({ messageId: { type: Number, default: null }, feedback: { type: Object, default: null } })
const emit = defineEmits(['change'])
const value = ref(props.feedback)
const open = ref(false)
const busy = ref(false)
const reasons = ref([])
const comment = ref('')
const options = ['误解了我的问题', '上下文理解错误', '回答模糊/不具体', '代码有错误', '回答不专业', '代码格式问题', '其他原因']
watch(() => props.feedback, feedback => { value.value = feedback })
function toggle(reason) { reasons.value = reasons.value.includes(reason) ? reasons.value.filter(item => item !== reason) : [...reasons.value, reason] }
function like() { open.value = false; submit(value.value?.rating === 'like' ? null : { rating: 'like' }) }
function dislike() {
  if (value.value?.rating === 'dislike') { open.value = false; return submit(null) }
  reasons.value = []; comment.value = ''; open.value = !open.value
}
async function submit(body) {
  if (busy.value || !props.messageId) return
  busy.value = true
  try {
    const result = body ? await feedbackApi.save(props.messageId, body) : await feedbackApi.remove(props.messageId)
    value.value = body ? result : null
    emit('change', value.value)
    open.value = false
    ElMessage.success(body ? '感谢反馈，已记录' : '已撤回反馈')
  } catch (error) {
    const detail = error.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : detail?.message || '反馈提交失败，请重试')
  } finally { busy.value = false }
}
</script>

<style scoped>
.message-feedback { display: inline-flex; align-items: center; gap: 2px; }
.feedback-trigger { display: inline-flex; }
.feedback-button svg { fill: none; stroke: currentColor; stroke-width: 1.4; stroke-linejoin: round; stroke-linecap: round; }
.thumb-down { transform: rotate(180deg); }
.feedback-button.selected svg { fill: #505050; stroke: #505050; }
.feedback-button.selected .wrist-divider { fill: none; stroke: var(--el-bg-color, #fff); stroke-width: 1.6; stroke-linecap: butt; }
.feedback-form header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.reason-options { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.reason-options button { border: 1px solid #e2e4e8; border-radius: 6px; padding: 7px 10px; background: white; color: #454b54; cursor: pointer; }
.reason-options button.selected { color: #2563eb; background: #eff6ff; border-color: #93b4ed; }
.submit-feedback { width: 100%; margin-top: 12px; }
</style>
