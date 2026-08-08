<template>
  <div class="dashboard-container">
    <el-row :gutter="20">
      <!-- 统计卡片 -->
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-info">
              <span class="stat-value">{{ stats.totalDevices }}</span>
              <span class="stat-label">设备总数</span>
            </div>
            <el-icon class="stat-icon" :size="48" color="#409EFF"><Monitor /></el-icon>
          </div>
          <div class="stat-trend up">
            <el-icon><CaretTop /></el-icon>
            <span>在线率 {{ stats.onlineRate }}%</span>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-info">
              <span class="stat-value">{{ stats.todayDetections }}</span>
              <span class="stat-label">今日检测</span>
            </div>
            <el-icon class="stat-icon" :size="48" color="#67C23A"><Camera /></el-icon>
          </div>
          <div class="stat-trend">
            <span>检测值 {{ stats.totalValues }}</span>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-info">
              <span class="stat-value">{{ stats.outlierCount }}</span>
              <span class="stat-label">离群检测</span>
            </div>
            <el-icon class="stat-icon" :size="48" color="#E6A23C"><Warning /></el-icon>
          </div>
          <div class="stat-trend down">
            <el-icon><CaretBottom /></el-icon>
            <span>异常率 {{ stats.outlierRate }}%</span>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-info">
              <span class="stat-value">{{ stats.totalProjects }}</span>
              <span class="stat-label">项目总数</span>
            </div>
            <el-icon class="stat-icon" :size="48" color="#909399"><Location /></el-icon>
          </div>
          <div class="stat-trend">
            <span>测点 {{ stats.totalMeasurePoints }}</span>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <el-row :gutter="20" style="margin-top: 20px;">
      <!-- 检测趋势图 -->
      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>检测趋势</span>
              <el-radio-group v-model="trendRange" size="small">
                <el-radio-button value="7d">7天</el-radio-button>
                <el-radio-button value="30d">30天</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <div ref="trendChartRef" style="height: 300px;"></div>
        </el-card>
      </el-col>
      
      <!-- 质量分布 -->
      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>质量等级分布</span>
            </div>
          </template>
          <div ref="qualityChartRef" style="height: 300px;"></div>
        </el-card>
      </el-col>
    </el-row>
    
    <el-row :gutter="20" style="margin-top: 20px;">
      <!-- 设备列表 -->
      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>在线设备</span>
              <el-button size="small" type="primary" plain>刷新</el-button>
            </div>
          </template>
          <el-table :data="onlineDevices" style="width: 100%" size="small">
            <el-table-column prop="code" label="设备编号" width="150" />
            <el-table-column prop="name" label="名称" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'online' ? 'success' : 'danger'" size="small">
                  {{ row.status === 'online' ? '在线' : '离线' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="lastUpdate" label="最后更新" width="150" />
          </el-table>
        </el-card>
      </el-col>
      
      <!-- 最近告警 -->
      <el-col :span="12">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>最近告警</span>
              <el-button size="small" type="danger" plain>查看全部</el-button>
            </div>
          </template>
          <el-timeline>
            <el-timeline-item
              v-for="(alert, index) in recentAlerts"
              :key="index"
              :type="alert.severity === 'high' ? 'danger' : alert.severity === 'medium' ? 'warning' : 'info'"
              :timestamp="alert.time"
            >
              <div class="alert-item">
                <span class="alert-title">{{ alert.title }}</span>
                <span class="alert-device">{{ alert.device }}</span>
              </div>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import {
  Monitor,
  Camera,
  Warning,
  Location,
  CaretTop,
  CaretBottom
} from '@element-plus/icons-vue'

// 统计数据
const stats = reactive({
  totalDevices: 12,
  onlineRate: 91.7,
  todayDetections: 356,
  totalValues: 2848,
  outlierCount: 23,
  outlierRate: 0.8,
  totalProjects: 5,
  totalMeasurePoints: 48,
})

const trendRange = ref('7d')
const trendChartRef = ref<HTMLDivElement>()
const qualityChartRef = ref<HTMLDivElement>()

// 在线设备
const onlineDevices = ref([
  { code: 'GW-00000001', name: '1号楼网关-01', status: 'online', lastUpdate: '2026-08-07 16:30' },
  { code: 'GW-00000002', name: '1号楼网关-02', status: 'online', lastUpdate: '2026-08-07 16:29' },
  { code: 'GW-00000003', name: '2号楼网关-01', status: 'online', lastUpdate: '2026-08-07 16:28' },
  { code: 'GW-00000004', name: '2号楼网关-02', status: 'offline', lastUpdate: '2026-08-06 18:45' },
  { code: 'GW-00000005', name: '3号楼网关-01', status: 'online', lastUpdate: '2026-08-07 16:30' },
])

// 最近告警
const recentAlerts = ref([
  { title: '设备 GW-00000004 离线', device: 'GW-00000004', severity: 'high', time: '2小时前' },
  { title: '测点 MP-015 检测异常值', device: 'GW-00000002', severity: 'medium', time: '3小时前' },
  { title: 'CF 树合并完成', device: 'GW-00000001', severity: 'info', time: '5小时前' },
  { title: '算法包灰度发布成功', device: '系统', severity: 'info', time: '1天前' },
])

onMounted(async () => {
  await nextTick()
  initTrendChart()
  initQualityChart()
})

function initTrendChart() {
  if (!trendChartRef.value) return
  
  const chart = echarts.init(trendChartRef.value)
  const days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
  
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['检测次数', '离群次数'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: days, boundaryGap: false },
    yAxis: { type: 'value' },
    series: [
      {
        name: '检测次数',
        type: 'line',
        smooth: true,
        data: [280, 320, 350, 290, 360, 400, 356],
        itemStyle: { color: '#409EFF' },
      },
      {
        name: '离群次数',
        type: 'line',
        smooth: true,
        data: [12, 18, 15, 10, 22, 28, 23],
        itemStyle: { color: '#E6A23C' },
      },
    ],
  })
}

function initQualityChart() {
  if (!qualityChartRef.value) return
  
  const chart = echarts.init(qualityChartRef.value)
  
  chart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: '5%', left: 'center' },
    series: [
      {
        name: '质量等级',
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 10, borderColor: '#141414', borderWidth: 2 },
        label: { show: false, position: 'center' },
        emphasis: { label: { show: true, fontSize: 20, fontWeight: 'bold' } },
        labelLine: { show: false },
        data: [
          { value: 2800, name: 'A 级 (优良)', itemStyle: { color: '#67C23A' } },
          { value: 800, name: 'B 级 (合格)', itemStyle: { color: '#409EFF' } },
          { value: 180, name: 'C 级 (警告)', itemStyle: { color: '#E6A23C' } },
          { value: 45, name: 'D 级 (不合格)', itemStyle: { color: '#F56C6C' } },
        ],
      },
    ],
  })
}
</script>

<style scoped>
.dashboard-container {
  padding: 10px;
}

.stat-card {
  background: linear-gradient(135deg, #1d1e1f 0%, #262626 100%);
  border: 1px solid #2d2d2d;
}

.stat-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 32px;
  font-weight: bold;
  color: #fff;
}

.stat-label {
  font-size: 14px;
  color: #888;
  margin-top: 5px;
}

.stat-icon {
  opacity: 0.8;
}

.stat-trend {
  margin-top: 10px;
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #888;
}

.stat-trend.up { color: #67C23A; }
.stat-trend.down { color: #F56C6C; }

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header span {
  font-weight: bold;
  color: #c0c4cc;
}

.alert-item {
  display: flex;
  flex-direction: column;
}

.alert-title {
  color: #fff;
}

.alert-device {
  font-size: 12px;
  color: #888;
  margin-top: 2px;
}
</style>