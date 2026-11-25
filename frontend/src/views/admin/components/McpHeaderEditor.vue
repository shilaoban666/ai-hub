<template>
  <div class="mcp-header-editor">
    <div class="header-toolbar">
      <slot name="heading" />
      <div v-if="rows.length" class="header-actions">
        <el-button v-if="allowAuthorization && !hasAuthorization" size="small" @click="add('Authorization')">添加 Authorization</el-button>
        <el-button v-if="addLabel === '添加请求头'" :icon="Plus" size="small" type="primary" plain @click="add('')">添加请求头</el-button>
        <el-button v-else :icon="Plus" size="small" type="primary" plain @click="add('')">{{ addLabel }}</el-button>
      </div>
    </div>
    <div v-if="!rows.length" class="header-empty">
      <span class="header-empty-icon"><el-icon><Operation /></el-icon></span>
      <strong>{{ emptyTitle }}</strong>
      <span>{{ emptyDescription }}</span>
      <div class="header-empty-actions">
        <el-button v-if="allowAuthorization" size="small" @click="add('Authorization')">添加 Authorization</el-button>
        <el-button v-if="addLabel === '添加请求头'" :icon="Plus" size="small" type="primary" plain @click="add('')">添加请求头</el-button>
        <el-button v-else :icon="Plus" size="small" type="primary" plain @click="add('')">{{ addLabel }}</el-button>
      </div>
    </div>
    <template v-else>
      <div class="header-list-head" aria-hidden="true">
        <span>{{ nameLabel }}</span>
        <span>{{ valueLabel }}</span>
      </div>
      <div v-for="(row, index) in rows" :key="index" class="header-row">
        <el-input v-model="row.name" :placeholder="namePlaceholder" :aria-label="`${nameLabel} ${index + 1}`" maxlength="200" />
        <div class="header-value">
          <el-input
            v-model="row.value"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 5 }"
            resize="vertical"
            autocomplete="new-password"
            spellcheck="false"
            :placeholder="row.configured ? '已配置，留空保留；输入新值可替换' : valuePlaceholder"
            :aria-label="`${valueLabel} ${index + 1}`"
            maxlength="20000"
            @keydown.enter.prevent
          />
        </div>
        <el-tooltip content="删除请求头" placement="top">
          <el-button class="header-delete" :icon="Delete" circle text aria-label="删除请求头" @click="rows.splice(index, 1)" />
        </el-tooltip>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Delete, Operation, Plus } from '@element-plus/icons-vue'
defineProps({
  allowAuthorization: { type: Boolean, default: true },
  nameLabel: { type: String, default: '请求头名称' },
  valueLabel: { type: String, default: '请求头值' },
  namePlaceholder: { type: String, default: '例如 X-Tenant-ID' },
  valuePlaceholder: { type: String, default: '请求头值' },
  addLabel: { type: String, default: '添加请求头' },
  emptyTitle: { type: String, default: '没有附加请求头' },
  emptyDescription: { type: String, default: '此连接器暂未配置其他请求头' },
})
const rows = defineModel({ type: Array, required: true })
const hasAuthorization = computed(() => rows.value.some(row => row.name.toLowerCase() === 'authorization'))
const add = name => rows.value.push({
  name,
  value: name.toLowerCase() === 'authorization' ? 'Bearer ' : '',
})
</script>

<style scoped>
.mcp-header-editor { width: 100%; min-width: 0; }
.header-empty { min-height: 106px; display: flex; align-items: center; justify-content: center; flex-direction: column; padding: 16px; border: 1px dashed #d9dde3; border-radius: 6px; color: #8a919c; background: #fafbfc; text-align: center; }
.header-empty-icon { width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 7px; border-radius: 6px; color: #76808c; background: #eef1f4; font-size: 16px; }
.header-empty strong { color: #555d68; font-size: 13px; font-weight: 600; line-height: 19px; }
.header-empty > span:not(.header-empty-icon) { margin-top: 1px; font-size: 12px; line-height: 18px; }
.header-empty-actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 12px; }
.header-toolbar { min-height: 32px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.header-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; margin-left: auto; }
.header-actions .el-button + .el-button { margin-left: 0; }
.header-list-head { display: grid; grid-template-columns: minmax(160px, 2fr) minmax(0, 4fr) 32px; gap: 8px; padding: 0 1px 6px; color: #7f8792; font-size: 11px; }
.header-row { display: grid; grid-template-columns: minmax(160px, 2fr) minmax(0, 4fr) 32px; align-items: start; gap: 8px; margin-top: 8px; }
.header-value { position: relative; min-width: 0; }
.header-value :deep(.el-textarea__inner) {
  min-height: 32px !important;
  line-height: 20px;
  overflow-wrap: anywhere;
  word-break: break-all;
}
.header-delete.el-button { margin-top: 4px; }
@media (max-width: 540px) {
  .header-list-head { display: none; }
  .header-row { grid-template-columns: minmax(0, 1fr) 32px; }
  .header-row > :first-child { grid-column: 1; }
  .header-row > :nth-child(2) { grid-column: 1; grid-row: 2; }
  .header-row > :last-child { grid-column: 2; grid-row: 1 / 3; align-self: center; }
}
</style>
