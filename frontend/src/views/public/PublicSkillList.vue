<template>
  <div class="skill-list">
    <div class="header">
      <h2>技能中心</h2>
      <div class="header-actions">
        <SkillMetadataFilters :module="moduleFilter" :role="roleFilter" public-only @change="selectMetadata" />
        <el-input
          class="skill-search"
          v-model="searchKeyword"
          placeholder="搜索技能名称、作者或适用角色"
          clearable
          @input="handleSearch"
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
        v-for="skill in skills"
        :key="skill.id"
        style="margin-bottom: 20px;"
      >
        <el-card
          class="skill-card"
          shadow="hover"
          @click="handleSelect(skill)"
        >
          <div class="skill-cover" v-if="skill.cover">
            <img :src="skill.cover" alt="cover" />
          </div>
          <div class="skill-icon" v-else>
            <el-icon :size="48" v-if="!skill.icon">
              <SkillIcon />
            </el-icon>
            <img v-else :src="skill.icon" alt="icon" />
          </div>
          <div class="skill-info">
            <h3>{{ skill.name }}</h3>
            <div class="skill-meta">
              <span class="meta-item">版本：{{ skill.version?.trim() || '无版本' }}</span>
              <span class="meta-item meta-center">作者：{{ skill.author || '无' }}</span>
            </div>
            <p class="description">描述：{{ skill.description || '无' }}</p>
            <div class="skill-module">
              <span>业务模块：</span><SkillMetadataTags :model-value="skill.module" clickable :selected-tag="moduleFilter" @select="selectMetadata('module', $event)" />
            </div>
            <div class="skill-roles">
              <span>适用角色：</span><SkillMetadataTags :model-value="skill.roles" field="roles" clickable :selected-tag="roleFilter" @select="selectMetadata('role', $event)" />
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!loading && (!skills || skills.length === 0)" description="暂无公开技能" />

    <div class="pagination-container" v-if="!loading && skills && skills.length > 0">
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
import { publicSkillsApi } from '@/api/skills'
import { ElMessage } from 'element-plus'
import SkillMetadataTags from '@/components/SkillMetadataTags.vue'
import SkillMetadataFilters from '@/components/SkillMetadataFilters.vue'
import SkillIcon from '@/components/icons/SkillIcon.vue'

const router = useRouter()
const loading = ref(false)
const skills = ref([])
const currentPage = ref(1)
const pageSize = ref(12)
const total = ref(0)
const searchKeyword = ref('')
const moduleFilter = ref('')
const roleFilter = ref('')
const selectMetadata = (field, value) => {
  if (field === 'module' || field === 'all') moduleFilter.value = value
  if (field === 'role' || field === 'all') roleFilter.value = value
  clearTimeout(searchTimer)
  currentPage.value = 1
  fetchSkills()
}
let searchTimer = null

let listRequestId = 0
const fetchSkills = async () => {
  const requestId = ++listRequestId
  loading.value = true
  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const params = { skip, limit: pageSize.value, module: moduleFilter.value, role: roleFilter.value }

    if (searchKeyword.value && searchKeyword.value.trim()) {
      params.search = searchKeyword.value.trim()
    }

    const response = await publicSkillsApi.getList(params)
    if (requestId !== listRequestId) return
    skills.value = response?.items || []
    total.value = response?.total || 0
  } catch (error) {
    if (requestId !== listRequestId) return
    console.error('获取列表失败:', error)
    ElMessage.error('获取列表失败')
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
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchSkills()
  }, 500)
}

const handleSelect = (skill) => {
  if (skill && skill.id) {
    router.push(`/skills/${skill.id}`)
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
  flex-wrap: wrap;
  gap: 16px;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px;
  margin-left: auto;
  max-width: 100%;
}

.header-actions .metadata-filters { margin-bottom: 0; max-width: 100%; }
.skill-search { width: 300px; max-width: 100%; flex: 0 0 auto; }
@media (max-width: 600px) {
  .header-actions { width: 100%; justify-content: flex-start; }
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

.skill-card {
  cursor: pointer;
  transition: transform 0.25s, box-shadow 0.25s;
  height: 100%;
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border-soft) !important;
}

.skill-card:hover {
  transform: translateY(-6px);
  box-shadow: var(--shadow-hover) !important;
  border-color: var(--brand-100) !important;
}

.skill-cover {
  position: relative;
  width: calc(100% + 40px);
  height: 150px;
  overflow: hidden;
  margin: -20px -20px 10px -20px;
  border-radius: 17px 17px 0 0;
}

.skill-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center center;
  display: block;
  transition: transform 0.4s;
}
.skill-card:hover .skill-cover img {
  transform: scale(1.06);
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
  color: var(--brand-600);
  background: linear-gradient(135deg, var(--brand-50), var(--brand-100));
  border-radius: 17px 17px 0 0;
}

.skill-icon img {
  width: 48px;
  height: 48px;
  object-fit: contain;
}

.skill-info {
  text-align: center;
}

.skill-info h3 {
  margin: 10px 0;
  font-size: 18px;
  color: var(--ink);
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
  color: var(--ink-soft);
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
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-align: left;
}

.skill-module {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-soft);
  font-size: 13px;
  text-align: left;
}

.skill-module > span:not(.skill-metadata-tags) {
  color: var(--ink-soft);
}

.skill-roles {
  margin-top: 10px;
  font-size: 13px;
  text-align: left;
}

.skill-roles > span:not(.skill-metadata-tags) {
  color: var(--ink-soft);
}

.skill-module, .skill-roles { display: flex; align-items: flex-start; gap: 4px; }
.skill-module > span:first-child, .skill-roles > span:first-child { flex-shrink: 0; line-height: 20px; }

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 4px;
  padding: 0;
}
</style>
