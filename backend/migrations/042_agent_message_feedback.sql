-- Feedback on individual assistant replies, associated with the owning conversation.
CREATE TABLE IF NOT EXISTS agent_message_feedback (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    message_id INT NOT NULL,
    user_id INT NOT NULL,
    username VARCHAR(200) NOT NULL DEFAULT '',
    display_name VARCHAR(200) NOT NULL DEFAULT '',
    session_title VARCHAR(200) NOT NULL DEFAULT '未命名对话',
    rating VARCHAR(10) NOT NULL,
    reasons TEXT NOT NULL,
    comment VARCHAR(2000) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_feedback_user_message (user_id, message_id),
    KEY ix_agent_message_feedback_session_id (session_id),
    KEY ix_agent_message_feedback_message_id (message_id),
    KEY ix_agent_message_feedback_user_id (user_id),
    KEY ix_agent_message_feedback_rating (rating),
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id),
    FOREIGN KEY (message_id) REFERENCES agent_messages(id)
);
