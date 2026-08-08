package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"github.com/joho/godotenv"
	_ "github.com/lib/pq" // PostgreSQL 驱动
	"golang.org/x/crypto/bcrypt"
)

// ============ 配置 ============

// Config 认证服务配置
type Config struct {
	AppName           string
	AppPort           string
	PGHost            string
	PGPort            string
	PGUser            string
	PGPassword        string
	PGDB              string
	JWTSecret         string
	JWTExpireHours    int // access token 过期小时数
	RefreshExpireDays int // refresh token 过期天数
	AdminUser         string
	AdminPassword     string
	AdminRole         string
}

func loadConfig() *Config {
	return &Config{
		AppName:           getEnv("APP_NAME", "auth-svc"),
		AppPort:           getEnv("APP_PORT", "8001"),
		PGHost:            getEnv("POSTGRES_HOST", "localhost"),
		PGPort:            getEnv("POSTGRES_PORT", "5432"),
		PGUser:            getEnv("POSTGRES_USER", "birchatlas"),
		PGPassword:        getEnv("POSTGRES_PASSWORD", ""),
		PGDB:              getEnv("POSTGRES_DB", "birchatlas"),
		JWTSecret:         getEnv("JWT_SECRET", "birchatlas-default-secret-change-me"),
		JWTExpireHours:    getEnvInt("JWT_EXPIRE_HOURS", 24),
		RefreshExpireDays: getEnvInt("REFRESH_EXPIRE_DAYS", 7),
		AdminUser:         getEnv("ADMIN_USER", "admin"),
		AdminPassword:     getEnv("ADMIN_PASSWORD", "admin123"),
		AdminRole:         getEnv("ADMIN_ROLE", "admin"),
	}
}

// getEnv 读取环境变量，缺失时返回默认值
func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

// getEnvInt 读取整型环境变量，缺失或非法时返回默认值
func getEnvInt(key string, defaultVal int) int {
	if val := os.Getenv(key); val != "" {
		if n, err := strconv.Atoi(val); err == nil {
			return n
		}
	}
	return defaultVal
}

// ============ 数据模型 ============

// User 用户数据模型
type User struct {
	ID           int64     `json:"id"`
	Username     string    `json:"username"`
	PasswordHash string    `json:"-"` // 密码哈希不返回
	Role         string    `json:"role"`
	CreatedAt    time.Time `json:"created_at"`
}

// LoginRequest 登录请求
type LoginRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

// RegisterRequest 注册请求
type RegisterRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
	Role     string `json:"role"` // 可选，默认 user
}

// TokenResponse 登录/刷新返回的 token 信息
type TokenResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int64  `json:"expires_in"` // access token 有效期（秒）
	TokenType    string `json:"token_type"`
}

// RefreshRequest 刷新 token 请求
type RefreshRequest struct {
	RefreshToken string `json:"refresh_token" binding:"required"`
}

// ValidateRequest 验证 token 请求
type ValidateRequest struct {
	Token string `json:"token" binding:"required"`
}

// ============ 统一响应 ============

const (
	codeSuccess = 1 // 成功
	codeFail    = 0 // 失败
)

// respondOK 返回成功响应
func respondOK(c *gin.Context, data interface{}) {
	c.JSON(http.StatusOK, gin.H{
		"code":    codeSuccess,
		"message": "ok",
		"data":    data,
	})
}

// respondError 返回错误响应
func respondError(c *gin.Context, httpStatus int, message string) {
	c.JSON(httpStatus, gin.H{
		"code":    codeFail,
		"message": message,
		"data":    nil,
	})
}

// ============ 用户存储接口 ============

// UserStore 用户存储抽象，支持 PostgreSQL 与内存两种实现
type UserStore interface {
	Init() error
	CreateUser(username, passwordHash, role string) (*User, error)
	GetUserByUsername(username string) (*User, error)
	GetUserByID(id int64) (*User, error)
	Close() error
}

// ============ PostgreSQL 存储 ============

// PGStore 基于 PostgreSQL 的用户存储
type PGStore struct {
	conn *sql.DB
}

// NewPGStore 创建 PostgreSQL 存储并测试连接
func NewPGStore(cfg *Config) (*PGStore, error) {
	dsn := fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=disable",
		cfg.PGHost, cfg.PGPort, cfg.PGUser, cfg.PGPassword, cfg.PGDB)
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, err
	}
	// 连接池配置
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(5 * time.Minute)

	// 测试连接（3 秒超时）
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		db.Close()
		return nil, err
	}
	return &PGStore{conn: db}, nil
}

// Init 初始化用户表
func (s *PGStore) Init() error {
	_, err := s.conn.Exec(`
		CREATE TABLE IF NOT EXISTS users (
			id SERIAL PRIMARY KEY,
			username VARCHAR(64) NOT NULL UNIQUE,
			password_hash VARCHAR(255) NOT NULL,
			role VARCHAR(32) NOT NULL DEFAULT 'user',
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)
	`)
	return err
}

// CreateUser 创建用户
func (s *PGStore) CreateUser(username, passwordHash, role string) (*User, error) {
	var u User
	err := s.conn.QueryRow(`
		INSERT INTO users (username, password_hash, role)
		VALUES ($1, $2, $3)
		RETURNING id, username, password_hash, role, created_at
	`, username, passwordHash, role).Scan(&u.ID, &u.Username, &u.PasswordHash, &u.Role, &u.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &u, nil
}

// GetUserByUsername 按用户名查询
func (s *PGStore) GetUserByUsername(username string) (*User, error) {
	var u User
	err := s.conn.QueryRow(`
		SELECT id, username, password_hash, role, created_at
		FROM users WHERE username = $1
	`, username).Scan(&u.ID, &u.Username, &u.PasswordHash, &u.Role, &u.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &u, nil
}

// GetUserByID 按 ID 查询
func (s *PGStore) GetUserByID(id int64) (*User, error) {
	var u User
	err := s.conn.QueryRow(`
		SELECT id, username, password_hash, role, created_at
		FROM users WHERE id = $1
	`, id).Scan(&u.ID, &u.Username, &u.PasswordHash, &u.Role, &u.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &u, nil
}

// Close 关闭连接
func (s *PGStore) Close() error {
	return s.conn.Close()
}

// ============ 内存存储（开发降级模式） ============

// MemoryStore 基于内存 map 的用户存储，用于无 PostgreSQL 环境开发测试
type MemoryStore struct {
	mu    sync.RWMutex
	users map[string]*User // 按用户名索引
	idSeq int64
}

// NewMemoryStore 创建内存存储
func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		users: make(map[string]*User),
	}
}

// Init 内存模式无需建表
func (s *MemoryStore) Init() error {
	return nil
}

// CreateUser 创建用户
func (s *MemoryStore) CreateUser(username, passwordHash, role string) (*User, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.users[username]; exists {
		return nil, fmt.Errorf("用户名已存在")
	}
	s.idSeq++
	u := &User{
		ID:           s.idSeq,
		Username:     username,
		PasswordHash: passwordHash,
		Role:         role,
		CreatedAt:    time.Now(),
	}
	s.users[username] = u
	return u, nil
}

// GetUserByUsername 按用户名查询
func (s *MemoryStore) GetUserByUsername(username string) (*User, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	u, ok := s.users[username]
	if !ok {
		return nil, sql.ErrNoRows
	}
	return u, nil
}

// GetUserByID 按 ID 查询
func (s *MemoryStore) GetUserByID(id int64) (*User, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, u := range s.users {
		if u.ID == id {
			return u, nil
		}
	}
	return nil, sql.ErrNoRows
}

// Close 内存模式无需关闭
func (s *MemoryStore) Close() error {
	return nil
}

// ============ JWT 服务 ============

// Claims 自定义 JWT 声明
type Claims struct {
	UserID   int64  `json:"user_id"`
	Username string `json:"username"`
	Role     string `json:"role"`
	Type     string `json:"type"` // access 或 refresh
	jwt.RegisteredClaims
}

// JWTService token 生成与解析服务
type JWTService struct {
	secret        []byte
	accessExpire  time.Duration
	refreshExpire time.Duration
}

// NewJWTService 创建 JWT 服务
func NewJWTService(cfg *Config) *JWTService {
	return &JWTService{
		secret:        []byte(cfg.JWTSecret),
		accessExpire:  time.Duration(cfg.JWTExpireHours) * time.Hour,
		refreshExpire: time.Duration(cfg.RefreshExpireDays) * 24 * time.Hour,
	}
}

// generateToken 生成指定类型的 token
func (j *JWTService) generateToken(user *User, tokenType string, expire time.Duration) (string, error) {
	now := time.Now()
	claims := Claims{
		UserID:   user.ID,
		Username: user.Username,
		Role:     user.Role,
		Type:     tokenType,
		RegisteredClaims: jwt.RegisteredClaims{
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(expire)),
			NotBefore: jwt.NewNumericDate(now),
			Subject:   user.Username,
		},
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(j.secret)
}

// GenerateAccessToken 生成 access token
func (j *JWTService) GenerateAccessToken(user *User) (string, error) {
	return j.generateToken(user, "access", j.accessExpire)
}

// GenerateRefreshToken 生成 refresh token
func (j *JWTService) GenerateRefreshToken(user *User) (string, error) {
	return j.generateToken(user, "refresh", j.refreshExpire)
}

// ParseToken 解析并校验 token
func (j *JWTService) ParseToken(tokenString string) (*Claims, error) {
	claims := &Claims{}
	token, err := jwt.ParseWithClaims(tokenString, claims, func(t *jwt.Token) (interface{}, error) {
		// 校验签名算法
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return j.secret, nil
	})
	if err != nil {
		return nil, err
	}
	if !token.Valid {
		return nil, fmt.Errorf("invalid token")
	}
	return claims, nil
}

// ============ HTTP 处理器 ============

// Handlers 业务处理器
type Handlers struct {
	store       UserStore
	cfg         *Config
	jwtSvc      *JWTService
	storageMode string // postgres 或 memory
}

// NewHandlers 创建处理器
func NewHandlers(store UserStore, cfg *Config, jwtSvc *JWTService, storageMode string) *Handlers {
	return &Handlers{
		store:       store,
		cfg:         cfg,
		jwtSvc:      jwtSvc,
		storageMode: storageMode,
	}
}

// HealthCheck 健康检查
func (h *Handlers) HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":       "ok",
		"service":      h.cfg.AppName,
		"storage_mode": h.storageMode,
		"time":         time.Now().Format(time.RFC3339),
	})
}

// Login 用户登录
func (h *Handlers) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		respondError(c, http.StatusBadRequest, "请求参数错误: "+err.Error())
		return
	}

	// 查询用户
	user, err := h.store.GetUserByUsername(req.Username)
	if err != nil {
		respondError(c, http.StatusUnauthorized, "用户名或密码错误")
		return
	}

	// 校验密码
	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(req.Password)); err != nil {
		respondError(c, http.StatusUnauthorized, "用户名或密码错误")
		return
	}

	// 生成 token
	accessToken, err := h.jwtSvc.GenerateAccessToken(user)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "生成 token 失败")
		return
	}
	refreshToken, err := h.jwtSvc.GenerateRefreshToken(user)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "生成 token 失败")
		return
	}

	respondOK(c, TokenResponse{
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		ExpiresIn:    int64(h.cfg.JWTExpireHours * 3600),
		TokenType:    "Bearer",
	})
}

// Register 用户注册（仅 admin 可调用）
func (h *Handlers) Register(c *gin.Context) {
	var req RegisterRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		respondError(c, http.StatusBadRequest, "请求参数错误: "+err.Error())
		return
	}

	// 检查用户名是否已存在
	if existing, _ := h.store.GetUserByUsername(req.Username); existing != nil {
		respondError(c, http.StatusConflict, "用户名已存在")
		return
	}

	// 角色默认 user
	role := req.Role
	if role == "" {
		role = "user"
	}

	// 密码哈希
	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "密码哈希失败")
		return
	}

	user, err := h.store.CreateUser(req.Username, string(hash), role)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "创建用户失败: "+err.Error())
		return
	}

	respondOK(c, gin.H{
		"id":         user.ID,
		"username":   user.Username,
		"role":       user.Role,
		"created_at": user.CreatedAt,
	})
}

// Profile 获取当前用户信息
func (h *Handlers) Profile(c *gin.Context) {
	userID, _ := c.Get("user_id")
	user, err := h.store.GetUserByID(userID.(int64))
	if err != nil {
		respondError(c, http.StatusNotFound, "用户不存在")
		return
	}

	respondOK(c, gin.H{
		"id":         user.ID,
		"username":   user.Username,
		"role":       user.Role,
		"created_at": user.CreatedAt,
	})
}

// Validate 验证 token 有效性
func (h *Handlers) Validate(c *gin.Context) {
	var req ValidateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		respondError(c, http.StatusBadRequest, "请求参数错误: "+err.Error())
		return
	}

	claims, err := h.jwtSvc.ParseToken(req.Token)
	if err != nil {
		respondError(c, http.StatusUnauthorized, "token 无效或已过期")
		return
	}

	respondOK(c, gin.H{
		"valid":      true,
		"user_id":    claims.UserID,
		"username":   claims.Username,
		"role":       claims.Role,
		"type":       claims.Type,
		"expires_at": claims.ExpiresAt.Time.Format(time.RFC3339),
	})
}

// Refresh 刷新 token
func (h *Handlers) Refresh(c *gin.Context) {
	var req RefreshRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		respondError(c, http.StatusBadRequest, "请求参数错误: "+err.Error())
		return
	}

	// 解析 refresh token
	claims, err := h.jwtSvc.ParseToken(req.RefreshToken)
	if err != nil {
		respondError(c, http.StatusUnauthorized, "refresh token 无效或已过期")
		return
	}
	if claims.Type != "refresh" {
		respondError(c, http.StatusUnauthorized, "token 类型错误，需要 refresh token")
		return
	}

	// 查询用户（确保用户仍然存在）
	user, err := h.store.GetUserByID(claims.UserID)
	if err != nil {
		respondError(c, http.StatusUnauthorized, "用户不存在")
		return
	}

	// 生成新的 token 对
	accessToken, err := h.jwtSvc.GenerateAccessToken(user)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "生成 token 失败")
		return
	}
	refreshToken, err := h.jwtSvc.GenerateRefreshToken(user)
	if err != nil {
		respondError(c, http.StatusInternalServerError, "生成 token 失败")
		return
	}

	respondOK(c, TokenResponse{
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		ExpiresIn:    int64(h.cfg.JWTExpireHours * 3600),
		TokenType:    "Bearer",
	})
}

// ============ 中间件 ============

// AuthMiddleware JWT 认证中间件，从 Authorization header 提取 Bearer token
func AuthMiddleware(jwtSvc *JWTService) gin.HandlerFunc {
	return func(c *gin.Context) {
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			respondError(c, http.StatusUnauthorized, "缺少认证信息")
			return
		}

		// 解析 Bearer token
		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
			respondError(c, http.StatusUnauthorized, "认证格式错误，应为 Bearer <token>")
			return
		}

		claims, err := jwtSvc.ParseToken(strings.TrimSpace(parts[1]))
		if err != nil {
			respondError(c, http.StatusUnauthorized, "token 无效或已过期")
			return
		}
		if claims.Type != "access" {
			respondError(c, http.StatusUnauthorized, "token 类型错误，需要 access token")
			return
		}

		// 注入用户信息到上下文
		c.Set("user_id", claims.UserID)
		c.Set("username", claims.Username)
		c.Set("role", claims.Role)
		c.Next()
	}
}

// AdminMiddleware 管理员权限校验中间件
func AdminMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		role, exists := c.Get("role")
		if !exists || role != "admin" {
			respondError(c, http.StatusForbidden, "需要管理员权限")
			return
		}
		c.Next()
	}
}

// CORSMiddleware 跨域中间件
func CORSMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", "*")
		c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

// ============ 辅助函数 ============

// ensureAdmin 确保默认 admin 用户存在
func ensureAdmin(store UserStore, cfg *Config) {
	// 检查 admin 是否已存在
	if _, err := store.GetUserByUsername(cfg.AdminUser); err == nil {
		log.Printf("[%s] admin 用户已存在", cfg.AppName)
		return
	}

	// 密码哈希
	hash, err := bcrypt.GenerateFromPassword([]byte(cfg.AdminPassword), bcrypt.DefaultCost)
	if err != nil {
		log.Printf("[%s] admin 密码哈希失败: %v", cfg.AppName, err)
		return
	}

	// 创建 admin
	if _, err := store.CreateUser(cfg.AdminUser, string(hash), cfg.AdminRole); err != nil {
		log.Printf("[%s] 创建默认 admin 用户失败: %v", cfg.AppName, err)
		return
	}
	log.Printf("[%s] 默认 admin 用户已创建 (用户名: %s)", cfg.AppName, cfg.AdminUser)
}

// ============ 主函数 ============

func main() {
	// 加载 .env 文件（可选，文件不存在时忽略）
	_ = godotenv.Load()

	cfg := loadConfig()
	log.Printf("[%s] Starting on port %s", cfg.AppName, cfg.AppPort)

	// 安全提示：使用默认 JWT 密钥时告警
	if cfg.JWTSecret == "birchatlas-default-secret-change-me" {
		log.Printf("[%s] 警告: 正在使用默认 JWT 密钥，生产环境请通过 JWT_SECRET 环境变量配置", cfg.AppName)
	}

	// 尝试连接 PostgreSQL，失败则降级到内存模式
	var store UserStore
	storageMode := "memory"
	if pgStore, err := NewPGStore(cfg); err != nil {
		log.Printf("[%s] PostgreSQL 不可用，降级到内存模式: %v", cfg.AppName, err)
		store = NewMemoryStore()
	} else {
		store = pgStore
		storageMode = "postgres"
		log.Printf("[%s] 已连接 PostgreSQL 存储", cfg.AppName)
	}
	defer store.Close()

	// 初始化存储（建表）
	if err := store.Init(); err != nil {
		log.Fatalf("[%s] 存储初始化失败: %v", cfg.AppName, err)
	}

	// 创建默认 admin 用户
	ensureAdmin(store, cfg)

	// JWT 服务
	jwtSvc := NewJWTService(cfg)

	// 处理器
	handlers := NewHandlers(store, cfg, jwtSvc, storageMode)

	// 配置路由
	r := gin.Default()
	r.Use(CORSMiddleware())

	// 健康检查
	r.GET("/health", handlers.HealthCheck)

	// API v1 路由组
	v1 := r.Group("/api/v1")
	{
		// 健康检查（兼容 /api/v1/health）
		v1.GET("/health", handlers.HealthCheck)

		auth := v1.Group("/auth")
		{
			// 用户登录
			auth.POST("/login", handlers.Login)
			// 用户注册（需 admin 权限）
			auth.POST("/register", AuthMiddleware(jwtSvc), AdminMiddleware(), handlers.Register)
			// 获取当前用户信息（需登录）
			auth.GET("/profile", AuthMiddleware(jwtSvc), handlers.Profile)
			// 验证 token 有效性
			auth.POST("/validate", handlers.Validate)
			// 刷新 token
			auth.POST("/refresh", handlers.Refresh)
		}
	}

	// 启动服务
	addr := ":" + cfg.AppPort
	log.Printf("[%s] Listening on %s (storage: %s)", cfg.AppName, addr, storageMode)

	if err := r.Run(addr); err != nil {
		log.Fatalf("[%s] 启动失败: %v", cfg.AppName, err)
	}
}
