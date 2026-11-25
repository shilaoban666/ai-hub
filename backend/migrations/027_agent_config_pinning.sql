-- 027: Pin model and published assistant configuration per conversation.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agents' AND COLUMN_NAME = 'settings_version') = 0,
    'ALTER TABLE agents ADD COLUMN settings_version INT NULL AFTER default_agent_user_id',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions' AND COLUMN_NAME = 'model_id') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN model_id INT NULL AFTER runtime_type, ADD INDEX ix_agent_sessions_model_id (model_id), ADD CONSTRAINT fk_agent_sessions_model FOREIGN KEY (model_id) REFERENCES ai_models(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions' AND COLUMN_NAME = 'config_version') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN config_version INT NULL AFTER model_id',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
