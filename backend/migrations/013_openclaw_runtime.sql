-- 013: OpenClaw runtime instances, session pinning, and runtime run metadata.

CREATE TABLE IF NOT EXISTS runtime_instances (
    id BIGINT NOT NULL AUTO_INCREMENT,
    agent_id INT NOT NULL,
    user_id INT NOT NULL,
    runtime_type VARCHAR(30) NOT NULL DEFAULT 'openclaw',
    deployment_mode VARCHAR(20) NOT NULL DEFAULT 'managed',
    external_agent_id VARCHAR(100) NOT NULL,
    endpoint VARCHAR(500) NULL,
    auth_secret_encrypted TEXT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'unprovisioned',
    desired_config_hash CHAR(64) NULL,
    applied_config_hash CHAR(64) NULL,
    runtime_version VARCHAR(50) NULL,
    image_ref VARCHAR(500) NULL,
    worker_id VARCHAR(100) NULL,
    lease_until DATETIME NULL,
    last_health_at DATETIME NULL,
    last_error_code VARCHAR(100) NULL,
    last_error_message TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_runtime_instances_agent_id (agent_id),
    KEY idx_runtime_instances_user_id (user_id),
    KEY idx_runtime_instances_status (status),
    KEY idx_runtime_instances_lease (lease_until),
    CONSTRAINT fk_runtime_instances_agent
        FOREIGN KEY (agent_id) REFERENCES agents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='long-lived runtime process or remote endpoint per agent';

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions'
       AND COLUMN_NAME = 'runtime_type') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN runtime_type VARCHAR(30) NULL COMMENT ''runtime pinned on first run''',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions'
       AND COLUMN_NAME = 'runtime_instance_id') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN runtime_instance_id BIGINT NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions'
       AND COLUMN_NAME = 'runtime_state') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN runtime_state VARCHAR(30) NOT NULL DEFAULT ''active''',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions'
       AND INDEX_NAME = 'idx_agent_sessions_runtime_instance') = 0,
    'ALTER TABLE agent_sessions ADD INDEX idx_agent_sessions_runtime_instance (runtime_instance_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'runtime_instance_id') = 0,
    'ALTER TABLE agent_runs ADD COLUMN runtime_instance_id BIGINT NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'runtime_run_id') = 0,
    'ALTER TABLE agent_runs ADD COLUMN runtime_run_id VARCHAR(200) NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'runtime_session_id') = 0,
    'ALTER TABLE agent_runs ADD COLUMN runtime_session_id VARCHAR(200) NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'runtime_protocol') = 0,
    'ALTER TABLE agent_runs ADD COLUMN runtime_protocol VARCHAR(50) NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'runtime_version') = 0,
    'ALTER TABLE agent_runs ADD COLUMN runtime_version VARCHAR(50) NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND INDEX_NAME = 'idx_agent_runs_runtime_instance') = 0,
    'ALTER TABLE agent_runs ADD INDEX idx_agent_runs_runtime_instance (runtime_instance_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE agent_sessions s
JOIN agents a ON a.id = s.agent_id
SET s.runtime_type = COALESCE(s.runtime_type, a.runtime_type, 'claude_code')
WHERE s.runtime_type IS NULL;
