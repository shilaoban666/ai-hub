-- 045: Give each expert agent its own persistent workspace and runtime cell.
SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_workspaces' AND COLUMN_NAME = 'agent_id') = 0,
    'ALTER TABLE user_workspaces ADD COLUMN agent_id INT NULL AFTER user_id, ADD INDEX ix_user_workspaces_agent (agent_id), ADD CONSTRAINT fk_user_workspaces_agent FOREIGN KEY (agent_id) REFERENCES agents(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'runtime_cells' AND COLUMN_NAME = 'agent_id') = 0,
    'ALTER TABLE runtime_cells ADD COLUMN agent_id INT NULL AFTER user_id, ADD INDEX ix_runtime_cells_agent (agent_id), ADD CONSTRAINT fk_runtime_cells_agent FOREIGN KEY (agent_id) REFERENCES agents(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Older installations used more than one name for this single-column
-- unique index. Find it by its shape so rerunning the migration repairs all
-- variants instead of only the original constraint name.
SELECT MIN(index_name) INTO @legacy_user_workspace_index
FROM (
    SELECT index_name
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'user_workspaces'
      AND NON_UNIQUE = 0
      AND INDEX_NAME <> 'PRIMARY'
    GROUP BY index_name
    HAVING GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') = 'user_id'
) AS legacy_indexes;
SET @sql = IF(
    @legacy_user_workspace_index IS NULL,
    'SELECT 1',
    CONCAT('ALTER TABLE user_workspaces DROP INDEX `', REPLACE(@legacy_user_workspace_index, '`', '``'), '`')
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT MIN(index_name) INTO @legacy_runtime_cell_index
FROM (
    SELECT index_name
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'runtime_cells'
      AND NON_UNIQUE = 0
      AND INDEX_NAME <> 'PRIMARY'
    GROUP BY index_name
    HAVING GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') = 'user_id'
) AS legacy_indexes;
SET @sql = IF(
    @legacy_runtime_cell_index IS NULL,
    'SELECT 1',
    CONCAT('ALTER TABLE runtime_cells DROP INDEX `', REPLACE(@legacy_runtime_cell_index, '`', '``'), '`')
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Existing rows remain the user's legacy workbench. New rows created for an
-- agent use agent_id and a new workspace_key.
