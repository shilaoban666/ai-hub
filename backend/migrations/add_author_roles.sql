-- 添加作者和适用岗位字段
ALTER TABLE skills ADD COLUMN author VARCHAR(100) AFTER description;
ALTER TABLE skills ADD COLUMN roles VARCHAR(500) AFTER author;

-- 更新现有数据的默认值
UPDATE skills SET author = '系统管理员' WHERE author IS NULL;
UPDATE skills SET roles = '通用' WHERE roles IS NULL;
