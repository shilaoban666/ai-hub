-- Run before starting the updated backend. Existing assistants default to enabled.
-- Safe to repeat without resetting user settings.
SET @noun_sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
     AND TABLE_NAME = 'agents' AND COLUMN_NAME = 'noun_highlight_enabled') = 0,
    'ALTER TABLE agents ADD COLUMN noun_highlight_enabled TINYINT(1) NOT NULL DEFAULT 1',
    'SELECT 1'
);
PREPARE noun_stmt FROM @noun_sql;
EXECUTE noun_stmt;
DEALLOCATE PREPARE noun_stmt;

SET @noun_sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
     AND TABLE_NAME = 'agents' AND COLUMN_NAME = 'noun_explanation_url') = 0,
    'ALTER TABLE agents ADD COLUMN noun_explanation_url VARCHAR(2000) NOT NULL DEFAULT ''https://online.fancyqube.net/Project/admin/skuapp/t_noun_explanation/?exact=1&noun_name=''',
    'SELECT 1'
);
PREPARE noun_stmt FROM @noun_sql;
EXECUTE noun_stmt;
DEALLOCATE PREPARE noun_stmt;

SET @noun_sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
     AND TABLE_NAME = 'workbench_settings' AND COLUMN_NAME = 'noun_highlight_enabled') = 0,
    'ALTER TABLE workbench_settings ADD COLUMN noun_highlight_enabled TINYINT(1) NOT NULL DEFAULT 1',
    'SELECT 1'
);
PREPARE noun_stmt FROM @noun_sql;
EXECUTE noun_stmt;
DEALLOCATE PREPARE noun_stmt;

SET @noun_sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
     AND TABLE_NAME = 'workbench_settings' AND COLUMN_NAME = 'noun_explanation_url') = 0,
    'ALTER TABLE workbench_settings ADD COLUMN noun_explanation_url VARCHAR(2000) NOT NULL DEFAULT ''https://online.fancyqube.net/Project/admin/skuapp/t_noun_explanation/?exact=1&noun_name=''',
    'SELECT 1'
);
PREPARE noun_stmt FROM @noun_sql;
EXECUTE noun_stmt;
DEALLOCATE PREPARE noun_stmt;
