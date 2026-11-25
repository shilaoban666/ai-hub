# AI Hub — Agent Instructions

AI 技能管理平台，支持 SKILL.md 文件的导入、编辑、版本发布和公开分享，同时包含 MCP 服务管理和 Token 用量看板。

## Tech Stack
- **Backend**: FastAPI + SQLAlchemy + MySQL (Python 3.8+), entry at `backend/main.py`
- **Frontend**: Vue 3 + Vite + Element Plus + Pinia + Vue Router, entry at `frontend/src/main.js`
- **Auth**: OAuth2 PKCE（前端直连 iam-service）→ 网关注入 header → 后端读 `x-user-id` 等

## Key Conventions

### UI 空值展示（项目默认规则）
- 后续新增或修改界面时，字段没有内容统一显示中文“无”，适用于表格、详情、抽屉等展示场景。
- `null`、`undefined`、空字符串、纯空白字符串和没有展示项的集合均按空值处理；不要使用 `—`、`-`、空白、“未填写”、“未指派”等替代文案。
- 数值 `0` 和布尔值 `false` 是有效值，不得因真假判断误显示为“无”。
- “待处理”、“处理中”、“已处理”、“无需处理”等明确业务状态保留原有含义；输入框提示、加载状态和错误提示不属于字段空值。
- 该规则默认应用于本项目后续开发，除非用户对具体场景另有明确要求。

### Gateway routing
All requests go through gateway, dispatched by path prefix:
- `/aihub/*` → aihub backend
- `/iam/*` → iam-service（认证 + RBAC + 服务发现）

### Auth flow
1. Frontend generates PKCE code_verifier + code_challenge, redirects browser to iam-service `/authorize/`
2. After authorization, callback to `/oauth/callback?code=...`
3. Frontend exchanges code for token via `POST /o/token/` (PKCE, no client_secret)
4. Gateway validates JWT, injects `x-user-id`, `x-user-username`, `x-user-permissions` headers
5. Backend `auth.py` reads headers → `CurrentUser` object (no JWT, no auth_mode switching)
6. Frontend Axios interceptor auto-refreshes on 401 via `POST /o/token/`, queues concurrent requests
7. All `/api/skills/*` and `/api/mcps/*` filtered by `current_user.user_id` — users own their data
8. Public endpoints `/api/public/*` require no auth, return only `is_public=true` records

### File storage
- Skill files saved to `backend/skills/{skill_id}/` as real filesystem tree, NOT in DB `files` column
- File tree format: `[{ id, label, type, path, content?, children? }]`
- Import accepts single SKILL.md or zip; auto-finds outermost SKILL.md, strips wrapper dirs
- Core utils in `backend/skill_utils.py`: `save_skill_files`, `load_skill_files`, `delete_skill_files`, `parse_skill_md`, `flatten_file_tree`, `build_file_tree_from_flat`

### Soft delete
Both skills and MCPs use `is_deleted=true` flag, with associated files (covers, skill dirs) cleaned up on delete.

### API patterns
- Pagination: `skip`/`limit` params, response `{ total, items }`
- Fuzzy search: SQL `LIKE` on `name`/`author`/`roles` (or `description`/`tags` for MCPs)
- All queries filter `is_deleted == False`; public queries filter `is_public == True`
- Config: `backend/database.py` loads from `../.env` via pydantic-settings; Vite loads via `loadEnv`

### Git sync
- Supports GitLab and GitHub via adapter in `backend/git_client.py`
- Sync directions: 0=none, 1=git→local, 2=local→git
- Users explicitly choose push or pull; file diff is available before synchronization
- Push safety: checks `git_last_commit_sha` to detect remote changes since last sync

### Dashboard
- Personal: `/api/dashboard/personal/token-usage` — all authenticated users
- Summary: `/api/dashboard/summary/token-usage` — requires superuser/staff/`dashboard.view_summary`
- Data from sub2api PostgreSQL `usage_logs` + `users` tables; config via `SUB2API_POSTGRES_*` env vars

### Static mounts
- `/releases` → `backend/releases/` (zip downloads)
- `/uploads/covers` → `backend/uploads/covers/` (cover images)
- `/uploads/images` → `backend/uploads/images/` (inline editor images)

## Project Structure Quick Reference
```
backend/main.py              # All /api/* routes (skills, mcps, public, uploads)
backend/models.py            # Skill, SkillRelease, McpService
backend/schemas.py           # Pydantic models (create, update, response, list)
backend/database.py          # Settings + SQLAlchemy engine/session (no auth config)
backend/auth.py              # CurrentUser, get_current_user (gateway headers only)
backend/git_routes.py        # /api/git/* (bind, push, pull, diff)
backend/dashboard_routes.py  # /api/dashboard/* (personal, summary)
backend/skill_utils.py       # File tree save/load, SKILL.md parser
frontend/src/router/index.js # All routes + auth guard (requiresAuth, requiresSuperuser)
frontend/src/api/request.js  # Axios: aihubRequest (/aihub/api), iamRequest (/iam/api), authRequest (VITE_AUTH_BASE), 401 interceptor
frontend/src/stores/auth.js  # Auth state, frontend PKCE login/callback/logout
```

## Dev Startup
```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend && npm install && npm run dev  # :15173, proxies /iam/api /aihub/api→:8000
```
