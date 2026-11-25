-- Apply before deploying the assistant appearance settings.
ALTER TABLE platform_agent_settings
    MODIFY COLUMN assistant_icon VARCHAR(255) NOT NULL DEFAULT 'H';

SET @has_assistant_mascot = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'platform_agent_settings'
      AND COLUMN_NAME = 'assistant_mascot'
);
SET @assistant_mascot_sql = IF(@has_assistant_mascot = 0,
    "ALTER TABLE platform_agent_settings ADD COLUMN assistant_mascot VARCHAR(255) NOT NULL DEFAULT '@cow' AFTER assistant_icon",
    'SELECT 1');
PREPARE assistant_mascot_stmt FROM @assistant_mascot_sql;
EXECUTE assistant_mascot_stmt;
DEALLOCATE PREPARE assistant_mascot_stmt;

ALTER TABLE agents MODIFY COLUMN icon VARCHAR(255) NULL;
