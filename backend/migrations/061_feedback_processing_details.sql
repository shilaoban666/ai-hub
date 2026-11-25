-- Processing evidence and notes; idempotent upgrade.
SET @column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_message_feedback' AND COLUMN_NAME = 'processing_remark');
SET @alter_sql = IF(@column_exists = 0, 'ALTER TABLE agent_message_feedback ADD COLUMN processing_remark TEXT NULL', 'SELECT 1');
PREPARE alter_stmt FROM @alter_sql;
EXECUTE alter_stmt;
DEALLOCATE PREPARE alter_stmt;

SET @column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_message_feedback' AND COLUMN_NAME = 'processing_images');
SET @alter_sql = IF(@column_exists = 0, 'ALTER TABLE agent_message_feedback ADD COLUMN processing_images TEXT NULL', 'SELECT 1');
PREPARE alter_stmt FROM @alter_sql;
EXECUTE alter_stmt;
DEALLOCATE PREPARE alter_stmt;
