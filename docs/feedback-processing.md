# 反馈分配与处理

- 超级管理员：分配处理人、编辑处理状态、截图、备注。
- 当前被分配处理人：处理反馈，不能重新分配。
- 反馈人：查看处理结果；非管理员且非当前处理人不能修改。
- 点赞无需处理。

前端复用现有 `PATCH /api/feedback/{id}/processing`，分配传 `action=assignment`，处理传 `processing_status`、`processing_remark`、`processing_images`。截图通过现有图片上传接口（purpose=feedback）上传到 OSS，数据库仅保存返回的 HTTPS URL，最多 10 张、每张 3MB，支持在处理弹窗内直接粘贴图片（Ctrl+V）。

通知复用 IAM 已注册路径 `/api/notifications/feedback-assignment`：分配事件维持原协议；完成事件传 `event=resolved`。仅从其他状态变为 resolved 时通知反馈人，重复保存不通知。通知失败回滚本次反馈变更；IAM 按事件标识去重。取消分配关闭旧处理人的待办，重新分配通知新处理人。

## 启用

1. AI Hub 数据库执行 `backend/migrations/061_feedback_processing_details.sql`，仅添加可空 TEXT 字段 `processing_remark`、`processing_images`，可重复执行。统一升级入口支持 `python backend/migrations/run_upgrade.py --from 061 --apply`；该入口会核验完整升级基线。
2. 发布本次 IAM 通知修改。配置 `AIHUB_GATEWAY_BASE_URL` 为 IAM 可访问的可信网关地址，本地默认 `http://127.0.0.1:8080`。IAM 会使用处理人当前 Bearer Token 回查反馈归属，禁止使用请求中的任意地址作为回查目标。
3. 重启 IAM 和 AI Hub 后端，发布前端。
4. 先分配、再由处理人打开通知链接处理；标记已处理后由反馈人查看通知与详情。

本地当前配置连接远程 `106.15.224.155/aihub`，不是隔离本机数据库。2026-11-11 经用户确认，已应用 061 迁移并重启本地 AI Hub、IAM；实际反馈查询已可读取新字段。未向真实用户发送验证通知，线上发布需同步部署 AI Hub 与 IAM。

反馈图片复用现有 OSS_ACCESS_KEY_ID、OSS_ACCESS_KEY_SECRET、OSS_BUCKET、OSS_ENDPOINT、OSS_PUBLIC_ENDPOINT 配置，独立目录由 OSS_FEEDBACK_IMAGE_PREFIX 配置，默认 feedback/images。旧的本地截图地址继续支持查看，本次不自动迁移旧图片。
