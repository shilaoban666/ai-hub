-- 018: Per-Agent encrypted MCP overrides and durable permission control.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agents'
       AND COLUMN_NAME = 'mcp_overrides_encrypted') = 0,
    'ALTER TABLE agents ADD COLUMN mcp_overrides_encrypted LONGTEXT NULL AFTER timeout_seconds',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- agent_runs.id is CHAR/ascii in migration-created installations and
-- VARCHAR/utf8mb4 in metadata-created installations. Copy its exact definition
-- so the foreign key is valid for both existing layouts.
SELECT CONCAT(
    COLUMN_TYPE,
    IF(CHARACTER_SET_NAME IS NULL, '', CONCAT(' CHARACTER SET ', CHARACTER_SET_NAME)),
    IF(COLLATION_NAME IS NULL, '', CONCAT(' COLLATE ', COLLATION_NAME))
) INTO @agent_run_id_definition
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'agent_runs'
  AND COLUMN_NAME = 'id';

SET @sql = CONCAT(
    'CREATE TABLE IF NOT EXISTS agent_permission_requests (',
    'req_id VARCHAR(100) NOT NULL,',
    'run_id ', @agent_run_id_definition, ' NOT NULL,',
    'tool_key VARCHAR(300) NOT NULL,',
    'tool_name VARCHAR(200) NOT NULL,',
    'tool_input LONGTEXT NOT NULL,',
    'status VARCHAR(20) NOT NULL DEFAULT ''pending'',',
    'decision VARCHAR(10) NULL,',
    'reason VARCHAR(1000) NULL,',
    'remember TINYINT(1) NOT NULL DEFAULT 0,',
    'delivered_at DATETIME(6) NULL,',
    'expires_at DATETIME(6) NOT NULL,',
    'decided_at DATETIME(6) NULL,',
    'created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),',
    'updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),',
    'PRIMARY KEY (req_id),',
    'KEY ix_agent_permission_requests_run_id (run_id),',
    'KEY ix_agent_permission_requests_status (status),',
    'KEY ix_agent_permission_requests_expires_at (expires_at),',
    'CONSTRAINT fk_agent_permission_requests_run FOREIGN KEY (run_id) REFERENCES agent_runs(id)',
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ',
    'COMMENT=''durable cross-process Agent permission requests'''
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
