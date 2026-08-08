import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authApi from '@/api/auth'

const TOKEN_KEY = 'birchatlas_token'
const REFRESH_TOKEN_KEY = 'birchatlas_refresh_token'
const USER_KEY = 'birchatlas_user'

export interface UserInfo {
  username: string
  role: string
}

function readUser(): UserInfo | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserInfo
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
  const refreshToken = ref<string>(localStorage.getItem(REFRESH_TOKEN_KEY) || '')
  const user = ref<UserInfo | null>(readUser())

  const isAuthenticated = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  /** 登录并持久化凭证 */
  async function login(username: string, password: string) {
    const data = await authApi.login(username, password)
    token.value = data.token
    refreshToken.value = data.refreshToken || ''
    user.value = {
      username: data.username || username,
      role: data.role || 'user',
    }
    localStorage.setItem(TOKEN_KEY, token.value)
    if (refreshToken.value) {
      localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken.value)
    }
    localStorage.setItem(USER_KEY, JSON.stringify(user.value))
  }

  /** 退出登录，清理全部凭证 */
  function logout() {
    token.value = ''
    refreshToken.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  /** 拉取并刷新当前用户信息 */
  async function fetchProfile() {
    const data = await authApi.getProfile()
    user.value = { username: data.username, role: data.role }
    localStorage.setItem(USER_KEY, JSON.stringify(user.value))
  }

  /** 从 localStorage 重新恢复状态（用于跨标签页同步等场景） */
  function restoreFromStorage() {
    token.value = localStorage.getItem(TOKEN_KEY) || ''
    refreshToken.value = localStorage.getItem(REFRESH_TOKEN_KEY) || ''
    user.value = readUser()
  }

  return {
    token,
    refreshToken,
    user,
    isAuthenticated,
    isAdmin,
    login,
    logout,
    fetchProfile,
    restoreFromStorage,
  }
})
