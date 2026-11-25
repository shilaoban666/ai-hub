<template>
  <div class="template-detail-page" v-loading="loading">
    <el-button class="back-btn" @click="router.push('/prompt-templates')" :icon="ArrowLeft" text>
      返回列表
    </el-button>
    <div class="detail-card" v-if="template.id">
      <div class="detail-header">
        <h1>{{ template.name }}</h1>
        <el-tag size="small" type="primary">{{ template.category }}</el-tag>
      </div>
      <div class="meta-row">
        <span>作者：{{ template.author || '匿名' }}</span>
        <span>创建时间：{{ formatTime(template.created_at) }}</span>
      </div>

      <div class="section" v-if="template.description">
        <h3>描述</h3>
        <p>{{ template.description }}</p>
      </div>

      <div class="section">
        <h3>提示词内容</h3>
        <pre class="prompt-content" v-html="highlightedContent" />
      </div>

      <div class="section" v-if="parsedVariables.length > 0">
        <h3>变量定义</h3>
        <el-table :data="parsedVariables" size="small">
          <el-table-column prop="name" label="变量名" min-width="100" />
          <el-table-column prop="type" label="类型" min-width="80" />
          <el-table-column prop="default" label="默认值" min-width="100" />
          <el-table-column prop="description" label="描述" min-width="120" />
          <el-table-column label="必填" min-width="80">
            <template #default="{ row }">{{ row.required ? '是' : '否' }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { publicPromptTemplatesApi } from '@/api/prompt-templates'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { formatBeijingDateTime } from '@/utils/date-time'

const router = useRouter()
const route = useRoute()
const templateId = Number(route.params.id)

const loading = ref(false)
const template = ref({})

const parseVariables = (str) => {
  if (!str) return []
  try {
    return JSON.parse(str)
  } catch {
    return []
  }
}

const parsedVariables = computed(() => parseVariables(template.value.variables))

const highlightedContent = computed(() => {
  const content = template.value.content || ''
  return content.replace(
    /\{\{(\w+)\}\}/g,
    '<mark class="var-highlight">{{ $1 }}</mark>'
  )
})

const formatTime = (t) => {
  if (!t) return '无'
  return formatBeijingDateTime(t, { fallback: '无' })
}

const fetchDetail = async () => {
  loading.value = true
  try {
    template.value = await publicPromptTemplatesApi.getDetail(templateId)
  } catch (e) {
    ElMessage.error('获取模板信息失败')
    router.push('/prompt-templates')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchDetail()
})
</script>

<style scoped>
.template-detail-page {
  max-width: 1400px;
  margin: 0 auto;
}

.back-btn {
  margin-bottom: 12px;
}

.detail-card {
  background: var(--card);
  border-radius: 18px;
  padding: 28px;
  box-shadow: var(--shadow);
  border: 1px solid var(--border-soft);
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.detail-header h1 {
  margin: 0;
  font-size: 24px;
  color: var(--ink);
}

.meta-row {
  display: flex;
  gap: 24px;
  color: var(--ink-soft);
  font-size: 13px;
  margin-bottom: 24px;
}

.section {
  margin-top: 24px;
}

.section h3 {
  margin: 0 0 12px 0;
  font-size: 16px;
  color: var(--ink);
  border-bottom: 1px solid var(--border-soft);
  padding-bottom: 8px;
}

.section p {
  color: var(--ink-soft);
  line-height: 1.7;
  margin: 0;
}

.prompt-content {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 14px;
  line-height: 1.6;
  color: var(--ink);
  background: var(--brand-100);
  padding: 16px;
  border-radius: 10px;
  margin: 0;
}

.prompt-content :deep(.var-highlight) {
  background: var(--brand-50);
  color: #4267c4;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 500;
}
</style>
