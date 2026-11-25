# feature/0928 历史入口

本分支 044～056 的 7 个 SQL、6 个 Python 迁移已统一收录到 [当前上线说明](README.md)。`feature/1014` 延续同一组迁移，无需维护第二套文件。

推荐使用 `python backend/migrations/run_upgrade.py`。原 `run_feature_0928.py` 保留兼容，支持相同的离线预览、`--apply`、`--check`、`--from`，执行相同清单。

完整顺序、上线操作、失败续跑、验收及历史基线边界均以 [README.md](README.md) 为准。
