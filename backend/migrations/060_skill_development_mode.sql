-- Author-only runtime preference; existing installations keep their pinned release.
SET @skill_development_sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
     AND TABLE_NAME = 'skills' AND COLUMN_NAME = 'development_mode') = 0,
    'ALTER TABLE skills ADD COLUMN development_mode BOOLEAN NOT NULL DEFAULT FALSE',
    'SELECT 1'
);
PREPARE skill_development_stmt FROM @skill_development_sql;
EXECUTE skill_development_stmt;
DEALLOCATE PREPARE skill_development_stmt;
