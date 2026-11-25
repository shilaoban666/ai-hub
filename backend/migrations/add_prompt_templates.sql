-- 提示词模板管理功能：创建 prompt_templates 表
-- 执行方式：mysql -u root -p aihub < add_prompt_templates.sql

CREATE TABLE IF NOT EXISTS prompt_templates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(200) NOT NULL COMMENT '模板名称',
    category VARCHAR(50) NOT NULL DEFAULT '其他' COMMENT '分类: 代码生成/文档写作/数据分析/翻译/对话/其他',
    content TEXT NOT NULL COMMENT '提示词模板内容，支持 {{variable}} 占位符',
    variables TEXT DEFAULT NULL COMMENT '变量定义，JSON数组格式',
    description TEXT DEFAULT NULL COMMENT '模板描述',
    is_deleted TINYINT(1) NOT NULL DEFAULT 0 COMMENT '软删除标记',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_name (name),
    INDEX idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='提示词模板管理';
