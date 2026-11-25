<template>
  <div class="knowledge-settings-page" v-loading="loading">
    <header class="page-heading">
      <div>
        <h1>知识库设置</h1>
        <p>配置百炼知识库和钉钉应用，供“知识库管理”上传文件和同步钉盘使用。密钥加密保存，保存后不再显示原文。</p>
      </div>
      <div class="heading-actions">
        <el-button :icon="Connection" :loading="testing" @click="testSettings">保存并测试连接</el-button>
        <el-button type="primary" :icon="DocumentChecked" :loading="saving" @click="saveSettings()">保存</el-button>
      </div>
    </header>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon class="block-alert" />
    <div v-if="testResult" class="test-result">
      <el-alert v-for="(item, key) in testResult" :key="key" :type="item.ok ? 'success' : 'error'" :closable="false" show-icon
        :title="`${key === 'bailian' ? '百炼' : '钉钉'}：${item.message}`" />
    </div>

    <section class="settings-section" aria-labelledby="bailian-title">
      <div class="section-heading">
        <h2 id="bailian-title">阿里云百炼</h2>
        <p>
          <el-tag :type="settings.bailian_configured ? 'success' : 'info'" effect="plain" size="small">{{ settings.bailian_configured ? '已配置' : '未配置' }}</el-tag>
          RAM 用户需要 AliyunBailianDataFullAccess 权限，并已加入对应业务空间。
        </p>
      </div>
      <el-form :model="form" label-position="top" class="settings-form">
        <el-form-item label="AccessKey ID">
          <el-input v-model="form.bailian_access_key_id" placeholder="RAM 用户的 AccessKey ID" autocomplete="off" />
        </el-form-item>
        <el-form-item label="AccessKey Secret">
          <el-input v-model="form.bailian_access_key_secret" type="password" show-password autocomplete="new-password"
            :placeholder="settings.bailian_access_key_secret_masked ? '已保存，留空表示不修改' : '请输入 AccessKey Secret'" />
        </el-form-item>
        <el-form-item label="业务空间 ID（WorkspaceId）">
          <el-input v-model="form.bailian_workspace_id" placeholder="例如 llm-xxxxxxxx" />
        </el-form-item>
        <el-form-item label="服务地址">
          <el-input v-model="form.bailian_endpoint" placeholder="bailian.cn-beijing.aliyuncs.com" />
        </el-form-item>
        <div class="form-row">
          <el-form-item label="默认知识库 ID">
            <el-input v-model="form.default_index_id" placeholder="例如 53zmggcvov" />
          </el-form-item>
          <el-form-item label="默认类目 ID">
            <el-input v-model="form.default_category_id" placeholder="可选，例如 cate_xxx" />
          </el-form-item>
        </div>
      </el-form>
    </section>

    <section class="settings-section" aria-labelledby="dingtalk-title">
      <div class="section-heading">
        <h2 id="dingtalk-title">钉钉应用（同步钉盘）</h2>
        <p>
          <el-tag :type="settings.dingtalk_configured ? 'success' : 'info'" effect="plain" size="small">{{ settings.dingtalk_configured ? '已配置' : '未配置' }}</el-tag>
          使用企业内部应用，用户扫码后以本人身份访问企业钉盘目录。
        </p>
      </div>
      <el-form :model="form" label-position="top" class="settings-form">
        <el-form-item label="Client ID（AppKey）">
          <el-input v-model="form.dingtalk_client_id" placeholder="企业内部应用的 Client ID" autocomplete="off" />
        </el-form-item>
        <el-form-item label="Client Secret（AppSecret）">
          <el-input v-model="form.dingtalk_client_secret" type="password" show-password autocomplete="new-password"
            :placeholder="settings.dingtalk_client_secret_masked ? '已保存，留空表示不修改' : '请输入 Client Secret'" />
        </el-form-item>
      </el-form>
      <div class="setup-notes">
        <strong>钉钉开发者后台需要完成</strong>
        <ol>
          <li>权限管理中开通：钉盘空间读权限（Drive.Space.Read，列出团队文件）、企业存储文件读写权限（Storage.File.Read、Storage.File.Write）、企业存储文件上传信息读权限（Storage.UploadInfo.Read）、知识库文档读权限（Document.WorkspaceDocument.Read，粘贴文件夹链接时用）、通讯录个人信息读权限。</li>
          <li>
            “登录与分享”中添加回调地址：
            <code>{{ callbackUrl }}</code>
            <el-button link type="primary" :icon="CopyDocument" @click="copyCallback">复制</el-button>
          </li>
          <li>发布应用版本，并确保使用者在应用可见范围内。</li>
        </ol>
      </div>
    </section>

    <section class="settings-section" aria-labelledby="access-title">
      <div class="section-heading">
        <h2 id="access-title">访问权限</h2>
        <p>按钉钉组织架构的一级部门开放；超级管理员始终可以。部门数据查不到时一律不放行。所有人都能浏览知识库文档和做检索测试。</p>
      </div>
      <el-form :model="form" label-position="top" class="settings-form">
        <el-form-item label="可以上传文件的部门">
          <el-select v-model="form.upload_departments" multiple filterable allow-create default-first-option
            :loading="departmentsLoading" placeholder="选择部门" class="department-select">
            <el-option v-for="name in departmentOptions" :key="name" :label="name" :value="name" />
          </el-select>
        </el-form-item>
        <el-form-item label="可以查看「知识库调用用量」看板的部门">
          <el-select v-model="form.usage_departments" multiple filterable allow-create default-first-option
            :loading="departmentsLoading" placeholder="选择部门" class="department-select">
            <el-option v-for="name in departmentOptions" :key="name" :label="name" :value="name" />
          </el-select>
        </el-form-item>
        <p v-if="departmentsError" class="department-hint">{{ departmentsError }}（仍可直接输入部门名称后回车）</p>
      </el-form>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, CopyDocument, DocumentChecked } from '@element-plus/icons-vue'
import { knowledgeApi, knowledgeErrorText } from '@/api/knowledge'

const callbackUrl = `${window.location.origin}/admin/knowledge/dingtalk-callback`
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null)
const settings = ref({})
const form = ref({})

function fillForm(value) {
  form.value = {
    bailian_endpoint: value.bailian_endpoint || 'bailian.cn-beijing.aliyuncs.com',
    bailian_access_key_id: value.bailian_access_key_id || '',
    bailian_access_key_secret: '',
    bailian_workspace_id: value.bailian_workspace_id || '',
    default_index_id: value.default_index_id || '',
    default_category_id: value.default_category_id || '',
    dingtalk_client_id: value.dingtalk_client_id || '',
    dingtalk_client_secret: '',
    upload_departments: [...(value.upload_departments || [])],
    usage_departments: [...(value.usage_departments || [])],
  }
}

const departmentOptions = ref([])
const departmentsLoading = ref(false)
const departmentsError = ref('')
async function loadDepartments() {
  departmentsLoading.value = true
  departmentsError.value = ''
  try {
    departmentOptions.value = (await knowledgeApi.getDepartmentOptions()).items || []
  } catch (err) {
    departmentsError.value = knowledgeErrorText(err, '部门列表加载失败')
  } finally { departmentsLoading.value = false }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    settings.value = await knowledgeApi.getSettings()
    fillForm(settings.value)
  } catch (err) {
    loadError.value = knowledgeErrorText(err, '知识库设置加载失败')
  } finally { loading.value = false }
}

async function saveSettings(silent = false) {
  saving.value = true
  try {
    settings.value = await knowledgeApi.saveSettings(form.value)
    fillForm(settings.value)
    if (!silent) ElMessage.success('知识库设置已保存')
    return true
  } catch (err) {
    ElMessage.error(knowledgeErrorText(err, '保存失败'))
    return false
  } finally { saving.value = false }
}

async function testSettings() {
  testing.value = true
  testResult.value = null
  try {
    if (!(await saveSettings(true))) return
    testResult.value = await knowledgeApi.testSettings()
  } catch (err) {
    ElMessage.error(knowledgeErrorText(err, '测试失败'))
  } finally { testing.value = false }
}

async function copyCallback() {
  try {
    await navigator.clipboard.writeText(callbackUrl)
    ElMessage.success('回调地址已复制')
  } catch {
    ElMessage.warning('复制失败，请手动复制')
  }
}

onMounted(() => { load(); loadDepartments() })
</script>

<style scoped>
.knowledge-settings-page { max-width: 1400px; margin: 0 auto; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.page-heading h1 { margin: 0; color: #1f2937; font-size: 24px; letter-spacing: 0; }
.page-heading p, .section-heading p { margin: 7px 0 0; color: #667085; font-size: 13px; }
.section-heading p { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.heading-actions { display: flex; gap: 10px; flex-shrink: 0; }
.block-alert { margin-bottom: 16px; }
.test-result { display: flex; flex-direction: column; gap: 8px; margin-bottom: 18px; }
.settings-section { border-top: 1px solid #e5e7eb; padding: 22px 0 10px; }
.section-heading h2 { margin: 0; color: #292d33; font-size: 16px; letter-spacing: 0; }
.settings-form { max-width: 560px; margin-top: 20px; }
.department-select { width: 100%; }
.department-hint { margin: -6px 0 12px; color: #b26b00; font-size: 12px; }
.form-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.setup-notes { max-width: 760px; margin: 4px 0 16px; padding: 14px 16px; border-radius: 6px; background: #f6f7f9; color: #4c5159; font-size: 13px; line-height: 1.8; }
.setup-notes ol { margin: 6px 0 0; padding-left: 20px; }
.setup-notes code { padding: 1px 6px; border-radius: 4px; background: #e9ebef; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .page-heading { flex-direction: column; }
  .form-row { grid-template-columns: 1fr; }
}
</style>
