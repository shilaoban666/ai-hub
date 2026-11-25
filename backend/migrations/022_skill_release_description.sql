-- 022: Optional release notes shown in skill release history.

ALTER TABLE skill_releases
    ADD COLUMN description TEXT NULL AFTER version;
