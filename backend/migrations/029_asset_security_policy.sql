-- 029: Enterprise asset approval, MCP policy and append-only security audit.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'skill_releases' AND COLUMN_NAME = 'scan_report_json') = 0,
    'ALTER TABLE skill_releases ADD COLUMN scan_report_json LONGTEXT NULL AFTER scan_status, ADD COLUMN reviewed_by INT NULL AFTER published_by, ADD COLUMN reviewed_at DATETIME NULL AFTER reviewed_by, ADD COLUMN native_approved TINYINT(1) NOT NULL DEFAULT 0 AFTER reviewed_at, ADD COLUMN revoked_by INT NULL AFTER native_approved, ADD COLUMN revoked_at DATETIME NULL AFTER revoked_by, ADD COLUMN revocation_reason VARCHAR(1000) NULL AFTER revoked_at',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mcp_revisions' AND COLUMN_NAME = 'security_report_json') = 0,
    'ALTER TABLE mcp_revisions ADD COLUMN security_report_json LONGTEXT NULL AFTER status',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mcp_connections' AND COLUMN_NAME = 'tool_policy_json') = 0,
    'ALTER TABLE mcp_connections ADD COLUMN tool_policy_json LONGTEXT NULL AFTER config_overrides_json',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS asset_security_events (
    id BIGINT NOT NULL AUTO_INCREMENT,
    asset_type VARCHAR(30) NOT NULL,
    asset_id BIGINT NOT NULL,
    action VARCHAR(30) NOT NULL,
    actor_user_id INT NOT NULL,
    reason VARCHAR(1000) NULL,
    details_json LONGTEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_asset_security_events_asset (asset_type, asset_id),
    KEY ix_asset_security_events_action (action),
    KEY ix_asset_security_events_actor (actor_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
