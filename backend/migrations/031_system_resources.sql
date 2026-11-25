-- 031: Distinguish administrator-managed prompts from user marketplace shares.

SET @has_prompt_system = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prompt_templates'
      AND COLUMN_NAME = 'is_system'
);
SET @prompt_system_sql = IF(
    @has_prompt_system = 0,
    'ALTER TABLE prompt_templates ADD COLUMN is_system TINYINT(1) NOT NULL DEFAULT 0 AFTER is_public, ADD INDEX ix_prompt_templates_is_system (is_system)',
    'SELECT 1'
);
PREPARE prompt_system_stmt FROM @prompt_system_sql;
EXECUTE prompt_system_stmt;
DEALLOCATE PREPARE prompt_system_stmt;
