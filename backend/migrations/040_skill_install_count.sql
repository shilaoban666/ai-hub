-- R2026092183178: cumulative successful personal/global skill installations.
-- Run before deploying the updated backend, with installation writes paused.
SET @has_skill_install_count = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'skills'
      AND COLUMN_NAME = 'install_count'
);
SET @skill_install_count_sql = IF(
    @has_skill_install_count = 0,
    'ALTER TABLE skills ADD COLUMN install_count BIGINT NULL DEFAULT NULL AFTER comment_count',
    'SELECT 1'
);
PREPARE skill_install_count_stmt FROM @skill_install_count_sql;
EXECUTE skill_install_count_stmt;
DEALLOCATE PREPARE skill_install_count_stmt;

-- Existing records prove at least one installation, including uninstalled rows.
-- Historical reinstalls were not recorded and cannot be reconstructed exactly.
-- Only seed NULL counters so rerunning this migration preserves new counts.
UPDATE skills s
LEFT JOIN (
    SELECT skill_id, COUNT(*) AS total FROM skill_installations GROUP BY skill_id
) personal ON personal.skill_id = s.id
LEFT JOIN (
    SELECT skill_id, COUNT(*) AS total FROM system_skill_installations GROUP BY skill_id
) global_install ON global_install.skill_id = s.id
SET s.install_count = COALESCE(personal.total, 0) + COALESCE(global_install.total, 0),
    s.updated_at = s.updated_at
WHERE s.install_count IS NULL;

ALTER TABLE skills MODIFY COLUMN install_count BIGINT NOT NULL DEFAULT 0;
