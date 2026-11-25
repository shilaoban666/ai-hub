# AI Hub

技能管理平台，支持导入、编辑、发布和分享 AI 技能文件（SKILL.md 格式），同时管理 MCP 服务和 Token 用量看板。

## 技术栈

- **后端**: FastAPI + SQLAlchemy + MySQL (Python 3.8+)
- **前端**: Vue 3 + Vite + Element Plus + Pinia + Vue Router
- **认证**: OAuth2 PKCE（前端直连 iam-service）→ 网关统一鉴权 → 后端读网关注入头
- **外部数据源**: sub2api PostgreSQL（Token 用量看板）

## 项目结构

```
aihub/
├── .env                     # 实际配置（gitignore）
├── .env.example             # 配置模板（git 跟踪）
├── backend/
│   ├── main.py              # FastAPI 入口，所有 /api/* 路由
│   ├── models.py            # Skill, SkillRelease, McpService (SQLAlchemy)
│   ├── schemas.py           # Pydantic 请求/响应模型
│   ├── database.py          # 数据库连接 + Settings (pydantic-settings)
│   ├── auth.py              # 网关注入头解析、CurrentUser（权限检查在网关侧，本地不执行）
│   ├── git_routes.py        # Git 同步路由 (/api/git/*)
│   ├── git_client.py        # GitLab/GitHub API 客户端
│   ├── dashboard_routes.py  # Token 用量看板路由 (/api/dashboard/*)
│   ├── sub2api_database.py  # sub2api PostgreSQL 数据源连接
│   ├── skill_utils.py       # 技能文件读写、SKILL.md 解析、文件树工具函数
│   ├── migrations/          # 手动 SQL 迁移脚本
│   ├── skills/              # 技能文件存储目录（按 skill_id 分文件夹）
│   ├── releases/            # 发布 zip 包
│   └── uploads/
│       ├── covers/          # 封面图片
│       └── images/          # Markdown 编辑器内嵌图片
└── frontend/
    ├── vite.config.js       # Vite 配置，dev 时代理 /auth /aihub/api /releases /uploads
    └── src/
        ├── main.js           # 入口: Pinia + Router + Element Plus (中文)
        ├── config.js         # 从 import.meta.env 读取配置
        ├── App.vue
        ├── router/index.js   # 路由表 + 全局认证守卫
        ├── api/
        │   ├── request.js    # Axios 实例 + 401 自动刷新令牌队列
        │   └── skills.js     # skillsApi (需认证) + publicSkillsApi + mcpApi + dashboardApi
        ├── stores/
        │   ├── auth.js       # 认证状态、OAuth2 PKCE 登录/回调/登出
        │   └── app.js        # 侧边栏折叠状态
        ├── components/
        │   ├── AdminLayout.vue   # 管理后台布局（侧边栏 + 顶栏）
        │   └── PublicLayout.vue  # 公开页面布局
        ├── views/
        │   ├── Login.vue
        │   ├── AuthCallback.vue
        │   ├── admin/         # 管理后台视图 (需认证)
        │   │   ├── AdminSkillList.vue / AdminSkillDetail.vue
        │   │   ├── McpList.vue / McpDetail.vue
        │   │   ├── ModelList.vue / AssetList.vue
        │   │   ├── PatManagement.vue (Personal Access Token)
        │   │   ├── PersonalTokenUsage.vue
        │   │   └── SummaryTokenUsage.vue (需 superuser)
        │   └── public/        # 公开页面 (无需认证)
        │       ├── PublicSkillList.vue / PublicSkillDetail.vue
        │       └── PublicMcpList.vue / PublicMcpDetail.vue
        └── utils/
            ├── cookies.js     # Cookie 读写工具
            └── oauth2.js      # PKCE code_verifier 生成 + SHA-256
```

## 关键约定

### 网关路由

所有请求通过网关按路径前缀分发：
- `/aihub/*` → aihub 后端
- `/iam/*` → iam-service（认证 + RBAC + 服务发现）

aihub 后端不直接调用 iam-service API，也不持有或验证 JWT。网关完成 token 验证、入口身份头清洗和路由级权限检查，再注入可信的 `x-user-*` 头；后端只解析这些身份头并执行对象级归属校验（owner / superuser）。

### 环境配置

根目录 `.env` 存放实际配置（gitignore），`.env.example` 为配置模板（git 跟踪）。后端 `database.py` 通过 `pydantic-settings` 的 `env_file = "../.env"` 加载，前端 `vite.config.js` 通过 `envDir` + `loadEnv` 从根目录加载。本地开发时复制 `.env.example` 为 `.env` 并修改对应值即可。

### 认证流

1. 前端 `/login` → 前端生成 PKCE code_verifier + code_challenge
2. 浏览器跳转 iam-service `/authorize/`（直连 VITE_AUTH_BASE 授权页）
3. 用户授权后回调到 `/oauth/callback?code=...`
4. 前端直连 `POST /o/token/` 用 code + code_verifier 换取 token（PKCE，无需 client_secret）
5. 后续请求带 `Authorization: Bearer <access_token>`
6. 网关本地验证 JWT 签名/过期，从 Redis 读 `perm:{user_id}` 做路由级权限检查；通过后注入 `x-user-id`、`x-user-is-superuser`、`x-user-username`、`x-user-first-name`、`x-user-email` 到下游（不再注入 `x-user-permissions`，权限检查留在网关侧）
7. 后端 `auth.py` 从 header 解析 `CurrentUser`（不含权限列表，`permissions` 恒为空）；对象级归属校验（owner、superuser）在各端点内完成
8. 401 时前端 Axios 拦截器自动调用 `POST /o/token/` 刷新，并发请求排队等待

### 技能文件存储

文件以文件树 JSON 从前端传到后端，后端解析后写入 `backend/skills/{skill_id}/` 目录。读取时从文件系统重组为文件树 JSON 返回。不再存储在数据库 `files` 字段。

文件树节点格式：`{ id, label, type: "file"|"folder", path, content?, children? }`

核心函数（`skill_utils.py`）：
- `save_skill_files(skill_id, file_tree)` — 先清空目录，再递归写入
- `load_skill_files(skill_id)` — 递归读取目录，构建文件树
- `delete_skill_files(skill_id)` — `shutil.rmtree` 整个技能目录
- `parse_skill_md(content)` — 正则提取 `name`/`version`/`description` 元数据
- `flatten_file_tree(nodes)` — 文件树 → `{path: content}` 字典
- `build_file_tree_from_flat(files)` — `{path: content}` → 文件树

### 导入技能

`POST /api/skills/import` 支持两种格式：
1. **单个 SKILL.md** — 直接上传 `.md` 文件
2. **ZIP 压缩包** — 自动找到最外层 SKILL.md（路径深度最小），递归构建文件树。单根目录时自动剥离包装目录直到出现 SKILL.md

### 数据隔离

所有 `/api/skills/*` 和 `/api/mcps/*` 端点通过 `current_user.user_id` 过滤，用户只能操作自己的数据。公开端点 `/api/public/*` 无需认证，只返回 `is_public=true` 的记录。

### 软删除

技能和 MCP 删除均为软删除（设置 `is_deleted=true`），同时清理封面文件（`uploads/covers/`）和技能文件目录（`skills/{id}/`）。

### API 风格

- 后端使用 `response_model` 定义响应 schema
- 分页参数 `skip`/`limit`，返回 `{ total, items }`
- 模糊搜索用 SQL `LIKE` 匹配多个字段
- 所有查询过滤 `is_deleted == False`
- 公开列表按 `created_at` 倒序排列

### Git 同步

支持 GitLab 和 GitHub，`git_client.py` 通过适配器模式统一 API 差异。

同步方向（`git_sync_direction`）：
- `0` — 不同步
- `1` — Git → 本地（拉取方向）
- `2` — 本地 → Git（推送方向）

同步时由用户明确选择推送或拉取，可先查看本地与远程的文件差异。

推送时检查远程是否有新提交（比对 `git_last_commit_sha`），如有新变更则拒绝推送（除非 `force=true`）。

### Token 用量看板

数据来自 sub2api PostgreSQL 数据库的 `usage_logs` 和 `users` 表。需要在 `.env` 中配置 `SUB2API_POSTGRES_*` 连接参数。

权限要求：
- 个人看板（`/api/dashboard/personal/token-usage`）：所有已认证用户
- 全局看板（`/api/dashboard/summary/token-usage`）：需要 `is_superuser`（后端 `dashboard_routes.py` 强制校验）；`/summary/token-usage/users/{user_id}` 仅允许查看本人用量，`is_superuser` 可查任意用户

### 静态文件

后端通过 `StaticFiles` 挂载三个目录：
- `/releases` → `backend/releases/`（发布 zip 包）
- `/uploads/covers` → `backend/uploads/covers/`（封面图片）
- `/uploads/images` → `backend/uploads/images/`（编辑器内嵌图片）

## 数据库模型

### skills
`id, user_id, name, version, description, author, module, roles, rating, comment_count, icon, cover, content, files, is_deleted, is_public, created_at, updated_at`
+ Git 字段: `git_provider, git_repo_url, git_branch, git_access_token, git_last_synced_at, git_sync_status, git_last_commit_sha, git_sync_direction`

### skill_releases
`id, skill_id (FK), version, file_path, file_url, created_at`

### mcp_services
`id, user_id, name, description, type (stdio/sse/streamable_http/json), config (JSON), usage_instructions (Markdown), tags, author, cover, is_deleted, is_public, created_at, updated_at`

## 路由表

### 前端路由
| 路径 | 组件 | 认证 |
|---|---|---|
| `/login` | Login | 否 |
| `/oauth/callback` | AuthCallback | 否 |
| `/skills` | PublicSkillList | 否 |
| `/skills/:id` | PublicSkillDetail | 否 |
| `/mcps` | PublicMcpList | 否 |
| `/mcps/:id` | PublicMcpDetail | 否 |
| `/admin/skills` | AdminSkillList | 是 |
| `/admin/skills/:id` | AdminSkillDetail | 是 |
| `/admin/mcp` | McpList | 是 |
| `/admin/mcp/:id` | McpDetail | 是 |
| `/admin/models` | ModelList | 是 |
| `/admin/assets` | AssetList | 是 |
| `/admin/tokens` | PatManagement | 是 |
| `/admin/dashboard/personal/token-usage` | PersonalTokenUsage | 是 |
| `/admin/dashboard/summary/token-usage` | SummaryTokenUsage | superuser |

### 后端路由模块
- `main.py` — `/api/skills`, `/api/mcps`, `/api/public/*`, 文件上传，静态挂载
- `git_routes.py` — `/api/git/*`（test-connection, bind, unbind, push, pull, sync, diff, sync-status）
- `dashboard_routes.py` — `/api/dashboard/*`（personal, summary）

## 启动开发环境

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev    # 启动在 :15173，代理 /iam/api /aihub/api /releases /uploads 到后端
```
