-- 011: Weixin ClawBot channel binding, durable inbox/run/outbox, and session source.
-- New channel records are retained for audit; foreign keys intentionally do not cascade.

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions'
       AND COLUMN_NAME = 'source') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN source VARCHAR(30) NOT NULL DEFAULT ''web'' COMMENT ''session source: web | weixin_clawbot''',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions'
       AND COLUMN_NAME = 'source_binding_id') = 0,
    'ALTER TABLE agent_sessions ADD COLUMN source_binding_id BIGINT NULL COMMENT ''originating agent_channel_bindings row''',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions'
       AND INDEX_NAME = 'idx_agent_sessions_source_binding') = 0,
    'ALTER TABLE agent_sessions ADD INDEX idx_agent_sessions_source_binding (source_binding_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS agent_channel_bindings (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    agent_id INT NOT NULL,
    provider VARCHAR(30) NOT NULL DEFAULT 'weixin_ilink',
    display_name VARCHAR(100) NOT NULL DEFAULT '微信ClawBot',
    provider_bot_id VARCHAR(200) NULL,
    provider_account_id VARCHAR(200) NULL,
    access_token_encrypted TEXT NULL,
    credential_key_version VARCHAR(50) NULL,
    api_base_url VARCHAR(500) NULL,
    active_conversation_id BIGINT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'unbound',
    poll_cursor LONGTEXT NULL,
    poller_owner VARCHAR(100) NULL,
    poller_lease_until DATETIME NULL,
    poller_fencing_token BIGINT NOT NULL DEFAULT 0,
    token_expires_at DATETIME NULL,
    last_poll_at DATETIME NULL,
    last_inbound_at DATETIME NULL,
    last_outbound_at DATETIME NULL,
    last_error_code VARCHAR(100) NULL,
    last_error_message TEXT NULL,
    bound_at DATETIME NULL,
    revoked_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    version INT NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    UNIQUE KEY uq_agent_channel_bindings_agent_id (agent_id),
    UNIQUE KEY uq_agent_channel_bindings_provider_bot (provider, provider_bot_id),
    UNIQUE KEY uq_agent_channel_bindings_active_conversation (active_conversation_id),
    KEY idx_agent_channel_bindings_user_id (user_id),
    KEY idx_agent_channel_bindings_poller (status, poller_lease_until),
    CONSTRAINT fk_agent_channel_bindings_agent
        FOREIGN KEY (agent_id) REFERENCES agents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='one stable Weixin bot binding per agent';

CREATE TABLE IF NOT EXISTS channel_bind_sessions (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    binding_id BIGINT NOT NULL,
    initiated_by_user_id INT NOT NULL,
    idempotency_key VARCHAR(100) NULL,
    state_hash VARCHAR(128) NOT NULL,
    provider_qr_id VARCHAR(200) NULL,
    qr_content_encrypted LONGTEXT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'created',
    expires_at DATETIME NOT NULL,
    scanned_at DATETIME NULL,
    confirmed_at DATETIME NULL,
    cancelled_at DATETIME NULL,
    pairing_attempt_count INT NOT NULL DEFAULT 0,
    poller_owner VARCHAR(100) NULL,
    poller_lease_until DATETIME NULL,
    poller_fencing_token BIGINT NOT NULL DEFAULT 0,
    error_code VARCHAR(100) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_channel_bind_sessions_idempotency
        (binding_id, initiated_by_user_id, idempotency_key),
    KEY idx_channel_bind_sessions_binding_id (binding_id),
    KEY idx_channel_bind_sessions_user_id (initiated_by_user_id),
    KEY idx_channel_bind_sessions_due (status, expires_at),
    KEY idx_channel_bind_sessions_poller (status, poller_lease_until),
    CONSTRAINT fk_channel_bind_sessions_binding
        FOREIGN KEY (binding_id) REFERENCES agent_channel_bindings(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='short-lived Weixin QR binding attempts';

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'channel_bind_sessions'
       AND COLUMN_NAME = 'poller_owner') = 0,
    'ALTER TABLE channel_bind_sessions ADD COLUMN poller_owner VARCHAR(100) NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'channel_bind_sessions'
       AND COLUMN_NAME = 'poller_lease_until') = 0,
    'ALTER TABLE channel_bind_sessions ADD COLUMN poller_lease_until DATETIME NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'channel_bind_sessions'
       AND COLUMN_NAME = 'poller_fencing_token') = 0,
    'ALTER TABLE channel_bind_sessions ADD COLUMN poller_fencing_token BIGINT NOT NULL DEFAULT 0',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'channel_bind_sessions'
       AND COLUMN_NAME = 'pairing_attempt_count') = 0,
    'ALTER TABLE channel_bind_sessions ADD COLUMN pairing_attempt_count INT NOT NULL DEFAULT 0',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'channel_bind_sessions'
       AND INDEX_NAME = 'idx_channel_bind_sessions_poller') = 0,
    'ALTER TABLE channel_bind_sessions ADD INDEX idx_channel_bind_sessions_poller (status, poller_lease_until)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS channel_conversations (
    id BIGINT NOT NULL AUTO_INCREMENT,
    binding_id BIGINT NOT NULL,
    external_wechat_user_id_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    external_wechat_user_id_encrypted TEXT NOT NULL,
    external_user_hash_key_version VARCHAR(50) NOT NULL,
    agent_session_id INT NOT NULL,
    latest_context_token_encrypted TEXT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    closed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_channel_conversations_agent_session_id (agent_session_id),
    KEY idx_channel_conversations_binding_id (binding_id),
    KEY idx_channel_conversations_binding_status (binding_id, status),
    CONSTRAINT fk_channel_conversations_binding
        FOREIGN KEY (binding_id) REFERENCES agent_channel_bindings(id),
    CONSTRAINT fk_channel_conversations_agent_session
        FOREIGN KEY (agent_session_id) REFERENCES agent_sessions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='historical Weixin identity and AgentSession mappings';

CREATE TABLE IF NOT EXISTS channel_messages (
    id BIGINT NOT NULL AUTO_INCREMENT,
    binding_id BIGINT NOT NULL,
    conversation_id BIGINT NOT NULL,
    agent_session_id INT NOT NULL,
    agent_message_id INT NULL,
    agent_run_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    direction VARCHAR(10) NOT NULL,
    provider_message_id VARCHAR(200) NULL,
    client_message_id VARCHAR(100) NULL,
    message_type VARCHAR(30) NOT NULL,
    content LONGTEXT NULL,
    raw_payload_encrypted LONGTEXT NULL,
    context_token_encrypted TEXT NULL,
    status VARCHAR(30) NOT NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    next_attempt_at DATETIME NULL,
    error_code VARCHAR(100) NULL,
    error_message TEXT NULL,
    provider_created_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_channel_messages_provider_message
        (binding_id, direction, provider_message_id),
    UNIQUE KEY uq_channel_messages_client_message (binding_id, client_message_id),
    KEY idx_channel_messages_binding_id (binding_id),
    KEY idx_channel_messages_conversation_id (conversation_id),
    KEY idx_channel_messages_agent_session_id (agent_session_id),
    KEY idx_channel_messages_agent_message_id (agent_message_id),
    KEY idx_channel_messages_agent_run_id (agent_run_id),
    KEY idx_channel_messages_retry (status, next_attempt_at),
    CONSTRAINT fk_channel_messages_binding
        FOREIGN KEY (binding_id) REFERENCES agent_channel_bindings(id),
    CONSTRAINT fk_channel_messages_conversation
        FOREIGN KEY (conversation_id) REFERENCES channel_conversations(id),
    CONSTRAINT fk_channel_messages_agent_session
        FOREIGN KEY (agent_session_id) REFERENCES agent_sessions(id),
    CONSTRAINT fk_channel_messages_agent_message
        FOREIGN KEY (agent_message_id) REFERENCES agent_messages(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='durable Weixin inbox and outbound message records';

CREATE TABLE IF NOT EXISTS agent_runs (
    id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    agent_id INT NOT NULL,
    session_id INT NOT NULL,
    user_id INT NOT NULL,
    source VARCHAR(30) NOT NULL DEFAULT 'web',
    source_message_id BIGINT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    worker_id VARCHAR(100) NULL,
    lease_until DATETIME NULL,
    heartbeat_at DATETIME NULL,
    deadline_at DATETIME NULL,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    config_snapshot LONGTEXT NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    error_code VARCHAR(100) NULL,
    error_message TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_agent_runs_source_message_id (source_message_id),
    KEY idx_agent_runs_agent_id (agent_id),
    KEY idx_agent_runs_session_id (session_id),
    KEY idx_agent_runs_user_id (user_id),
    KEY idx_agent_runs_claim (status, lease_until, created_at),
    CONSTRAINT fk_agent_runs_agent
        FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_agent_runs_session
        FOREIGN KEY (session_id) REFERENCES agent_sessions(id),
    CONSTRAINT fk_agent_runs_source_message
        FOREIGN KEY (source_message_id) REFERENCES channel_messages(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='persistent agent execution queue and lifecycle';

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
     WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'channel_messages'
       AND CONSTRAINT_NAME = 'fk_channel_messages_agent_run') = 0,
    'ALTER TABLE channel_messages ADD CONSTRAINT fk_channel_messages_agent_run FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS channel_outbox (
    id BIGINT NOT NULL AUTO_INCREMENT,
    binding_id BIGINT NOT NULL,
    run_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    channel_message_id BIGINT NOT NULL,
    part_no INT NOT NULL DEFAULT 0,
    payload LONGTEXT NOT NULL,
    context_token_encrypted TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    attempt_count INT NOT NULL DEFAULT 0,
    next_attempt_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_owner VARCHAR(100) NULL,
    lease_until DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_channel_outbox_channel_message_id (channel_message_id),
    UNIQUE KEY uq_channel_outbox_run_part (run_id, part_no),
    KEY idx_channel_outbox_binding_id (binding_id),
    KEY idx_channel_outbox_run_id (run_id),
    KEY idx_channel_outbox_claim (status, next_attempt_at, lease_until),
    CONSTRAINT fk_channel_outbox_binding
        FOREIGN KEY (binding_id) REFERENCES agent_channel_bindings(id),
    CONSTRAINT fk_channel_outbox_run
        FOREIGN KEY (run_id) REFERENCES agent_runs(id),
    CONSTRAINT fk_channel_outbox_channel_message
        FOREIGN KEY (channel_message_id) REFERENCES channel_messages(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='reliable Weixin outbound delivery queue';

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
     WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_channel_bindings'
       AND CONSTRAINT_NAME = 'fk_agent_channel_bindings_active_conversation') = 0,
    'ALTER TABLE agent_channel_bindings ADD CONSTRAINT fk_agent_channel_bindings_active_conversation FOREIGN KEY (active_conversation_id) REFERENCES channel_conversations(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
    (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
     WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'agent_sessions'
       AND CONSTRAINT_NAME = 'fk_agent_sessions_source_binding') = 0,
    'ALTER TABLE agent_sessions ADD CONSTRAINT fk_agent_sessions_source_binding FOREIGN KEY (source_binding_id) REFERENCES agent_channel_bindings(id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
