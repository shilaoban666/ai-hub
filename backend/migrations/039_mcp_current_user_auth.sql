-- 039: Per-connector authentication mode for forwarding the current Web user's Bearer token.

SET @has_connection_auth_mode = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'mcp_connections'
      AND COLUMN_NAME = 'auth_mode'
);
SET @connection_auth_mode_sql = IF(
    @has_connection_auth_mode = 0,
    'ALTER TABLE mcp_connections ADD COLUMN auth_mode VARCHAR(30) NOT NULL DEFAULT ''manual'' AFTER config_overrides_json',
    'SELECT 1'
);
PREPARE connection_auth_mode_stmt FROM @connection_auth_mode_sql;
EXECUTE connection_auth_mode_stmt;
DEALLOCATE PREPARE connection_auth_mode_stmt;

SET @has_user_header_auth_mode = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'mcp_user_headers'
      AND COLUMN_NAME = 'auth_mode'
);
SET @user_header_auth_mode_sql = IF(
    @has_user_header_auth_mode = 0,
    'ALTER TABLE mcp_user_headers ADD COLUMN auth_mode VARCHAR(30) NOT NULL DEFAULT ''manual'' AFTER headers_encrypted',
    'SELECT 1'
);
PREPARE user_header_auth_mode_stmt FROM @user_header_auth_mode_sql;
EXECUTE user_header_auth_mode_stmt;
DEALLOCATE PREPARE user_header_auth_mode_stmt;
