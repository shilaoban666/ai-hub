# 对话图片 OSS 存储

对话输入框粘贴或选择 PNG、JPEG、GIF、WebP 图片时，前端通过已认证的
`POST /api/agents/{agent_id}/images/upload` 上传，表单字段为 `file`。
后端检查智能体访问权限、图片格式和 5 MB 大小限制，再直接写入 OSS。
普通附件继续通过原工作区上传接口保存。

后端环境配置参见根目录 `.env.example` 的 `OSS_*` 字段。实际密钥仅放在部署环境变量
或被 Git 忽略的 `.env` 中，不能写入前端变量或提交到仓库。部署脚本若用其他环境文件
替换 `.env`，需在该环境同步配置这组后端变量。

- Bucket：`fancyqube-aihub`
- 公网 endpoint：`oss-cn-shanghai.aliyuncs.com`
- VPC 上传及读取 endpoint（按部署网络选用）：`vpc100-oss-cn-shanghai.aliyuncs.com`
- 默认对象路径：`tmp/chat-images/{workspace_id}/{UTC日期}/{随机UUID}.{扩展名}`

每张图片以 `public-read` 对象 ACL 写入，上传凭据需要有写对象及设置该 ACL 的权限。
返回的 `url` 是没有签名过期时间的 HTTPS 公网链接；后端的内部 endpoint 不会出现在链接中。
不修改整个 Bucket 的 ACL。

图片 URL 随消息的 `attached_files` 保存。鼠标悬停图片时显示链接图标，点击即可复制公网链接；
键盘聚焦时也会显示，触屏设备直接显示图标。刷新历史后仍然可复制。
模型本轮输入同时包含图片字节和公网链接，后续轮次的历史上下文也保留链接。
模型读取只接受配置 Bucket、指定目录、当前工作区下的规范图片 URL，禁止重定向，并限制读取大小。
历史工作区图片仍通过原鉴权下载接口展示。

验证：`.venv/bin/python -m pytest test_chat_image_storage.py test_runtime_attachments.py test_message_content.py`
（在 `backend` 目录执行）；浏览器回归位于 `frontend/browser-tests/chat-image-paste.mjs`，
设置 `CHAT_IMAGES_ONLY=1` 可只验证桌面和手机的图片上传、链接、历史恢复和错误处理。
