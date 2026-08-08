<template>
  <div class="clustering-page">
    <el-row :gutter="20">
      <!-- 左侧：聚类任务配置 -->
      <el-col :span="8">
        <el-card>
          <template #header>
            <span>创建聚类任务</span>
          </template>
          
          <el-form :model="jobForm" label-position="top">
            <el-form-item label="任务 ID">
              <el-input v-model="jobForm.id" placeholder="留空自动生成" />
            </el-form-item>
            
            <el-form-item label="算法选择">
              <el-select v-model="jobForm.algorithm" style="width: 100%">
                <el-option label="K-Means 聚类" value="kmeans" />
                <el-option label="层次聚类" value="hierarchical" />
                <el-option label="DBSCAN 密度聚类" value="dbscan" />
              </el-select>
            </el-form-item>
            
            <el-form-item label="数据源">
              <el-select v-model="jobForm.source.type" style="width: 100%">
                <el-option label="数据库查询" value="database" />
                <el-option label="内联数据" value="inline" />
              </el-select>
            </el-form-item>
            
            <el-form-item v-if="jobForm.source.type === 'database'" label="数据表">
              <el-select v-model="jobForm.source.table" style="width: 100%">
                <el-option label="检测明细表" value="detect_data" />
                <el-option label="聚类结果表" value="cluster_result" />
              </el-select>
            </el-form-item>
            
            <el-form-item label="算法参数">
              <div v-if="jobForm.algorithm === 'kmeans'">
                <el-form-item label="簇数 K" inline>
                  <el-input-number v-model="jobForm.params.k" :min="2" :max="10" />
                </el-form-item>
              </div>
              <div v-else-if="jobForm.algorithm === 'dbscan'">
                <el-form-item label="半径 eps" inline>
                  <el-input-number v-model="jobForm.params.eps" :min="0.1" :step="0.1" />
                </el-form-item>
                <el-form-item label="最小点数" inline>
                  <el-input-number v-model="jobForm.params.min_pts" :min="3" :max="20" />
                </el-form-item>
              </div>
            </el-form-item>
            
            <el-form-item>
              <el-button type="primary" @click="createJob" :loading="submitting">
                创建任务
              </el-button>
              <el-button @click="resetForm">重置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
        
        <!-- CF 树合并 -->
        <el-card style="margin-top: 20px;">
          <template #header>
            <span>CF 树合并</span>
          </template>
          <p class="tip">将多个边缘网关的 BIRCH CF 树合并为全局模型</p>
          <el-button type="success" @click="mergeCFTrees">执行合并</el-button>
        </el-card>
      </el-col>
      
      <!-- 右侧：聚类结果展示 -->
      <el-col :span="16">
        <el-card v-if="currentJob">
          <template #header>
            <div class="result-header">
              <span>聚类结果 - {{ currentJob.algorithm }}</span>
              <el-tag :type="currentJob.status === 'completed' ? 'success' : 'warning'">
                {{ currentJob.status === 'completed' ? '已完成' : '运行中' }}
              </el-tag>
            </div>
          </template>
          
          <!-- 评估指标 -->
          <el-row :gutter="16" class="metrics-row">
            <el-col :span="6">
              <el-statistic title="轮廓系数" :value="currentJob.evaluation?.silhouette ?? 0" :precision="3">
                <template #prefix><el-icon><TrendCharts /></el-icon></template>
              </el-statistic>
            </el-col>
            <el-col :span="6">
              <el-statistic title="DBI 指数" :value="currentJob.evaluation?.daviesBouldin ?? 0" :precision="3">
                <template #prefix><el-icon><Odometer /></el-icon></template>
              </el-statistic>
            </el-col>
            <el-col :span="6">
              <el-statistic title="CH 指数" :value="currentJob.evaluation?.calinskiHarabasz ?? 0" :precision="2">
                <template #prefix><el-icon><DataLine /></el-icon></template>
              </el-statistic>
            </el-col>
            <el-col :span="6">
              <el-statistic title="簇数" :value="currentJob.evaluation?.nClusters ?? 0" />
            </el-col>
          </el-row>
          
          <!-- 散点图 -->
          <div ref="chartRef" style="height: 400px; margin-top: 20px;"></div>
          
          <!-- 结果表格 -->
          <el-table :data="resultTableData" style="width: 100%; margin-top: 20px;" size="small">
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="id" label="点 ID" width="100" />
            <el-table-column label="特征值">
              <template #default="{ row }">
                [{{ row.feature.map((f: number) => f.toFixed(2)).join(', ') }}]
              </template>
            </el-table-column>
            <el-table-column prop="label" label="簇标签" width="100">
              <template #default="{ row }">
                <el-tag :type="getTagType(row.label)" size="small">簇 {{ row.label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="dist" label="距质心" width="100">
              <template #default="{ row }">{{ row.dist.toFixed(3) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
        
        <el-card v-else>
          <div class="empty-state">
            <el-icon :size="64" color="#666"><Share /></el-icon>
            <p>暂无聚类结果</p>
            <span>请在左侧创建聚类任务</span>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, nextTick, computed } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Share, TrendCharts, Odometer, DataLine } from '@element-plus/icons-vue'

const submitting = ref(false)
const currentJob = ref<any>(null)
const chartRef = ref<HTMLDivElement>()

const jobForm = reactive({
  id: '',
  algorithm: 'kmeans',
  source: {
    type: 'database',
    table: 'detect_data',
  },
  params: {
    k: 3,
    eps: 0.5,
    min_pts: 5,
  },
})

// 模拟数据
const mockData = [
  [302.1], [305.5], [298.3], [301.8], [303.2],
  [148.5], [152.3], [149.8], [151.2], [150.1],
  [248.9], [253.4], [249.6], [251.2], [250.8],
  [201.3], [198.7], [202.1], [199.5], [200.4],
]

const mockLabels = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3]

const resultTableData = computed(() => {
  if (!currentJob.value?.results) return []
  return currentJob.value.results.slice(0, 50)
})

async function createJob() {
  submitting.value = true
  
  // 模拟调用 API
  await new Promise(resolve => setTimeout(resolve, 1500))
  
  // 生成模拟结果
  const results = mockData.map((feature, i) => ({
    id: `p_${i}`,
    feature,
    label: mockLabels[i],
    dist: Math.random() * 5,
  }))
  
  currentJob.value = {
    id: jobForm.id || `cj_${Date.now()}`,
    algorithm: jobForm.algorithm,
    status: 'completed',
    progress: 100,
    results,
    evaluation: {
      silhouette: 0.782,
      daviesBouldin: 0.534,
      calinskiHarabasz: 2845.67,
      nClusters: 4,
      nPoints: 20,
      stability: 0.95,
    },
  }
  
  submitting.value = false
  ElMessage.success('聚类任务完成')
  
  await nextTick()
  renderChart()
}

function resetForm() {
  jobForm.id = ''
  jobForm.algorithm = 'kmeans'
  jobForm.params.k = 3
  jobForm.params.eps = 0.5
  jobForm.params.min_pts = 5
}

function mergeCFTrees() {
  ElMessage.success('CF 树合并已触发')
}

function renderChart() {
  if (!chartRef.value || !currentJob.value) return
  
  const chart = echarts.init(chartRef.value)
  const results = currentJob.value.results
  
  const scatterData = results.map((r: any) => ({
    value: [...r.feature, r.dist],
    itemStyle: { color: getClusterColor(r.label) },
  }))
  
  chart.setOption({
    tooltip: {
      formatter: (params: any) => {
        return `簇 ${params.dataIndex + 1}<br/>特征值: ${params.data.value[0].toFixed(2)}<br/>标签: ${params.seriesName}`
      },
    },
    xAxis: { name: '特征值', nameLocation: 'middle', nameGap: 30 },
    yAxis: { name: '距质心', nameLocation: 'middle', nameGap: 40 },
    series: [
      {
        name: '数据点',
        type: 'scatter',
        data: scatterData,
        symbolSize: 10,
      },
    ],
  })
}

function getClusterColor(label: number): string {
  const colors = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399']
  return colors[label % colors.length]
}

function getTagType(label: number): string {
  const types = ['', 'primary', 'success', 'warning', 'danger']
  return types[label] || ''
}
</script>

<style scoped>
.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.result-header span {
  font-weight: bold;
  color: #c0c4cc;
}

.metrics-row {
  padding: 10px 0;
}

.empty-state {
  text-align: center;
  padding: 60px 0;
  color: #888;
}

.empty-state p {
  margin: 16px 0 8px;
  font-size: 16px;
  color: #c0c4cc;
}

.tip {
  font-size: 12px;
  color: #888;
  margin-bottom: 12px;
}

.clustering-page :deep(.el-card),
.clustering-page :deep(.el-table) {
  background-color: transparent;
  border-color: #2d2d2d;
}
</style>