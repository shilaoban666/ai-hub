-- 008: Agent runtime 支持
-- 为智能体添加 runtime_type 字段

ALTER TABLE agents
    ADD COLUMN runtime_type VARCHAR(30) NOT NULL DEFAULT 'claude_code'
    COMMENT 'runtime 类型: claude_code | openclaw';

-- 为 agent_sessions 添加 runtime_session_id 字段（存储 Claude Code 的 session_id 等）
ALTER TABLE agent_sessions
    ADD COLUMN runtime_session_id VARCHAR(200) DEFAULT NULL
    COMMENT 'runtime 内部会话 ID（用于 --resume 等）';
