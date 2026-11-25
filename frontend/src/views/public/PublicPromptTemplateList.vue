<template>
  <div class="template-list">
    <div class="header">
      <h2>提示词模板</h2>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索名称、分类、描述或作者"
          clearable
          @input="handleSearch"
          style="width: 300px;"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </div>
    </div>

    <el-table
      :data="templates"
      v-loading="loading"
      stripe
      @row-click="handleSelect"
      style="cursor: pointer;"
    >
      <el-table-column prop="name" label="模板名称" min-width="180" />
      <el-table-column prop="category" label="分类" width="120">
        <template #default="{ row }">
          <el-tag size="small" type="primary">{{ row.category }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="content" label="内容预览" min-width="280">
        <template #default="{ row }">
          {{ truncate(row.content) }}
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.description || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="author" label="作者" width="120">
        <template #default="{ row }">
          {{ row.author || '匿名' }}
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && templates.length === 0" description="暂无公开模板" />

    <div class="pagination-container" v-if="!loading && total > 0">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next, jumper"
        @current-change="handlePageChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { publicPromptTemplatesApi } from '@/api/prompt-templates'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { formatBeijingDateTime } from '@/utils/date-time'

const router = useRouter()
const loading = ref(false)
const templates = ref([])
const currentPage = ref(1)
const pageSize = ref(12)
const total = ref(0)
const searchKeyword = ref('')
let searchTimer = null

const truncate = (content) => {
  if (!content) return '-'
  const oneLine = content.replace(/\s+/g, ' ').trim()
  return oneLine.length > 60 ? oneLine.slice(0, 60) + '...' : oneLine
}

const formatTime = (t) => {
  if (!t) return '-'
  return formatBeijingDateTime(t)
}

const fetchList = async () => {
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const params = { skip, limit: pageSize.value }
    if (searchKeyword.value?.trim()) {
      params.search = searchKeyword.value.trim()
    }
    const res = await publicPromptTemplatesApi.getList(params)
    templates.value = res?.items || []
    total.value = res?.total || 0
  } catch (e) {
    ElMessage.error('获取模板列表失败')
    templates.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const handlePageChange = (p) => {
  currentPage.value = p
  fetchList()
}

const handleSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchList()
  }, 500)
}

const handleSelect = (row) => {
  if (row?.id) {
    router.push(`/prompt-templates/${row.id}`)
  }
}

onMounted(() => {
  fetchList()
})
</script>

<style scoped>
.template-list {
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
  font-weight: 800;
  color: var(--ink);
  position: relative;
  padding-left: 14px;
}
.header h2::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 5px;
  height: 22px;
  border-radius: 999px;
  background: linear-gradient(120deg, var(--brand-600), var(--brand-400));
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}
</style>
