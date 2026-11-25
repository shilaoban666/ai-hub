-- 015: Make the model wire protocol and reasoning capability explicit.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_models'
       AND COLUMN_NAME = 'api_protocol') = 0,
    'ALTER TABLE ai_models ADD COLUMN api_protocol VARCHAR(30) NOT NULL DEFAULT ''auto'' COMMENT ''auto | openai-completions | anthropic-messages'' AFTER api_proxy_url',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_models'
       AND COLUMN_NAME = 'reasoning_support') = 0,
    'ALTER TABLE ai_models ADD COLUMN reasoning_support VARCHAR(10) NOT NULL DEFAULT ''auto'' COMMENT ''auto | enabled | disabled'' AFTER api_protocol',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE ai_models SET api_protocol = 'auto'
WHERE api_protocol IS NULL OR api_protocol = '';

UPDATE ai_models SET reasoning_support = 'auto'
WHERE reasoning_support IS NULL OR reasoning_support = '';
