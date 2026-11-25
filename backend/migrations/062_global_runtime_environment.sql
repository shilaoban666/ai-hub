-- Administrator-managed environment shared by all users' Skill scripts.
SET @column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'platform_global_settings' AND COLUMN_NAME = 'runtime_environment');
SET @alter_sql = IF(@column_exists = 0, 'ALTER TABLE platform_global_settings ADD COLUMN runtime_environment JSON NULL', 'SELECT 1');
PREPARE alter_stmt FROM @alter_sql;
EXECUTE alter_stmt;
DEALLOCATE PREPARE alter_stmt;
