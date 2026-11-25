<template>
  <div class="skill-list">
    <div class="header">
      <h2>技能管理</h2>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索技能名称、作者或适用角色"
          clearable
          @input="handleSearch"
          style="width: 300px; margin-right: 12px;"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="handleCreate">
          <el-icon><Plus /></el-icon>
          新建技能
        </el-button>
        <el-button type="success" @click="handleImport">
          <el-icon><Upload /></el-icon>
          导入技能
        </el-button>
      </div>
    </div>

    <el-row :gutter="20" v-loading="loading">
      <el-col
        :xs="24"
        :sm="12"
        :md="8"
        :lg="6"
        v-for="skill in skills"
        :key="skill.id"
        style="margin-bottom: 20px;"
      >
        <el-card
          class="skill-card"
          shadow="hover"
          @click="handleSelect(skill)"
        >
          <el-tag
            v-if="!isSkillOwner(skill)"
            class="collaboration-badge"
            size="small"
            type="primary"
          >
            协作技能
          </el-tag>
          <div class="skill-cover" v-if="skill.cover">
            <img :src="skill.cover" alt="cover" />
            <div class="cover-overlay" @click.stop>
              <el-button
                type="primary"
                :icon="Picture"
                size="small"
                @click="handleChangeCover(skill)"
              >
                更换
              </el-button>
              <el-button
                type="danger"
                :icon="Delete"
                size="small"
                @click="handleDeleteCover(skill)"
                style="margin-left: 8px;"
              >
                删除
              </el-button>
            </div>
          </div>
          <div class="skill-icon" v-else>
            <el-icon :size="48" v-if="!skill.icon">
              <SkillIcon />
            </el-icon>
            <img v-else :src="skill.icon" alt="icon" />
            <div class="icon-overlay" @click.stop>
              <el-button
                type="primary"
                :icon="Picture"
                size="small"
                @click="handleChangeCover(skill)"
              >
                更换
              </el-button>
            </div>
          </div>
          <div class="skill-info">
            <h3>{{ skill.name }}</h3>
            <div class="skill-meta">
              <span class="meta-item">版本：{{ skill.version?.trim() || '无版本' }}</span>
              <span class="meta-item meta-center">作者：{{ skill.author || '无' }}</span>
            </div>
            <p class="description">描述：{{ skill.description || '无' }}</p>
            <div class="skill-module">
              <span>业务模块：</span><SkillMetadataTags :model-value="skill.module" />
            </div>
            <div class="skill-roles">
              <span>适用角色：</span><SkillMetadataTags :model-value="skill.roles" field="roles" />
            </div>
          </div>

          <div class="skill-actions" @click.stop>
            <el-tooltip :content="skill.is_public ? '公开' : '私有'" placement="top">
              <el-button
                :type="skill.is_public ? 'success' : 'info'"
                :icon="skill.is_public ? View : Hide"
                link
                size="small"
                @click="handleToggleVisibility(skill)"
              />
            </el-tooltip>
            <el-button
              type="primary"
              :icon="Edit"
              link
              size="small"
              @click="handleEdit(skill)"
            />
            <el-button
              v-if="isSkillOwner(skill)"
              type="danger"
              :icon="Delete"
              link
              size="small"
              @click="handleDelete(skill)"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!loading && (!skills || skills.length === 0)" description="暂无数据" />

    <!-- 分页 -->
    <div class="pagination-container" v-if="!loading && skills && skills.length > 0">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next, jumper"
        @current-change="handlePageChange"
      />
    </div>

    <!-- 添加技能对话框 -->
    <el-dialog
      v-model="createDialogVisible"
      title="新建技能"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-radio-group v-model="createMode" style="margin-bottom: 20px;">
        <el-radio-button value="manual">手工创建</el-radio-button>
        <el-radio-button value="git">Git 仓库</el-radio-button>
      </el-radio-group>

      <!-- 手工创建表单 -->
      <el-form
        v-if="createMode === 'manual'"
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-width="80px"
      >
        <el-form-item label="技能名称" prop="name">
          <el-input v-model="createForm.name" placeholder="请输入技能名称" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="3"
            placeholder="请输入描述"
          />
        </el-form-item>
        <el-form-item label="版本" prop="version">
          <el-input v-model="createForm.version" placeholder="请输入版本号" />
        </el-form-item>
        <el-form-item label="作者" prop="author">
          <el-input v-model="createForm.author" placeholder="请输入作者" disabled />
        </el-form-item>
        <el-form-item label="业务模块" prop="module">
          <SkillMetadataTags v-model="createForm.module" editable :disabled="creating" />
        </el-form-item>
        <el-form-item label="适用角色" prop="roles">
          <SkillMetadataTags v-model="createForm.roles" field="roles" editable :disabled="creating" />
        </el-form-item>
      </el-form>

      <!-- Git 仓库表单 -->
      <el-form
        v-if="createMode === 'git'"
        ref="gitFormRef"
        :model="gitForm"
        :rules="gitRules"
        label-width="80px"
        autocomplete="off"
      >
        <el-form-item label="服务商">
          <el-radio-group v-model="gitForm.provider">
            <el-radio-button value="gitlab">GitLab</el-radio-button>
            <el-radio-button value="github">GitHub</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="仓库地址" prop="repo_url">
          <el-input
            v-model="gitForm.repo_url"
            :placeholder="gitForm.provider === 'github' ? 'https://github.com/user/repo.git' : 'https://gitlab.example.com/user/repo.git'"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item label="访问令牌">
          <el-input
            v-model="gitForm.access_token"
            placeholder="公开仓库可留空，私有仓库需填写"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item label="分支">
          <el-radio-group v-model="gitForm.branch" style="margin-bottom: 8px;">
            <el-radio value="main">main</el-radio>
            <el-radio value="master">master</el-radio>
            <el-radio value="custom">其他</el-radio>
          </el-radio-group>
          <el-input
            v-if="gitForm.branch === 'custom'"
            v-model="gitForm.branch_custom"
            placeholder="请输入分支名"
          />
        </el-form-item>
        <el-form-item>
          <el-button @click="handleTestConnection" :loading="gitTesting" :type="gitTestResult?.success ? 'success' : 'primary'">
            {{ gitTestResult?.success ? '连接成功' : '测试连接' }}
          </el-button>
          <span v-if="gitTestResult?.success" style="margin-left: 8px; color: #67c23a; font-size: 13px;">
            {{ gitTestResult.project_name }}
          </span>
          <span v-if="gitTestResult && !gitTestResult.success" style="margin-left: 8px; color: #f56c6c; font-size: 13px;">
            {{ gitTestResult.message }}
          </span>
        </el-form-item>
        <el-alert type="info" :closable="false" style="margin-bottom: 12px;">
          创建后将自动从仓库拉取文件，技能名称等信息从 SKILL.md 中解析。
        </el-alert>
      </el-form>

      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleConfirmCreate" :loading="creating">
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- 导入技能对话框 -->
    <el-dialog
      v-model="importDialogVisible"
      title="导入技能"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-upload
        ref="uploadRef"
        class="upload-demo"
        drag
        :auto-upload="false"
        :limit="1"
        :on-change="handleFileChange"
        :on-exceed="handleExceed"
        accept=".md,.zip"
      >
        <el-icon class="el-icon--upload"><upload-filled /></el-icon>
        <div class="el-upload__text">
          将文件拖到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            只能上传 SKILL.md 文件或包含 SKILL.md 的 zip 压缩包
          </div>
        </template>
      </el-upload>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleConfirmImport" :loading="importing">
          确定导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { skillsApi } from '@/api/skills'
import { gitApi } from '@/api/git'
import { useAuthStore } from '@/stores/auth'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, UploadFilled, Search, Picture, View, Hide, Connection } from '@element-plus/icons-vue'
import { showError } from '@/utils/error'
import JSZip from 'jszip'
import SkillMetadataTags from '@/components/SkillMetadataTags.vue'
import SkillIcon from '@/components/icons/SkillIcon.vue'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const skills = ref([])
const currentPage = ref(1)
const pageSize = ref(12)
const total = ref(0)
const searchKeyword = ref('')
let searchTimer = null
const createDialogVisible = ref(false)
const creating = ref(false)
const createFormRef = ref(null)
const importDialogVisible = ref(false)
const importing = ref(false)
const uploadRef = ref(null)
const selectedFile = ref(null)

const createMode = ref('manual')  // manual / git
const createForm = ref({
  name: '',
  version: '1.0.0',
  author: '',
  description: '',
  module: '全局',
  roles: '通用'
})

const gitForm = ref({
  provider: 'gitlab',
  repo_url: '',
  branch: 'main',
  branch_custom: '',
  access_token: ''
})
const gitTesting = ref(false)
const gitTestResult = ref(null)

const createRules = {
  name: [
    { required: true, message: '请输入技能名称', trigger: 'blur' }
  ],
  version: [
    { required: true, message: '请输入版本号', trigger: 'blur' }
  ],
  author: [
    { required: true, message: '请输入作者', trigger: 'blur' }
  ],
  description: [
    { required: true, message: '请输入描述', trigger: 'blur' }
  ],
  module: [
    { required: true, message: '请添加业务模块标签', trigger: 'change' }
  ],
  roles: [
    { required: true, message: '请添加适用角色标签', trigger: 'change' }
  ]
}

const gitFormRef = ref(null)
const gitRules = {
  repo_url: [
    { required: true, message: '请输入 GitLab 仓库地址', trigger: 'blur' }
  ],
  branch: [
    { required: true, message: '请输入分支名', trigger: 'blur' }
  ]
}

let listRequestId = 0
const fetchSkills = async () => {
  const requestId = ++listRequestId
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const params = { skip, limit: pageSize.value }

    // 如果有搜索关键词，添加到参数中
    if (searchKeyword.value && searchKeyword.value.trim()) {
      params.search = searchKeyword.value.trim()
    }

    const response = await skillsApi.getList(params)
    if (requestId !== listRequestId) return

    // 兼容两种返回格式：数组或 {total, items}
    if (Array.isArray(response)) {
      // 旧格式：直接返回数组
      skills.value = response
      total.value = response.length
    } else {
      // 新格式：返回 {total, items}
      skills.value = response?.items || []
      total.value = response?.total || 0
    }

  } catch (error) {
    if (requestId !== listRequestId) return
    console.error('获取列表失败:', error)
    showError(error, '获取列表失败')
    skills.value = []
    total.value = 0
  } finally {
    if (requestId === listRequestId) loading.value = false
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
  fetchSkills()
}

const handleSearch = () => {
  // 使用防抖，避免频繁请求
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  searchTimer = setTimeout(() => {
    // 搜索时重置到第一页
    currentPage.value = 1
    fetchSkills()
  }, 500)
}

const handleSelect = (skill) => {
  if (skill && skill.id) {
    router.push(`/admin/skills/${skill.id}`)
  } else {
    console.error('Invalid skill object:', skill)
    ElMessage.error('无法打开技能详情')
  }
}

const handleEdit = (skill) => {
  router.push(`/admin/skills/${skill.id}`)
}

const isSkillOwner = (skill) => {
  const currentUserId = authStore.user?.id ?? authStore.user?.user_id
  return Number(skill?.user_id) === Number(currentUserId)
}

const handleDelete = async (skill) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除技能"${skill.name}"吗？此操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )

    await skillsApi.delete(skill.id)
    ElMessage.success('删除成功')
    await fetchSkills()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const handleToggleVisibility = async (skill) => {
  try {
    const result = await skillsApi.toggleVisibility(skill.id)
    skill.is_public = result.is_public
    ElMessage.success(`技能已设为${result.is_public ? '公开' : '私有'}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '切换可见性失败')
  }
}

const handleCreate = () => {
  createMode.value = 'manual'
  createForm.value = {
    name: '',
    version: '1.0.0',
    author: authStore.user?.first_name || '',
    description: '',
    module: '全局',
    roles: '通用'
  }
  gitForm.value = {
    provider: 'gitlab',
    repo_url: '',
    branch: 'main',
    branch_custom: '',
    access_token: ''
  }
  gitTestResult.value = null
  createDialogVisible.value = true
}

const handleTestConnection = async () => {
  if (!gitForm.value.repo_url) {
    ElMessage.warning('请先输入仓库地址')
    return
  }
  gitTesting.value = true
  gitTestResult.value = null
  try {
    const result = await gitApi.testConnection({
      provider: gitForm.value.provider,
      repo_url: gitForm.value.repo_url,
      access_token: gitForm.value.access_token || undefined,
      branch: gitForm.value.branch === 'custom' ? gitForm.value.branch_custom : gitForm.value.branch
    })
    gitTestResult.value = { success: true, ...result }
    ElMessage.success(`连接成功：${result.project_name}`)
  } catch (e) {
    gitTestResult.value = { success: false, message: e.response?.data?.detail || '连接失败' }
    ElMessage.error(gitTestResult.value.message)
  } finally {
    gitTesting.value = false
  }
}

const handleConfirmCreate = async () => {
  creating.value = true
  try {
    if (createMode.value === 'manual') {
      if (!createFormRef.value) return
      try {
        await createFormRef.value.validate()
      } catch (error) {
        creating.value = false
        return
      }

      // 生成SKILL.md文件内容
      const skillMdContent = `---
name: ${JSON.stringify(createForm.value.name)}
description: ${JSON.stringify(createForm.value.description)}
author: ${JSON.stringify(createForm.value.author)}
version: ${JSON.stringify(createForm.value.version)}
---

# ${createForm.value.name}

## 描述
${createForm.value.description}

## 业务模块
${createForm.value.module}

## 适用角色
${createForm.value.roles}

## 使用说明
请在此处添加技能的详细使用说明。
`

      const defaultFileTree = [
        {
          id: 1,
          label: 'SKILL.md',
          type: 'file',
          path: 'SKILL.md',
          content: skillMdContent
        }
      ]

      const filesData = JSON.stringify({ tree: defaultFileTree })

      const newSkill = await skillsApi.create({
        name: createForm.value.name,
        version: createForm.value.version,
        author: createForm.value.author,
        description: createForm.value.description,
        module: createForm.value.module,
        roles: createForm.value.roles,
        files: filesData
      })

      ElMessage.success('创建成功')
      createDialogVisible.value = false
      router.push(`/admin/skills/${newSkill.id}`)

    } else if (createMode.value === 'git') {
      if (!gitFormRef.value) return
      try {
        await gitFormRef.value.validate()
      } catch (error) {
        creating.value = false
        return
      }

      const branch = gitForm.value.branch === 'custom' ? gitForm.value.branch_custom : gitForm.value.branch
      if (gitForm.value.branch === 'custom' && !branch) {
        ElMessage.warning('请输入自定义分支名')
        creating.value = false
        return
      }

      const newSkill = await gitApi.importSkill({
        provider: gitForm.value.provider,
        repo_url: gitForm.value.repo_url,
        branch,
        access_token: gitForm.value.access_token || undefined,
      })

      ElMessage.success('已从 Git 仓库创建技能')
      createDialogVisible.value = false
      router.push(`/admin/skills/${newSkill.id}`)
    }
  } catch (error) {
    console.error('[Git] 创建失败，完整错误:', error)
    console.error('[Git] error.response:', error?.response)
    console.error('[Git] error.response?.data:', error?.response?.data)
    const detail = typeof error.response?.data?.detail === 'string'
      ? error.response.data.detail
      : (error.response?.data?.detail?.[0]?.msg || error.message || '创建失败')
    ElMessage.error(detail)
  } finally {
    creating.value = false
  }
}

const handleImport = () => {
  selectedFile.value = null
  importDialogVisible.value = true
}

const handleFileChange = (file) => {
  selectedFile.value = file.raw
}

const handleExceed = () => {
  ElMessage.warning('只能上传一个文件')
}

const validateFile = async (file) => {
  const fileName = file.name.toLowerCase()

  // 检查是否是 SKILL.md 文件
  if (fileName === 'skill.md') {
    return true
  }

  // 检查是否是 zip 文件
  if (fileName.endsWith('.zip')) {
    try {
      const zip = new JSZip()
      const zipContent = await zip.loadAsync(file)

      // 检查 zip 中是否包含 SKILL.md 文件
      const hasSkillMd = Object.keys(zipContent.files).some(
        filename => filename.toLowerCase() === 'skill.md' ||
                   filename.toLowerCase().endsWith('/skill.md')
      )

      if (!hasSkillMd) {
        ElMessage.error('zip 压缩包中必须包含 SKILL.md 文件')
        return false
      }

      return true
    } catch (error) {
      ElMessage.error('无法解析 zip 文件')
      return false
    }
  }

  ElMessage.error('文件格式不正确，请上传 SKILL.md 文件或包含 SKILL.md 的 zip 压缩包')
  return false
}

const handleConfirmImport = async () => {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择要导入的文件')
    return
  }

  // 验证文件
  const isValid = await validateFile(selectedFile.value)
  if (!isValid) {
    return
  }

  importing.value = true
  try {
    await skillsApi.import(selectedFile.value)
    ElMessage.success('导入成功')
    importDialogVisible.value = false
    await fetchSkills()
  } catch (error) {
    console.error('导入失败:', error)
    const isTimeout = error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
    const errorMsg = isTimeout
      ? '导入请求超时，请先刷新技能列表确认是否已导入，再决定是否重试'
      : error.response?.data?.detail || error.response?.data?.message || error.message || '导入失败'
    ElMessage.error(errorMsg)
  } finally {
    importing.value = false
  }
}

const handleChangeCover = (skill) => {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.onchange = async (e) => {
    const file = e.target.files[0]
    if (!file) return

    // 检查文件大小
    if (file.size > 1048576) {
      ElMessage.error('图片大小不能超过1MB')
      return
    }

    // 检查文件类型
    if (!file.type.startsWith('image/')) {
      ElMessage.error('只能上传图片文件')
      return
    }

    try {
      console.log('开始上传封面，skill.id:', skill.id)
      const result = await skillsApi.uploadCover(skill.id, file)
      console.log('上传成功，返回结果:', result)

      // 更新当前skill的cover
      if (result && result.cover) {
        skill.cover = result.cover
        ElMessage.success('封面更换成功')
        // 刷新列表以确保数据同步
        await fetchSkills()
      } else {
        console.error('返回结果中没有cover字段:', result)
        ElMessage.error('封面上传失败：返回数据格式错误')
      }
    } catch (error) {
      console.error('封面上传失败:', error)
      console.error('错误详情:', error.response)
      const errorMsg = error.response?.data?.detail || error.message || '封面上传失败'
      ElMessage.error(errorMsg)
    }
  }
  input.click()
}

const handleDeleteCover = async (skill) => {
  try {
    await ElMessageBox.confirm(
      '确定要删除封面吗？',
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )

    console.log('开始删除封面，skill.id:', skill.id)
    await skillsApi.deleteCover(skill.id)
    console.log('删除成功')

    // 清空当前skill的cover
    skill.cover = null
    ElMessage.success('封面删除成功')
    // 刷新列表以确保数据同步
    await fetchSkills()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('封面删除失败:', error)
      const errorMsg = error.response?.data?.detail || error.message || '封面删除失败'
      ElMessage.error(errorMsg)
    }
  }
}

onMounted(() => {
  fetchSkills()
})
</script>

<style scoped>
.skill-list {
  max-width: 1400px;
  margin: 0 auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.header h2 {
  margin: 0;
  font-size: 24px;
  color: #333;
}

.skill-card {
  cursor: pointer;
  transition: all 0.3s;
  height: 100%;
  position: relative;
}

.skill-card:hover {
  transform: translateY(-4px);
}

.skill-card:hover .skill-actions {
  opacity: 1;
}

.skill-cover {
  position: relative;
  width: calc(100% + 40px);
  height: 150px;
  overflow: hidden;
  margin: -20px -20px 10px -20px;

}

.skill-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center center;
  display: block;
}

.cover-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.3s;
}

.cover-overlay .el-button {
  background: rgba(255, 255, 255, 0.9);
  border-color: transparent;
  color: #409eff;
}

.cover-overlay .el-button:hover {
  background: #fff;
}

.skill-cover:hover .cover-overlay {
  opacity: 1;
}

.skill-actions {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  gap: 1px;
  z-index: 10;
  opacity: 0;
  transition: opacity 0.3s;
}

.skill-actions .el-button + .el-button {
  margin-left: 5px;
}

.skill-actions .el-button {
  padding: 2px;
  min-width: auto;
}

.collaboration-badge {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
}

.skill-icon {
  position: relative;
  width: calc(100% + 40px);
  height: 150px;
  overflow: hidden;
  margin: -20px -20px 10px -20px;

  display: flex;
  align-items: center;
  justify-content: center;
  color: #409eff;
}

.skill-icon img {
  width: 48px;
  height: 48px;
  object-fit: contain;
}

.icon-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.3s;
}

.skill-icon:hover .icon-overlay {
  opacity: 1;
}

.skill-info {
  text-align: center;
}

.skill-info h3 {
  margin: 10px 0;
  font-size: 18px;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
  font-size: 13px;
  color: #606266;
}

.meta-item {
  display: inline-block;
}

.meta-center {
  flex: 1;
  text-align: center;
}

.skill-info .description {
  margin-top: 10px;
  color: #666;
  font-size: 13px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-align: left;
}

.skill-stats {
  display: flex;
  margin-top: 10px;
  font-size: 13px;
  color: #606266;
}

.stat-item {
  display: inline-block;
}

.stat-center {
  flex: 1;
  text-align: center;
}

.skill-module {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #f0f0f0;
  font-size: 13px;
  text-align: left;
}

.skill-module > span:not(.skill-metadata-tags) {
  color: #606266;
}

.skill-roles {
  margin-top: 10px;
  font-size: 13px;
  text-align: left;
}

.skill-roles > span:not(.skill-metadata-tags) {
  color: #606266;
}

.skill-module, .skill-roles { display: flex; align-items: flex-start; gap: 4px; }
.skill-module > span:first-child, .skill-roles > span:first-child { flex-shrink: 0; line-height: 20px; }

.upload-demo {
  width: 100%;
}

.el-icon--upload {
  font-size: 67px;
  color: #409eff;
  margin-bottom: 16px;
}

.el-upload__text {
  font-size: 14px;
  color: #606266;
}

.el-upload__text em {
  color: #409eff;
  font-style: normal;
}

.el-upload__tip {
  font-size: 12px;
  color: #909399;
  margin-top: 7px;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 4px;
  padding: 0;
}
</style>

