<template>
  <div class="page-container">
    <header class="page-header">
      <h2>访问令牌</h2>
      <el-button type="primary" :icon="Plus" @click="showCreateDialog">
        生成令牌
      </el-button>
    </header>

    <div class="security-notice">
      <el-icon :size="20"><Lock /></el-icon>
      <div>
        <strong>像密码一样保管令牌</strong>
        <span>令牌仅在生成时显示一次，请存放在安全的密钥管理工具中。</span>
      </div>
    </div>

    <section class="token-list" aria-labelledby="token-list-title">
      <div class="list-header">
        <div>
          <h2 id="token-list-title">令牌列表</h2>
          <span>共 {{ total }} 个</span>
        </div>
        <el-tooltip content="刷新列表" placement="top">
          <el-button
            :icon="Refresh"
            :loading="loading"
            circle
            text
            aria-label="刷新令牌列表"
            @click="fetchTokens"
          />
        </el-tooltip>
      </div>

      <el-table
        :data="tokens"
        v-loading="loading"
        empty-text=""
        table-layout="fixed"
      >
        <el-table-column prop="name" label="名称" min-width="180">
          <template #default="{ row }">
            <div class="token-name">
              <el-icon><Key /></el-icon>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag :type="isExpired(row.expires_at) ? 'info' : 'success'" effect="plain" size="small">
              {{ isExpired(row.expires_at) ? '已过期' : '有效' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="168">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="last_used_at" label="最近使用" min-width="168">
          <template #default="{ row }">
            {{ row.last_used_at ? formatDate(row.last_used_at) : '尚未使用' }}
          </template>
        </el-table-column>
        <el-table-column prop="expires_at" label="到期时间" min-width="168">
          <template #default="{ row }">
            <span :class="{ 'expired-text': isExpired(row.expires_at) }">
              {{ formatDate(row.expires_at) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="72" align="center" fixed="right">
          <template #default="{ row }">
            <el-popconfirm
              :title="`撤销“${row.name}”后将立即无法使用，确定撤销吗？`"
              width="280"
              confirm-button-text="撤销"
              cancel-button-text="取消"
              confirm-button-type="danger"
              @confirm="handleRevoke(row.id)"
            >
              <template #reference>
                <span class="revoke-trigger">
                  <el-tooltip content="撤销令牌" placement="top">
                    <el-button type="danger" :icon="Delete" link circle aria-label="撤销令牌" />
                  </el-tooltip>
                </span>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :image-size="72" description="暂无访问令牌">
            <el-button type="primary" plain :icon="Plus" @click="showCreateDialog">
              生成第一个令牌
            </el-button>
          </el-empty>
        </template>
      </el-table>

      <div class="pagination-container" v-if="total > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="handlePageChange"
        />
      </div>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="generatedToken ? '令牌已生成' : '生成访问令牌'"
      width="min(600px, calc(100vw - 32px))"
      :close-on-click-modal="false"
      :close-on-press-escape="!generatedToken"
      :show-close="!generatedToken"
      @closed="resetCreateDialog"
    >
      <el-form v-if="!generatedToken" label-position="top" @submit.prevent="handleCreate">
        <p class="dialog-intro">用一个容易辨认的名称标记令牌的使用位置。</p>
        <el-form-item label="名称" required>
          <el-input
            v-model="tokenName"
            placeholder="例如：悟空生产环境"
            maxlength="100"
            show-word-limit
            autofocus
          />
        </el-form-item>
      </el-form>

      <div v-else class="generated-content">
        <div class="success-heading">
          <span class="success-icon"><el-icon><CircleCheck /></el-icon></span>
          <div>
            <strong>令牌已生成</strong>
            <span>这是唯一一次可以查看完整令牌的机会。</span>
          </div>
        </div>

        <div class="token-field">
          <code>{{ generatedToken }}</code>
          <el-tooltip content="复制令牌" placement="top">
            <el-button
              class="copy-button"
              type="primary"
              :icon="CopyDocument"
              circle
              aria-label="复制令牌"
              @click="copyToken"
            />
          </el-tooltip>
        </div>

        <div class="token-meta">
          <div>
            <span>到期时间</span>
            <strong>{{ formatDate(generatedExpiresAt) }}</strong>
          </div>
          <div>
            <span>当前权限</span>
            <strong>{{ generatedPermissions?.length ? `${generatedPermissions.length} 项` : '无额外权限' }}</strong>
          </div>
        </div>

        <el-alert
          title="关闭前请确认令牌已保存；页面不会保留令牌明文。"
          type="warning"
          :closable="false"
          show-icon
        />
      </div>

      <template #footer>
        <template v-if="!generatedToken">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="creating" @click="handleCreate">生成令牌</el-button>
        </template>
        <template v-else>
          <el-button type="primary" @click="closeCreateDialog">已保存并关闭</el-button>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, CopyDocument, Delete, Key, Lock, Plus, Refresh } from '@element-plus/icons-vue'
import { patsApi } from '@/api/pats'
import { formatBeijingDateTime, isPastDateTime } from '@/utils/date-time'

const tokens = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const creating = ref(false)
const tokenName = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

const generatedToken = ref('')
const generatedExpiresAt = ref('')
const generatedPermissions = ref([])

onMounted(() => {
  fetchTokens()
})

async function fetchTokens() {
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const res = await patsApi.getList({ skip, limit: pageSize.value })
    tokens.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error('获取令牌列表失败')
  } finally {
    loading.value = false
  }
}

function handlePageChange(page) {
  currentPage.value = page
  fetchTokens()
}

function showCreateDialog() {
  tokenName.value = ''
  generatedToken.value = ''
  dialogVisible.value = true
}

async function handleCreate() {
  if (!tokenName.value.trim()) {
    ElMessage.warning('请输入令牌名称')
    return
  }

  creating.value = true
  try {
    const res = await patsApi.create(tokenName.value.trim())
    generatedToken.value = res.token
    generatedExpiresAt.value = res.expires_at
    generatedPermissions.value = res.permissions || []
    fetchTokens()
  } catch (e) {
    ElMessage.error('生成令牌失败')
  } finally {
    creating.value = false
  }
}

function closeCreateDialog() {
  dialogVisible.value = false
}

function resetCreateDialog() {
  generatedToken.value = ''
  generatedExpiresAt.value = ''
  generatedPermissions.value = []
  tokenName.value = ''
}

function copyToken() {
  navigator.clipboard.writeText(generatedToken.value).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败，请手动复制')
  })
}

async function handleRevoke(id) {
  try {
    await patsApi.revoke(id)
    ElMessage.success('令牌已撤销')
    fetchTokens()
  } catch (e) {
    ElMessage.error('撤销失败')
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  return formatBeijingDateTime(dateStr)
}

function isExpired(dateStr) {
  return isPastDateTime(dateStr)
}
</script>

<style scoped>
.page-container {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  margin-bottom: 24px;
}

.page-header h2 {
  margin: 0;
  font-size: 24px;
  color: #303133;
}

.security-notice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 16px;
  margin-bottom: 20px;
  color: #4c4f52;
  background: #f0f7ff;
  border: 1px solid #d9ecff;
  border-radius: 6px;
}

.security-notice > .el-icon {
  flex: 0 0 auto;
  margin-top: 1px;
  color: #337ecc;
}

.security-notice div {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  min-width: 0;
  font-size: 13px;
  line-height: 20px;
}

.security-notice strong {
  color: #303133;
}

.token-list {
  overflow: hidden;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 64px;
  padding: 0 20px;
  border-bottom: 1px solid #ebeef5;
}

.list-header > div {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.list-header h2 {
  margin: 0;
  color: #303133;
  font-size: 16px;
  line-height: 24px;
  letter-spacing: 0;
}

.list-header span {
  color: #909399;
  font-size: 13px;
}

.token-name {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  color: #303133;
  font-weight: 500;
}

.token-name .el-icon {
  flex: 0 0 auto;
  color: #909399;
}

.token-name span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.expired-text {
  color: #909399;
}

.revoke-trigger {
  display: inline-flex;
}

.pagination-container {
  display: flex;
  justify-content: flex-end;
  padding: 16px 20px;
  border-top: 1px solid #ebeef5;
}

.dialog-intro {
  margin: -2px 0 18px;
  color: #606266;
  font-size: 14px;
  line-height: 22px;
}

.generated-content {
  display: grid;
  gap: 18px;
}

.success-heading {
  display: flex;
  align-items: center;
  gap: 12px;
}

.success-heading > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.success-heading strong {
  color: #303133;
  font-size: 15px;
}

.success-heading span:not(.success-icon) {
  color: #73767a;
  font-size: 13px;
}

.success-icon {
  display: grid;
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  place-items: center;
  color: #529b2e;
  background: #f0f9eb;
  border-radius: 50%;
  font-size: 20px;
}

.token-field {
  position: relative;
  min-height: 108px;
  padding: 14px 54px 14px 14px;
  overflow: auto;
  background: #f5f7fa;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
}

.token-field code {
  color: #303133;
  font-family: Consolas, "Courier New", monospace;
  font-size: 12px;
  line-height: 19px;
  overflow-wrap: anywhere;
}

.copy-button {
  position: absolute;
  top: 10px;
  right: 10px;
}

.token-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-top: 1px solid #ebeef5;
  border-bottom: 1px solid #ebeef5;
}

.token-meta > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
}

.token-meta > div + div {
  border-left: 1px solid #ebeef5;
}

.token-meta span {
  color: #909399;
  font-size: 12px;
}

.token-meta strong {
  color: #303133;
  font-size: 13px;
  font-weight: 500;
}

@media (max-width: 640px) {
  .page-header {
    align-items: center;
  }

  .page-header .el-button {
    flex: 0 0 auto;
  }

  .security-notice div {
    display: block;
  }

  .security-notice strong {
    display: block;
    margin-bottom: 2px;
  }

  .list-header {
    padding: 0 14px;
  }

  .token-meta {
    grid-template-columns: 1fr;
  }

  .token-meta > div + div {
    border-top: 1px solid #ebeef5;
    border-left: 0;
  }
}
</style>
