-- 014: Persist agent-level reasoning defaults across runtimes.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agents'
       AND COLUMN_NAME = 'thinking_level') = 0,
    'ALTER TABLE agents ADD COLUMN thinking_level VARCHAR(20) NOT NULL DEFAULT ''inherit'' COMMENT ''agent reasoning effort default'' AFTER runtime_type',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agents'
       AND COLUMN_NAME = 'reasoning_visibility') = 0,
    'ALTER TABLE agents ADD COLUMN reasoning_visibility VARCHAR(20) NOT NULL DEFAULT ''off'' COMMENT ''off | on | stream'' AFTER thinking_level',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE agents
SET thinking_level = 'inherit'
WHERE thinking_level IS NULL OR thinking_level = '';

UPDATE agents
SET reasoning_visibility = 'off'
WHERE reasoning_visibility IS NULL OR reasoning_visibility = '';
