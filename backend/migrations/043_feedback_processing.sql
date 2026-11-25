-- Add feedback processing fields; safe to rerun on existing installations.

SET @feedback_column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_message_feedback' AND COLUMN_NAME = 'processing_status');
SET @feedback_alter_sql = IF(@feedback_column_exists = 0,
    'ALTER TABLE agent_message_feedback ADD COLUMN processing_status VARCHAR(20) NULL', 'SELECT 1');
PREPARE feedback_alter_stmt FROM @feedback_alter_sql;
EXECUTE feedback_alter_stmt;
DEALLOCATE PREPARE feedback_alter_stmt;

SET @feedback_column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_message_feedback' AND COLUMN_NAME = 'assignee_user_id');
SET @feedback_alter_sql = IF(@feedback_column_exists = 0,
    'ALTER TABLE agent_message_feedback ADD COLUMN assignee_user_id INT NULL', 'SELECT 1');
PREPARE feedback_alter_stmt FROM @feedback_alter_sql;
EXECUTE feedback_alter_stmt;
DEALLOCATE PREPARE feedback_alter_stmt;

SET @feedback_column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_message_feedback' AND COLUMN_NAME = 'assignee_username');
SET @feedback_alter_sql = IF(@feedback_column_exists = 0,
    'ALTER TABLE agent_message_feedback ADD COLUMN assignee_username VARCHAR(200) NULL', 'SELECT 1');
PREPARE feedback_alter_stmt FROM @feedback_alter_sql;
EXECUTE feedback_alter_stmt;
DEALLOCATE PREPARE feedback_alter_stmt;

SET @feedback_column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_message_feedback' AND COLUMN_NAME = 'assignee_name');
SET @feedback_alter_sql = IF(@feedback_column_exists = 0,
    'ALTER TABLE agent_message_feedback ADD COLUMN assignee_name VARCHAR(200) NULL', 'SELECT 1');
PREPARE feedback_alter_stmt FROM @feedback_alter_sql;
EXECUTE feedback_alter_stmt;
DEALLOCATE PREPARE feedback_alter_stmt;

SET @feedback_index_exists = (SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_message_feedback' AND INDEX_NAME = 'ix_agent_message_feedback_processing_status');
SET @feedback_alter_sql = IF(@feedback_index_exists = 0,
    'ALTER TABLE agent_message_feedback ADD INDEX ix_agent_message_feedback_processing_status (processing_status)', 'SELECT 1');
PREPARE feedback_alter_stmt FROM @feedback_alter_sql;
EXECUTE feedback_alter_stmt;
DEALLOCATE PREPARE feedback_alter_stmt;

SET @feedback_index_exists = (SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_message_feedback' AND INDEX_NAME = 'ix_agent_message_feedback_assignee_user_id');
SET @feedback_alter_sql = IF(@feedback_index_exists = 0,
    'ALTER TABLE agent_message_feedback ADD INDEX ix_agent_message_feedback_assignee_user_id (assignee_user_id)', 'SELECT 1');
PREPARE feedback_alter_stmt FROM @feedback_alter_sql;
EXECUTE feedback_alter_stmt;
DEALLOCATE PREPARE feedback_alter_stmt;

UPDATE agent_message_feedback SET processing_status = 'pending', updated_at = updated_at
WHERE rating = 'dislike' AND processing_status IS NULL;
