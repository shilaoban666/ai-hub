-- AI 模型管理功能：创建 ai_models 表
-- 执行方式：mysql -u root -p aihub < add_ai_models.sql

CREATE TABLE IF NOT EXISTS ai_models (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL COMMENT '模型名称',
    provider VARCHAR(50) NOT NULL COMMENT '服务商',
    api_key VARCHAR(500) NOT NULL COMMENT 'API Key',
    api_proxy_url VARCHAR(500) DEFAULT NULL COMMENT 'API 代理地址',
    description TEXT DEFAULT NULL COMMENT '描述',
    is_deleted TINYINT(1) NOT NULL DEFAULT 0 COMMENT '软删除标记',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 模型管理';
