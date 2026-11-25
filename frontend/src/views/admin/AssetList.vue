<template>
  <div class="asset-list">
    <div class="header">
      <h2>数字资产</h2>
      <div class="header-actions">
        <el-button type="primary">
          <el-icon><Plus /></el-icon>
          添加资产
        </el-button>
      </div>
    </div>

    <el-empty description="功能开发中..." />
  </div>
</template>

<script setup>
import { Plus } from '@element-plus/icons-vue'
</script>

<style scoped>
.asset-list {
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
  color: #333;
}

.header-actions {
  display: flex;
  gap: 12px;
}
</style>
