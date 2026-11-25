<template>
  <el-select
    v-model="category"
    filterable
    allow-create
    default-first-option
    :reserve-keyword="false"
    placeholder="选择或输入分类"
    aria-label="MCP 分类"
    no-match-text="没有匹配的分类，回车创建新分类"
    style="width: 100%"
  >
    <el-option v-for="name in categoryOptions" :key="name" :label="name" :value="name" />
  </el-select>
</template>

<script setup>
import { computed } from 'vue'
import { mcpCategories } from '@/constants/mcp-categories'

const category = defineModel({ type: String, default: '' })
// 编辑历史 MCP 时保留当前自定义分类，避免未修改分类时丢失原值。
const categoryOptions = computed(() => category.value && !mcpCategories.includes(category.value)
  ? [category.value, ...mcpCategories]
  : mcpCategories)
</script>
