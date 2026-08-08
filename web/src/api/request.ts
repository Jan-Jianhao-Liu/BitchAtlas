import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

/** 后端统一响应体格式：code=1 表示成功 */
export interface ApiResult<T = any> {
  code: number
  message: string
  data: T
}

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001',
  timeout: 15000,
})

// 请求拦截器：自动携带 Authorization Bearer token
service.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('birchatlas_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：统一处理错误
service.interceptors.response.use(
  (response) => {
    const res = response.data as ApiResult
    // 业务成功：解包返回 data 字段
    if (res && typeof res.code === 'number' && res.code === 1) {
      return res.data
    }
    // 业务失败
    const message = (res && res.message) || '请求失败'
    ElMessage.error(message)
    return Promise.reject(new Error(message))
  },
  (error) => {
    const { response } = error
    if (response) {
      // 401：登录态失效，清理并跳转登录
      if (response.status === 401) {
        const authStore = useAuthStore()
        authStore.logout()
        ElMessage.error('登录已过期，请重新登录')
        router.replace('/login')
      } else {
        const message =
          (response.data && response.data.message) ||
          `请求错误 (${response.status})`
        ElMessage.error(message)
      }
    } else {
      ElMessage.error('网络异常，请检查网络连接')
    }
    return Promise.reject(error)
  }
)

export const get = <T = any>(
  url: string,
  params?: any,
  config?: AxiosRequestConfig
): Promise<T> => service.get(url, { params, ...config })

export const post = <T = any>(
  url: string,
  data?: any,
  config?: AxiosRequestConfig
): Promise<T> => service.post(url, data, config)

export const put = <T = any>(
  url: string,
  data?: any,
  config?: AxiosRequestConfig
): Promise<T> => service.put(url, data, config)

export const del = <T = any>(
  url: string,
  params?: any,
  config?: AxiosRequestConfig
): Promise<T> => service.delete(url, { params, ...config })

export default service
