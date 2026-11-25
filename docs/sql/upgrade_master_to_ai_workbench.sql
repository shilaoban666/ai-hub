-- AI Hub: master -> AI workbench incremental database upgrade
-- Baseline: master de8a590; includes migrations 025 through 034 (both 028 files).
-- Includes 22 new tables, 32 new columns on existing tables, decimal conversions,
-- and the historical data backfills supplied by the source migrations.
--
-- Usage:
-- 1. Select the target MySQL database before executing this file.
-- 2. The database must already have the master schema.
-- 3. Back up the database and stop application writes during the upgrade.
-- 4. Execute the complete file in ONE connection, in the order below.
--    PREPARE statements use connection-local variables.
-- 5. MySQL DDL commits implicitly; this file is not an atomic transaction.
--    Stop on the first error; do not use a client option that ignores errors.
--
-- This bundle preserves the original migration statements without alteration.
-- It is an incremental upgrade, not a complete schema for an empty database.
-- Existing migrations use IF NOT EXISTS / column checks, but some checks guard
-- multiple columns together. Inspect partially migrated schemas before reruns.
-- Do not also execute this bundle through a recursive migration-file scanner.
--
-- Included data backfills:
-- - Link historical runs only when exactly one assistant message matches.
-- - Create workspaces for existing agent owners and bind agents/sessions/runs.
-- - Create initial runtime-cell records for existing workspaces.
--
-- Not performed by SQL:
-- - Copying legacy workspace files (handled by application runtime preparation).
-- - Scanning historical skill archives (handled by the application).
-- - Creating production model secrets or publishing assistant settings.
-- - Replacing existing quota values with USER_WORKSPACE_QUOTA_BYTES.
--   Migrated workspaces retain the source migration default quota_bytes=0.

-- BEGIN 025_enterprise_assistant_credits.sql
-- 025: Enterprise default assistant, platform models and authoritative credit wallet.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_models' AND COLUMN_NAME = 'scope') = 0,
    "ALTER TABLE ai_models ADD COLUMN scope VARCHAR(20) NOT NULL DEFAULT 'user' AFTER user_id, ADD INDEX ix_ai_models_scope (scope)",
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_models' AND COLUMN_NAME = 'is_enabled') = 0,
    'ALTER TABLE ai_models ADD COLUMN is_enabled TINYINT(1) NOT NULL DEFAULT 1 AFTER scope, ADD INDEX ix_ai_models_is_enabled (is_enabled)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_models' AND COLUMN_NAME = 'health_status') = 0,
    "ALTER TABLE ai_models ADD COLUMN health_status VARCHAR(20) NOT NULL DEFAULT 'unknown' AFTER is_enabled",
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agents' AND COLUMN_NAME = 'kind') = 0,
    "ALTER TABLE agents ADD COLUMN kind VARCHAR(30) NOT NULL DEFAULT 'expert' AFTER user_id, ADD INDEX ix_agents_kind (kind)",
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agents' AND COLUMN_NAME = 'default_agent_user_id') = 0,
    'ALTER TABLE agents ADD COLUMN default_agent_user_id INT NULL AFTER kind, ADD UNIQUE INDEX uq_agents_default_agent_user_id (default_agent_user_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs' AND COLUMN_NAME = 'pricing_snapshot') = 0,
    'ALTER TABLE agent_runs ADD COLUMN pricing_snapshot LONGTEXT NULL AFTER usage_detail',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs' AND COLUMN_NAME = 'reserved_points') = 0,
    'ALTER TABLE agent_runs ADD COLUMN reserved_points BIGINT NOT NULL DEFAULT 0 AFTER pricing_snapshot',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs' AND COLUMN_NAME = 'charged_points') = 0,
    'ALTER TABLE agent_runs ADD COLUMN charged_points BIGINT NOT NULL DEFAULT 0 AFTER reserved_points',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs' AND COLUMN_NAME = 'settlement_status') = 0,
    "ALTER TABLE agent_runs ADD COLUMN settlement_status VARCHAR(30) NOT NULL DEFAULT 'not_required' AFTER charged_points, ADD INDEX ix_agent_runs_settlement_status (settlement_status)",
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS platform_agent_settings (
    id BIGINT NOT NULL AUTO_INCREMENT,
    version INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    assistant_name VARCHAR(200) NOT NULL DEFAULT 'AI 助手',
    assistant_description TEXT NULL,
    system_prompt LONGTEXT NULL,
    runtime_type VARCHAR(30) NOT NULL DEFAULT 'claude_code',
    default_model_id INT NULL,
    max_turns INT NOT NULL DEFAULT 50,
    timeout_seconds INT NOT NULL DEFAULT 600,
    credit_display_name VARCHAR(50) NOT NULL DEFAULT '算点',
    credit_display_name_en VARCHAR(50) NOT NULL DEFAULT 'Credits',
    initial_claim_amount BIGINT NOT NULL DEFAULT 0,
    daily_claim_amount BIGINT NOT NULL DEFAULT 0,
    per_run_limit BIGINT NOT NULL DEFAULT 0,
    low_balance_threshold BIGINT NOT NULL DEFAULT 0,
    claim_timezone VARCHAR(50) NOT NULL DEFAULT 'Asia/Shanghai',
    max_concurrent_runs INT NOT NULL DEFAULT 1,
    created_by INT NOT NULL,
    published_by INT NULL,
    published_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_platform_agent_settings_version (version),
    KEY ix_platform_agent_settings_status (status),
    CONSTRAINT fk_platform_settings_default_model FOREIGN KEY (default_model_id) REFERENCES ai_models(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS credit_accounts (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    available_balance BIGINT NOT NULL DEFAULT 0,
    reserved_balance BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    version BIGINT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_credit_accounts_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS credit_claim_records (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    claim_type VARCHAR(20) NOT NULL,
    claim_date DATE NOT NULL,
    amount BIGINT NOT NULL,
    policy_version INT NOT NULL,
    business_key VARCHAR(200) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_credit_claim_records_business_key (business_key),
    UNIQUE KEY uq_credit_claim_user_type_date (user_id, claim_type, claim_date),
    KEY ix_credit_claim_user_date (user_id, claim_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS credit_ledger (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    entry_type VARCHAR(30) NOT NULL,
    amount BIGINT NOT NULL,
    available_after BIGINT NOT NULL,
    reserved_after BIGINT NOT NULL,
    run_id VARCHAR(32) NULL,
    business_key VARCHAR(200) NOT NULL,
    operator_user_id INT NULL,
    reason VARCHAR(1000) NULL,
    metadata LONGTEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_credit_ledger_business_key (business_key),
    KEY ix_credit_ledger_user_created (user_id, created_at),
    KEY ix_credit_ledger_run_id (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS model_pricing_versions (
    id BIGINT NOT NULL AUTO_INCREMENT,
    model_id INT NOT NULL,
    version INT NOT NULL,
    input_rate BIGINT NOT NULL DEFAULT 0,
    output_rate BIGINT NOT NULL DEFAULT 0,
    cache_read_rate BIGINT NOT NULL DEFAULT 0,
    cache_creation_rate BIGINT NOT NULL DEFAULT 0,
    rate_scale BIGINT NOT NULL DEFAULT 1000000,
    effective_from DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_model_pricing_model_version (model_id, version),
    CONSTRAINT fk_model_pricing_model FOREIGN KEY (model_id) REFERENCES ai_models(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS model_usage_events (
    id BIGINT NOT NULL AUTO_INCREMENT,
    run_id VARCHAR(32) NOT NULL,
    provider_request_id VARCHAR(200) NOT NULL,
    model_id INT NOT NULL,
    input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    cache_read_tokens BIGINT NOT NULL DEFAULT 0,
    cache_creation_tokens BIGINT NOT NULL DEFAULT 0,
    occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_usage LONGTEXT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_model_usage_provider_request (provider_request_id),
    KEY ix_model_usage_run_id (run_id),
    KEY ix_model_usage_model_id (model_id),
    CONSTRAINT fk_model_usage_model FOREIGN KEY (model_id) REFERENCES ai_models(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- END 025_enterprise_assistant_credits.sql

-- BEGIN 026_model_run_credentials.sql
-- 026: Short-lived per-Run credentials for the AI Hub model gateway.

CREATE TABLE IF NOT EXISTS model_run_credentials (
    id BIGINT NOT NULL AUTO_INCREMENT,
    token_hash VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    run_id VARCHAR(32) NOT NULL,
    user_id INT NOT NULL,
    model_id INT NOT NULL,
    pricing_version_id BIGINT NOT NULL,
    max_points BIGINT NOT NULL,
    consumed_points BIGINT NOT NULL DEFAULT 0,
    request_count INT NOT NULL DEFAULT 0,
    request_in_flight TINYINT(1) NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_model_run_credentials_token_hash (token_hash),
    UNIQUE KEY uq_model_run_credentials_run_id (run_id),
    KEY ix_model_run_credentials_user_id (user_id),
    KEY ix_model_run_credentials_model_id (model_id),
    KEY ix_model_run_credentials_status_expires (status, expires_at),
    CONSTRAINT fk_model_run_credentials_model FOREIGN KEY (model_id) REFERENCES ai_models(id),
    CONSTRAINT fk_model_run_credentials_pricing FOREIGN KEY (pricing_version_id) REFERENCES model_pricing_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- END 026_model_run_credentials.sql

-- BEGIN 027_agent_config_pinning.sql
-- 027: Pin model and published assistant configuration per conversation.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agents' AND COLUMN_NAME = 'settings_version') = 0,
    'ALTER TABLE agents ADD COLUMN settings_version INT NULL AFTER default_agent_user_id',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions' AND COLUMN_NAME = 'model_id') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN model_id INT NULL AFTER runtime_type, ADD INDEX ix_agent_sessions_model_id (model_id), ADD CONSTRAINT fk_agent_sessions_model FOREIGN KEY (model_id) REFERENCES ai_models(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions' AND COLUMN_NAME = 'config_version') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN config_version INT NULL AFTER model_id',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
-- END 027_agent_config_pinning.sql

-- BEGIN 028_credit_decimal_precision.sql
-- 028: Store credit balances and per-run charges with two decimal places.

ALTER TABLE agent_runs
    MODIFY COLUMN reserved_points DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN charged_points DECIMAL(20, 2) NOT NULL DEFAULT 0.00;

SET @agent_run_message_sql = IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'agent_runs'
       AND COLUMN_NAME = 'assistant_message_id') = 0,
    'ALTER TABLE agent_runs ADD COLUMN assistant_message_id INT NULL AFTER runtime_version, ADD INDEX ix_agent_runs_assistant_message_id (assistant_message_id)',
    'SELECT 1'
);
PREPARE agent_run_message_stmt FROM @agent_run_message_sql;
EXECUTE agent_run_message_stmt;
DEALLOCATE PREPARE agent_run_message_stmt;

-- Backfill only unambiguous historical turns. Failed runs without an assistant
-- message remain NULL instead of being linked heuristically.
UPDATE agent_runs AS target
JOIN (
    SELECT candidates.run_id, candidates.assistant_message_id
    FROM (
        SELECT
            run_record.id AS run_id,
            MIN(message.id) AS assistant_message_id,
            COUNT(message.id) AS candidate_count
        FROM agent_runs AS run_record
        JOIN agent_messages AS message
          ON message.session_id = run_record.session_id
         AND message.role = 'assistant'
         AND message.created_at >= COALESCE(run_record.started_at, run_record.created_at)
         AND message.created_at <= DATE_ADD(
             COALESCE(run_record.finished_at, run_record.updated_at),
             INTERVAL 2 SECOND
         )
        WHERE run_record.assistant_message_id IS NULL
        GROUP BY run_record.id
    ) AS candidates
    WHERE candidates.candidate_count = 1
) AS matched ON matched.run_id = target.id
SET target.assistant_message_id = matched.assistant_message_id
WHERE target.assistant_message_id IS NULL;

ALTER TABLE platform_agent_settings
    MODIFY COLUMN initial_claim_amount DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN daily_claim_amount DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN per_run_limit DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN low_balance_threshold DECIMAL(20, 2) NOT NULL DEFAULT 0.00;

ALTER TABLE credit_accounts
    MODIFY COLUMN available_balance DECIMAL(20, 2) NOT NULL DEFAULT 0.00,
    MODIFY COLUMN reserved_balance DECIMAL(20, 2) NOT NULL DEFAULT 0.00;

ALTER TABLE credit_claim_records
    MODIFY COLUMN amount DECIMAL(20, 2) NOT NULL;

ALTER TABLE credit_ledger
    MODIFY COLUMN amount DECIMAL(20, 2) NOT NULL,
    MODIFY COLUMN available_after DECIMAL(20, 2) NOT NULL,
    MODIFY COLUMN reserved_after DECIMAL(20, 2) NOT NULL;

ALTER TABLE model_run_credentials
    MODIFY COLUMN max_points DECIMAL(20, 2) NOT NULL,
    MODIFY COLUMN consumed_points DECIMAL(20, 2) NOT NULL DEFAULT 0.00;
-- END 028_credit_decimal_precision.sql

-- BEGIN 028_user_workspace_and_assets.sql
-- 028: User-owned workspaces, isolated run views and installable enterprise assets.

CREATE TABLE IF NOT EXISTS user_workspaces (
    id BIGINT NOT NULL AUTO_INCREMENT,
    workspace_key VARCHAR(32) NOT NULL,
    user_id INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ready',
    storage_path VARCHAR(500) NULL,
    quota_bytes BIGINT NOT NULL DEFAULT 0,
    used_bytes BIGINT NOT NULL DEFAULT 0,
    migration_status VARCHAR(30) NOT NULL DEFAULT 'not_required',
    last_accessed_at DATETIME NULL,
    is_deleted TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_user_workspaces_key (workspace_key),
    UNIQUE KEY uq_user_workspaces_user (user_id),
    KEY ix_user_workspaces_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS runtime_cells (
    id BIGINT NOT NULL AUTO_INCREMENT,
    workspace_id BIGINT NOT NULL,
    user_id INT NOT NULL,
    runtime_type VARCHAR(30) NOT NULL DEFAULT 'claude_code',
    sandbox_type VARCHAR(20) NOT NULL DEFAULT 'container',
    status VARCHAR(30) NOT NULL DEFAULT 'unprovisioned',
    container_name VARCHAR(200) NULL,
    image_ref VARCHAR(500) NULL,
    desired_config_hash VARCHAR(64) NULL,
    applied_config_hash VARCHAR(64) NULL,
    last_started_at DATETIME NULL,
    last_active_at DATETIME NULL,
    hibernated_at DATETIME NULL,
    last_error_code VARCHAR(100) NULL,
    last_error_message TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_runtime_cells_workspace (workspace_id),
    UNIQUE KEY uq_runtime_cells_user (user_id),
    KEY ix_runtime_cells_status (status),
    CONSTRAINT fk_runtime_cells_workspace FOREIGN KEY (workspace_id) REFERENCES user_workspaces(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workspace_execution_leases (
    workspace_id BIGINT NOT NULL,
    run_id VARCHAR(32) NULL,
    owner_id VARCHAR(100) NULL,
    fencing_token BIGINT NOT NULL DEFAULT 0,
    lease_until DATETIME(6) NOT NULL,
    heartbeat_at DATETIME(6) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id),
    KEY ix_workspace_execution_leases_run (run_id),
    KEY ix_workspace_execution_leases_until (lease_until),
    CONSTRAINT fk_workspace_execution_leases_workspace FOREIGN KEY (workspace_id) REFERENCES user_workspaces(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agents' AND COLUMN_NAME = 'workspace_id') = 0,
    'ALTER TABLE agents ADD COLUMN workspace_id BIGINT NULL AFTER user_id, ADD INDEX ix_agents_workspace_id (workspace_id), ADD CONSTRAINT fk_agents_workspace FOREIGN KEY (workspace_id) REFERENCES user_workspaces(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions' AND COLUMN_NAME = 'workspace_id') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN workspace_id BIGINT NULL AFTER user_id, ADD INDEX ix_agent_sessions_workspace_id (workspace_id), ADD CONSTRAINT fk_agent_sessions_workspace FOREIGN KEY (workspace_id) REFERENCES user_workspaces(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_runs' AND COLUMN_NAME = 'workspace_id') = 0,
    'ALTER TABLE agent_runs ADD COLUMN workspace_id BIGINT NULL AFTER user_id, ADD INDEX ix_agent_runs_workspace_id (workspace_id), ADD CONSTRAINT fk_agent_runs_workspace FOREIGN KEY (workspace_id) REFERENCES user_workspaces(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

INSERT IGNORE INTO user_workspaces (workspace_key, user_id, status, migration_status)
SELECT REPLACE(UUID(), '-', ''), source.user_id, 'ready', 'pending'
FROM (SELECT DISTINCT user_id FROM agents WHERE user_id > 0) AS source;

UPDATE agents a
JOIN user_workspaces w ON w.user_id = a.user_id
SET a.workspace_id = w.id
WHERE a.workspace_id IS NULL;

UPDATE agent_sessions s
JOIN user_workspaces w ON w.user_id = s.user_id
SET s.workspace_id = w.id
WHERE s.workspace_id IS NULL;

UPDATE agent_runs r
JOIN user_workspaces w ON w.user_id = r.user_id
SET r.workspace_id = w.id
WHERE r.workspace_id IS NULL;

INSERT IGNORE INTO runtime_cells (
    workspace_id, user_id, runtime_type, sandbox_type, status
)
SELECT w.id, w.user_id, 'claude_code', 'container', 'unprovisioned'
FROM user_workspaces w
WHERE w.is_deleted = 0;

-- Match the existing parent column, including databases initialized by SQL or ORM.
SET @workspace_run_id_definition = (
    SELECT CONCAT(COLUMN_TYPE, ' CHARACTER SET ', CHARACTER_SET_NAME,
                  ' COLLATE ', COLLATION_NAME, ' NOT NULL')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'agent_runs'
      AND COLUMN_NAME = 'id'
);
SET @workspace_run_views_sql = CONCAT(
    'CREATE TABLE IF NOT EXISTS workspace_run_views (
    id BIGINT NOT NULL AUTO_INCREMENT,
    run_id ',
    @workspace_run_id_definition,
    ',
    workspace_id BIGINT NOT NULL,
    agent_id INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT ''preparing'',
    host_path VARCHAR(500) NULL,
    sandbox_ref VARCHAR(300) NULL,
    config_hash VARCHAR(64) NULL,
    cleanup_status VARCHAR(20) NOT NULL DEFAULT ''pending'',
    prepared_at DATETIME NULL,
    cleaned_at DATETIME NULL,
    last_error TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_workspace_run_views_run (run_id),
    KEY ix_workspace_run_views_workspace (workspace_id),
    KEY ix_workspace_run_views_agent (agent_id),
    KEY ix_workspace_run_views_status (status),
    CONSTRAINT fk_workspace_run_views_run FOREIGN KEY (run_id) REFERENCES agent_runs(id),
    CONSTRAINT fk_workspace_run_views_workspace FOREIGN KEY (workspace_id) REFERENCES user_workspaces(id),
    CONSTRAINT fk_workspace_run_views_agent FOREIGN KEY (agent_id) REFERENCES agents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;'
);
PREPARE workspace_run_views_stmt FROM @workspace_run_views_sql;
EXECUTE workspace_run_views_stmt;
DEALLOCATE PREPARE workspace_run_views_stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'skill_releases' AND COLUMN_NAME = 'content_sha256') = 0,
    'ALTER TABLE skill_releases ADD COLUMN content_sha256 VARCHAR(64) NULL AFTER file_url, ADD INDEX ix_skill_releases_content_sha256 (content_sha256), ADD COLUMN manifest_json LONGTEXT NULL AFTER content_sha256, ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT ''published'' AFTER manifest_json, ADD INDEX ix_skill_releases_status (status), ADD COLUMN scan_status VARCHAR(20) NOT NULL DEFAULT ''pending'' AFTER status, ADD COLUMN published_by INT NULL AFTER scan_status',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS skill_installations (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    workspace_id BIGINT NOT NULL,
    skill_id INT NOT NULL,
    release_id INT NOT NULL,
    previous_release_id INT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    granted_capabilities LONGTEXT NULL,
    installed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_skill_installations_user_skill (user_id, skill_id),
    KEY ix_skill_installations_workspace (workspace_id),
    KEY ix_skill_installations_release (release_id),
    KEY ix_skill_installations_status (status),
    CONSTRAINT fk_skill_installations_workspace FOREIGN KEY (workspace_id) REFERENCES user_workspaces(id),
    CONSTRAINT fk_skill_installations_skill FOREIGN KEY (skill_id) REFERENCES skills(id),
    CONSTRAINT fk_skill_installations_release FOREIGN KEY (release_id) REFERENCES skill_releases(id),
    CONSTRAINT fk_skill_installations_previous_release FOREIGN KEY (previous_release_id) REFERENCES skill_releases(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS expert_skill_bindings (
    id BIGINT NOT NULL AUTO_INCREMENT,
    agent_id INT NOT NULL,
    installation_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_expert_skill_binding (agent_id, installation_id),
    KEY ix_expert_skill_bindings_installation (installation_id),
    CONSTRAINT fk_expert_skill_bindings_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_expert_skill_bindings_installation FOREIGN KEY (installation_id) REFERENCES skill_installations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS credential_references (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    secret_encrypted LONGTEXT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    last_rotated_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_credential_references_user_name (user_id, name),
    KEY ix_credential_references_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcp_definitions (
    id BIGINT NOT NULL AUTO_INCREMENT,
    owner_user_id INT NULL,
    scope VARCHAR(20) NOT NULL DEFAULT 'user',
    name VARCHAR(100) NOT NULL,
    description TEXT NULL,
    transport_type VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    source_mcp_service_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_mcp_definitions_owner (owner_user_id),
    KEY ix_mcp_definitions_scope (scope),
    KEY ix_mcp_definitions_status (status),
    CONSTRAINT fk_mcp_definitions_source FOREIGN KEY (source_mcp_service_id) REFERENCES mcp_services(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcp_revisions (
    id BIGINT NOT NULL AUTO_INCREMENT,
    definition_id BIGINT NOT NULL,
    version INT NOT NULL,
    config_json LONGTEXT NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'published',
    created_by INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mcp_revision_definition_version (definition_id, version),
    KEY ix_mcp_revisions_content (content_sha256),
    KEY ix_mcp_revisions_status (status),
    CONSTRAINT fk_mcp_revisions_definition FOREIGN KEY (definition_id) REFERENCES mcp_definitions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcp_connections (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    workspace_id BIGINT NOT NULL,
    definition_id BIGINT NOT NULL,
    revision_id BIGINT NOT NULL,
    credential_reference_id BIGINT NULL,
    name VARCHAR(100) NOT NULL,
    config_overrides_json LONGTEXT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    last_tested_at DATETIME NULL,
    last_test_status VARCHAR(20) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mcp_connections_user_name (user_id, name),
    KEY ix_mcp_connections_workspace (workspace_id),
    KEY ix_mcp_connections_definition (definition_id),
    KEY ix_mcp_connections_revision (revision_id),
    KEY ix_mcp_connections_credential (credential_reference_id),
    KEY ix_mcp_connections_status (status),
    CONSTRAINT fk_mcp_connections_workspace FOREIGN KEY (workspace_id) REFERENCES user_workspaces(id),
    CONSTRAINT fk_mcp_connections_definition FOREIGN KEY (definition_id) REFERENCES mcp_definitions(id),
    CONSTRAINT fk_mcp_connections_revision FOREIGN KEY (revision_id) REFERENCES mcp_revisions(id),
    CONSTRAINT fk_mcp_connections_credential FOREIGN KEY (credential_reference_id) REFERENCES credential_references(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS expert_mcp_bindings (
    id BIGINT NOT NULL AUTO_INCREMENT,
    agent_id INT NOT NULL,
    connection_id BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_expert_mcp_binding (agent_id, connection_id),
    KEY ix_expert_mcp_bindings_connection (connection_id),
    CONSTRAINT fk_expert_mcp_bindings_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_expert_mcp_bindings_connection FOREIGN KEY (connection_id) REFERENCES mcp_connections(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prompt_templates' AND COLUMN_NAME = 'source_template_id') = 0,
    'ALTER TABLE prompt_templates ADD COLUMN source_template_id INT NULL AFTER is_public, ADD INDEX ix_prompt_templates_source_template (source_template_id), ADD COLUMN source_snapshot_hash VARCHAR(64) NULL AFTER source_template_id, ADD COLUMN imported_at DATETIME NULL AFTER source_snapshot_hash, ADD CONSTRAINT fk_prompt_templates_source FOREIGN KEY (source_template_id) REFERENCES prompt_templates(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
-- END 028_user_workspace_and_assets.sql

-- BEGIN 029_asset_security_policy.sql
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
-- END 029_asset_security_policy.sql

-- BEGIN 030_system_default_skills.sql
-- 030: Administrator-managed default skills shared by every user Runtime.

CREATE TABLE IF NOT EXISTS system_skill_installations (
    id BIGINT NOT NULL AUTO_INCREMENT,
    skill_id INT NOT NULL,
    release_id INT NOT NULL,
    previous_release_id INT NULL,
    granted_capabilities LONGTEXT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_by INT NOT NULL,
    installed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_system_skill_installations_skill (skill_id),
    KEY ix_system_skill_installations_release (release_id),
    KEY ix_system_skill_installations_status (status),
    KEY ix_system_skill_installations_created_by (created_by),
    CONSTRAINT fk_system_skill_installations_skill FOREIGN KEY (skill_id) REFERENCES skills(id),
    CONSTRAINT fk_system_skill_installations_release FOREIGN KEY (release_id) REFERENCES skill_releases(id),
    CONSTRAINT fk_system_skill_installations_previous_release FOREIGN KEY (previous_release_id) REFERENCES skill_releases(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- END 030_system_default_skills.sql

-- BEGIN 031_system_resources.sql
-- 031: Distinguish administrator-managed prompts from user marketplace shares.

SET @has_prompt_system = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prompt_templates'
      AND COLUMN_NAME = 'is_system'
);
SET @prompt_system_sql = IF(
    @has_prompt_system = 0,
    'ALTER TABLE prompt_templates ADD COLUMN is_system TINYINT(1) NOT NULL DEFAULT 0 AFTER is_public, ADD INDEX ix_prompt_templates_is_system (is_system)',
    'SELECT 1'
);
PREPARE prompt_system_stmt FROM @prompt_system_sql;
EXECUTE prompt_system_stmt;
DEALLOCATE PREPARE prompt_system_stmt;
-- END 031_system_resources.sql

-- BEGIN 032_assistant_identity_icon.sql
-- 032: Make the published assistant icon configurable.

SET @has_assistant_icon = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'platform_agent_settings'
      AND COLUMN_NAME = 'assistant_icon'
);
SET @assistant_icon_sql = IF(
    @has_assistant_icon = 0,
    "ALTER TABLE platform_agent_settings ADD COLUMN assistant_icon VARCHAR(50) NOT NULL DEFAULT 'H' AFTER assistant_name",
    'SELECT 1'
);
PREPARE assistant_icon_stmt FROM @assistant_icon_sql;
EXECUTE assistant_icon_stmt;
DEALLOCATE PREPARE assistant_icon_stmt;
-- END 032_assistant_identity_icon.sql

-- BEGIN 033_platform_global_settings.sql
-- 033: Add singleton platform branding settings for the application shell.

CREATE TABLE IF NOT EXISTS platform_global_settings (
    id INT NOT NULL DEFAULT 1,
    brand_icon VARCHAR(50) NOT NULL DEFAULT 'H',
    brand_name VARCHAR(100) NOT NULL DEFAULT 'AI Hub',
    brand_subtitle VARCHAR(100) NOT NULL DEFAULT '合趣网络',
    updated_by INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- END 033_platform_global_settings.sql

-- BEGIN 034_workspace_prompt_removals.sql
-- Workbench removal is a user preference, not a source-template deletion.
CREATE TABLE IF NOT EXISTS workspace_prompt_removals (
    user_id INT NOT NULL,
    template_id INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, template_id),
    CONSTRAINT fk_workspace_prompt_removal_template
        FOREIGN KEY (template_id) REFERENCES prompt_templates(id)
);
-- END 034_workspace_prompt_removals.sql
