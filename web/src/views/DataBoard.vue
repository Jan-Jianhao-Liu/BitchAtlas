<template>
  <div class="page-container">
    <el-empty description="功能开发中...">
      <template #image>
        <el-icon :size="64" color="#666"><DataLine /></el-icon>
      </template>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { DataLine } from '@element-plus/icons-vue'
</script>