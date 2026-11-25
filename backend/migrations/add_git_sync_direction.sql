-- 为 skills 表添加 git_sync_direction 字段
-- 0=不同步, 1=git→本地, 2=本地→git
ALTER TABLE skills ADD COLUMN git_sync_direction INT NOT NULL DEFAULT 0 COMMENT '同步方向: 0=不同步, 1=git→本地, 2=本地→git';
