<template>
  <div class="mcp-list">
    <div class="header">
      <h2>MCP 服务</h2>
      <div class="header-actions">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索名称、描述、分类或作者"
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

    <el-row :gutter="20" v-loading="loading">
      <el-col
        :xs="24"
        :sm="12"
        :md="8"
        :lg="6"
        v-for="mcp in mcps"
        :key="mcp.id"
        style="margin-bottom: 20px;"
      >
        <el-card
          class="mcp-card"
          shadow="hover"
          @click="handleSelect(mcp)"
        >
          <div class="mcp-cover" v-if="mcp.cover">
            <img :src="mcp.cover" alt="cover" />
          </div>
          <div class="mcp-icon" v-else>
            <el-icon :size="48">
              <Connection />
            </el-icon>
          </div>
          <div class="mcp-info">
            <h3>{{ mcp.name }}</h3>
            <div class="mcp-meta">
              <span class="meta-item">类型：{{ typeLabel(mcp.type) }}</span>
              <span class="meta-item meta-center">作者：{{ mcp.author || '无' }}</span>
            </div>
            <p class="description">描述：{{ mcp.description || '无' }}</p>
            <div class="mcp-tags">
              <span class="tags-label">分类：</span>
              <el-tag
                size="small"
                class="tag-item"
                type="primary"
              >
                {{ mcp.tags || '无' }}
              </el-tag>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!loading && mcps.length === 0" description="暂无数据" />

    <div class="pagination-container" v-if="!loading && mcps.length > 0">
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
import { publicMcpsApi } from '@/api/mcps'
import { ElMessage } from 'element-plus'
import { Search, Connection } from '@element-plus/icons-vue'

const router = useRouter()
const loading = ref(false)
const mcps = ref([])
const currentPage = ref(1)
const pageSize = ref(12)
const total = ref(0)
const searchKeyword = ref('')
let searchTimer = null

const typeLabelMap = {
  stdio: 'STDIO',
  sse: 'SSE',
  streamable_http: 'Streamable HTTP',
  json: 'JSON'
}

const typeLabel = (type) => typeLabelMap[type] || type

const fetchMcps = async () => {
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const params = { skip, limit: pageSize.value }
    if (searchKeyword.value?.trim()) {
      params.search = searchKeyword.value.trim()
    }
    const response = await publicMcpsApi.getList(params)
    mcps.value = response?.items || []
    total.value = response?.total || 0
  } catch (error) {
    console.error('获取列表失败:', error)
    ElMessage.error('获取列表失败')
    mcps.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
  fetchMcps()
}

const handleSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchMcps()
  }, 500)
}

const handleSelect = (mcp) => {
  if (mcp?.id) {
    router.push(`/mcps/${mcp.id}`)
  }
}

onMounted(() => {
  fetchMcps()
})
</script>

<style scoped>
.mcp-list {
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

.mcp-card {
  cursor: pointer;
  transition: transform 0.25s, box-shadow 0.25s;
  height: 100%;
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border-soft) !important;
}

.mcp-card:hover {
  transform: translateY(-6px);
  box-shadow: var(--shadow-hover) !important;
  border-color: var(--brand-100) !important;
}

.mcp-cover {
  position: relative;
  width: calc(100% + 40px);
  height: 150px;
  overflow: hidden;
  margin: -20px -20px 10px -20px;
  border-radius: 17px 17px 0 0;
}

.mcp-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center center;
  display: block;
  transition: transform 0.4s;
}
.mcp-card:hover .mcp-cover img {
  transform: scale(1.06);
}

.mcp-icon {
  position: relative;
  width: calc(100% + 40px);
  height: 150px;
  overflow: hidden;
  margin: -20px -20px 10px -20px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-600);
  background: linear-gradient(135deg, var(--brand-50), var(--brand-100));
  border-radius: 17px 17px 0 0;
}

.mcp-info {
  text-align: center;
}

.mcp-info h3 {
  margin: 10px 0;
  font-size: 18px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--ink-soft);
}

.meta-item {
  display: inline-block;
}

.meta-center {
  flex: 1;
  text-align: center;
}

.mcp-info .description {
  margin-top: 10px;
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-align: left;
}

.mcp-tags {
  margin-top: 10px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.tags-label {
  font-size: 13px;
  color: var(--ink-soft);
}

.tag-item {
  margin: 0;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 4px;
  padding: 0;
}
</style>
