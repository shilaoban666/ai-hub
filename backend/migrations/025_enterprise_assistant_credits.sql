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
