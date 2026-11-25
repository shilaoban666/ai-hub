-- Run before starting the updated backend. Safe to repeat without resetting settings.
SET @assistant_thinking_sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'platform_agent_settings'
       AND COLUMN_NAME = 'thinking_level') = 0,
    'ALTER TABLE platform_agent_settings ADD COLUMN thinking_level VARCHAR(20) NOT NULL DEFAULT ''inherit'' AFTER runtime_type',
    'SELECT 1'
);
PREPARE assistant_reasoning_stmt FROM @assistant_thinking_sql;
EXECUTE assistant_reasoning_stmt;
DEALLOCATE PREPARE assistant_reasoning_stmt;

SET @assistant_visibility_sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'platform_agent_settings'
       AND COLUMN_NAME = 'reasoning_visibility') = 0,
    'ALTER TABLE platform_agent_settings ADD COLUMN reasoning_visibility VARCHAR(20) NOT NULL DEFAULT ''off'' AFTER thinking_level',
    'SELECT 1'
);
PREPARE assistant_reasoning_stmt FROM @assistant_visibility_sql;
EXECUTE assistant_reasoning_stmt;
DEALLOCATE PREPARE assistant_reasoning_stmt;
