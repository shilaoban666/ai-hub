-- 工具调用日志表（审计和排查问题）
CREATE TABLE IF NOT EXISTS tool_call_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    workspace_id INT NOT NULL,
    session_id INT NOT NULL,
    user_id INT NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    tool_args JSON,
    tool_result TEXT,
    status ENUM('success', 'error') NOT NULL,
    error_message TEXT,
    execution_time_ms INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_workspace (workspace_id),
    INDEX idx_session (session_id),
    INDEX idx_user (user_id),
    INDEX idx_created (created_at),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
