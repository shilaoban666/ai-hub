-- Git 仓库绑定功能：为 skills 表添加 Git 相关字段
-- 执行方式：mysql -u root -p aihub < add_git_fields.sql

ALTER TABLE skills ADD COLUMN git_provider VARCHAR(20) DEFAULT 'gitlab' COMMENT '服务商类型: gitlab/github等';
ALTER TABLE skills ADD COLUMN git_repo_url VARCHAR(500) DEFAULT NULL COMMENT '绑定的 Git 仓库地址';
ALTER TABLE skills ADD COLUMN git_branch VARCHAR(100) DEFAULT 'main' COMMENT '分支名';
ALTER TABLE skills ADD COLUMN git_access_token VARCHAR(200) DEFAULT NULL COMMENT 'Personal Access Token';
ALTER TABLE skills ADD COLUMN git_last_synced_at DATETIME DEFAULT NULL COMMENT '最后一次同步时间';
ALTER TABLE skills ADD COLUMN git_sync_status VARCHAR(20) DEFAULT NULL COMMENT '同步状态: never/synced/syncing/error';
ALTER TABLE skills ADD COLUMN git_last_commit_sha VARCHAR(40) DEFAULT NULL COMMENT '最后一次同步的 commit SHA';
