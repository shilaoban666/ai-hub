-- Knowledge base console: Bailian settings, DingTalk drive sync, retrieval call usage.
-- Idempotent: tables use IF NOT EXISTS; later-added columns are added only when missing.
CREATE TABLE IF NOT EXISTS knowledge_settings (
    id INT NOT NULL PRIMARY KEY,
    bailian_endpoint VARCHAR(200) NOT NULL DEFAULT 'bailian.cn-beijing.aliyuncs.com',
    bailian_access_key_id VARCHAR(200) NULL,
    bailian_access_key_secret_encrypted TEXT NULL,
    bailian_workspace_id VARCHAR(100) NULL,
    default_index_id VARCHAR(100) NULL,
    default_category_id VARCHAR(100) NULL,
    dingtalk_client_id VARCHAR(200) NULL,
    dingtalk_client_secret_encrypted TEXT NULL,
    updated_by INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowledge_dingtalk_identities (
    user_id INT NOT NULL PRIMARY KEY,
    union_id VARCHAR(100) NOT NULL,
    nick VARCHAR(100) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowledge_uploads (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    index_id VARCHAR(100) NOT NULL,
    index_name VARCHAR(200) NULL,
    category_id VARCHAR(100) NOT NULL,
    category_name VARCHAR(200) NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'uploading',
    bailian_file_id VARCHAR(100) NULL,
    bailian_job_id VARCHAR(100) NULL,
    error_message TEXT NULL,
    sync_dingtalk TINYINT(1) NOT NULL DEFAULT 0,
    dingtalk_workspace_id VARCHAR(100) NULL,
    dingtalk_folder_id VARCHAR(100) NULL,
    dingtalk_folder_path VARCHAR(500) NULL,
    dingtalk_status VARCHAR(20) NOT NULL DEFAULT 'none',
    dingtalk_dentry_id VARCHAR(100) NULL,
    dingtalk_error TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_knowledge_uploads_user_id (user_id),
    INDEX ix_knowledge_uploads_status (status),
    INDEX ix_knowledge_uploads_created_at (created_at),
    INDEX ix_knowledge_uploads_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowledge_call_logs (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    index_id VARCHAR(100) NOT NULL,
    index_name VARCHAR(200) NULL,
    source VARCHAR(30) NOT NULL DEFAULT 'api',
    query VARCHAR(1000) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'success',
    result_count INT NOT NULL DEFAULT 0,
    query_tokens INT NOT NULL DEFAULT 0,
    result_tokens INT NOT NULL DEFAULT 0,
    rag_tokens INT NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    error_message VARCHAR(1000) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_knowledge_call_logs_user_id (user_id),
    INDEX ix_knowledge_calls_created_user (created_at, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowledge_call_hits (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    call_id BIGINT NOT NULL,
    index_id VARCHAR(100) NOT NULL,
    doc_name VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_knowledge_call_hits_call_id (call_id),
    INDEX ix_knowledge_call_hits_created_doc (created_at, doc_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS knowledge_doc_links (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    index_id VARCHAR(100) NOT NULL,
    doc_name VARCHAR(255) NOT NULL,
    dingtalk_url VARCHAR(500) NULL,
    folder_path VARCHAR(500) NULL,
    checked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_knowledge_doc_links_index_doc (index_id, doc_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'knowledge_uploads' AND COLUMN_NAME = 'dingtalk_url');
SET @alter_sql = IF(@column_exists = 0, 'ALTER TABLE knowledge_uploads ADD COLUMN dingtalk_url VARCHAR(500) NULL', 'SELECT 1');
PREPARE alter_stmt FROM @alter_sql;
EXECUTE alter_stmt;
DEALLOCATE PREPARE alter_stmt;

SET @column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'knowledge_call_logs' AND COLUMN_NAME = 'session_id');
SET @alter_sql = IF(@column_exists = 0, 'ALTER TABLE knowledge_call_logs ADD COLUMN session_id VARCHAR(64) NULL, ADD INDEX ix_knowledge_call_logs_session_id (session_id)', 'SELECT 1');
PREPARE alter_stmt FROM @alter_sql;
EXECUTE alter_stmt;
DEALLOCATE PREPARE alter_stmt;

SET @column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'knowledge_call_logs' AND COLUMN_NAME = 'external_id');
SET @alter_sql = IF(@column_exists = 0, 'ALTER TABLE knowledge_call_logs ADD COLUMN external_id VARCHAR(100) NULL, ADD UNIQUE INDEX uq_knowledge_calls_external (external_id)', 'SELECT 1');
PREPARE alter_stmt FROM @alter_sql;
EXECUTE alter_stmt;
DEALLOCATE PREPARE alter_stmt;

SET @column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'knowledge_settings' AND COLUMN_NAME = 'usage_departments');
SET @alter_sql = IF(@column_exists = 0, 'ALTER TABLE knowledge_settings ADD COLUMN usage_departments TEXT NULL, ADD COLUMN upload_departments TEXT NULL', 'SELECT 1');
PREPARE alter_stmt FROM @alter_sql;
EXECUTE alter_stmt;
DEALLOCATE PREPARE alter_stmt;
