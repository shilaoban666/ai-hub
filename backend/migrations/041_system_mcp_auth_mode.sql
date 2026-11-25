-- System MCP authentication defaults; existing personal overrides stay intact.
SET @has_system_mcp_auth_mode = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'mcp_definitions'
      AND COLUMN_NAME = 'auth_mode'
);
SET @system_mcp_auth_mode_sql = IF(
    @has_system_mcp_auth_mode = 0,
    'ALTER TABLE mcp_definitions ADD COLUMN auth_mode VARCHAR(30) NOT NULL DEFAULT ''manual'' AFTER transport_type',
    'SELECT 1'
);
PREPARE system_mcp_auth_mode_stmt FROM @system_mcp_auth_mode_sql;
EXECUTE system_mcp_auth_mode_stmt;
DEALLOCATE PREPARE system_mcp_auth_mode_stmt;
