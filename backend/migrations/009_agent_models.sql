-- 009: Agent ↔ Model 多对多关联表
-- 支持一个智能体绑定多个 AI 模型

CREATE TABLE IF NOT EXISTS agent_models (
    agent_id INT NOT NULL,
    model_id INT NOT NULL,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (agent_id, model_id),
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    FOREIGN KEY (model_id) REFERENCES ai_models(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体与AI模型多对多关联';

-- 迁移现有数据：将 agents.default_model_id 写入 agent_models
INSERT INTO agent_models (agent_id, model_id, added_at)
SELECT id, default_model_id, NOW()
FROM agents
WHERE default_model_id IS NOT NULL
  AND is_deleted = 0
  AND NOT EXISTS (
    SELECT 1 FROM agent_models
    WHERE agent_models.agent_id = agents.id
      AND agent_models.model_id = agents.default_model_id
  );
