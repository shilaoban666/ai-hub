-- 为 ai_models 表添加 remarks（备注）字段，用于区分同名模型的不同来源
-- 执行方式：mysql -u root -p aihub < add_ai_models_remarks.sql

ALTER TABLE ai_models
    ADD COLUMN remarks VARCHAR(200) DEFAULT NULL COMMENT '备注，用于区分同名模型的不同来源（如 deepseek-v4-pro 是官方还是火山）'
    AFTER description;
