package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net/http"
	"os"
	"sort"
	"time"

	"github.com/gin-gonic/gin"
)

// ============ 配置 ============
type Config struct {
	AppName        string
	AppPort        string
	ClickHouseHost string
	ClickHousePort string
	ClickHouseUser string
	ClickHousePwd  string
	ClickHouseDB   string
	PGHost         string
	PGPort         string
	PGUser         string
	PGPassword     string
	PGDB           string
}

func loadConfig() *Config {
	return &Config{
		AppName:        getEnv("APP_NAME", "cluster-svc"),
		AppPort:        getEnv("APP_PORT", "8007"),
		ClickHouseHost: getEnv("CLICKHOUSE_HOST", "localhost"),
		ClickHousePort: getEnv("CLICKHOUSE_PORT", "8123"),
		ClickHouseUser: getEnv("CLICKHOUSE_USER", "birchatlas"),
		ClickHousePwd:  getEnv("CLICKHOUSE_PASSWORD", ""),
		ClickHouseDB:   getEnv("CLICKHOUSE_DB", "birchatlas"),
		PGHost:         getEnv("POSTGRES_HOST", "localhost"),
		PGPort:         getEnv("POSTGRES_PORT", "5432"),
		PGUser:         getEnv("POSTGRES_USER", "birchatlas"),
		PGPassword:     getEnv("POSTGRES_PASSWORD", ""),
		PGDB:           getEnv("POSTGRES_DB", "birchatlas"),
	}
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

// ============ 数据模型 ============

// 聚类任务请求
type ClusterJobRequest struct {
	ID        string                 `json:"id"`
	Algorithm string                 `json:"algorithm"` // kmeans/hierarchical/dbscan
	Source    DataSource             `json:"source"`
	Params    map[string]interface{} `json:"params"`
	Output    OutputConfig           `json:"output"`
}

type DataSource struct {
	Type      string   `json:"type"` // clickhouse/database/inline
	Query     string   `json:"query,omitempty"`
	Table     string   `json:"table,omitempty"`
	Features  []string `json:"features,omitempty"`
	Data      [][]float64 `json:"data,omitempty"`
	Labels    []int    `json:"labels,omitempty"`
}

type OutputConfig struct {
	Table         string `json:"table"`
	Visualization bool   `json:"visualization"`
}

// 聚类任务响应
type ClusterJobResponse struct {
	ID        string            `json:"id"`
	Status    string            `json:"status"` // pending/running/completed/failed
	Progress  int               `json:"progress"`
	Results   []ClusterPoint    `json:"results,omitempty"`
	Evaluation *ClusterEvaluation `json:"evaluation,omitempty"`
	Error     string            `json:"error,omitempty"`
	CreatedAt string            `json:"created_at,omitempty"`
}

type ClusterPoint struct {
	ID      string    `json:"id"`
	Feature []float64 `json:"features"`
	Label   int       `json:"label"`
	Dist    float64   `json:"distance_to_centroid"`
}

type ClusterEvaluation struct {
	Silhouette      float64 `json:"silhouette_score"`
	DaviesBouldin   float64 `json:"davies_bouldin"`
	CalinskiHarabasz float64 `json:"calinski_harabasz"`
	NClusters       int     `json:"n_clusters"`
	NPoints         int     `json:"n_points"`
	Stability       float64 `json:"stability_score"`
}

// CF 树合并请求
type CFmergeRequest struct {
	MergeID    string     `json:"merge_id"`
	Trees      []CFTree   `json:"trees"`
	TargetType string     `json:"target_data_type"`
}

type CFTree struct {
	GatewayCode    string       `json:"gateway_code"`
	MeasurePointID string       `json:"measure_point_id"`
	DataType       string       `json:"data_type"`
	LeafCFs        []CFVector   `json:"leaf_cfs"`
}

type CFVector struct {
	N    int       `json:"n"`
	LS   []float64 `json:"ls"`
	SS   []float64 `json:"ss"`
}

type CFmergeResponse struct {
	MergeID       string          `json:"merge_id"`
	TotalClusters int             `json:"total_clusters"`
	Clusters      []MergedCluster `json:"clusters"`
	Timestamp     string          `json:"timestamp"`
}

type MergedCluster struct {
	ClusterID      int       `json:"cluster_id"`
	Centroid       []float64 `json:"centroid"`
	PointCount     int       `json:"point_count"`
	Radius         float64   `json:"radius"`
	MemberGateways []string  `json:"member_gateways"`
}

// ============ 数据库操作 ============

type Database struct {
	conn *sql.DB
}

func NewDatabase() (*Database, error) {
	db, err := sql.Open("sqlite3", "./data/cluster.db")
	if err != nil {
		return nil, err
	}

	// 创建表
	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS cluster_job (
			id TEXT PRIMARY KEY,
			job_id TEXT,
			algorithm TEXT NOT NULL,
			params TEXT,
			status TEXT DEFAULT 'pending',
			progress INTEGER DEFAULT 0,
			result TEXT,
			evaluation TEXT,
			error_message TEXT,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);
		
		CREATE TABLE IF NOT EXISTS cluster_result (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			job_id TEXT NOT NULL,
			point_id TEXT,
			cluster_label INTEGER,
			distance REAL,
			features TEXT,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);
		
		CREATE TABLE IF NOT EXISTS cf_tree_merge (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			merge_id TEXT NOT NULL,
			cluster_data TEXT,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);
	`)
	if err != nil {
		return nil, err
	}

	return &Database{conn: db}, nil
}

func (db *Database) Close() {
	db.conn.Close()
}

// ============ 聚类算法实现 ============

// K-Means 聚类
func kmeans(data [][]float64, k int, maxIter int) ([]int, [][]float64) {
	n := len(data)
	if n == 0 || k <= 0 {
		return nil, nil
	}

	// 初始化质心（K-Means++）
	centroids := make([][]float64, k)
	centroids[0] = copySlice(data[randInt(n)])

	for i := 1; i < k; i++ {
		// 计算到最近质心的距离
		distances := make([]float64, n)
		for j := range data {
			minDist := math.MaxFloat64
			for _, c := range centroids[:i] {
				dist := euclideanDist(data[j], c)
				if dist < minDist {
					minDist = dist
				}
			}
			distances[j] = minDist * minDist
		}

		// 概率选择下一个质心
		sum := 0.0
		for _, d := range distances {
			sum += d
		}

		if sum == 0 {
			centroids[i] = copySlice(data[randInt(n)])
		} else {
			randVal := randFloat64() * sum
			cumSum := 0.0
			for j, d := range distances {
				cumSum += d
				if cumSum >= randVal {
					centroids[i] = copySlice(data[j])
					break
				}
			}
		}
	}

	// 迭代
	labels := make([]int, n)
	for iter := 0; iter < maxIter; iter++ {
		// 分配样本
		changed := false
		for i, point := range data {
			minDist := math.MaxFloat64
			minLabel := 0
			for j, c := range centroids {
				dist := euclideanDist(point, c)
				if dist < minDist {
					minDist = dist
					minLabel = j
				}
			}
			if labels[i] != minLabel {
				changed = true
				labels[i] = minLabel
			}
		}

		if !changed {
			break
		}

		// 更新质心
		sums := make([][]float64, k)
		counts := make([]int, k)
		for i := range sums {
			sums[i] = make([]float64, len(data[0]))
		}

		for i, point := range data {
			for j := range point {
				sums[labels[i]][j] += point[j]
			}
			counts[labels[i]]++
		}

		for i := 0; i < k; i++ {
			if counts[i] > 0 {
				for j := range centroids[i] {
					centroids[i][j] = sums[i][j] / float64(counts[i])
				}
			}
		}
	}

	return labels, centroids
}

// 层次聚类（单链接）
func hierarchical(data [][]float64, numClusters int) []int {
	n := len(data)
	if n == 0 || numClusters <= 0 {
		return nil
	}

	// 初始化每个点为一个簇
	clusters := make([][]int, n)
	for i := range clusters {
		clusters[i] = []int{i}
	}

	// 计算距离矩阵
	distMatrix := make([][]float64, n)
	for i := range distMatrix {
		distMatrix[i] = make([]float64, n)
		for j := range distMatrix[i] {
			if i == j {
				distMatrix[i][j] = 0
			} else if j > i {
				distMatrix[i][j] = euclideanDist(data[i], data[j])
			} else {
				distMatrix[i][j] = distMatrix[j][i]
			}
		}
	}

	// 合并直到达到目标簇数
	activeClusters := n
	for activeClusters > numClusters {
		// 找最近的两个簇
		minDist := math.MaxFloat64
		mergeI, mergeJ := -1, -1

		for i := 0; i < len(clusters); i++ {
			if len(clusters[i]) == 0 {
				continue
			}
			for j := i + 1; j < len(clusters); j++ {
				if len(clusters[j]) == 0 {
					continue
				}
				// 单链接：最小点对距离
				dist := minClusterDist(clusters[i], clusters[j], distMatrix)
				if dist < minDist {
					minDist = dist
					mergeI, mergeJ = i, j
				}
			}
		}

		// 合并
		if mergeI >= 0 && mergeJ >= 0 {
			clusters[mergeI] = append(clusters[mergeI], clusters[mergeJ]...)
			clusters[mergeJ] = nil
			activeClusters--
		}
	}

	// 分配标签
	labels := make([]int, n)
	labelMap := make(map[int]int)
	currentLabel := 0

	for i, cluster := range clusters {
		if len(cluster) > 0 {
			for _, pointIdx := range cluster {
				labels[pointIdx] = currentLabel
			}
			labelMap[i] = currentLabel
			currentLabel++
		}
	}

	return labels
}

// DBSCAN 聚类
func dbscan(data [][]float64, eps float64, minPts int) []int {
	n := len(data)
	if n == 0 {
		return nil
	}

	labels := make([]int, n)
	for i := range labels {
		labels[i] = -1 // 未访问
	}

	// 计算邻域
	neighbors := make([][]int, n)
	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			if euclideanDist(data[i], data[j]) <= eps {
				neighbors[i] = append(neighbors[i], j)
			}
		}
	}

	clusterID := 0
	for i := 0; i < n; i++ {
		if labels[i] != -1 {
			continue
		}

		if len(neighbors[i]) < minPts {
			labels[i] = -2 // 噪声
			continue
		}

		// BFS 扩展
		clusterID++
		labels[i] = clusterID
		queue := append([]int{}, neighbors[i]...)

		for len(queue) > 0 {
			point := queue[0]
			queue = queue[1:]

			if labels[point] == -2 {
				labels[point] = clusterID
			}

			if len(neighbors[point]) >= minPts {
				for _, neighbor := range neighbors[point] {
					if labels[neighbor] <= 0 {
						queue = append(queue, neighbor)
						labels[neighbor] = clusterID
					}
				}
			}
		}
	}

	// 重新编号（0 为噪声）
	renumbered := make([]int, n)
	clusterCount := 0
	idMap := make(map[int]int)
	idMap[-1] = 0
	idMap[-2] = 0

	for _, label := range labels {
		if _, exists := idMap[label]; !exists {
			clusterCount++
			idMap[label] = clusterCount
		}
	}

	for i, label := range labels {
		renumbered[i] = idMap[label]
	}

	return renumbered
}

// 聚类评估指标
func computeSilhouette(data [][]float64, labels []int) float64 {
	n := len(data)
	if n <= 1 {
		return 0
	}

	// 统计每个簇的索引
	clusterPoints := make(map[int][]int)
	for i, label := range labels {
		clusterPoints[label] = append(clusterPoints[label], i)
	}

	if len(clusterPoints) <= 1 || len(clusterPoints) >= n {
		return 0
	}

	scores := make([]float64, n)
	for i := 0; i < n; i++ {
		currentLabel := labels[i]

		// a: 簇内平均距离
		sameCluster := clusterPoints[currentLabel]
		if len(sameCluster) <= 1 {
			scores[i] = 0
			continue
		}

		a := 0.0
		for _, j := range sameCluster {
			if j != i {
				a += euclideanDist(data[i], data[j])
			}
		}
		a /= float64(len(sameCluster) - 1)

		// b: 最近其他簇的平均距离
		b := math.MaxFloat64
		for label, points := range clusterPoints {
			if label == currentLabel {
				continue
			}
			if len(points) == 0 {
				continue
			}
			dist := 0.0
			for _, j := range points {
				dist += euclideanDist(data[i], data[j])
			}
			dist /= float64(len(points))
			if dist < b {
				b = dist
			}
		}

		if b == math.MaxFloat64 {
			scores[i] = 0
		} else {
			maxAB := math.Max(a, b)
			if maxAB > 0 {
				scores[i] = (b - a) / maxAB
			}
		}
	}

	sum := 0.0
	for _, s := range scores {
		sum += s
	}
	return sum / float64(n)
}

func computeDaviesBouldin(data [][]float64, labels []int) float64 {
	n := len(data)
	if n <= 1 {
		return 0
	}

	// 统计簇
	clusterPoints := make(map[int][]int)
	for i, label := range labels {
		clusterPoints[label] = append(clusterPoints[label], i)
	}

	k := len(clusterPoints)
	if k <= 1 {
		return 0
	}

	// 计算质心和散度
	centroids := make(map[int][]float64)
	dispersions := make(map[int]float64)

	for label, points := range clusterPoints {
		centroid := make([]float64, len(data[0]))
		for _, idx := range points {
			for j, val := range data[idx] {
				centroid[j] += val
			}
		}
		for j := range centroid {
			centroid[j] /= float64(len(points))
		}
		centroids[label] = centroid

		// 散度
		disp := 0.0
		for _, idx := range points {
			disp += euclideanDist(data[idx], centroid)
		}
		dispersions[label] = disp / float64(len(points))
	}

	// 计算 DBI
	dbiSum := 0.0
	clusterIDs := getSortedKeys(clusterPoints)
	for i := 0; i < len(clusterIDs); i++ {
		maxRatio := 0.0
		for j := 0; j < len(clusterIDs); j++ {
			if i == j {
				continue
			}
			dist := euclideanDist(centroids[clusterIDs[i]], centroids[clusterIDs[j]])
			if dist > 0 {
				ratio := (dispersions[clusterIDs[i]] + dispersions[clusterIDs[j]]) / dist
				if ratio > maxRatio {
					maxRatio = ratio
				}
			}
		}
		dbiSum += maxRatio
	}

	return dbiSum / float64(k)
}

func computeCalinskiHarabasz(data [][]float64, labels []int) float64 {
	n := len(data)
	if n <= 1 {
		return 0
	}

	clusterPoints := make(map[int][]int)
	for i, label := range labels {
		clusterPoints[label] = append(clusterPoints[label], i)
	}

	k := len(clusterPoints)
	if k <= 1 || k >= n {
		return 0
	}

	// 全局质心
	globalCentroid := make([]float64, len(data[0]))
	for _, point := range data {
		for j, val := range point {
			globalCentroid[j] += val
		}
	}
	for j := range globalCentroid {
		globalCentroid[j] /= float64(n)
	}

	// 簇间方差和簇内方差
	betweenVar := 0.0
	withinVar := 0.0

	for label, points := range clusterPoints {
		centroid := make([]float64, len(data[0]))
		for _, idx := range points {
			for j, val := range data[idx] {
				centroid[j] += val
			}
		}
		for j := range centroid {
			centroid[j] /= float64(len(points))
		}

		// 簇间
		betweenVar += float64(len(points)) * euclideanDist(centroid, globalCentroid)

		// 簇内
		for _, idx := range points {
			withinVar += euclideanDist(data[idx], centroid)
		}
	}

	if withinVar == 0 {
		return 0
	}

	return (betweenVar / float64(k-1)) / (withinVar / float64(n-k))
}

// ============ HTTP 处理器 ============

type Handlers struct {
	db  *Database
	cfg *Config
}

func NewHandlers(db *Database, cfg *Config) *Handlers {
	return &Handlers{db: db, cfg: cfg}
}

func (h *Handlers) HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":  "ok",
		"service": h.cfg.AppName,
		"time":    time.Now().Format(time.RFC3339),
	})
}

// 创建聚类任务
func (h *Handlers) CreateJob(c *gin.Context) {
	var req ClusterJobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code": 0,
			"msg":  "Invalid request: " + err.Error(),
		})
		return
	}

	// 生成任务 ID
	jobID := fmt.Sprintf("cj_%d", time.Now().UnixNano())

	// 准备数据
	var data [][]float64
	if req.Source.Type == "inline" {
		data = req.Source.Data
	} else if req.Source.Type == "database" {
		// 从数据库查询
		var err error
		data, err = queryDataFromDB(h.db, req.Source.Table, req.Source.Query)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{
				"code": 0,
				"msg":  "Failed to query data: " + err.Error(),
			})
			return
		}
	}

	// 执行聚类
	results, evaluation := executeClustering(req.Algorithm, data, req.Params)

	// 存储结果
	resultJSON, _ := json.Marshal(results)
	evalJSON, _ := json.Marshal(evaluation)

	h.db.conn.Exec(`
		INSERT INTO cluster_job (id, job_id, algorithm, params, status, progress, result, evaluation, created_at)
		VALUES (?, ?, ?, ?, ?, 100, ?, ?, ?)
	`, req.ID, jobID, req.Algorithm, toJSON(req.Params), "completed", resultJSON, evalJSON, time.Now().Format(time.RFC3339))

	// 返回结果
	response := ClusterJobResponse{
		ID:        req.ID,
		Status:    "completed",
		Progress:  100,
		Results:   results,
		Evaluation: evaluation,
		CreatedAt: time.Now().Format(time.RFC3339),
	}

	c.JSON(http.StatusOK, gin.H{
		"code": 1,
		"msg":  "ok",
		"data": response,
	})
}

// 查询任务状态
func (h *Handlers) GetJob(c *gin.Context) {
	id := c.Param("id")

	var resultJSON, evalJSON string
	var status string
	var progress int

	err := h.db.conn.QueryRow(`
		SELECT status, progress, result, evaluation 
		FROM cluster_job WHERE id = ?
	`, id).Scan(&status, &progress, &resultJSON, &evalJSON)

	if err == sql.ErrNoRows {
		c.JSON(http.StatusNotFound, gin.H{
			"code": 0,
			"msg":  "Job not found",
		})
		return
	}

	var results []ClusterPoint
	var evaluation *ClusterEvaluation

	if resultJSON != "" {
		json.Unmarshal([]byte(resultJSON), &results)
	}
	if evalJSON != "" {
		json.Unmarshal([]byte(evalJSON), &evaluation)
	}

	c.JSON(http.StatusOK, gin.H{
		"code": 1,
		"msg":  "ok",
		"data": ClusterJobResponse{
			ID:         id,
			Status:     status,
			Progress:   progress,
			Results:    results,
			Evaluation: evaluation,
		},
	})
}

// CF 树合并
func (h *Handlers) MergeCFtrees(c *gin.Context) {
	var req CFmergeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code": 0,
			"msg":  "Invalid request: " + err.Error(),
		})
		return
	}

	// 合并 CF 树
	mergedClusters := mergeCFTrees(req.Trees, req.TargetType)

	// 存储合并结果
	clusterJSON, _ := json.Marshal(mergedClusters)
	h.db.conn.Exec(`
		INSERT INTO cf_tree_merge (merge_id, cluster_data)
		VALUES (?, ?)
	`, req.MergeID, string(clusterJSON))

	response := CFmergeResponse{
		MergeID:       req.MergeID,
		TotalClusters: len(mergedClusters),
		Clusters:      mergedClusters,
		Timestamp:     time.Now().Format(time.RFC3339),
	}

	c.JSON(http.StatusOK, gin.H{
		"code": 1,
		"msg":  "ok",
		"data": response,
	})
}

// ============ 辅助函数 ============

func executeClustering(algorithm string, data [][]float64, params map[string]interface{}) ([]ClusterPoint, *ClusterEvaluation) {
	if len(data) == 0 {
		return nil, nil
	}

	var labels []int
	var centroids [][]float64

	switch algorithm {
	case "kmeans":
		k := getIntParam(params, "k", 3)
		labels, centroids = kmeans(data, k, 100)
	case "hierarchical":
		k := getIntParam(params, "k", 3)
		labels = hierarchical(data, k)
	case "dbscan":
		eps := getFloatParam(params, "eps", 0.5)
		minPts := getIntParam(params, "min_pts", 5)
		labels = dbscan(data, eps, minPts)
	default:
		k := getIntParam(params, "k", 3)
		labels, centroids = kmeans(data, k, 100)
	}

	// 计算质心（如果算法没有返回）
	if centroids == nil && len(labels) > 0 {
		centroids = computeCentroids(data, labels)
	}

	// 生成结果点
	results := make([]ClusterPoint, len(data))
	for i, point := range data {
		label := labels[i]

		// 计算到质心距离
		dist := 0.0
		if label > 0 && label <= len(centroids) {
			dist = euclideanDist(point, centroids[label-1])
		}

		results[i] = ClusterPoint{
			ID:                 fmt.Sprintf("p_%d", i),
			Feature:            point,
			Label:              label,
			Dist:               dist,
		}
	}

	// 计算评估指标
	evaluation := &ClusterEvaluation{
		Silhouette:      computeSilhouette(data, labels),
		DaviesBouldin:   computeDaviesBouldin(data, labels),
		CalinskiHarabasz: computeCalinskiHarabasz(data, labels),
		NClusters:       len(centroids),
		NPoints:         len(data),
		Stability:       0.0,
	}

	return results, evaluation
}

func computeCentroids(data [][]float64, labels []int) [][]float64 {
	clusterPoints := make(map[int][]int)
	for i, label := range labels {
		clusterPoints[label] = append(clusterPoints[label], i)
	}

	centroids := make([][]float64, 0)
	for _, points := range clusterPoints {
		centroid := make([]float64, len(data[0]))
		for _, idx := range points {
			for j, val := range data[idx] {
				centroid[j] += val
			}
		}
		for j := range centroid {
			centroid[j] /= float64(len(points))
		}
		centroids = append(centroids, centroid)
	}

	return centroids
}

func mergeCFTrees(trees []CFTree, targetType string) []MergedCluster {
	// 收集所有 CF 向量
	var allPoints []struct {
		vector  CFVector
		gateway string
	}

	for _, tree := range trees {
		for _, cf := range tree.LeafCFs {
			point := make([]float64, len(cf.LS))
			for i := range cf.LS {
				point[i] = cf.LS[i] / float64(cf.N) // 质心
			}
			allPoints = append(allPoints, struct {
				vector  CFVector
				gateway string
			}{cf, tree.GatewayCode})
		}
	}

	if len(allPoints) == 0 {
		return nil
	}

	// 转换为数组
	data := make([][]float64, len(allPoints))
	for i, ap := range allPoints {
		data[i] = make([]float64, len(ap.vector.LS))
		for j := range ap.vector.LS {
			data[i][j] = ap.vector.LS[j] / float64(ap.vector.N)
		}
	}

	// 聚类
	k := min(3, len(data))
	labels, centroids := kmeans(data, k, 50)

	// 生成合并结果
	clusters := make([]MergedCluster, len(centroids))
	for i := 0; i < len(centroids); i++ {
		cluster := MergedCluster{
			ClusterID:  i + 1,
			Centroid:   centroids[i],
			PointCount: 0,
			MemberGateways: []string{},
		}

		// 统计每个簇的信息
		gatewaySet := make(map[string]bool)
		for j, label := range labels {
			if label == i {
				cluster.PointCount += allPoints[j].vector.N
				gatewaySet[allPoints[j].gateway] = true

				// 计算半径
				dist := euclideanDist(data[j], centroids[i])
				if dist > cluster.Radius {
					cluster.Radius = dist
				}
			}
		}

		for gw := range gatewaySet {
			cluster.MemberGateways = append(cluster.MemberGateways, gw)
		}

		clusters[i] = cluster
	}

	return clusters
}

func queryDataFromDB(db *Database, table, query string) ([][]float64, error) {
	// 简化实现：从 SQLite 查询
	rows, err := db.conn.Query("SELECT factor FROM detect_data LIMIT 100")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var data [][]float64
	for rows.Next() {
		var factor float64
		rows.Scan(&factor)
		data = append(data, []float64{factor})
	}

	return data, nil
}

// ============ 工具函数 ============

func euclideanDist(a, b []float64) float64 {
	sum := 0.0
	for i := range a {
		diff := a[i] - b[i]
		sum += diff * diff
	}
	return math.Sqrt(sum)
}

func minClusterDist(indicesA, indicesB []int, distMatrix [][]float64) float64 {
	minDist := math.MaxFloat64
	for _, i := range indicesA {
		for _, j := range indicesB {
			d := distMatrix[i][j]
			if d < minDist {
				minDist = d
			}
		}
	}
	return minDist
}

func copySlice(s []float64) []float64 {
	return append([]float64{}, s...)
}

func getIntParam(params map[string]interface{}, key string, defaultVal int) int {
	if v, ok := params[key]; ok {
		switch val := v.(type) {
		case float64:
			return int(val)
		case int:
			return val
		}
	}
	return defaultVal
}

func getFloatParam(params map[string]interface{}, key string, defaultVal float64) float64 {
	if v, ok := params[key]; ok {
		if val, ok := v.(float64); ok {
			return val
		}
	}
	return defaultVal
}

func toJSON(v interface{}) string {
	data, _ := json.Marshal(v)
	return string(data)
}

func getSortedKeys(m map[int][]int) []int {
	keys := make([]int, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Ints(keys)
	return keys
}

func randInt(max int) int {
	return int(time.Now().UnixNano()) % max
}

func randFloat64() float64 {
	return float64(time.Now().UnixNano()%1000000) / 1000000.0
}

// ============ 主函数 ============

func main() {
	// 创建数据目录
	os.MkdirAll("./data", 0755)

	cfg := loadConfig()
	log.Printf("[%s] Starting on port %s", cfg.AppName, cfg.AppPort)

	// 连接数据库
	db, err := NewDatabase()
	if err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}
	defer db.Close()

	// 创建处理器
	handlers := NewHandlers(db, cfg)

	// 配置路由
	r := gin.Default()

	// CORS
	r.Use(func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", "*")
		c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	})

	// 路由
	v1 := r.Group("/api/v1")
	{
		v1.GET("/health", handlers.HealthCheck)
		v1.POST("/cluster/jobs", handlers.CreateJob)
		v1.GET("/cluster/jobs/:id", handlers.GetJob)
		v1.POST("/cluster/cf/merge", handlers.MergeCFtrees)
	}

	addr := ":" + cfg.AppPort
	log.Printf("[%s] Listening on %s", cfg.AppName, addr)

	if err := r.Run(addr); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}