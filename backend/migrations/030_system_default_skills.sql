-- 030: Administrator-managed default skills shared by every user Runtime.

CREATE TABLE IF NOT EXISTS system_skill_installations (
    id BIGINT NOT NULL AUTO_INCREMENT,
    skill_id INT NOT NULL,
    release_id INT NOT NULL,
    previous_release_id INT NULL,
    granted_capabilities LONGTEXT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_by INT NOT NULL,
    installed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_system_skill_installations_skill (skill_id),
    KEY ix_system_skill_installations_release (release_id),
    KEY ix_system_skill_installations_status (status),
    KEY ix_system_skill_installations_created_by (created_by),
    CONSTRAINT fk_system_skill_installations_skill FOREIGN KEY (skill_id) REFERENCES skills(id),
    CONSTRAINT fk_system_skill_installations_release FOREIGN KEY (release_id) REFERENCES skill_releases(id),
    CONSTRAINT fk_system_skill_installations_previous_release FOREIGN KEY (previous_release_id) REFERENCES skill_releases(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
