-- Stop legacy private/deleted global skills; never publish authors' skills implicitly.
-- Run during deployment with skill installation and visibility writes paused.
UPDATE system_skill_installations AS installation
JOIN skills AS skill ON skill.id = installation.skill_id
SET installation.status = 'uninstalled', installation.updated_at = CURRENT_TIMESTAMP
WHERE installation.status = 'active'
  AND (skill.is_public = 0 OR skill.is_deleted = 1);
