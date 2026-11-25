-- 020: Revocable public links for Agent conversation sessions.

CREATE TABLE IF NOT EXISTS agent_conversation_shares (
    id BIGINT NOT NULL AUTO_INCREMENT,
    session_id INT NOT NULL,
    agent_id INT NOT NULL,
    user_id INT NOT NULL,
    token VARCHAR(64) NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_agent_conversation_shares_token (token),
    KEY idx_agent_conversation_shares_session_id (session_id),
    KEY idx_agent_conversation_shares_agent_id (agent_id),
    KEY idx_agent_conversation_shares_user_id (user_id),
    KEY idx_agent_conversation_shares_is_active (is_active),
    CONSTRAINT fk_agent_conversation_shares_session
        FOREIGN KEY (session_id) REFERENCES agent_sessions(id),
    CONSTRAINT fk_agent_conversation_shares_agent
        FOREIGN KEY (agent_id) REFERENCES agents(id)
) COMMENT='revocable public links for Agent conversations';
