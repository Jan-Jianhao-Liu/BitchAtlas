package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"reflect"
	"regexp"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
	_ "github.com/lib/pq"
)

// ============ 配置 ============

type Config struct {
	AppName    string
	AppPort    string
	PGHost     string
	PGPort     string
	PGUser     string
	PGPassword string
	PGDB       string
	PGSSLMode  string
}

func loadConfig() *Config {
	// 加载 .env 文件（若存在，忽略错误）
	_ = godotenv.Load()
	return &Config{
		AppName:    getEnv("APP_NAME", "device-svc"),
		AppPort:    getEnv("APP_PORT", "8002"),
		PGHost:     getEnv("POSTGRES_HOST", "localhost"),
		PGPort:     getEnv("POSTGRES_PORT", "5432"),
		PGUser:     getEnv("POSTGRES_USER", "birchatlas"),
		PGPassword: getEnv("POSTGRES_PASSWORD", ""),
		PGDB:       getEnv("POSTGRES_DB", "birchatlas"),
		PGSSLMode:  getEnv("POSTGRES_SSLMODE", "disable"),
	}
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

// ============ 数据模型 ============

// 设备编号正则：AA-BBBBBBBB（AA=2位大写字母设备类型码，BBBBBBBB=8位数字序列号）
var devCodeRegex = regexp.MustCompile(`^[A-Z]{2}-\d{8}$`)

// 已知设备类型编码
var deviceTypeMap = map[string]string{
	"GW": "网关",
	"ED": "边缘设备",
	"SN": "传感节点",
	"CM": "摄像头",
}

// Device 设备实体
type Device struct {
	DevCode   string    `json:"dev_code"`
	Name      string    `json:"name"`
	Type      string    `json:"type"`
	ProjectID string    `json:"project_id"`
	Status    string    `json:"status"` // online/offline
	IP        string    `json:"ip"`
	Version   string    `json:"version"`
	LastSeen  time.Time `json:"last_seen"`
	CreatedAt time.Time `json:"created_at"`
}

// DeviceShadow 设备影子
type DeviceShadow struct {
	DeviceCode string                 `json:"device_code"`
	Reported   map[string]interface{} `json:"reported"`          // 设备实际上报的状态
	Desired    map[string]interface{} `json:"desired"`           // 云端期望的状态
	Version    int                    `json:"version"`           // 影子版本号，每次更新自增
	Timestamp  time.Time              `json:"timestamp"`         // 最后更新时间
	NeedSync   bool                   `json:"need_sync"`         // reported 与 desired 不一致时为 true，标记需要同步
}

// CreateDeviceRequest 注册设备请求
type CreateDeviceRequest struct {
	DevCode   string `json:"dev_code" binding:"required"`
	Name      string `json:"name"`
	Type      string `json:"type"`
	ProjectID string `json:"project_id"`
	IP        string `json:"ip"`
	Version   string `json:"version"`
}

// UpdateDeviceRequest 更新设备请求（指针类型支持部分更新）
type UpdateDeviceRequest struct {
	Name      *string `json:"name"`
	Type      *string `json:"type"`
	ProjectID *string `json:"project_id"`
	IP        *string `json:"ip"`
	Version   *string `json:"version"`
}

// DeviceFilter 设备列表筛选与分页
type DeviceFilter struct {
	Type      string `form:"type"`
	ProjectID string `form:"project_id"`
	Status    string `form:"status"` // online/offline
	Page      int    `form:"page"`
	PageSize  int    `form:"page_size"`
}

// HeartbeatRequest 心跳上报
type HeartbeatRequest struct {
	IP       string                 `json:"ip"`
	Version  string                 `json:"version"`
	Reported map[string]interface{} `json:"reported"` // 可选，设备上报的状态
}

// UpdateDesiredRequest 更新期望状态
type UpdateDesiredRequest struct {
	Desired map[string]interface{} `json:"desired" binding:"required"`
}

// DeviceStats 设备统计
type DeviceStats struct {
	Total   int64 `json:"total"`
	Online  int64 `json:"online"`
	Offline int64 `json:"offline"`
}

// 在线判定阈值：5 分钟内有心跳即视为在线
const onlineTimeout = 5 * time.Minute

// computeStatus 根据 last_seen 计算设备状态
func computeStatus(lastSeen time.Time) string {
	if !lastSeen.IsZero() && time.Since(lastSeen) <= onlineTimeout {
		return "online"
	}
	return "offline"
}

// normalizeMap 将 nil map 归一化为空 map，便于比较与 JSON 输出 {}
func normalizeMap(m map[string]interface{}) map[string]interface{} {
	if m == nil {
		return map[string]interface{}{}
	}
	return m
}

// mapsEqual 比较两个状态 map 是否一致
func mapsEqual(a, b map[string]interface{}) bool {
	return reflect.DeepEqual(normalizeMap(a), normalizeMap(b))
}

// ============ 数据库 / 存储操作 ============

// Database 同时支持 PostgreSQL 与内存模式（PG 不可用时自动降级）
type Database struct {
	conn       *sql.DB
	cfg        *Config
	memoryMode bool
	// 内存模式存储
	devices map[string]*Device
	shadows map[string]*DeviceShadow
	mu      sync.RWMutex
}

func NewDatabase(cfg *Config) (*Database, error) {
	dsn := fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=%s",
		cfg.PGHost, cfg.PGPort, cfg.PGUser, cfg.PGPassword, cfg.PGDB, cfg.PGSSLMode)

	db, err := sql.Open("postgres", dsn)
	if err != nil {
		log.Printf("[%s] PostgreSQL 连接打开失败，降级为内存模式: %v", cfg.AppName, err)
		return newMemoryDatabase(cfg), nil
	}

	db.SetMaxOpenConns(20)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(5 * time.Minute)

	// 验证连接可达
	if err := db.Ping(); err != nil {
		log.Printf("[%s] PostgreSQL 不可达，降级为内存模式: %v", cfg.AppName, err)
		db.Close()
		return newMemoryDatabase(cfg), nil
	}

	// 初始化表结构
	if err := initPGTables(db); err != nil {
		log.Printf("[%s] PostgreSQL 表初始化失败，降级为内存模式: %v", cfg.AppName, err)
		db.Close()
		return newMemoryDatabase(cfg), nil
	}

	log.Printf("[%s] 已连接 PostgreSQL: %s:%s/%s", cfg.AppName, cfg.PGHost, cfg.PGPort, cfg.PGDB)
	return &Database{conn: db, cfg: cfg, memoryMode: false}, nil
}

func newMemoryDatabase(cfg *Config) *Database {
	log.Printf("[%s] 运行于内存模式（数据不持久化）", cfg.AppName)
	return &Database{
		cfg:        cfg,
		memoryMode: true,
		devices:    make(map[string]*Device),
		shadows:    make(map[string]*DeviceShadow),
	}
}

func initPGTables(db *sql.DB) error {
	_, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS devices (
			dev_code   VARCHAR(20) PRIMARY KEY,
			name       VARCHAR(128) NOT NULL DEFAULT '',
			type       VARCHAR(16) NOT NULL DEFAULT '',
			project_id VARCHAR(64) NOT NULL DEFAULT '',
			status     VARCHAR(16) NOT NULL DEFAULT 'offline',
			ip         VARCHAR(64) NOT NULL DEFAULT '',
			version    VARCHAR(32) NOT NULL DEFAULT '',
			last_seen  TIMESTAMP,
			created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
		);
		CREATE INDEX IF NOT EXISTS idx_devices_type       ON devices(type);
		CREATE INDEX IF NOT EXISTS idx_devices_project_id ON devices(project_id);

		CREATE TABLE IF NOT EXISTS device_shadows (
			device_code VARCHAR(20) PRIMARY KEY,
			reported    TEXT NOT NULL DEFAULT '{}',
			desired     TEXT NOT NULL DEFAULT '{}',
			version     INTEGER NOT NULL DEFAULT 1,
			timestamp   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (device_code) REFERENCES devices(dev_code) ON DELETE CASCADE
		);
	`)
	return err
}

func (db *Database) Close() {
	if db.conn != nil {
		db.conn.Close()
	}
}

func (db *Database) IsMemoryMode() bool { return db.memoryMode }

func (db *Database) modeString() string {
	if db.memoryMode {
		return "memory"
	}
	return "postgres"
}

// CreateDevice 注册新设备，并为其创建空影子
func (db *Database) CreateDevice(dev *Device) error {
	if db.memoryMode {
		return db.createDeviceMemory(dev)
	}
	_, err := db.conn.Exec(`
		INSERT INTO devices (dev_code, name, type, project_id, status, ip, version, last_seen, created_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
	`,
		dev.DevCode, dev.Name, dev.Type, dev.ProjectID, dev.Status,
		dev.IP, dev.Version, nullableTime(dev.LastSeen), dev.CreatedAt,
	)
	if err != nil {
		return err
	}
	// 创建空影子
	_, err = db.conn.Exec(`
		INSERT INTO device_shadows (device_code, reported, desired, version, timestamp)
		VALUES ($1, '{}', '{}', 1, $2)
	`, dev.DevCode, time.Now())
	return err
}

func (db *Database) createDeviceMemory(dev *Device) error {
	db.mu.Lock()
	defer db.mu.Unlock()
	if _, exists := db.devices[dev.DevCode]; exists {
		return fmt.Errorf("设备已存在: %s", dev.DevCode)
	}
	cp := *dev
	db.devices[dev.DevCode] = &cp
	db.shadows[dev.DevCode] = &DeviceShadow{
		DeviceCode: dev.DevCode,
		Reported:   map[string]interface{}{},
		Desired:    map[string]interface{}{},
		Version:    1,
		Timestamp:  time.Now(),
	}
	return nil
}

// GetDevice 查询单个设备（状态由 last_seen 动态计算）
func (db *Database) GetDevice(code string) (*Device, error) {
	if db.memoryMode {
		return db.getDeviceMemory(code)
	}
	var d Device
	var lastSeen sql.NullTime
	err := db.conn.QueryRow(`
		SELECT dev_code, name, type, project_id, status, ip, version, last_seen, created_at
		FROM devices WHERE dev_code = $1
	`, code).Scan(&d.DevCode, &d.Name, &d.Type, &d.ProjectID, &d.Status, &d.IP, &d.Version, &lastSeen, &d.CreatedAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if lastSeen.Valid {
		d.LastSeen = lastSeen.Time
	}
	d.Status = computeStatus(d.LastSeen)
	return &d, nil
}

func (db *Database) getDeviceMemory(code string) (*Device, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()
	d, ok := db.devices[code]
	if !ok {
		return nil, nil
	}
	cp := *d
	cp.Status = computeStatus(cp.LastSeen)
	return &cp, nil
}

// ListDevices 设备列表（支持分页与筛选），返回 (设备列表, 总数, 错误)
func (db *Database) ListDevices(filter DeviceFilter) ([]*Device, int64, error) {
	if db.memoryMode {
		return db.listDevicesMemory(filter)
	}

	where := "WHERE 1=1"
	var args []interface{}
	idx := 1
	if filter.Type != "" {
		where += fmt.Sprintf(" AND type = $%d", idx)
		args = append(args, filter.Type)
		idx++
	}
	if filter.ProjectID != "" {
		where += fmt.Sprintf(" AND project_id = $%d", idx)
		args = append(args, filter.ProjectID)
		idx++
	}
	// 状态由 last_seen 推导，直接在 SQL 中过滤
	if filter.Status == "online" {
		where += " AND last_seen IS NOT NULL AND last_seen >= NOW() - INTERVAL '5 minutes'"
	} else if filter.Status == "offline" {
		where += " AND (last_seen IS NULL OR last_seen < NOW() - INTERVAL '5 minutes')"
	}

	// 计数
	var total int64
	if err := db.conn.QueryRow("SELECT COUNT(*) FROM devices "+where, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	// 分页
	pageSize := filter.pageSize()
	offset := (filter.page() - 1) * pageSize

	query := "SELECT dev_code, name, type, project_id, status, ip, version, last_seen, created_at FROM devices " +
		where + fmt.Sprintf(" ORDER BY created_at DESC LIMIT $%d OFFSET $%d", idx, idx+1)
	args = append(args, pageSize, offset)

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	var devices []*Device
	for rows.Next() {
		var d Device
		var lastSeen sql.NullTime
		if err := rows.Scan(&d.DevCode, &d.Name, &d.Type, &d.ProjectID, &d.Status, &d.IP, &d.Version, &lastSeen, &d.CreatedAt); err != nil {
			continue
		}
		if lastSeen.Valid {
			d.LastSeen = lastSeen.Time
		}
		d.Status = computeStatus(d.LastSeen)
		devices = append(devices, &d)
	}
	return devices, total, nil
}

func (db *Database) listDevicesMemory(filter DeviceFilter) ([]*Device, int64, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	var all []*Device
	for _, d := range db.devices {
		cp := *d
		cp.Status = computeStatus(cp.LastSeen)
		if filter.Type != "" && cp.Type != filter.Type {
			continue
		}
		if filter.ProjectID != "" && cp.ProjectID != filter.ProjectID {
			continue
		}
		if filter.Status != "" && cp.Status != filter.Status {
			continue
		}
		all = append(all, &cp)
	}

	total := int64(len(all))
	pageSize := filter.pageSize()
	offset := (filter.page() - 1) * pageSize
	if offset >= len(all) {
		return []*Device{}, total, nil
	}
	end := offset + pageSize
	if end > len(all) {
		end = len(all)
	}
	return all[offset:end], total, nil
}

// UpdateDevice 更新设备信息（部分更新）
func (db *Database) UpdateDevice(code string, req UpdateDeviceRequest) (*Device, error) {
	if db.memoryMode {
		return db.updateDeviceMemory(code, req)
	}

	setParts := ""
	var args []interface{}
	idx := 1
	if req.Name != nil {
		setParts += fmt.Sprintf("name = $%d, ", idx)
		args = append(args, *req.Name)
		idx++
	}
	if req.Type != nil {
		setParts += fmt.Sprintf("type = $%d, ", idx)
		args = append(args, *req.Type)
		idx++
	}
	if req.ProjectID != nil {
		setParts += fmt.Sprintf("project_id = $%d, ", idx)
		args = append(args, *req.ProjectID)
		idx++
	}
	if req.IP != nil {
		setParts += fmt.Sprintf("ip = $%d, ", idx)
		args = append(args, *req.IP)
		idx++
	}
	if req.Version != nil {
		setParts += fmt.Sprintf("version = $%d, ", idx)
		args = append(args, *req.Version)
		idx++
	}
	if setParts == "" {
		return db.GetDevice(code)
	}
	// 去掉末尾 ", "
	setParts = setParts[:len(setParts)-2]
	args = append(args, code)
	if _, err := db.conn.Exec("UPDATE devices SET "+setParts+fmt.Sprintf(" WHERE dev_code = $%d", idx), args...); err != nil {
		return nil, err
	}
	return db.GetDevice(code)
}

func (db *Database) updateDeviceMemory(code string, req UpdateDeviceRequest) (*Device, error) {
	db.mu.Lock()
	defer db.mu.Unlock()
	d, ok := db.devices[code]
	if !ok {
		return nil, nil
	}
	if req.Name != nil {
		d.Name = *req.Name
	}
	if req.Type != nil {
		d.Type = *req.Type
	}
	if req.ProjectID != nil {
		d.ProjectID = *req.ProjectID
	}
	if req.IP != nil {
		d.IP = *req.IP
	}
	if req.Version != nil {
		d.Version = *req.Version
	}
	cp := *d
	cp.Status = computeStatus(cp.LastSeen)
	return &cp, nil
}

// DeleteDevice 删除设备（PG 通过外键级联删除影子）
func (db *Database) DeleteDevice(code string) error {
	if db.memoryMode {
		db.mu.Lock()
		defer db.mu.Unlock()
		delete(db.devices, code)
		delete(db.shadows, code)
		return nil
	}
	_, err := db.conn.Exec("DELETE FROM devices WHERE dev_code = $1", code)
	return err
}

// GetShadow 获取设备影子
func (db *Database) GetShadow(code string) (*DeviceShadow, error) {
	if db.memoryMode {
		return db.getShadowMemory(code)
	}
	var s DeviceShadow
	var reported, desired string
	err := db.conn.QueryRow(`
		SELECT device_code, reported, desired, version, timestamp
		FROM device_shadows WHERE device_code = $1
	`, code).Scan(&s.DeviceCode, &reported, &desired, &s.Version, &s.Timestamp)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	json.Unmarshal([]byte(reported), &s.Reported)
	json.Unmarshal([]byte(desired), &s.Desired)
	s.Reported = normalizeMap(s.Reported)
	s.Desired = normalizeMap(s.Desired)
	s.NeedSync = !mapsEqual(s.Reported, s.Desired)
	return &s, nil
}

func (db *Database) getShadowMemory(code string) (*DeviceShadow, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()
	s, ok := db.shadows[code]
	if !ok {
		return nil, nil
	}
	cp := *s
	cp.Reported = normalizeMap(cp.Reported)
	cp.Desired = normalizeMap(cp.Desired)
	cp.NeedSync = !mapsEqual(cp.Reported, cp.Desired)
	return &cp, nil
}

// UpdateDesired 更新期望状态
func (db *Database) UpdateDesired(code string, desired map[string]interface{}) (*DeviceShadow, error) {
	if db.memoryMode {
		return db.updateDesiredMemory(code, desired)
	}
	desiredJSON, _ := json.Marshal(desired)
	if _, err := db.conn.Exec(`
		UPDATE device_shadows SET desired = $1, version = version + 1, timestamp = $2
		WHERE device_code = $3
	`, string(desiredJSON), time.Now(), code); err != nil {
		return nil, err
	}
	return db.GetShadow(code)
}

func (db *Database) updateDesiredMemory(code string, desired map[string]interface{}) (*DeviceShadow, error) {
	db.mu.Lock()
	defer db.mu.Unlock()
	s, ok := db.shadows[code]
	if !ok {
		return nil, nil
	}
	s.Desired = normalizeMap(desired)
	s.Version++
	s.Timestamp = time.Now()
	cp := *s
	cp.Reported = normalizeMap(cp.Reported)
	cp.Desired = normalizeMap(cp.Desired)
	cp.NeedSync = !mapsEqual(cp.Reported, cp.Desired)
	return &cp, nil
}

// updateReported 更新设备实际上报状态
func (db *Database) updateReported(code string, reported map[string]interface{}) (*DeviceShadow, error) {
	if db.memoryMode {
		return db.updateReportedMemory(code, reported)
	}
	reportedJSON, _ := json.Marshal(reported)
	if _, err := db.conn.Exec(`
		UPDATE device_shadows SET reported = $1, version = version + 1, timestamp = $2
		WHERE device_code = $3
	`, string(reportedJSON), time.Now(), code); err != nil {
		return nil, err
	}
	return db.GetShadow(code)
}

func (db *Database) updateReportedMemory(code string, reported map[string]interface{}) (*DeviceShadow, error) {
	db.mu.Lock()
	defer db.mu.Unlock()
	s, ok := db.shadows[code]
	if !ok {
		return nil, nil
	}
	s.Reported = normalizeMap(reported)
	s.Version++
	s.Timestamp = time.Now()
	cp := *s
	cp.Reported = normalizeMap(cp.Reported)
	cp.Desired = normalizeMap(cp.Desired)
	cp.NeedSync = !mapsEqual(cp.Reported, cp.Desired)
	return &cp, nil
}

// Heartbeat 心跳上报：更新 last_seen（及 ip/version），可选更新 reported
func (db *Database) Heartbeat(code string, req HeartbeatRequest) error {
	if db.memoryMode {
		return db.heartbeatMemory(code, req)
	}
	if _, err := db.conn.Exec(`
		UPDATE devices SET last_seen = $1, status = 'online',
			ip = CASE WHEN $2 <> '' THEN $2 ELSE ip END,
			version = CASE WHEN $3 <> '' THEN $3 ELSE version END
		WHERE dev_code = $4
	`, time.Now(), req.IP, req.Version, code); err != nil {
		return err
	}
	if len(req.Reported) > 0 {
		if _, err := db.updateReported(code, req.Reported); err != nil {
			return err
		}
	}
	return nil
}

func (db *Database) heartbeatMemory(code string, req HeartbeatRequest) error {
	db.mu.Lock()
	defer db.mu.Unlock()
	d, ok := db.devices[code]
	if !ok {
		return nil
	}
	d.LastSeen = time.Now()
	d.Status = "online"
	if req.IP != "" {
		d.IP = req.IP
	}
	if req.Version != "" {
		d.Version = req.Version
	}
	if len(req.Reported) > 0 {
		if s, ok := db.shadows[code]; ok {
			s.Reported = normalizeMap(req.Reported)
			s.Version++
			s.Timestamp = time.Now()
		}
	}
	return nil
}

// GetStats 设备统计（在线/离线/总数）
func (db *Database) GetStats() (*DeviceStats, error) {
	if db.memoryMode {
		return db.getStatsMemory()
	}
	var total, online int64
	err := db.conn.QueryRow(`
		SELECT COUNT(*),
		       COUNT(CASE WHEN last_seen IS NOT NULL AND last_seen >= NOW() - INTERVAL '5 minutes' THEN 1 END)
		FROM devices
	`).Scan(&total, &online)
	if err != nil {
		return nil, err
	}
	return &DeviceStats{Total: total, Online: online, Offline: total - online}, nil
}

func (db *Database) getStatsMemory() (*DeviceStats, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()
	var stats DeviceStats
	stats.Total = int64(len(db.devices))
	for _, d := range db.devices {
		if computeStatus(d.LastSeen) == "online" {
			stats.Online++
		} else {
			stats.Offline++
		}
	}
	return &stats, nil
}

// nullableTime 将零值时间转为 NULL
func nullableTime(t time.Time) interface{} {
	if t.IsZero() {
		return nil
	}
	return t
}

// ============ HTTP 处理器 ============

type Handlers struct {
	db  *Database
	cfg *Config
}

func NewHandlers(db *Database, cfg *Config) *Handlers {
	return &Handlers{db: db, cfg: cfg}
}

// 统一 JSON 响应
func respondOK(c *gin.Context, data interface{}) {
	c.JSON(http.StatusOK, gin.H{
		"code":    1,
		"message": "ok",
		"data":    data,
	})
}

func respondError(c *gin.Context, httpStatus int, msg string) {
	c.JSON(httpStatus, gin.H{
		"code":    0,
		"message": msg,
		"data":    nil,
	})
}

// HealthCheck 健康检查
func (h *Handlers) HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":  "ok",
		"service": h.cfg.AppName,
		"mode":    h.db.modeString(),
		"time":    time.Now().Format(time.RFC3339),
	})
}

// RegisterDevice 注册新设备
func (h *Handlers) RegisterDevice(c *gin.Context) {
	var req CreateDeviceRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		respondError(c, http.StatusBadRequest, "请求参数无效: "+err.Error())
		return
	}
	// 校验设备编号格式 AA-BBBBBBBB
	if !devCodeRegex.MatchString(req.DevCode) {
		respondError(c, http.StatusBadRequest, "设备编号格式错误，应为 AA-BBBBBBBB（2位大写字母-8位数字）")
		return
	}
	// 检查是否已存在
	exist, err := h.db.GetDevice(req.DevCode)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "查询设备失败: "+err.Error())
		return
	}
	if exist != nil {
		respondError(c, http.StatusConflict, "设备已存在: "+req.DevCode)
		return
	}

	dev := &Device{
		DevCode:   req.DevCode,
		Name:      req.Name,
		Type:      req.Type,
		ProjectID: req.ProjectID,
		Status:    "offline",
		IP:        req.IP,
		Version:   req.Version,
		CreatedAt: time.Now(),
	}
	// type 为空时从编号前缀推断
	if dev.Type == "" {
		dev.Type = req.DevCode[:2]
	}
	// name 为空时根据类型编码生成默认名
	if dev.Name == "" {
		if desc, ok := deviceTypeMap[dev.Type]; ok {
			dev.Name = desc + "-" + req.DevCode[3:]
		} else {
			dev.Name = dev.Type + "-" + req.DevCode[3:]
		}
	}

	if err := h.db.CreateDevice(dev); err != nil {
		respondError(c, http.StatusInternalServerError, "注册设备失败: "+err.Error())
		return
	}
	respondOK(c, dev)
}

// ListDevices 设备列表
func (h *Handlers) ListDevices(c *gin.Context) {
	var filter DeviceFilter
	if err := c.ShouldBindQuery(&filter); err != nil {
		respondError(c, http.StatusBadRequest, "查询参数无效: "+err.Error())
		return
	}
	devices, total, err := h.db.ListDevices(filter)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "查询设备列表失败: "+err.Error())
		return
	}
	if devices == nil {
		devices = []*Device{}
	}
	respondOK(c, gin.H{
		"total":     total,
		"page":      filter.page(),
		"page_size": filter.pageSize(),
		"items":     devices,
	})
}

// GetDevice 设备详情
func (h *Handlers) GetDevice(c *gin.Context) {
	code := c.Param("code")
	dev, err := h.db.GetDevice(code)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "查询设备失败: "+err.Error())
		return
	}
	if dev == nil {
		respondError(c, http.StatusNotFound, "设备不存在: "+code)
		return
	}
	respondOK(c, dev)
}

// UpdateDevice 更新设备信息
func (h *Handlers) UpdateDevice(c *gin.Context) {
	code := c.Param("code")
	var req UpdateDeviceRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		respondError(c, http.StatusBadRequest, "请求参数无效: "+err.Error())
		return
	}
	dev, err := h.db.UpdateDevice(code, req)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "更新设备失败: "+err.Error())
		return
	}
	if dev == nil {
		respondError(c, http.StatusNotFound, "设备不存在: "+code)
		return
	}
	respondOK(c, dev)
}

// DeleteDevice 删除设备
func (h *Handlers) DeleteDevice(c *gin.Context) {
	code := c.Param("code")
	dev, _ := h.db.GetDevice(code)
	if dev == nil {
		respondError(c, http.StatusNotFound, "设备不存在: "+code)
		return
	}
	if err := h.db.DeleteDevice(code); err != nil {
		respondError(c, http.StatusInternalServerError, "删除设备失败: "+err.Error())
		return
	}
	respondOK(c, gin.H{"dev_code": code, "deleted": true})
}

// GetShadow 获取设备影子
func (h *Handlers) GetShadow(c *gin.Context) {
	code := c.Param("code")
	s, err := h.db.GetShadow(code)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "查询设备影子失败: "+err.Error())
		return
	}
	if s == nil {
		respondError(c, http.StatusNotFound, "设备影子不存在: "+code)
		return
	}
	respondOK(c, s)
}

// UpdateDesired 更新期望状态
func (h *Handlers) UpdateDesired(c *gin.Context) {
	code := c.Param("code")
	var req UpdateDesiredRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		respondError(c, http.StatusBadRequest, "请求参数无效: "+err.Error())
		return
	}
	dev, _ := h.db.GetDevice(code)
	if dev == nil {
		respondError(c, http.StatusNotFound, "设备不存在: "+code)
		return
	}
	s, err := h.db.UpdateDesired(code, req.Desired)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "更新期望状态失败: "+err.Error())
		return
	}
	respondOK(c, s)
}

// Heartbeat 设备心跳上报
func (h *Handlers) Heartbeat(c *gin.Context) {
	code := c.Param("code")
	// 心跳请求体可选，允许空 body
	var req HeartbeatRequest
	_ = c.ShouldBindJSON(&req)

	dev, _ := h.db.GetDevice(code)
	if dev == nil {
		respondError(c, http.StatusNotFound, "设备不存在: "+code)
		return
	}
	if err := h.db.Heartbeat(code, req); err != nil {
		respondError(c, http.StatusInternalServerError, "心跳处理失败: "+err.Error())
		return
	}
	shadow, _ := h.db.GetShadow(code)
	respondOK(c, gin.H{
		"dev_code": code,
		"status":   "online",
		"shadow":   shadow,
	})
}

// GetStats 设备统计
func (h *Handlers) GetStats(c *gin.Context) {
	stats, err := h.db.GetStats()
	if err != nil {
		respondError(c, http.StatusInternalServerError, "统计失败: "+err.Error())
		return
	}
	respondOK(c, stats)
}

// ============ 辅助函数 ============

func (f DeviceFilter) page() int {
	if f.Page <= 0 {
		return 1
	}
	return f.Page
}

func (f DeviceFilter) pageSize() int {
	if f.PageSize <= 0 {
		return 20
	}
	return f.PageSize
}

// ============ 主函数 ============

func main() {
	cfg := loadConfig()
	log.Printf("[%s] Starting on port %s", cfg.AppName, cfg.AppPort)

	// 初始化数据库（PG 不可用时自动降级为内存模式）
	db, err := NewDatabase(cfg)
	if err != nil {
		log.Fatalf("数据库初始化失败: %v", err)
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

	// 健康检查
	r.GET("/health", handlers.HealthCheck)

	// API 路由组
	v1 := r.Group("/api/v1")
	{
		// 静态路由优先注册（避免与 :code 冲突）
		v1.GET("/devices/stats", handlers.GetStats)

		v1.POST("/devices", handlers.RegisterDevice)
		v1.GET("/devices", handlers.ListDevices)
		v1.GET("/devices/:code", handlers.GetDevice)
		v1.PUT("/devices/:code", handlers.UpdateDevice)
		v1.DELETE("/devices/:code", handlers.DeleteDevice)

		v1.GET("/devices/:code/shadow", handlers.GetShadow)
		v1.PUT("/devices/:code/shadow/desired", handlers.UpdateDesired)
		v1.POST("/devices/:code/heartbeat", handlers.Heartbeat)
	}

	// 启动服务
	addr := ":" + cfg.AppPort
	log.Printf("[%s] Listening on %s", cfg.AppName, addr)
	if err := r.Run(addr); err != nil {
		log.Fatalf("服务启动失败: %v", err)
	}
}
