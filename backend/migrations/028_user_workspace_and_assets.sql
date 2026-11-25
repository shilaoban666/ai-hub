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
