<template>
  <div class="devices-page">
    <el-card>
      <template #header>
        <div class="page-header">
          <span>设备管理</span>
          <el-button type="primary" :icon="Plus">注册设备</el-button>
        </div>
      </template>
      
      <el-form :inline="true" :model="searchForm" class="search-form">
        <el-form-item label="设备编号">
          <el-input v-model="searchForm.code" placeholder="请输入" clearable />
        </el-form-item>
        <el-form-item label="设备类型">
          <el-select v-model="searchForm.type" placeholder="全部" clearable>
            <el-option label="网关" value="gateway" />
            <el-option label="采集仪" value="collector" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="searchForm.status" placeholder="全部" clearable>
            <el-option label="在线" value="online" />
            <el-option label="离线" value="offline" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search">搜索</el-button>
          <el-button :icon="Refresh">重置</el-button>
        </el-form-item>
      </el-form>
      
      <el-table :data="devices" style="width: 100%">
        <el-table-column prop="code" label="设备编号" width="150" />
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag :type="row.type === 'gateway' ? 'primary' : 'success'" size="small">
              {{ row.type === 'gateway' ? '网关' : '采集仪' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="project" label="所属项目" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'online' ? 'success' : 'danger'" size="small">
              {{ row.status === 'online' ? '在线' : '离线' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="lastUpdate" label="最后更新" width="170" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="viewShadow(row)">影子</el-button>
            <el-button size="small" type="warning" link @click="otaUpgrade(row)">OTA</el-button>
            <el-button size="small" type="danger" link @click="removeDevice(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      
      <el-pagination
        style="margin-top: 16px; justify-content: flex-end;"
        background
        layout="total, prev, pager, next"
        :total="devices.length"
        v-model:current-page="currentPage"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { Plus, Search, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const searchForm = reactive({
  code: '',
  type: '',
  status: '',
})

const currentPage = ref(1)

const devices = ref([
  { code: 'GW-00000001', name: '1号楼网关-01', type: 'gateway', project: '1号楼', status: 'online', lastUpdate: '2026-08-07 16:30' },
  { code: 'GW-00000002', name: '1号楼网关-02', type: 'gateway', project: '1号楼', status: 'online', lastUpdate: '2026-08-07 16:29' },
  { code: 'GW-00000003', name: '2号楼网关-01', type: 'gateway', project: '2号楼', status: 'online', lastUpdate: '2026-08-07 16:28' },
  { code: 'GW-00000004', name: '2号楼网关-02', type: 'gateway', project: '2号楼', status: 'offline', lastUpdate: '2026-08-06 18:45' },
  { code: 'BB-00000001', name: '采集仪-01', type: 'collector', project: '1号楼', status: 'online', lastUpdate: '2026-08-07 16:30' },
  { code: 'BB-00000002', name: '采集仪-02', type: 'collector', project: '1号楼', status: 'online', lastUpdate: '2026-08-07 16:29' },
  { code: 'BB-00000003', name: '采集仪-03', type: 'collector', project: '2号楼', status: 'online', lastUpdate: '2026-08-07 16:28' },
])

function viewShadow(row: any) {
  ElMessage.info(`查看设备影子: ${row.code}`)
}

function otaUpgrade(row: any) {
  ElMessageBox.confirm(
    `确定对设备 ${row.code} 发起 OTA 升级？`,
    'OTA 升级确认',
    {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    }
  ).then(() => {
    ElMessage.success('OTA 升级指令已下发')
  }).catch(() => {})
}

function removeDevice(row: any) {
  ElMessageBox.confirm(
    `确定删除设备 ${row.code}？此操作不可恢复！`,
    '删除确认',
    {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'error',
    }
  ).then(() => {
    ElMessage.success('设备已删除')
  }).catch(() => {})
}
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-header span {
  font-weight: bold;
  font-size: 16px;
  color: #c0c4cc;
}

.search-form {
  margin-bottom: 20px;
}

.devices-page :deep(.el-card),
.devices-page :deep(.el-table) {
  background-color: transparent;
  border-color: #2d2d2d;
}

.devices-page :deep(.el-table th) {
  background-color: #1d1e1f;
  color: #888;
}

.devices-page :deep(.el-table tr),
.devices-page :deep(.el-table td) {
  border-bottom-color: #2d2d2d;
}
</style>