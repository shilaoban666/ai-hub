<template>
  <el-card v-loading="loading" class="open-call" shadow="never">
    <template #header>
      <div class="card-header">
        <span>开放调用</span>
        <el-tag :type="savedEnabled ? 'success' : 'info'">{{ savedEnabled ? '已开启' : '已关闭' }}</el-tag>
      </div>
    </template>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false">
      <el-button link type="primary" @click="load">重新加载</el-button>
    </el-alert>
    <template v-else-if="loaded">
      <el-form-item label="允许程序调用">
        <el-switch :model-value="savedEnabled" :loading="saving" :before-change="save" aria-label="允许程序调用" />
        <div class="hint">凭密钥调用，无需登录。自动使用智能体已保存的主提示词、技能和连接器，积分计入你的账户。</div>
      </el-form-item>

      <template v-if="savedEnabled">
        <el-divider />
        <el-form-item label="调用地址">
          <div class="value-row"><code>{{ endpoint }}</code><el-button link type="primary" @click="copy(endpoint)">复制</el-button></div>
        </el-form-item>
        <el-form-item label="调用密钥">
          <div class="value-row">
            <el-input v-if="sessionKey" :model-value="sessionKey" type="password" show-password readonly aria-label="本次生成的调用密钥" />
            <el-tag v-else type="success">已配置</el-tag>
            <el-button v-if="sessionKey" link type="primary" @click="copy(sessionKey)">复制密钥</el-button>
            <el-button :loading="saving" :disabled="loading" @click="rotate">重置密钥</el-button>
          </div>
          <div class="hint">{{ sessionKey ? '请保存密钥；离开页面后无法再次查看。' : '密钥已配置，明文仅在生成时展示；如未保存，请重置。' }}重置后，旧密钥及其结果查询立即失效，正在执行的调用将停止。</div>
        </el-form-item>
        <el-form-item label="请求示例">
          <div class="example-block">
            <div class="example-actions"><span>POST · JSON</span><el-button link type="primary" @click="copy(curlExample)">复制示例</el-button></div>
            <pre>{{ curlExample }}</pre>
          </div>
          <div class="hint">skill 和 prompt 均可省略：默认按智能体的主提示词执行，可从全部绑定技能中按需选择。需要网页登录或人工确认的连接器仅在网页对话中可用。长任务返回 202 和 status_url，使用同一密钥查询。</div>
        </el-form-item>
        <el-form-item v-if="queryEnabled" label="拼参调用 URL">
          <div class="value-row"><code>{{ queryUrl }}</code><el-button link type="primary" @click="copy(queryUrl)">复制</el-button></div>
          <div class="hint">使用 POST 请求此 URL。外部入口应已配置查询参数日志脱敏。</div>
        </el-form-item>
        <el-form-item label="重试与限制">
          <span>重试时携带相同的 Idempotency-Key 可避免重复执行。每个智能体最多 4 个待完成任务，每分钟最多发起 20 次调用。</span>
        </el-form-item>
      </template>
    </template>
  </el-card>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api/request'
import { copyToClipboard } from '@/utils/clipboard'
import { useAgentOpenCall } from '@/composables/useAgentOpenCall'

const props = defineProps({ agentId: { type: [Number, String], required: true } })
const openCall = useAgentOpenCall()
const loading = ref(false)
const loaded = ref(false)
const saving = ref(false)
const loadError = ref('')
const savedEnabled = ref(false)
const sessionKey = ref('')
const queryEnabled = ref(false)
const path = ref('')
let loadSequence = 0

const endpoint = computed(() => path.value ? new URL(path.value, window.location.origin).href : '无')
const exampleBody = { prompt: '请介绍你能帮我完成哪些任务' }
const shellQuote = value => "'" + value.replaceAll("'", "'\\''") + "'"
const curlExample = computed(() => [
  'curl -X POST ' + shellQuote(endpoint.value),
  '  -H ' + shellQuote('X-Agent-Key: ' + (sessionKey.value || '<已保存的密钥>')),
  "  -H 'Content-Type: application/json'",
  "  -H 'Idempotency-Key: <每个新任务使用唯一值>'",
  '  --data ' + shellQuote(JSON.stringify(exampleBody)),
].join(' \\\n'))
const queryUrl = computed(() => {
  const url = new URL(endpoint.value)
  url.searchParams.set('session_key', sessionKey.value || '<已保存的密钥>')
  url.searchParams.set('prompt', exampleBody.prompt)
  return url.href
})

const apply = data => {
  savedEnabled.value = data.enabled
  openCall?.update(props.agentId, data.enabled)
  queryEnabled.value = data.query_enabled
  path.value = data.path
  if (data.session_key) sessionKey.value = data.session_key
  if (!data.enabled) sessionKey.value = ''
}
const load = async () => {
  const sequence = ++loadSequence
  loading.value = true
  loadError.value = ''
  try {
    const data = await api.get('/agents/' + props.agentId + '/open-call')
    if (sequence !== loadSequence) return
    apply(data)
    loaded.value = true
  } catch (error) {
    if (sequence === loadSequence) loadError.value = error.response?.data?.detail || '开放调用设置加载失败'
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}
const save = async () => {
  const sequence = loadSequence
  const enabled = !savedEnabled.value
  saving.value = true
  try {
    const data = await api.put('/agents/' + props.agentId + '/open-call', { enabled })
    if (sequence === loadSequence) {
      apply(data)
      ElMessage.success(enabled ? '开放调用已开启' : '开放调用已关闭')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '更新开放调用失败')
  } finally {
    saving.value = false
  }
  // The switch is controlled by the server response through savedEnabled.
  return false
}
const rotate = async () => {
  try {
    await ElMessageBox.confirm('重置后旧密钥立即失效，旧任务将停止且不能再通过新密钥查询。是否重置？', '重置调用密钥', { type: 'warning' })
  } catch { return }
  saving.value = true
  try {
    apply(await api.post('/agents/' + props.agentId + '/open-call/rotate'))
    ElMessage.success('新密钥已生成，请及时保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重置失败')
  } finally {
    saving.value = false
  }
}
const copy = async value => {
  try {
    await copyToClipboard(value)
    ElMessage.success('已复制')
  } catch { ElMessage.error('复制失败，请手动复制') }
}
onMounted(load)
watch(() => props.agentId, () => {
  sessionKey.value = ''
  loaded.value = false
  load()
})
</script>

<style scoped>
.card-header, .value-row, .example-actions { display: flex; align-items: center; gap: 12px; }
.card-header, .example-actions { justify-content: space-between; }
.value-row { width: 100%; flex-wrap: wrap; min-width: 0; }
.value-row .el-input { flex: 1; min-width: 180px; }
code { overflow-wrap: anywhere; font-size: 12px; }
.example-block { width: 100%; }
.hint { width: 100%; margin-top: 6px; font-size: 12px; line-height: 1.65; color: var(--el-text-color-secondary); }
.example-block { min-width: 0; padding: 12px; background: var(--el-fill-color-light); border-radius: 6px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; margin: 8px 0 0; font-size: 12px; line-height: 1.7; }
</style>
