-- 053: Idempotent Web submissions and bounded retry/recovery metadata.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'idempotency_key') = 0,
    'ALTER TABLE agent_runs ADD COLUMN idempotency_key VARCHAR(100) NULL AFTER source',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND INDEX_NAME = 'ix_agent_runs_queue_admission') = 0,
    'ALTER TABLE agent_runs ADD INDEX ix_agent_runs_queue_admission (user_id, source, status)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'idempotency_fingerprint') = 0,
    'ALTER TABLE agent_runs ADD COLUMN idempotency_fingerprint VARCHAR(64) NULL AFTER idempotency_key',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND INDEX_NAME = 'uq_agent_runs_user_idempotency') = 0,
    'ALTER TABLE agent_runs ADD UNIQUE KEY uq_agent_runs_user_idempotency (user_id, idempotency_key)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
