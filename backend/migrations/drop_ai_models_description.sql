-- 删除 ai_models 表的 description 字段（已被 remarks 替代）
-- 执行方式：mysql -u root -p aihub < drop_ai_models_description.sql

ALTER TABLE ai_models
    DROP COLUMN description;
