<template>
  <el-container class="app-container">
    <el-aside width="220px" class="sidebar">
      <div class="logo">
        <h2>BirchAtlas</h2>
        <span>桦聚图集</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        background-color="#1d1e1f"
        text-color="#c0c4cc"
        active-text-color="#409EFF"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataAnalysis /></el-icon>
          <span>总览大屏</span>
        </el-menu-item>
        <el-menu-item index="/devices">
          <el-icon><Monitor /></el-icon>
          <span>设备管理</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><Location /></el-icon>
          <span>项目测点</span>
        </el-menu-item>
        <el-menu-item index="/algorithms">
          <el-icon><Cpu /></el-icon>
          <span>算法中心</span>
        </el-menu-item>
        <el-menu-item index="/detection">
          <el-icon><Camera /></el-icon>
          <span>检测任务</span>
        </el-menu-item>
        <el-menu-item index="/data">
          <el-icon><DataLine /></el-icon>
          <span>数据看板</span>
        </el-menu-item>
        <el-menu-item index="/clustering">
          <el-icon><Share /></el-icon>
          <span>聚类分析</span>
        </el-menu-item>
        <el-menu-item index="/alerts">
          <el-icon><Bell /></el-icon>
          <span>告警中心</span>
        </el-menu-item>
        <el-menu-item index="/system">
          <el-icon><Setting /></el-icon>
          <span>系统管理</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentPage }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-dropdown>
            <span class="user-info">
              <el-avatar :size="32" :icon="UserFilled" />
              <span class="username">Admin</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item>个人中心</el-dropdown-item>
                <el-dropdown-item>修改密码</el-dropdown-item>
                <el-dropdown-item divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      
      <el-main class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  DataAnalysis,
  Monitor,
  Location,
  Cpu,
  Camera,
  DataLine,
  Share,
  Bell,
  Setting,
  UserFilled
} from '@element-plus/icons-vue'

const route = useRoute()
const activeMenu = computed(() => route.path)
const currentPage = computed(() => route.meta.title as string || '首页')
</script>

<style scoped>
.app-container {
  height: 100vh;
  background-color: #141414;
}

.sidebar {
  background-color: #1d1e1f;
  border-right: 1px solid #2d2d2d;
  overflow-x: hidden;
}

.logo {
  padding: 20px;
  text-align: center;
  border-bottom: 1px solid #2d2d2d;
}

.logo h2 {
  color: #409EFF;
  margin: 0;
  font-size: 20px;
}

.logo span {
  color: #888;
  font-size: 12px;
}

.sidebar .el-menu {
  border-right: none;
}

.sidebar .el-menu-item {
  height: 50px;
  line-height: 50px;
}

.sidebar .el-menu-item.is-active {
  background-color: #263445;
  border-right: 3px solid #409EFF;
}

.header {
  background-color: #1d1e1f;
  border-bottom: 1px solid #2d2d2d;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 20px;
}

.header-left .el-breadcrumb {
  font-size: 14px;
}

.user-info {
  display: flex;
  align-items: center;
  cursor: pointer;
}

.username {
  margin-left: 8px;
  color: #c0c4cc;
}

.main-content {
  background-color: #141414;
  padding: 20px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>