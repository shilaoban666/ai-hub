-- Skill metadata, independent of SKILL.md and historical release archives.
-- Nullable for compatibility with existing rows; API responses normalize NULL to [].
SET @skill_examples_sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
     AND TABLE_NAME = 'skills' AND COLUMN_NAME = 'conversation_examples') = 0,
    'ALTER TABLE skills ADD COLUMN conversation_examples JSON NULL',
    'SELECT 1'
);
PREPARE skill_examples_stmt FROM @skill_examples_sql;
EXECUTE skill_examples_stmt;
DEALLOCATE PREPARE skill_examples_stmt;
