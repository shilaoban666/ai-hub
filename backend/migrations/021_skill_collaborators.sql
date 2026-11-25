-- 021: Users who can manage a skill without owning or deleting it.

CREATE TABLE IF NOT EXISTS skill_collaborators (
    id INT NOT NULL AUTO_INCREMENT,
    skill_id INT NOT NULL,
    user_id INT NOT NULL,
    username VARCHAR(100) NOT NULL,
    created_by INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_skill_collaborators_skill_user (skill_id, user_id),
    KEY idx_skill_collaborators_skill_id (skill_id),
    KEY idx_skill_collaborators_user_id (user_id),
    CONSTRAINT fk_skill_collaborators_skill
        FOREIGN KEY (skill_id) REFERENCES skills(id)
) COMMENT='users allowed to manage a skill';
