<template>
  <div class="mcp-resource-inspector">
    <div v-if="data?.server" class="server-summary">
      <div>
        <strong>{{ data.server.name || '连接器' }}</strong>
        <span v-if="data.server.version">v{{ data.server.version }}</span>
      </div>
      <small v-if="data.protocol_version">协议版本 {{ data.protocol_version }}</small>
    </div>

    <el-tabs v-model="activeTab" class="resource-tabs">
      <el-tab-pane :label="`工具 (${items(data?.tools).length})`" name="tools">
        <el-table :data="items(data?.tools)" class="resource-table" height="min(52vh, 520px)" empty-text="无工具">
          <el-table-column label="名称" min-width="190"><template #default="{ row }">{{ row.name || '无' }}</template></el-table-column>
          <el-table-column label="说明" min-width="280">
            <template #default="{ row }">{{ row.description || '无' }}</template>
          </el-table-column>
          <el-table-column label="输入参数" min-width="260">
            <template #default="{ row }">
              <pre v-if="row.inputSchema" class="schema-preview">{{ pretty(row.inputSchema) }}</pre>
              <span v-else>无</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="`资源 (${items(data?.resources).length})`" name="resources">
        <el-table :data="items(data?.resources)" class="resource-table" height="min(52vh, 520px)" empty-text="无资源">
          <el-table-column prop="name" label="名称" min-width="170"><template #default="{ row }">{{ row.name || '无' }}</template></el-table-column>
          <el-table-column prop="uri" label="URI" min-width="280"><template #default="{ row }">{{ row.uri || '无' }}</template></el-table-column>
          <el-table-column prop="mimeType" label="类型" width="150"><template #default="{ row }">{{ row.mimeType || '无' }}</template></el-table-column>
          <el-table-column label="说明" min-width="240"><template #default="{ row }">{{ row.description || '无' }}</template></el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="`资源模板 (${items(data?.resource_templates).length})`" name="templates">
        <el-table :data="items(data?.resource_templates)" class="resource-table" height="min(52vh, 520px)" empty-text="无资源模板">
          <el-table-column prop="name" label="名称" min-width="170"><template #default="{ row }">{{ row.name || '无' }}</template></el-table-column>
          <el-table-column prop="uriTemplate" label="URI 模板" min-width="300"><template #default="{ row }">{{ row.uriTemplate || '无' }}</template></el-table-column>
          <el-table-column label="说明" min-width="260"><template #default="{ row }">{{ row.description || '无' }}</template></el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="`提示词 (${items(data?.prompts).length})`" name="prompts">
        <el-table :data="items(data?.prompts)" class="resource-table" height="min(52vh, 520px)" empty-text="无提示词">
          <el-table-column label="名称" min-width="190"><template #default="{ row }">{{ row.name || '无' }}</template></el-table-column>
          <el-table-column label="说明" min-width="280"><template #default="{ row }">{{ row.description || '无' }}</template></el-table-column>
          <el-table-column label="参数" min-width="260"><template #default="{ row }">{{ row.arguments?.length ? row.arguments.map(item => item.name).join('、') : '无' }}</template></el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: null },
})
const activeTab = ref('tools')
const items = value => Array.isArray(value) ? value : []
const pretty = value => {
  try { return JSON.stringify(value, null, 2) } catch { return String(value || '') }
}
watch(() => props.data, () => { activeTab.value = 'tools' })
</script>

<style scoped>
.server-summary {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  padding: 4px 2px 14px;
  color: var(--el-text-color-secondary);
}
.server-summary strong { color: var(--el-text-color-primary); font-size: 15px; }
.server-summary span { margin-left: 8px; font-size: 12px; }
.resource-table { width: 100%; }
.schema-preview { max-height: 100px; margin: 0; overflow: auto; white-space: pre-wrap; font: 12px/1.5 var(--el-font-family); color: var(--el-text-color-secondary); }
</style>
