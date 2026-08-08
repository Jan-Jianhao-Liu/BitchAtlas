<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <span>项目测点</span>
      </template>
      <el-tree
        :data="treeData"
        :props="{ label: 'name', children: 'children' }"
        default-expand-all
        node-key="id"
      >
        <template #default="{ node, data }">
          <span class="tree-node">
            <el-icon v-if="data.type === 'project'"><Folder /></el-icon>
            <el-icon v-else-if="data.type === 'gateway'"><Monitor /></el-icon>
            <el-icon v-else><Location /></el-icon>
            <span>{{ node.label }}</span>
            <el-tag size="small" style="margin-left: 8px;">{{ data.code }}</el-tag>
          </span>
        </template>
      </el-tree>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { Folder, Monitor, Location } from '@element-plus/icons-vue'

const treeData = [
  {
    id: '1',
    name: '1号楼',
    type: 'project',
    code: 'PRJ-001',
    children: [
      {
        id: '1-1',
        name: '网关-01',
        type: 'gateway',
        code: 'GW-00000001',
        children: [
          { id: '1-1-1', name: '测点-001', type: 'measure_point', code: 'MP-001' },
          { id: '1-1-2', name: '测点-002', type: 'measure_point', code: 'MP-002' },
          { id: '1-1-3', name: '测点-003', type: 'measure_point', code: 'MP-003' },
        ],
      },
      {
        id: '1-2',
        name: '网关-02',
        type: 'gateway',
        code: 'GW-00000002',
        children: [
          { id: '1-2-1', name: '测点-004', type: 'measure_point', code: 'MP-004' },
          { id: '1-2-2', name: '测点-005', type: 'measure_point', code: 'MP-005' },
        ],
      },
    ],
  },
  {
    id: '2',
    name: '2号楼',
    type: 'project',
    code: 'PRJ-002',
    children: [
      {
        id: '2-1',
        name: '网关-01',
        type: 'gateway',
        code: 'GW-00000003',
        children: [
          { id: '2-1-1', name: '测点-006', type: 'measure_point', code: 'MP-006' },
          { id: '2-1-2', name: '测点-007', type: 'measure_point', code: 'MP-007' },
        ],
      },
    ],
  },
]
</script>

<style scoped>
.tree-node {
  display: flex;
  align-items: center;
  padding: 4px 0;
}
</style>