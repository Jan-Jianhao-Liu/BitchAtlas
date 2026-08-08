import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', requiresAuth: false },
  },
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '总览大屏', icon: 'DataAnalysis', requiresAuth: true },
  },
  {
    path: '/devices',
    name: 'Devices',
    component: () => import('@/views/Devices.vue'),
    meta: { title: '设备管理', icon: 'Monitor', requiresAuth: true },
  },
  {
    path: '/projects',
    name: 'Projects',
    component: () => import('@/views/Projects.vue'),
    meta: { title: '项目测点', icon: 'Location', requiresAuth: true },
  },
  {
    path: '/algorithms',
    name: 'Algorithms',
    component: () => import('@/views/Algorithms.vue'),
    meta: { title: '算法中心', icon: 'Cpu', requiresAuth: true },
  },
  {
    path: '/detection',
    name: 'Detection',
    component: () => import('@/views/Detection.vue'),
    meta: { title: '检测任务', icon: 'Camera', requiresAuth: true },
  },
  {
    path: '/data',
    name: 'Data',
    component: () => import('@/views/DataBoard.vue'),
    meta: { title: '数据看板', icon: 'DataLine', requiresAuth: true },
  },
  {
    path: '/clustering',
    name: 'Clustering',
    component: () => import('@/views/Clustering.vue'),
    meta: { title: '聚类分析', icon: 'Share', requiresAuth: true },
  },
  {
    path: '/alerts',
    name: 'Alerts',
    component: () => import('@/views/Alerts.vue'),
    meta: { title: '告警中心', icon: 'Bell', requiresAuth: true },
  },
  {
    path: '/system',
    name: 'System',
    component: () => import('@/views/System.vue'),
    meta: { title: '系统管理', icon: 'Setting', requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局前置守卫：未登录跳转 /login，已登录访问 /login 跳转 /dashboard
router.beforeEach((to) => {
  const authStore = useAuthStore()
  if (to.path === '/login') {
    return authStore.isAuthenticated ? '/dashboard' : true
  }
  return authStore.isAuthenticated ? true : '/login'
})

export default router
