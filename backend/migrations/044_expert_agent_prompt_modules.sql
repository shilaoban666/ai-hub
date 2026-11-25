-- 044: Prompt modules bound to expert agents.
CREATE TABLE IF NOT EXISTS agent_prompt_templates (
    agent_id INT NOT NULL,
    prompt_template_id INT NOT NULL,
    position INT NOT NULL DEFAULT 0,
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (agent_id, prompt_template_id),
    KEY ix_agent_prompt_templates_position (agent_id, position),
    CONSTRAINT fk_agent_prompt_templates_agent
        FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_agent_prompt_templates_prompt
        FOREIGN KEY (prompt_template_id) REFERENCES prompt_templates(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
