-- Workbench removal is a user preference, not a source-template deletion.
CREATE TABLE IF NOT EXISTS workspace_prompt_removals (
    user_id INT NOT NULL,
    template_id INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, template_id),
    CONSTRAINT fk_workspace_prompt_removal_template
        FOREIGN KEY (template_id) REFERENCES prompt_templates(id)
);
