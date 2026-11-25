<template>
  <span v-if="feedback?.rating === 'dislike'" class="feedback-actions">
    <el-button v-if="canAssign" :link="link" type="primary" @click="open('assignment')">分配处理人</el-button>
    <el-button :link="link" type="primary" @click="open('processing')">处理反馈</el-button>
  </span>
  <el-dialog v-model="visible" :title="mode === 'assignment' ? '分配处理人' : '处理反馈'" width="540px" :style="{ maxWidth: 'calc(100vw - 24px)' }" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" append-to-body>
    <el-form label-width="80px" :disabled="busy" @paste="pasteImages">
      <el-form-item v-if="mode === 'assignment'" label="处理人">
        <el-select v-model="assignee" clearable filterable remote :remote-method="searchPeople" :loading="peopleLoading" placeholder="搜索姓名或账号，可留空" @visible-change="value => value && searchPeople('')">
          <el-option v-for="person in people" :key="person.id" :value="Number(person.id)" :label="person.first_name || person.username" />
        </el-select>
      </el-form-item>
      <template v-else>
        <el-form-item label="处理状态"><el-select v-model="status"><el-option v-for="(label, value) in labels" :key="value" :value="value" :label="label" /></el-select></el-form-item>
        <el-form-item label="处理截图" tabindex="0" aria-label="处理截图，可按 Ctrl+V 粘贴图片">
          <el-upload :file-list="files" :http-request="upload" :on-remove="remove" :on-preview="preview" :limit="MAX_IMAGES" :on-exceed="exceed" accept="image/*" list-type="picture-card" :disabled="busy">
            <span>上传截图</span>
            <template #tip><div class="el-upload__tip">最多 10 张，每张不超过 3MB，支持直接粘贴图片（Ctrl+V）</div></template>
          </el-upload>
        </el-form-item>
        <el-form-item label="处理备注"><el-input v-model="remark" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="请填写处理情况或结果" /></el-form-item>
      </template>
    </el-form>
    <template #footer><el-button :disabled="busy" @click="visible = false">取消</el-button><el-button type="primary" :loading="busy" @click="save">保存</el-button></template>
  </el-dialog>
  <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" @close="previewUrl = ''" teleported />
</template>
<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, genFileId } from 'element-plus'
import { adminApi } from '@/api/admin'
import { feedbackApi } from '@/api/feedback'
import { uploadImage } from '@/api/upload'
import { normalizeProcessingStatus, processingLabels as labels } from '@/utils/feedback-status'
const props = defineProps({ feedback: Object, link: Boolean, canAssign: { type: Boolean, default: true } })
const emit = defineEmits(['saved'])
const router = useRouter()
const MAX_IMAGES = 10, MAX_IMAGE_BYTES = 3 * 1024 * 1024
const visible = ref(false), mode = ref('processing'), saving = ref(false), uploading = ref(0)
const busy = computed(() => saving.value || uploading.value > 0)
const assignee = ref(null), status = ref('pending'), remark = ref(''), files = ref([]), people = ref([]), peopleLoading = ref(false), previewUrl = ref('')
let peopleRequest = 0, generation = 0
const errorText = err => typeof err.response?.data?.detail === 'string' ? err.response.data.detail : '保存失败，请重试'
function open(value) {
  ++generation; ++peopleRequest
  mode.value = value; assignee.value = props.feedback.assignee_user_id; status.value = normalizeProcessingStatus(props.feedback.processing_status)
  remark.value = props.feedback.processing_remark || ''
  files.value = (props.feedback.processing_images || []).map((url, index) => ({ name: `截图 ${index + 1}`, url, status: 'success', uid: index }))
  people.value = assignee.value ? [{ id: assignee.value, first_name: props.feedback.assignee_name, username: props.feedback.assignee_username }] : []
  visible.value = true
}
async function searchPeople(search) {
  const request = ++peopleRequest; peopleLoading.value = true
  try {
    const result = await adminApi.getUsers({ search: search.trim() || undefined, limit: 50 })
    if (request !== peopleRequest) return
    const selected = people.value.find(person => Number(person.id) === assignee.value)
    const items = (result.items || result).filter(person => person.is_active !== false)
    people.value = selected && !items.some(person => Number(person.id) === assignee.value) ? [selected, ...items] : items
  } catch { if (request === peopleRequest) ElMessage.error('用户列表加载失败') }
  finally { if (request === peopleRequest) peopleLoading.value = false }
}
async function upload(options) {
  if (files.value.length + uploading.value >= MAX_IMAGES) {
    exceed(); options.onError(new Error('Image limit exceeded')); return
  }
  if (!options.file.type.startsWith('image/') || options.file.size > MAX_IMAGE_BYTES) {
    ElMessage.error('请选择不超过 3MB 的图片'); options.onError(new Error('Invalid image')); return
  }
  const request = generation; uploading.value++
  try {
    const result = await uploadImage(options.file, 'feedback')
    if (request !== generation) return
    files.value.push({ name: options.file.name, url: result.url, uid: options.file.uid, status: 'success' })
    options.onSuccess(result)
  } catch (err) { options.onError(err); ElMessage.error('截图上传失败，请重试') }
  finally { uploading.value-- }
}
async function pasteImages(event) {
  if (!visible.value || mode.value !== 'processing') return
  const images = Array.from(event.clipboardData?.items || [])
    .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
    .map(item => item.getAsFile()).filter(Boolean)
  if (!images.length) return
  event.preventDefault()
  if (busy.value) return
  const available = MAX_IMAGES - files.value.length
  if (images.length > available) exceed()
  for (const image of images.slice(0, available)) {
    const file = new File([image], image.name || '粘贴截图.png', { type: image.type })
    file.uid = genFileId()
    await upload({ file, onSuccess: () => {}, onError: () => {} })
  }
}
function remove(file) { files.value = files.value.filter(item => item.uid !== file.uid) }
function preview(file) { previewUrl.value = file.url }
function exceed() { ElMessage.warning('最多上传 10 张截图') }
async function save() {
  if (busy.value || !props.feedback) return
  saving.value = true
  try {
    const detail_url = new URL(router.resolve({ name: 'FeedbackDetail', params: { id: props.feedback.id } }).href, window.location.origin).toString()
    let result
    if (mode.value === 'assignment') {
      const person = people.value.find(item => Number(item.id) === assignee.value)
      result = await feedbackApi.assign(props.feedback.id, { assignee_user_id: assignee.value || null, assignee_username: person?.username || '', assignee_name: person?.first_name || person?.username || '', detail_url })
    } else {
      result = await feedbackApi.process(props.feedback.id, { processing_status: status.value, processing_remark: remark.value.trim(), processing_images: files.value.map(file => file.url), detail_url })
    }
    visible.value = false
    ElMessage.success(result.resolution_notification_sent ? '处理信息已保存，已通知反馈人' : result.notification_sent ? '分配已保存，已通知处理人' : '保存成功')
    emit('saved', result)
  } catch (err) { ElMessage.error(errorText(err)) }
  finally { saving.value = false }
}
onBeforeUnmount(() => { ++generation; ++peopleRequest })
</script>
<style scoped>
.feedback-actions { display: inline-flex; align-items: center; gap: 12px; }
.feedback-actions .el-button + .el-button { margin-left: 0; }
</style>
