-- ============================================================
-- Channel 相关表 DDL（可独立执行）
--
-- 前置条件：以下表必须已存在
--   agents, agent_sessions, agent_messages
--
-- 循环外键处理：
--   1. agent_channel_bindings ↔ channel_conversations
--      → agent_channel_bindings 的 FK 推迟到 ALTER TABLE
--   2. channel_messages ↔ agent_runs
--      → channel_messages 的 FK 推迟到 ALTER TABLE
-- ============================================================

-- -----------------------------------------------------------
-- 1. agent_channel_bindings（agent ←→ 渠道一对一绑定）
--    注意：active_conversation_id 的外键在最后 ALTER TABLE 补上
-- -----------------------------------------------------------
DROP TABLE IF EXISTS agent_channel_bindings;
CREATE TABLE agent_channel_bindings (
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

-- -----------------------------------------------------------
-- 2. channel_bind_sessions（短期 QR 绑定会话）
-- -----------------------------------------------------------
DROP TABLE IF EXISTS channel_bind_sessions;
CREATE TABLE channel_bind_sessions (
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
    poll_interval_seconds INT NULL COMMENT 'provider minimum QR poll interval',
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

-- -----------------------------------------------------------
-- 3. channel_pairing_attempts（每次配对失败计数）
-- -----------------------------------------------------------
DROP TABLE IF EXISTS channel_pairing_attempts;
CREATE TABLE channel_pairing_attempts (
    bind_session_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    sender_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (bind_session_id, sender_hash),
    CONSTRAINT fk_channel_pairing_attempts_bind_session
        FOREIGN KEY (bind_session_id) REFERENCES channel_bind_sessions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='per-sender pairing failure counters';

-- -----------------------------------------------------------
-- 4. channel_conversations（渠道用户 ←→ AgentSession 映射）
-- -----------------------------------------------------------
DROP TABLE IF EXISTS channel_conversations;
CREATE TABLE channel_conversations (
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

-- -----------------------------------------------------------
-- 5. channel_messages（入站/出站消息持久化）
--    注意：agent_run_id 的外键在最后 ALTER TABLE 补上
-- -----------------------------------------------------------
DROP TABLE IF EXISTS channel_messages;
CREATE TABLE channel_messages (
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

-- -----------------------------------------------------------
-- 6. agent_runs（持久化执行队列与生命周期）
-- -----------------------------------------------------------
DROP TABLE IF EXISTS agent_runs;
CREATE TABLE agent_runs (
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
    duration_ms BIGINT NULL,
    input_tokens BIGINT NULL,
    output_tokens BIGINT NULL,
    cache_read_tokens BIGINT NULL,
    cache_creation_tokens BIGINT NULL,
    total_tokens BIGINT NULL,
    usage_detail LONGTEXT NULL,
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

-- -----------------------------------------------------------
-- 7. channel_outbox（可靠投递队列）
-- -----------------------------------------------------------
DROP TABLE IF EXISTS channel_outbox;
CREATE TABLE channel_outbox (
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

-- ============================================================
-- 推迟的外键（解决循环依赖）
-- ============================================================

-- A. channel_messages.agent_run_id → agent_runs.id
--    与 agent_runs.source_message_id → channel_messages.id 形成循环
ALTER TABLE channel_messages
    ADD CONSTRAINT fk_channel_messages_agent_run
    FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id);

-- B. agent_channel_bindings.active_conversation_id → channel_conversations.id
--    与 channel_conversations.binding_id → agent_channel_bindings.id 形成循环
ALTER TABLE agent_channel_bindings
    ADD CONSTRAINT fk_agent_channel_bindings_active_conversation
    FOREIGN KEY (active_conversation_id) REFERENCES channel_conversations(id);

-- C. agent_sessions.source_binding_id → agent_channel_bindings.id
--    agent_sessions 在 011 迁移中已添加 source_binding_id 列，此处补外键
--    如果 agent_sessions 还没有 source_binding_id 列，先执行:
--    ALTER TABLE agent_sessions ADD COLUMN source_binding_id BIGINT NULL COMMENT 'originating agent_channel_bindings row';
--    ALTER TABLE agent_sessions ADD INDEX idx_agent_sessions_source_binding (source_binding_id);
ALTER TABLE agent_sessions
    ADD CONSTRAINT fk_agent_sessions_source_binding
    FOREIGN KEY (source_binding_id) REFERENCES agent_channel_bindings(id);
