# 助手形象

智能体设置提供两个独立字段：

- `assistant_icon`：聊天头像。支持小牛、小树苗、上传图片以及原有文字/emoji。
- `assistant_mascot`：悬浮精灵。支持小牛、小树苗及上传图片，默认小牛。

内置值分别是 `@cow`、`@sprout`。上传复用 `/api/upload/image?purpose=assistant`，保存返回的 `/uploads/images/...` 路径。图片建议控制在 100KB 以内，前后端均限制不超过 200KB（编辑器图片仍保持原有 1MB 限制）；支持 PNG、JPG、GIF、WebP、ICO、SVG。头像容器透明。上传图片不自动生效，必须保存并生效工作台设置；图片本身使用普通 `img` 渲染，不插入为页面代码。

## 发布与部署

先执行 `backend/migrations/038_assistant_characters.sql`，再更新后端、前端及 `/embed/assistant.js`。迁移增加 `assistant_mascot` 并扩展头像字段长度，保留已有数据，可重复执行。

悬浮脚本每次挂载仅请求一次 `/aihub/api/public/assistant-appearance`，不携带登录凭据，不轮询。该接口仅返回已发布的精灵标识或图片路径，不返回草稿、提示词或其他设置。网关需允许此公开 GET 请求，沿用 `/aihub/api/public/*` 路由和跨域策略。接口不可用或上传图片加载失败时回退到内置小牛。

发布后刷新宿主页面应用精灵；个人默认助手按原有 bootstrap 流程同步聊天头像。聊天头像和精灵互不影响；普通智能体详情也可选择或上传头像。上传图片保留自身动画（例如 GIF），悬停时轻微抬升；内置小牛抬头，小树苗挥手。

## 形象源文件

`frontend/public/characters/cow-motion-v1.svg` 和 `sprout-motion-v1.svg` 固化两个形象及动画。对应的 `cow-v1.svg`、`sprout-v1.svg` 是静态头像预览。已有 v1 形象应保持稳定，新增版本用新文件名。

在 frontend 目录运行 `node scripts/sync-assistant-characters.mjs` 同步静态文件、兼容的 `assistant-core.svg` 和悬浮脚本内嵌图形，避免 SVG 以外部图片载入时动画不生效。形象目录及脚本必须一同部署。
