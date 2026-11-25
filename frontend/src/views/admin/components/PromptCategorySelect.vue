<template>
  <el-select
    v-model="category"
    filterable
    allow-create
    default-first-option
    :reserve-keyword="false"
    placeholder="选择或输入分类"
    aria-label="提示词分类"
    no-match-text="没有匹配的分类，回车创建新分类"
    style="width: 100%"
  >
    <el-option v-for="name in categoryOptions" :key="name" :label="name" :value="name" />
  </el-select>
</template>

<script setup>
import { computed } from 'vue'
import { promptCategories } from '@/constants/prompt-categories'

const category = defineModel({ type: String, default: '' })
// 编辑历史模板时保留当前分类，避免改动其他字段时意外改变分类。
const categoryOptions = computed(() => category.value && !promptCategories.includes(category.value)
  ? [category.value, ...promptCategories]
  : promptCategories)
</script>
