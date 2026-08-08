import { get, post } from './request'

export interface LoginResult {
  token: string
  refreshToken?: string
  username?: string
  role?: string
}

export interface UserProfile {
  username: string
  role: string
}

/** 登录 */
export function login(username: string, password: string) {
  return post<LoginResult>('/api/v1/auth/login', { username, password })
}

/** 获取当前用户信息 */
export function getProfile() {
  return get<UserProfile>('/api/v1/auth/profile')
}

/** 校验 token 是否有效 */
export function validateToken() {
  return post('/api/v1/auth/validate')
}

/** 刷新 token */
export function refreshToken() {
  return post<LoginResult>('/api/v1/auth/refresh')
}
