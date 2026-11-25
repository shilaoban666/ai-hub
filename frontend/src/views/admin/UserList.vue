<template>
  <div class="page-container">
    <div class="page-header">
      <h2>用户管理</h2>
      <div class="header-actions">
        <el-select v-model="superuser" clearable placeholder="全部超级用户状态" aria-label="超级用户筛选"
          class="superuser-filter" @change="applyFilters">
          <el-option label="超级用户：是" :value="true" />
          <el-option label="超级用户：否" :value="false" />
        </el-select>
        <el-input
          v-model="search"
          clearable
          placeholder="搜索用户名、姓名或邮箱"
          class="username-filter"
          @keyup.enter="applyFilters"
          @clear="applyFilters"
        />
        <el-button type="primary" :loading="loading" @click="applyFilters">搜索</el-button>
        <el-button type="primary" plain @click="openCreateDialog">新建用户</el-button>
      </div>
    </div>

    <el-table :data="users" v-loading="loading" stripe empty-text="无">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" min-width="140" />
      <el-table-column prop="first_name" label="姓名" min-width="120">
        <template #default="{ row }">{{ display(row.first_name) }}</template>
      </el-table-column>
      <el-table-column prop="email" label="邮箱" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ display(row.email) }}</template>
      </el-table-column>
      <el-table-column label="超级用户" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_superuser ? 'danger' : 'info'" size="small">
            {{ row.is_superuser ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'warning'" size="small">
            {{ row.is_active ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="openEditDialog(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-container" v-if="total > 0">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next, jumper"
        @current-change="loadUsers"
      />
    </div>

    <el-dialog v-model="showDialog" :title="editingUser ? '编辑用户' : '新建用户'" width="460px" :close-on-click-modal="false">
      <el-form label-width="90px">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" :disabled="!!editingUser" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item :label="editingUser ? '重置密码' : '密码'" :required="!editingUser">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="editingUser ? '留空则不修改密码' : '至少 4 位'"
          />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.first_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="可选" />
        </el-form-item>
        <el-form-item label="超级用户">
          <el-switch v-model="form.is_superuser" />
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveUser">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api/admin'

const users = ref([])
const loading = ref(false)
const search = ref('')
const superuser = ref(null)
const page = ref(1)
const pageSize = 20
const total = ref(0)

const showDialog = ref(false)
const saving = ref(false)
const editingUser = ref(null)
const form = reactive({
  username: '',
  password: '',
  first_name: '',
  email: '',
  is_superuser: false,
  is_active: true,
})

const display = (value) => (value == null || !String(value).trim() ? '无' : value)

const loadUsers = async () => {
  loading.value = true
  try {
    const params = {
      skip: (page.value - 1) * pageSize,
      limit: pageSize,
    }
    if (search.value.trim()) params.search = search.value.trim()
    if (superuser.value !== null && superuser.value !== '') params.is_superuser = superuser.value
    const data = await adminApi.getManagementUsers(params)
    users.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '获取用户列表失败')
  } finally {
    loading.value = false
  }
}

const applyFilters = () => {
  page.value = 1
  loadUsers()
}

const openCreateDialog = () => {
  editingUser.value = null
  Object.assign(form, {
    username: '',
    password: '',
    first_name: '',
    email: '',
    is_superuser: false,
    is_active: true,
  })
  showDialog.value = true
}

const openEditDialog = (row) => {
  editingUser.value = row
  Object.assign(form, {
    username: row.username,
    password: '',
    first_name: row.first_name || '',
    email: row.email || '',
    is_superuser: !!row.is_superuser,
    is_active: row.is_active !== false,
  })
  showDialog.value = true
}

const saveUser = async () => {
  if (!editingUser.value && (!form.username.trim() || form.password.length < 4)) {
    ElMessage.warning('请填写用户名和至少 4 位密码')
    return
  }
  saving.value = true
  try {
    if (editingUser.value) {
      const payload = {
        first_name: form.first_name,
        email: form.email,
        is_superuser: form.is_superuser,
        is_active: form.is_active,
      }
      if (form.password) payload.password = form.password
      await adminApi.updateUser(editingUser.value.id, payload)
      ElMessage.success('用户已更新')
    } else {
      await adminApi.createUser({
        username: form.username.trim(),
        password: form.password,
        first_name: form.first_name,
        email: form.email,
        is_superuser: form.is_superuser,
        is_active: form.is_active,
      })
      ElMessage.success('用户已创建')
    }
    showDialog.value = false
    await loadUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存用户失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.page-container { padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 20px; }
.page-header h2 { margin: 0; font-size: 20px; flex-shrink: 0; }
.header-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.superuser-filter { width: 170px; }
.username-filter { width: 220px; }
.pagination-container { display: flex; justify-content: flex-end; margin-top: 20px; }
</style>
