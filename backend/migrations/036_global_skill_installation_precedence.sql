-- Run during deployment with skill installation writes paused.
-- Global installations replace all personal versions, including expert bindings.
-- Keep installation history; uninstalling the global version must not revive it.
START TRANSACTION;

DELETE binding
FROM expert_skill_bindings AS binding
JOIN skill_installations AS personal ON personal.id = binding.installation_id
JOIN system_skill_installations AS global_install ON global_install.skill_id = personal.skill_id
WHERE global_install.status = 'active';

UPDATE skill_installations AS personal
JOIN system_skill_installations AS global_install ON global_install.skill_id = personal.skill_id
SET personal.status = 'uninstalled', personal.updated_at = CURRENT_TIMESTAMP
WHERE global_install.status = 'active' AND personal.status <> 'uninstalled';

COMMIT;
