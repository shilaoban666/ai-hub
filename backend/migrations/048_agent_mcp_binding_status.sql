-- Per-agent MCP enable/disable state. Re-running preserves subsequent changes.
SET @has_binding_status = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'expert_mcp_bindings' AND COLUMN_NAME = 'status'
);
SET @binding_status_sql = IF(@has_binding_status = 0,
    'ALTER TABLE expert_mcp_bindings ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT ''active'' AFTER connection_id',
    'SELECT 1');
PREPARE binding_status_stmt FROM @binding_status_sql;
EXECUTE binding_status_stmt;
DEALLOCATE PREPARE binding_status_stmt;

-- Retain the effective state before the migration, including disabled imports.
SET @binding_status_backfill = IF(@has_binding_status = 0,
    'UPDATE expert_mcp_bindings b JOIN mcp_connections c ON c.id = b.connection_id SET b.status = IF(c.status = ''active'', ''active'', ''disabled'')',
    'SELECT 1');
PREPARE binding_status_stmt FROM @binding_status_backfill;
EXECUTE binding_status_stmt;
DEALLOCATE PREPARE binding_status_stmt;
