<template>
  <div class="agent-list">
    <div class="header">
      <h2>自定义 Agent</h2>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索名称或描述"
          clearable
          @input="handleSearch"
          class="search-input"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="handleCreate">
          <el-icon><Plus /></el-icon>
          新建自定义 Agent
        </el-button>
        <!-- 暂时隐藏自定义 Agent 共享入口。 -->
        <el-button v-if="false" plain @click="openSharedAgents">共享 Agent</el-button>
      </div>
    </div>

    <div class="agent-grid" v-loading="loading">
      <el-card
        v-for="agent in agents"
        :key="agent.id"
        class="agent-card"
        shadow="never"
        @click="handleEdit(agent)"
      >
        <div class="agent-card-actions">
          <el-tooltip :content="agent.is_public ? '公开' : '私有'" placement="top">
            <el-button
              :type="agent.is_public ? 'success' : 'info'"
              class="visibility-button"
              :icon="agent.is_public ? View : Hide"
              link
              size="small"
              :loading="sharingId === agent.id"
              :aria-label="agent.is_public ? '设为私有' : '设为公开'"
              @click.stop="handleToggleVisibility(agent)"
            />
          </el-tooltip>
          <el-tooltip content="删除 Agent" placement="top">
            <el-button
              type="danger"
              class="delete-button"
              :icon="Delete"
              link
              size="small"
              :loading="deletingId === agent.id"
              aria-label="删除 Agent"
              @click.stop="handleDelete(agent)"
            />
          </el-tooltip>
          <el-tooltip content="Agent 设置" placement="top">
            <el-button
              type="primary"
              class="settings-button"
              :icon="Setting"
              link
              size="small"
              aria-label="Agent 设置"
              @click.stop="handleEdit(agent)"
            />
          </el-tooltip>
        </div>

        <div class="agent-profile">
          <div v-if="agent.icon?.trim()" class="agent-avatar" :class="{ 'has-image': getAssistantImage(agent.icon) }">
            <span class="agent-emoji" :class="{ 'image-icon': getAssistantImage(agent.icon) }"><AssistantIcon :icon="agent.icon" /></span>
          </div>
          <div class="agent-identity">
            <h3>{{ agent.name }}</h3>
            <div class="author-line" :title="authorName(agent)">作者：{{ authorName(agent) }}</div>
          </div>
        </div>

        <p class="agent-description" :class="{ muted: !agent.description }">
          {{ agent.description || '无' }}
        </p>

        <div v-if="agent.skills?.length" class="expertise-row">
          <span class="expertise-label">技能</span>
          <div class="expertise-tags">
            <span v-for="skill in agent.skills.slice(0, 3)" :key="skill.id" class="expertise-tag">{{ skill.name }}</span>
            <span v-if="agent.skills.length > 3" class="expertise-more">+{{ agent.skills.length - 3 }}</span>
          </div>
        </div>

      </el-card>
    </div>

    <el-empty v-if="!loading && agents.length === 0" description="暂无自定义 Agent，点击右上角新建" />

    <div class="pagination-container" v-if="!loading && total > pageSize">
      <el-pagination
        background
        layout="prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="currentPage"
        @current-change="handlePageChange"
      />
    </div>

    <el-dialog v-model="sharedOpen" title="共享 Agent" width="min(760px, calc(100vw - 32px))">
      <div v-loading="sharedLoading" class="shared-agent-list">
        <div v-for="agent in sharedAgents" :key="agent.id" class="shared-agent-row">
          <div class="shared-agent-identity">
            <span v-if="agent.icon?.trim()" class="shared-agent-icon" :class="{ 'image-icon': getAssistantImage(agent.icon) }">
              <AssistantIcon :icon="agent.icon" />
            </span>
            <div>
              <strong>{{ agent.name }}</strong>
              <p>{{ agent.description || '无' }}</p>
            </div>
          </div>
          <div class="shared-agent-meta">技能 {{ agent.skill_count }} · MCP {{ agent.mcp_count }} · 提示词 {{ agent.prompt_count }}</div>
          <el-button type="primary" plain :loading="copyingId === agent.id" @click="copySharedAgent(agent)">创建副本</el-button>
        </div>
        <el-empty v-if="!sharedLoading && !sharedAgents.length" description="暂无公开 Agent" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import AssistantIcon from '@/components/AssistantIcon.vue'
import { getAssistantImage } from '@/config/assistant-characters'
import { h, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus, Setting, Delete, View, Hide } from '@element-plus/icons-vue'
import api from '@/api/request'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const agents = ref([])
const loading = ref(false)
const searchKeyword = ref('')
const currentPage = ref(1)
const pageSize = ref(12)
const total = ref(0)
const sharedOpen = ref(false)
const sharedLoading = ref(false)
const sharedAgents = ref([])
const copyingId = ref(null)
const deletingId = ref(null)
const sharingId = ref(null)
let fetchSequence = 0

const authorName = agent => (
  agent.kind === 'personal_default' || Number(agent.id) === 0
    ? '平台'
    : agent.author?.trim() || auth.user?.first_name?.trim() || auth.user?.username?.trim() || '无'
)

const fetchAgents = async () => {
  const sequence = ++fetchSequence
  loading.value = true
  try {
    const res = await api.get('/agents', {
      params: {
        skip: (currentPage.value - 1) * pageSize.value,
        limit: pageSize.value,
        search: searchKeyword.value || undefined,
      },
    })
    if (sequence !== fetchSequence) return
    agents.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    if (sequence === fetchSequence) {
      ElMessage.error('加载失败：' + (e.response?.data?.detail || e.message))
    }
  } finally {
    if (sequence === fetchSequence) loading.value = false
  }
}

const handleSearch = () => {
  currentPage.value = 1
  fetchAgents()
}

const handlePageChange = (page) => {
  currentPage.value = page
  fetchAgents()
}

const handleCreate = () => {
  router.push('/admin/agents/new')
}

const handleEdit = (agent) => {
  router.push(`/admin/agents/${agent.id}`)
}

const handleToggleVisibility = async (agent) => {
  if (sharingId.value !== null) return
  sharingId.value = agent.id
  try {
    const result = await api.post(`/agents/${agent.id}/${agent.is_public ? 'unpublish' : 'publish'}`)
    agent.is_public = Boolean(result.is_public)
    ElMessage.success(agent.is_public ? 'Agent 已公开' : '已取消公开')
  } catch (error) {
    const body = error.response?.data
    const detail = body?.detail
    const message = typeof detail === 'string' ? detail : detail?.message
    const items = body?.data?.items || detail?.data?.items || detail?.items
    const resources = Array.isArray(items) ? [...new Set(items.filter(item => typeof item === 'string' && item.trim()))] : []
    if (resources.length) {
      await ElMessageBox.alert(h('div', [
        h('p', { style: { margin: '0 0 12px' } }, '请先将以下资源设为公开，再重试：'),
        h('ul', { style: { margin: 0, paddingLeft: '20px', maxHeight: '40vh', overflowY: 'auto', overflowWrap: 'anywhere' } },
          resources.map(item => h('li', { style: { marginBottom: '8px' } }, item))),
      ]), '无法设为公开', { type: 'warning', confirmButtonText: '知道了' }).catch(() => {})
    } else {
      ElMessage.error({ message: message || body?.message || '共享设置更新失败', grouping: true })
    }
  } finally {
    sharingId.value = null
  }
}

const handleDelete = async (agent) => {
  if (deletingId.value !== null) return
  try {
    await ElMessageBox.confirm(
      `确定删除 Agent “${agent.name}”？删除后将停止运行中的任务并清理相关配置。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    deletingId.value = agent.id
    await api.delete(`/agents/${agent.id}`)
    ElMessage.success('已删除')
    if (agents.value.length === 1 && currentPage.value > 1) currentPage.value -= 1
    await fetchAgents()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error.response?.data?.detail || '删除失败')
    }
  } finally {
    deletingId.value = null
  }
}

const openSharedAgents = async () => {
  sharedOpen.value = true
  sharedLoading.value = true
  try {
    const result = await api.get('/public/agents', { params: { limit: 100 } })
    sharedAgents.value = result.items || []
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '共享 Agent 加载失败')
  } finally {
    sharedLoading.value = false
  }
}

const copySharedAgent = async agent => {
  copyingId.value = agent.id
  try {
    const copied = await api.post(`/agents/${agent.id}/copy`)
    ElMessage.success('已创建 Agent 副本')
    sharedOpen.value = false
    await fetchAgents()
    router.push(`/admin/agents/${copied.id}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '创建副本失败')
  } finally {
    copyingId.value = null
  }
}

onMounted(() => {
  fetchAgents()
})
</script>

<style scoped>
.agent-list {
  max-width: 1400px;
  margin: 0 auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header h2 {
  margin: 0;
  font-size: 24px;
  color: #17191e;
  font-weight: 600;
  line-height: 1.35;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-input {
  width: 280px;
}

.shared-agent-list { min-height: 120px; }
.shared-agent-row { display: flex; align-items: center; gap: 16px; padding: 14px 0; border-bottom: 1px solid #eef0f3; }
.shared-agent-row:last-child { border-bottom: 0; }
.shared-agent-identity { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1; }
.shared-agent-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 10px; background: #f1f3f5; font-size: 20px; }
.shared-agent-icon.image-icon { overflow: hidden; padding: 4px; background: #fff; border: 1px solid #e3e8ef; }
.shared-agent-identity strong { display: block; color: #2c3138; }
.shared-agent-identity p { margin: 4px 0 0; color: #7a818c; font-size: 12px; overflow-wrap: anywhere; }
.shared-agent-meta { color: #747b86; font-size: 12px; white-space: nowrap; }
@media (max-width: 720px) { .shared-agent-row { align-items: flex-start; flex-wrap: wrap; } .shared-agent-meta { flex: 1 1 100%; margin-left: 44px; } }

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(286px, 1fr));
  gap: 16px;
  min-height: 120px;
}

.agent-card {
  position: relative;
  min-width: 0;
  min-height: 230px;
  height: 100%;
  cursor: pointer;
  overflow: hidden;
  border: 1px solid #e1e6ed;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfcfe 0, #fff 38%);
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
}

.agent-card:hover {
  transform: translateY(-2px);
  border-color: #bbd3ef;
  box-shadow: 0 12px 28px rgba(31, 41, 55, 0.1);
}

.agent-card:focus-within {
  border-color: #a8c7f0;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.1);
}

@media (max-width: 760px) {
  .header {
    align-items: stretch;
    flex-direction: column;
    gap: 16px;
  }

  .header-actions {
    align-items: stretch;
  }

  .search-input {
    width: auto;
    flex: 1;
    min-width: 0;
  }
}

@media (max-width: 480px) {
  .header-actions {
    flex-direction: column;
  }

  .header-actions :deep(.el-button) {
    width: 100%;
    margin: 0;
  }
}

.agent-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 24px 20px 20px;
  box-sizing: border-box;
}

.agent-profile {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  padding-right: 58px;
}

.agent-avatar {
  width: 76px;
  height: 76px;
  flex: 0 0 76px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  color: #53657d;
  background: #eef3f8;
  border: 1px solid #dce5ef;
  border-radius: 50%;
  box-shadow: 0 3px 10px rgba(47, 74, 104, 0.08);
}

.agent-avatar.has-image { background: #fff; border-color: #d8e3ee; }
.agent-emoji.image-icon { display: block; width: 100%; height: 100%; }
.agent-emoji {
  font-size: 38px;
  line-height: 1;
}

.agent-identity {
  flex: 1;
  min-width: 0;
}

.agent-identity h3 {
  margin: 0 0 7px;
  overflow: hidden;
  color: #1f2937;
  font-size: 20px;
  font-weight: 650;
  line-height: 26px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.author-line {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #728096;
  font-size: 12px;
  line-height: 18px;
}

.agent-card-actions {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  align-items: center;
  gap: 1px;
  z-index: 10;
}

.agent-card-actions :deep(.el-button) {
  min-width: auto;
  height: 24px;
  margin: 0;
  padding: 2px;
}

.agent-card-actions :deep(.el-button + .el-button) {
  margin-left: 5px;
}

.agent-description {
  min-height: 44px;
  margin: 18px 0 14px;
  overflow: hidden;
  color: #5f6977;
  font-size: 13px;
  line-height: 21px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.agent-description.muted {
  color: #a4abb5;
}

.expertise-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-height: 28px;
  margin-top: auto;
}

.expertise-label {
  flex: 0 0 auto;
  padding-top: 3px;
  color: #8a96a5;
  font-size: 11px;
}

.expertise-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
}

.expertise-tag,
.expertise-more {
  max-width: 120px;
  overflow: hidden;
  padding: 3px 8px;
  border: 1px solid #dce8f4;
  border-radius: 999px;
  color: #4d7197;
  background: #f5f9fd;
  font-size: 11px;
  line-height: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.expertise-more {
  color: #8190a1;
  background: #f7f8fa;
  border-color: #e5e9ef;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}

@media (max-width: 700px) {
  .header {
    align-items: stretch;
    flex-direction: column;
    gap: 16px;
  }

  .header-actions {
    width: 100%;
  }

  .search-input {
    flex: 1;
    width: auto;
    min-width: 0;
  }
}

@media (max-width: 420px) {
  .agent-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .header-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .header-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>
