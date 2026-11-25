-- 为 prompt_templates 表补充 is_public（公开/私有）与 author（作者）字段
-- 执行方式：mysql -u root -p aihub < add_prompt_templates_public_author.sql

ALTER TABLE prompt_templates
    ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT 0 COMMENT '是否公开' AFTER is_deleted;

ALTER TABLE prompt_templates
    ADD COLUMN author VARCHAR(100) DEFAULT NULL COMMENT '作者（创建时由后端按登录用户自动写入）' AFTER description;
