<template>
  <div class="global-settings-page" v-loading="loading">
    <header class="page-heading">
      <div>
        <h1>全局设置</h1>
        <p>配置平台品牌信息和所有用户共用的技能环境变量。</p>
      </div>
      <el-button
        type="primary"
        :icon="DocumentChecked"
        :loading="saving"
        :disabled="!isDirty"
        @click="save"
      >
        保存品牌信息
      </el-button>
    </header>

    <section class="settings-section" aria-labelledby="brand-settings-title">
      <div class="section-heading">
        <h2 id="brand-settings-title">品牌信息</h2>
        <p>修改后将应用到所有用户的主侧栏。</p>
      </div>

      <div class="settings-layout">
        <el-form :model="form" label-position="top" class="settings-form">
          <el-form-item label="品牌图标" required>
            <div class="icon-field">
              <span class="brand-mark-preview" :class="{ compact: previewIconCompact }" aria-hidden="true">
                {{ preview.brand_icon }}
              </span>
              <el-input v-model="form.brand_icon" maxlength="8" placeholder="输入字母、文字或 emoji" />
            </div>
          </el-form-item>
          <el-form-item label="平台名称" required>
            <el-input v-model="form.brand_name" maxlength="100" placeholder="例如：AI Hub" />
          </el-form-item>
          <el-form-item label="名称小字" required>
            <el-input v-model="form.brand_subtitle" maxlength="100" placeholder="例如：合趣网络" />
          </el-form-item>
        </el-form>

        <div class="sidebar-preview" aria-label="侧栏品牌预览">
          <span class="preview-label">侧栏预览</span>
          <div class="preview-brand">
            <span class="preview-brand__mark" :class="{ compact: previewIconCompact }">{{ preview.brand_icon }}</span>
            <span class="preview-brand__copy">
              <strong>{{ preview.brand_name }}</strong>
              <small>{{ preview.brand_subtitle }}</small>
            </span>
            <el-icon><Fold /></el-icon>
          </div>
        </div>
      </div>
    </section>

    <section class="settings-section environment-section" aria-labelledby="environment-settings-title">
      <div class="environment-heading">
        <div class="section-heading">
          <h2 id="environment-settings-title">技能环境变量</h2>
          <p>所有用户运行技能脚本时自动读取，保存后从下一次运行生效，无需重启服务。</p>
          <p>变量名与脚本读取的名称保持一致，例如配置 <code>X_MCP_TOKEN</code>，Python 脚本中使用：</p>
          <pre class="environment-example"><code>import os
token = os.environ["X_MCP_TOKEN"]
user = os.environ.get("X_MCP_USER", "toolbox")</code></pre>
        </div>
        <div class="environment-actions">
          <el-button :icon="Plus" :disabled="!environmentLoaded || savingEnvironment || environmentRows.length >= 100" @click="addEnvironmentRow">添加环境变量</el-button>
          <el-button
            type="primary"
            :icon="DocumentChecked"
            :loading="savingEnvironment"
            :disabled="!isEnvironmentDirty || !environmentLoaded"
            @click="saveEnvironment"
          >保存环境变量</el-button>
        </div>
      </div>

      <div v-if="!environmentLoaded" class="environment-empty">
        <span>环境变量加载失败</span>
        <el-button link type="primary" @click="loadEnvironment">重新加载</el-button>
      </div>
      <template v-else>
        <el-empty v-if="!environmentRows.length" description="无" :image-size="56" />
        <div v-else class="environment-fields">
          <div v-for="(row, index) in environmentRows" :key="row.id" class="environment-row">
            <label>
              <span>变量名</span>
              <el-input v-model="row.name" :disabled="savingEnvironment" :aria-label="`变量名 ${index + 1}`" placeholder="例如：X_MCP_TOKEN" maxlength="128" />
            </label>
            <label>
              <span>变量值</span>
              <el-input v-model="row.value" :disabled="savingEnvironment" :aria-label="`变量值 ${index + 1}`" type="password" show-password autocomplete="new-password" placeholder="请输入变量值" />
            </label>
            <el-button :icon="Delete" :disabled="savingEnvironment" :aria-label="`删除环境变量 ${index + 1}`" @click="environmentRows.splice(index, 1)">删除</el-button>
          </div>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Delete, DocumentChecked, Fold, Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { enterpriseApi } from '@/api/enterprise'

const defaults = { brand_icon: 'H', brand_name: 'AI Hub', brand_subtitle: '合趣网络' }
const form = reactive({ ...defaults })
const loading = ref(false)
const saving = ref(false)
const savedSignature = ref('')
const environmentRows = ref([])
const environmentLoaded = ref(false)
const savingEnvironment = ref(false)
const savedEnvironmentSignature = ref('[]')
let nextEnvironmentId = 0

const environmentSignature = () => JSON.stringify(environmentRows.value.map(row => [row.name.trim(), row.value]))
const isEnvironmentDirty = computed(() => environmentSignature() !== savedEnvironmentSignature.value)
const addEnvironmentRow = () => environmentRows.value.push({ id: nextEnvironmentId++, name: '', value: '' })
const errorMessage = (error, fallback) => {
  const detail = error.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(item => item.msg).filter(Boolean).join('；') || fallback
  return detail?.message || fallback
}
const setEnvironment = result => {
  environmentRows.value = Object.entries(result.variables || {}).map(([name, value]) => ({ id: nextEnvironmentId++, name, value }))
  savedEnvironmentSignature.value = environmentSignature()
  environmentLoaded.value = true
}
const loadEnvironment = async () => {
  try {
    setEnvironment(await enterpriseApi.getGlobalRuntimeEnvironment())
  } catch (error) {
    ElMessage.error(errorMessage(error, '加载环境变量失败'))
  }
}
const saveEnvironment = async () => {
  const variables = Object.create(null)
  for (const row of environmentRows.value) {
    const name = row.name.trim()
    if (!/^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name)) {
      ElMessage.warning('变量名须以字母或下划线开头，仅包含字母、数字、下划线，最多 128 个字符')
      return
    }
    if (Object.hasOwn(variables, name)) {
      ElMessage.warning(`变量名 ${name} 重复，请修改后保存`)
      return
    }
    variables[name] = row.value
  }
  savingEnvironment.value = true
  try {
    setEnvironment(await enterpriseApi.updateGlobalRuntimeEnvironment({ variables }))
    ElMessage.success('环境变量已保存，下次运行技能时生效')
  } catch (error) {
    ElMessage.error(errorMessage(error, '保存环境变量失败'))
  } finally {
    savingEnvironment.value = false
  }
}

const payload = () => ({
  brand_icon: form.brand_icon.trim(),
  brand_name: form.brand_name.trim(),
  brand_subtitle: form.brand_subtitle.trim(),
})
const signature = () => JSON.stringify(payload())
const isDirty = computed(() => signature() !== savedSignature.value)
const preview = computed(() => ({
  brand_icon: form.brand_icon.trim() || defaults.brand_icon,
  brand_name: form.brand_name.trim() || defaults.brand_name,
  brand_subtitle: form.brand_subtitle.trim() || defaults.brand_subtitle,
}))
const previewIconCompact = computed(() => Array.from(preview.value.brand_icon).length > 2)

const load = async () => {
  loading.value = true
  try {
    Object.assign(form, defaults, await enterpriseApi.getGlobalSettings())
    savedSignature.value = signature()
  } catch (error) {
    const detail = error.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : (detail?.message || '加载全局设置失败'))
  } finally {
    loading.value = false
  }
}

const save = async () => {
  if (!form.brand_icon.trim() || !form.brand_name.trim() || !form.brand_subtitle.trim()) {
    ElMessage.warning('请完整填写品牌图标、平台名称和名称小字')
    return
  }
  saving.value = true
  try {
    const result = await enterpriseApi.updateGlobalSettings(payload())
    Object.assign(form, result)
    savedSignature.value = signature()
    window.dispatchEvent(new CustomEvent('aihub:global-settings-updated', { detail: result }))
    ElMessage.success('全局设置已保存')
  } catch (error) {
    const detail = error.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : (detail?.message || '保存失败'))
  } finally {
    saving.value = false
  }
}

onMounted(() => Promise.all([load(), loadEnvironment()]))
</script>

<style scoped>
.global-settings-page { max-width: 1400px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.page-heading h1 { margin: 0; color: #1f2937; font-size: 24px; letter-spacing: 0; }
.page-heading p, .section-heading p { margin: 7px 0 0; color: #667085; font-size: 13px; }
.settings-section { border-top: 1px solid #e5e7eb; padding-top: 22px; }
.section-heading h2 { margin: 0; color: #292d33; font-size: 16px; letter-spacing: 0; }
.settings-layout { display: grid; grid-template-columns: minmax(0, 520px) minmax(280px, 360px); gap: 56px; align-items: start; margin-top: 22px; }
.settings-form { width: 100%; }
.icon-field { width: 100%; display: flex; align-items: center; gap: 10px; }
.brand-mark-preview, .preview-brand__mark { display: grid; flex: 0 0 auto; place-items: center; overflow: hidden; color: #fff; background: #292d33; font-weight: 750; line-height: 1; white-space: nowrap; }
.brand-mark-preview { width: 32px; height: 32px; border-radius: 7px; font-size: 15px; }
.brand-mark-preview.compact, .preview-brand__mark.compact { font-size: 10px; }
.sidebar-preview { padding: 18px; border-left: 1px solid #e5e7eb; background: #fafafa; }
.preview-label { display: block; margin-bottom: 14px; color: #8b9098; font-size: 11px; }
.preview-brand { min-width: 0; display: flex; align-items: center; gap: 10px; }
.preview-brand__mark { width: 48px; height: 48px; border-radius: 10px; font-size: 18px; }
.preview-brand__copy { min-width: 0; display: flex; flex: 1; flex-direction: column; line-height: 1.25; }
.preview-brand__copy strong, .preview-brand__copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview-brand__copy strong { color: #202329; font-size: 17px; }
.preview-brand__copy small { margin-top: 3px; color: #7d828a; font-size: 11px; }
.preview-brand > .el-icon { flex: 0 0 auto; color: #858a91; }
.environment-section { margin-top: 32px; padding-bottom: 24px; }
.environment-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 22px; }
.environment-heading .section-heading { min-width: 0; }
.environment-actions { display: flex; flex-shrink: 0; align-items: center; }
.environment-example { margin: 12px 0 0; padding: 12px 16px; overflow-x: auto; border-radius: 6px; background: #f4f5f7; color: #344054; font-size: 13px; line-height: 1.7; }
.section-heading code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.environment-fields { display: grid; gap: 14px; margin-bottom: 18px; }
.environment-row { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(200px, 2fr) auto; align-items: end; gap: 12px; }
.environment-row label { display: grid; gap: 7px; color: #606266; font-size: 13px; }
.environment-empty { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 32px; color: #667085; }
@media (max-width: 760px) {
  .page-heading { align-items: stretch; flex-direction: column; }
  .settings-layout { grid-template-columns: 1fr; gap: 28px; }
  .sidebar-preview { border-top: 1px solid #e5e7eb; border-left: 0; }
  .environment-heading { align-items: stretch; flex-direction: column; }
  .environment-actions { flex-wrap: wrap; gap: 8px; }
  .environment-actions .el-button + .el-button { margin-left: 0; }
  .environment-row { grid-template-columns: minmax(0, 1fr); padding-bottom: 16px; border-bottom: 1px solid #e5e7eb; }
  .environment-row > .el-button { justify-self: start; }
}
</style>
