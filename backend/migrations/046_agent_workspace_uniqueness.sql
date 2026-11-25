-- 046: Keep one persistent workspace and one runtime cell per user/expert.
-- NULL agent_id remains allowed for the legacy personal workbench because
-- MySQL permits multiple NULL values in a unique key.

SET @has_agent_workspace_key = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'user_workspaces'
      AND INDEX_NAME = 'uq_user_workspaces_user_agent'
);
SET @agent_workspace_key_sql = IF(
    @has_agent_workspace_key = 0,
    'ALTER TABLE user_workspaces ADD UNIQUE KEY uq_user_workspaces_user_agent (user_id, agent_id)',
    'SELECT 1'
);
PREPARE agent_workspace_key_stmt FROM @agent_workspace_key_sql;
EXECUTE agent_workspace_key_stmt;
DEALLOCATE PREPARE agent_workspace_key_stmt;

SET @has_agent_runtime_key = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'runtime_cells'
      AND INDEX_NAME = 'uq_runtime_cells_user_agent'
);
SET @agent_runtime_key_sql = IF(
    @has_agent_runtime_key = 0,
    'ALTER TABLE runtime_cells ADD UNIQUE KEY uq_runtime_cells_user_agent (user_id, agent_id)',
    'SELECT 1'
);
PREPARE agent_runtime_key_stmt FROM @agent_runtime_key_sql;
EXECUTE agent_runtime_key_stmt;
DEALLOCATE PREPARE agent_runtime_key_stmt;

-- MySQL allows multiple NULL values in a unique key. A generated scope key
-- maps the legacy personal workspace (agent_id=NULL) to 0, so concurrent
-- first requests still converge on one row per user while expert rows remain
-- isolated by their agent id.
SET @has_workspace_scope = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'user_workspaces'
      AND COLUMN_NAME = 'scope_agent_id'
);
SET @workspace_scope_sql = IF(
    @has_workspace_scope = 0,
    'ALTER TABLE user_workspaces ADD COLUMN scope_agent_id BIGINT GENERATED ALWAYS AS (COALESCE(agent_id, 0)) STORED AFTER agent_id',
    'SELECT 1'
);
PREPARE workspace_scope_stmt FROM @workspace_scope_sql;
EXECUTE workspace_scope_stmt;
DEALLOCATE PREPARE workspace_scope_stmt;

SET @has_workspace_scope_key = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'user_workspaces'
      AND INDEX_NAME = 'uq_user_workspaces_user_scope'
);
SET @workspace_scope_key_sql = IF(
    @has_workspace_scope_key = 0,
    'ALTER TABLE user_workspaces ADD UNIQUE KEY uq_user_workspaces_user_scope (user_id, scope_agent_id)',
    'SELECT 1'
);
PREPARE workspace_scope_key_stmt FROM @workspace_scope_key_sql;
EXECUTE workspace_scope_key_stmt;
DEALLOCATE PREPARE workspace_scope_key_stmt;

SET @has_runtime_scope = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'runtime_cells'
      AND COLUMN_NAME = 'scope_agent_id'
);
SET @runtime_scope_sql = IF(
    @has_runtime_scope = 0,
    'ALTER TABLE runtime_cells ADD COLUMN scope_agent_id BIGINT GENERATED ALWAYS AS (COALESCE(agent_id, 0)) STORED AFTER agent_id',
    'SELECT 1'
);
PREPARE runtime_scope_stmt FROM @runtime_scope_sql;
EXECUTE runtime_scope_stmt;
DEALLOCATE PREPARE runtime_scope_stmt;

SET @has_runtime_scope_key = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'runtime_cells'
      AND INDEX_NAME = 'uq_runtime_cells_user_scope'
);
SET @runtime_scope_key_sql = IF(
    @has_runtime_scope_key = 0,
    'ALTER TABLE runtime_cells ADD UNIQUE KEY uq_runtime_cells_user_scope (user_id, scope_agent_id)',
    'SELECT 1'
);
PREPARE runtime_scope_key_stmt FROM @runtime_scope_key_sql;
EXECUTE runtime_scope_key_stmt;
DEALLOCATE PREPARE runtime_scope_key_stmt;
