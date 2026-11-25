-- 017: Cross-process Agent execution lease and encrypted credential storage.

CREATE TABLE IF NOT EXISTS agent_execution_leases (
    agent_id INT NOT NULL,
    run_id VARCHAR(32) NULL,
    owner_id VARCHAR(100) NULL,
    fencing_token BIGINT NOT NULL DEFAULT 0,
    lease_until DATETIME(6) NOT NULL,
    heartbeat_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (agent_id),
    KEY ix_agent_execution_leases_run_id (run_id),
    KEY ix_agent_execution_leases_lease_until (lease_until),
    CONSTRAINT fk_agent_execution_leases_agent
        FOREIGN KEY (agent_id) REFERENCES agents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='renewable cross-process execution lease per Agent';

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_models'
       AND COLUMN_NAME = 'api_key_encrypted') = 0,
    'ALTER TABLE ai_models ADD COLUMN api_key_encrypted TEXT NULL AFTER api_key',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mcp_services'
       AND COLUMN_NAME = 'config_encrypted') = 0,
    'ALTER TABLE mcp_services ADD COLUMN config_encrypted LONGTEXT NULL AFTER config',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
