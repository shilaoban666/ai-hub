-- 032: Make the published assistant icon configurable.

SET @has_assistant_icon = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'platform_agent_settings'
      AND COLUMN_NAME = 'assistant_icon'
);
SET @assistant_icon_sql = IF(
    @has_assistant_icon = 0,
    "ALTER TABLE platform_agent_settings ADD COLUMN assistant_icon VARCHAR(50) NOT NULL DEFAULT 'H' AFTER assistant_name",
    'SELECT 1'
);
PREPARE assistant_icon_stmt FROM @assistant_icon_sql;
EXECUTE assistant_icon_stmt;
DEALLOCATE PREPARE assistant_icon_stmt;
