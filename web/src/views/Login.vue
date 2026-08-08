<template>
  <div class="login-container">
    <el-card class="login-card" shadow="always">
      <div class="login-header">
        <h2>BirchAtlas</h2>
        <span>桦聚图集控制台</span>
      </div>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @keyup.enter="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            :prefix-icon="User"
            placeholder="请输入用户名"
            size="large"
          />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            :prefix-icon="Lock"
            type="password"
            show-password
            placeholder="请输入密码"
            size="large"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            size="large"
            style="width: 100%"
            @click="handleLogin"
          >
            登 录
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await authStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      router.replace('/dashboard')
    } catch {
      // 错误信息已在 request 拦截器中统一提示
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-container {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #141414;
  background-image: radial-gradient(
      circle at 20% 20%,
      rgba(64, 158, 255, 0.08),
      transparent 40%
    ),
    radial-gradient(circle at 80% 80%, rgba(64, 158, 255, 0.05), transparent 40%);
}

.login-card {
  width: 400px;
  background-color: #1d1e1f;
  border: 1px solid #2d2d2d;
}

.login-header {
  text-align: center;
  margin-bottom: 24px;
}

.login-header h2 {
  color: #409eff;
  margin: 0 0 6px;
  font-size: 24px;
}

.login-header span {
  color: #888;
  font-size: 13px;
}

.login-card :deep(.el-form-item__label) {
  color: #c0c4cc;
}

.login-card :deep(.el-input__wrapper) {
  background-color: #141414;
  box-shadow: 0 0 0 1px #2d2d2d inset;
}

.login-card :deep(.el-input__inner) {
  color: #fff;
}
</style>
