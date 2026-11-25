<template>
  <IdentityShell>
    <div class="login-heading">
      <span class="login-icon" aria-hidden="true">
        <Lock />
      </span>
      <h1>登录 AI Hub</h1>
      <p>使用本地账号密码访问工作台</p>
    </div>

    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      class="login-form"
      @submit.prevent="handleLogin"
    >
      <el-form-item label="用户名" prop="username">
        <el-input
          v-model="form.username"
          size="large"
          placeholder="请输入用户名"
          autocomplete="username"
          @keyup.enter="handleLogin"
        />
      </el-form-item>
      <el-form-item label="密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          size="large"
          show-password
          placeholder="请输入密码"
          autocomplete="current-password"
          @keyup.enter="handleLogin"
        />
      </el-form-item>

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        :closable="false"
        show-icon
        class="login-error"
      />

      <el-button
        class="login-button"
        type="primary"
        size="large"
        native-type="submit"
        :loading="isLoggingIn"
      >
        <template v-if="!isLoggingIn">
          <span>登录</span>
          <el-icon><Right /></el-icon>
        </template>
        <span v-else>正在登录...</span>
      </el-button>
    </el-form>

    <router-link class="back-link" to="/home">返回首页</router-link>

    <div class="secure-note">
      <el-icon><CircleCheck /></el-icon>
      <span>默认管理员账号：admin / admin123（首次启动自动初始化）</span>
    </div>
  </IdentityShell>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CircleCheck, Lock, Right } from '@element-plus/icons-vue'
import IdentityShell from '@/components/auth/IdentityShell.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref(null)
const isLoggingIn = ref(false)
const errorMessage = ref('')

const form = reactive({
  username: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const handleLogin = async () => {
  if (isLoggingIn.value) return
  errorMessage.value = ''
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  isLoggingIn.value = true
  try {
    await authStore.login(form.username.trim(), form.password)
    const redirect = sessionStorage.getItem('auth_redirect')
    sessionStorage.removeItem('auth_redirect')
    await router.replace(redirect || '/workspace/chat')
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.friendlyMessage || error?.message
    errorMessage.value = typeof detail === 'string' && detail ? detail : '用户名或密码错误'
  } finally {
    isLoggingIn.value = false
  }
}
</script>

<style scoped>
.login-heading {
  text-align: center;
}

.login-icon {
  width: 44px;
  height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  color: #315efb;
  background: #edf2ff;
  border-radius: 8px;
}

.login-icon :deep(svg) {
  width: 22px;
  height: 22px;
}

h1 {
  margin: 0;
  color: #1f2937;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.35;
}

.login-heading p {
  margin: 8px 0 24px;
  color: #667085;
  font-size: 14px;
  line-height: 1.6;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.login-error {
  margin-bottom: 16px;
}

.login-button.el-button {
  width: 100%;
  height: 44px;
  gap: 6px;
  margin-top: 4px;
  color: #fff;
  background: #315efb;
  border-color: #315efb;
  border-radius: 6px;
  font-size: 15px;
  font-weight: 600;
}

.login-button.el-button:hover,
.login-button.el-button:focus-visible {
  background: #2447cc;
  border-color: #2447cc;
}

.back-link {
  width: 100%;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 10px;
  color: #667085;
  font-size: 13px;
  text-decoration: none;
}

.back-link:hover {
  color: #1f2937;
}

.secure-note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 14px;
  color: #667085;
  font-size: 12px;
}
</style>
