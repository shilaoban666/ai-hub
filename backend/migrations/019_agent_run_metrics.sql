-- 019: Queryable duration and token usage metrics for Agent runs.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'duration_ms') = 0,
    'ALTER TABLE agent_runs ADD COLUMN duration_ms BIGINT NULL AFTER finished_at',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'input_tokens') = 0,
    'ALTER TABLE agent_runs ADD COLUMN input_tokens BIGINT NULL AFTER duration_ms',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'output_tokens') = 0,
    'ALTER TABLE agent_runs ADD COLUMN output_tokens BIGINT NULL AFTER input_tokens',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'cache_read_tokens') = 0,
    'ALTER TABLE agent_runs ADD COLUMN cache_read_tokens BIGINT NULL AFTER output_tokens',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'cache_creation_tokens') = 0,
    'ALTER TABLE agent_runs ADD COLUMN cache_creation_tokens BIGINT NULL AFTER cache_read_tokens',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'total_tokens') = 0,
    'ALTER TABLE agent_runs ADD COLUMN total_tokens BIGINT NULL AFTER cache_creation_tokens',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'usage_detail') = 0,
    'ALTER TABLE agent_runs ADD COLUMN usage_detail LONGTEXT NULL AFTER total_tokens',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
