-- Resume only when the full upgrade stopped at CREATE TABLE workspace_run_views.
-- Select the same target database. Earlier statements must have succeeded.
-- Run this entire file in one connection; stop on any error.
-- The run_id definition is read from agent_runs.id; the parent table is unchanged.
-- This includes the failed CREATE TABLE and all remaining upgrade statements.
-- Do not execute both this continuation and the same remaining part of the bundle.

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
