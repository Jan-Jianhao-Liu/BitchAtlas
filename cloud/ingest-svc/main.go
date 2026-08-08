package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
)

// ============ 配置 ============
type Config struct {
	AppName           string
	AppPort           string
	ClickHouseHost    string
	ClickHousePort    string
	ClickHouseUser    string
	ClickHousePassword string
	ClickHouseDB      string
	MinIOEndpoint     string
	MinIOAccessKey    string
	MinIOSecretKey    string
}

func loadConfig() *Config {
	return &Config{
		AppName:           getEnv("APP_NAME", "ingest-svc"),
		AppPort:           getEnv("APP_PORT", "8006"),
		ClickHouseHost:    getEnv("CLICKHOUSE_HOST", "localhost"),
		ClickHousePort:    getEnv("CLICKHOUSE_PORT", "8123"),
		ClickHouseUser:    getEnv("CLICKHOUSE_USER", "birchatlas"),
		ClickHousePassword: getEnv("CLICKHOUSE_PASSWORD", ""),
		ClickHouseDB:      getEnv("CLICKHOUSE_DB", "birchatlas"),
		MinIOEndpoint:     getEnv("MINIO_ENDPOINT", "http://localhost:9000"),
		MinIOAccessKey:    getEnv("MINIO_ACCESS_KEY", "birchatlas"),
		MinIOSecretKey:    getEnv("MINIO_SECRET_KEY", ""),
	}
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

// ============ 数据模型 ============

// 兼容 V1.0 的检测数据上传请求
type DataUploadRequest struct {
	ID         string        `json:"id"`
	DevCode    string        `json:"dev_code"`
	Img1W      int           `json:"img1_w"`
	Img1H      int           `json:"img1_h"`
	Img2W      int           `json:"img2_w"`
	Img2H      int           `json:"img2_h"`
	Img3W      int           `json:"img3_w"`
	Img3H      int           `json:"img3_h"`
	Factor     float64       `json:"factor"`
	High       float64       `json:"high"`
	Par1       string        `json:"par1"`
	Par2       string        `json:"par2"`
	Par3       string        `json:"par3"`
	URL1       string        `json:"url1"`
	URL2       string        `json:"url2"`
	URL3       string        `json:"url3"`
	RecordTime string        `json:"record_time"`
	DataList   []DataItem    `json:"data_list"`
	Source     int           `json:"source"`
}

type DataItem struct {
	Type           int       `json:"type"`
	Vals           []float64 `json:"vals"`
	OutlierIndices []int     `json:"outlier_indices,omitempty"`
}

type OutlierDetail struct {
	DataType      int     `json:"data_type"`
	Index         int     `json:"index"`
	Value         float64 `json:"value"`
	ExpectedMean  float64 `json:"expected_mean"`
	ZScore        float64 `json:"z_score"`
}

type DataUploadResponse struct {
	Code int    `json:"code"`
	Msg  string `json:"msg"`
	Data struct {
		RecordID      int64           `json:"record_id"`
		OutlierHint   string          `json:"outlier_hint"`
		Outliers      []OutlierDetail `json:"outliers"`
	} `json:"data"`
}

// 批量上传请求
type BatchUploadRequest struct {
	Records []DataUploadRequest `json:"records"`
}

type BatchUploadResponse struct {
	Code        int              `json:"code"`
	Msg         string           `json:"msg"`
	TotalCount  int              `json:"total_count"`
	SuccessCount int             `json:"success_count"`
	FailedCount int              `json:"failed_count"`
	FailedRecords []FailedRecord  `json:"failed_records"`
}

type FailedRecord struct {
	RecordID string `json:"record_id"`
	Error    string `json:"error"`
}

// 查询请求
type QueryDataRequest struct {
	ProjectID   string `form:"project_id"`
	GatewayCode string `form:"gateway_code"`
	DevCode     string `form:"dev_code"`
	DataType    string `form:"data_type"`
	StartTime   string `form:"start_time"`
	EndTime     string `form:"end_time"`
	Page        int    `form:"page"`
	PageSize    int    `form:"page_size"`
}

type QueryDataResponse struct {
	Code  int              `json:"code"`
	Msg   string           `json:"msg"`
	Data  QueryDataData    `json:"data"`
}

type QueryDataData struct {
	Total   int64           `json:"total"`
	Records []DataRecord    `json:"records"`
}

type DataRecord struct {
	RecordID      string  `json:"record_id"`
	DevCode       string  `json:"dev_code"`
	RecordTime    string  `json:"record_time"`
	Factor        float64 `json:"factor"`
	DataType      int     `json:"data_type"`
	Vals          string  `json:"vals"`
	OutlierIndices string `json:"outlier_indices"`
	QualityGrade  string  `json:"quality_grade"`
}

// ============ 数据库操作 ============

type Database struct {
	conn *sql.DB
	cfg  *Config
}

func NewDatabase(cfg *Config) (*Database, error) {
	// 使用 SQLite 作为主存储（简化 demo）
	// 生产环境应使用 ClickHouse
	db, err := sql.Open("sqlite3", "./data/birchatlas.db")
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// 创建表
	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS detect_data (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			record_id TEXT NOT NULL,
			project_id TEXT,
			gateway_code TEXT,
			dev_code TEXT,
			measure_point_id INTEGER,
			img_url TEXT,
			factor REAL,
			high REAL,
			data_type INTEGER,
			vals TEXT,
			outlier_indices TEXT,
			quality_grade TEXT DEFAULT 'A',
			source INTEGER DEFAULT 0,
			record_time TEXT,
			algo_version TEXT DEFAULT '',
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);
		
		CREATE INDEX IF NOT EXISTS idx_detect_data_dev_code ON detect_data(dev_code);
		CREATE INDEX IF NOT EXISTS idx_detect_data_record_time ON detect_data(record_time);
	`)
	if err != nil {
		return nil, fmt.Errorf("failed to create tables: %w", err)
	}

	return &Database{conn: db, cfg: cfg}, nil
}

func (db *Database) InsertData(req DataUploadRequest, outlierDetails []OutlierDetail) (int64, error) {
	// 生成记录 ID
	recordID := fmt.Sprintf("rec_%d", time.Now().UnixNano())

	// 处理数据列表
	var valsJSON, outlierJSON string
	if len(req.DataList) > 0 {
		valsBytes, _ := json.Marshal(req.DataList[0].Vals)
		valsJSON = string(valsBytes)

		outlierBytes, _ := json.Marshal(outlierDetails)
		outlierJSON = string(outlierBytes)
	}

	_, err := db.conn.Exec(`
		INSERT INTO detect_data 
		(record_id, project_id, gateway_code, dev_code, measure_point_id, 
		 img_url, factor, high, data_type, vals, outlier_indices, 
		 quality_grade, source, record_time, algo_version)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`,
		recordID,
		"default_project",
		"gateway_001",
		req.DevCode,
		parseInt(req.ID),
		req.URL1,
		req.Factor,
		req.High,
		1, // 默认底横筋
		valsJSON,
		outlierJSON,
		"", // quality_grade 由聚类服务计算
		req.Source,
		req.RecordTime,
		"v1.0",
	)

	if err != nil {
		return 0, fmt.Errorf("failed to insert data: %w", err)
	}

	return time.Now().UnixNano(), nil
}

func (db *Database) QueryData(req QueryDataRequest) (*QueryDataData, error) {
	// 构建查询
	query := "SELECT record_id, dev_code, record_time, factor, data_type, vals, outlier_indices, quality_grade FROM detect_data WHERE 1=1"
	var args []interface{}

	if req.DevCode != "" {
		query += " AND dev_code = ?"
		args = append(args, req.DevCode)
	}

	if req.StartTime != "" {
		query += " AND record_time >= ?"
		args = append(args, req.StartTime)
	}

	if req.EndTime != "" {
		query += " AND record_time <= ?"
		args = append(args, req.EndTime)
	}

	// 计数
	var total int64
	countQuery := "SELECT COUNT(*) FROM detect_data WHERE 1=1"
	if req.DevCode != "" {
		countQuery += " AND dev_code = ?"
	}
	if req.StartTime != "" {
		countQuery += " AND record_time >= ?"
	}
	if req.EndTime != "" {
		countQuery += " AND record_time <= ?"
	}

	err := db.conn.QueryRow(countQuery, args...).Scan(&total)
	if err != nil {
		return nil, err
	}

	// 分页
	pageSize := req.PageSize
	if pageSize <= 0 {
		pageSize = 20
	}
	page := req.Page
	if page <= 0 {
		page = 1
	}
	offset := (page - 1) * pageSize

	query += " ORDER BY record_time DESC LIMIT ? OFFSET ?"
	args = append(args, pageSize, offset)

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var records []DataRecord
	for rows.Next() {
		var r DataRecord
		var vals, outlierIndices string
		err := rows.Scan(&r.RecordID, &r.DevCode, &r.RecordTime, &r.Factor, &r.DataType, &vals, &outlierIndices, &r.QualityGrade)
		if err != nil {
			continue
		}
		r.Vals = vals
		r.OutlierIndices = outlierIndices
		records = append(records, r)
	}

	return &QueryDataData{
		Total:   total,
		Records: records,
	}, nil
}

func (db *Database) Close() {
	db.conn.Close()
}

func parseInt(s string) int64 {
	var n int64
	fmt.Sscanf(s, "%d", &n)
	return n
}

// ============ 离群检测（简化版）============

func detectOutliers(req DataUploadRequest) []OutlierDetail {
	var outliers []OutlierDetail

	for _, item := range req.DataList {
		if len(item.Vals) < 5 {
			continue
		}

		// 计算统计量
		var sum, sumSq float64
		for _, v := range item.Vals {
			sum += v
			sumSq += v * v
		}
		n := float64(len(item.Vals))
		mean := sum / n
		std := sqrt((sumSq/n - mean*mean))

		if std < 0.01 {
			continue
		}

		// 检查每个值
		for i, v := range item.Vals {
			zScore := (v - mean) / std
			if abs(zScore) > 2.5 { // 2.5σ 阈值
				outliers = append(outliers, OutlierDetail{
					DataType:     item.Type,
					Index:        i,
					Value:        v,
					ExpectedMean: mean,
					ZScore:       zScore,
				})
			}
		}
	}

	return outliers
}

func sqrt(x float64) float64 {
	if x <= 0 {
		return 0
	}
	// Newton 法
	z := x
	for i := 0; i < 20; i++ {
		z = (z + x/z) / 2
	}
	return z
}

func abs(x float64) float64 {
	if x < 0 {
		return -x
	}
	return x
}

// ============ HTTP 处理器 ============

type Handlers struct {
	db  *Database
	cfg *Config
}

func NewHandlers(db *Database, cfg *Config) *Handlers {
	return &Handlers{db: db, cfg: cfg}
}

// 健康检查
func (h *Handlers) HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":  "ok",
		"service": h.cfg.AppName,
		"time":    time.Now().Format(time.RFC3339),
	})
}

// 人工检测上传（兼容 V1.0）
func (h *Handlers) UploadManual(c *gin.Context) {
	var req DataUploadRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code": 0,
			"msg":  "Invalid request: " + err.Error(),
		})
		return
	}

	// 离群检测
	outliers := detectOutliers(req)

	// 存储
	recordID, err := h.db.InsertData(req, outliers)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"code": 0,
			"msg":  "Failed to store data: " + err.Error(),
		})
		return
	}

	// 构建响应
	resp := DataUploadResponse{
		Code: 1,
		Msg:  "ok",
	}
	resp.Data.RecordID = recordID
	if len(outliers) > 0 {
		resp.Data.OutlierHint = fmt.Sprintf(
			"测点%s 存在%d个离群值",
			req.ID, len(outliers),
		)
		resp.Data.Outliers = outliers
	}

	c.JSON(http.StatusOK, resp)
}

// 算法检测上传（兼容 V1.0，新增离群提示）
func (h *Handlers) UploadAlgorithm(c *gin.Context) {
	var req DataUploadRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code": 0,
			"msg":  "Invalid request: " + err.Error(),
		})
		return
	}

	// 离群检测
	outliers := detectOutliers(req)

	// 存储
	recordID, err := h.db.InsertData(req, outliers)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"code": 0,
			"msg":  "Failed to store data: " + err.Error(),
		})
		return
	}

	// 构建响应（与 V1.0 格式兼容）
	resp := DataUploadResponse{
		Code: 1,
		Msg:  "ok",
	}
	resp.Data.RecordID = recordID
	if len(outliers) > 0 {
		resp.Data.OutlierHint = fmt.Sprintf(
			"测点%s type=%d 存在%d个离群值",
			req.ID, req.DataList[0].Type, len(outliers),
		)
		resp.Data.Outliers = outliers
	}

	c.JSON(http.StatusOK, resp)
}

// 批量上传
func (h *Handlers) BatchUpload(c *gin.Context) {
	var req BatchUploadRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code": 0,
			"msg":  "Invalid request: " + err.Error(),
		})
		return
	}

	var failedRecords []FailedRecord
	successCount := 0

	for _, record := range req.Records {
		outliers := detectOutliers(record)
		_, err := h.db.InsertData(record, outliers)
		if err != nil {
			failedRecords = append(failedRecords, FailedRecord{
				RecordID: record.ID,
				Error:    err.Error(),
			})
		} else {
			successCount++
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"code":          1,
		"msg":           "ok",
		"total_count":    len(req.Records),
		"success_count": successCount,
		"failed_count":  len(failedRecords),
		"failed_records": failedRecords,
	})
}

// 查询检测数据
func (h *Handlers) QueryData(c *gin.Context) {
	var req QueryDataRequest
	if err := c.ShouldBindQuery(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code": 0,
			"msg":  "Invalid request: " + err.Error(),
		})
		return
	}

	data, err := h.db.QueryData(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"code": 0,
			"msg":  "Query failed: " + err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, QueryDataResponse{
		Code: 1,
		Msg:  "ok",
		Data: *data,
	})
}

// ============ 主函数 ============

func main() {
	// 创建数据目录
	os.MkdirAll("./data", 0755)

	cfg := loadConfig()
	log.Printf("[%s] Starting on port %s", cfg.AppName, cfg.AppPort)

	// 连接数据库
	db, err := NewDatabase(cfg)
	if err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}
	defer db.Close()

	// 创建处理器
	handlers := NewHandlers(db, cfg)

	// 配置路由
	r := gin.Default()

	// CORS 中间件
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

	// 路由组
	v1 := r.Group("/api/v1")
	{
		// 健康检查
		v1.GET("/health", handlers.HealthCheck)

		// 数据上传（兼容 V1.0 路径）
		v1.POST("/upload/manual", handlers.UploadManual)
		v1.POST("/upload/algorithm", handlers.UploadAlgorithm)
		v1.POST("/upload/batch", handlers.BatchUpload)

		// 数据查询
		v1.GET("/data/query", handlers.QueryData)
	}

	// 启动服务
	addr := ":" + cfg.AppPort
	log.Printf("[%s] Listening on %s", cfg.AppName, addr)

	if err := r.Run(addr); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}