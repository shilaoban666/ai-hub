# AI 工作台相对 master 的字段与配置变更

对比日期：2026-09-07。

基线：本地 `master` / 本地远程跟踪分支 `origin/master` 均为 `de8a590`。
目标：`feature/bot`，提交 `f2bff40`。对比时工作区干净；未联网刷新远端，未连接或修改数据库。

结论：新增 **22 张表**，在 **6 张原有表新增 32 个字段**，新增 **15 个后端环境配置项**，新增 **11 个 SQL 迁移文件**。本次只整理差异，未修改业务代码或部署配置。

## 1. 原有表新增字段

以下类型和默认值以全部迁移执行后的 MySQL 结构为准。标记 NULL 的字段允许为空；其余均为 NOT NULL。

| 表 | 字段 | 类型 / 默认值 | 用途 | 迁移 |
| --- | --- | --- | --- | --- |
| ai_models | scope | VARCHAR(20)，user | 区分个人模型与平台模型 | 025 |
| ai_models | is_enabled | TINYINT(1)，1 | 模型启停 | 025 |
| ai_models | health_status | VARCHAR(20)，unknown | 模型健康状态 | 025 |
| agents | kind | VARCHAR(30)，expert | 区分专家智能体与默认助手 | 025 |
| agents | default_agent_user_id | INT，NULL，唯一索引 | 每个用户唯一的默认助手 | 025 |
| agents | settings_version | INT，NULL | 助手配置版本 | 027 |
| agents | workspace_id | BIGINT，NULL，外键 | 关联用户工作区 | 028_user |
| agent_sessions | model_id | INT，NULL，外键 | 会话绑定模型 | 027 |
| agent_sessions | config_version | INT，NULL | 会话绑定配置版本 | 027 |
| agent_sessions | workspace_id | BIGINT，NULL，外键 | 会话所属用户工作区 | 028_user |
| agent_runs | pricing_snapshot | LONGTEXT，NULL | 运行时计价快照 | 025 |
| agent_runs | reserved_points | DECIMAL(20,2)，0.00 | 预占点数 | 025、028_credit |
| agent_runs | charged_points | DECIMAL(20,2)，0.00 | 实际扣费点数 | 025、028_credit |
| agent_runs | settlement_status | VARCHAR(30)，not_required | 结算状态 | 025 |
| agent_runs | assistant_message_id | INT，NULL，索引 | 将运行记录关联到助手消息 | 028_credit |
| agent_runs | workspace_id | BIGINT，NULL，外键 | 运行所属用户工作区 | 028_user |
| skill_releases | content_sha256 | VARCHAR(64)，NULL | 发布包内容摘要 | 028_user |
| skill_releases | manifest_json | LONGTEXT，NULL | 技能能力清单 | 028_user |
| skill_releases | status | VARCHAR(20)，published | 发布、拒绝、撤销等状态 | 028_user |
| skill_releases | scan_status | VARCHAR(20)，pending | 扫描状态 | 028_user |
| skill_releases | published_by | INT，NULL | 发布人 | 028_user |
| skill_releases | scan_report_json | LONGTEXT，NULL | 扫描报告 | 029 |
| skill_releases | reviewed_by | INT，NULL | 审核人 | 029 |
| skill_releases | reviewed_at | DATETIME，NULL | 审核时间 | 029 |
| skill_releases | native_approved | TINYINT(1)，0 | 原生运行批准标记 | 029 |
| skill_releases | revoked_by | INT，NULL | 撤销人 | 029 |
| skill_releases | revoked_at | DATETIME，NULL | 撤销时间 | 029 |
| skill_releases | revocation_reason | VARCHAR(1000)，NULL | 撤销原因 | 029 |
| prompt_templates | source_template_id | INT，NULL，外键 | 导入来源模板 | 028_user |
| prompt_templates | source_snapshot_hash | VARCHAR(64)，NULL | 导入来源摘要 | 028_user |
| prompt_templates | imported_at | DATETIME，NULL | 导入时间 | 028_user |
| prompt_templates | is_system | TINYINT(1)，0 | 系统提示词标记 | 031 |

上述字段均为新增，没有删除 master 已有的数据库字段。`028_credit` 中的类型调整针对本分支早先迁移新增的点数字段，将 BIGINT 改为 DECIMAL(20,2)，不是修改 master 的原有点数字段。

## 2. 新增表及字段

下表列出全部字段名；主键、外键、索引和完整 DDL 见对应迁移文件。

| 表 | 用途 | 字段 | 迁移 |
| --- | --- | --- | --- |
| platform_agent_settings | 助手配置草稿及发布版本 | id, version, status, assistant_name, assistant_icon, assistant_description, system_prompt, runtime_type, default_model_id, max_turns, timeout_seconds, credit_display_name, credit_display_name_en, initial_claim_amount, daily_claim_amount, per_run_limit, low_balance_threshold, claim_timezone, max_concurrent_runs, created_by, published_by, published_at, created_at, updated_at | 025、028_credit、032 |
| credit_accounts | 用户点数账户 | id, user_id, available_balance, reserved_balance, status, version, created_at, updated_at | 025、028_credit |
| credit_claim_records | 初始及每日领取记录 | id, user_id, claim_type, claim_date, amount, policy_version, business_key, created_at | 025、028_credit |
| credit_ledger | 点数流水 | id, user_id, entry_type, amount, available_after, reserved_after, run_id, business_key, operator_user_id, reason, metadata, created_at | 025、028_credit |
| model_pricing_versions | 模型计价版本 | id, model_id, version, input_rate, output_rate, cache_read_rate, cache_creation_rate, rate_scale, effective_from, effective_to, created_at | 025 |
| model_usage_events | 模型请求用量事件 | id, run_id, provider_request_id, model_id, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, occurred_at, raw_usage | 025 |
| model_run_credentials | 每次运行的临时模型凭证 | id, token_hash, run_id, user_id, model_id, pricing_version_id, max_points, consumed_points, request_count, request_in_flight, status, expires_at, created_at, updated_at | 026、028_credit |
| user_workspaces | 每用户唯一持久工作区 | id, workspace_key, user_id, status, storage_path, quota_bytes, used_bytes, migration_status, last_accessed_at, is_deleted, created_at, updated_at | 028_user |
| runtime_cells | 用户运行环境状态 | id, workspace_id, user_id, runtime_type, sandbox_type, status, container_name, image_ref, desired_config_hash, applied_config_hash, last_started_at, last_active_at, hibernated_at, last_error_code, last_error_message, created_at, updated_at | 028_user |
| workspace_execution_leases | 工作区运行租约与并发协调 | workspace_id, run_id, owner_id, fencing_token, lease_until, heartbeat_at, created_at, updated_at | 028_user |
| workspace_run_views | 单次运行的执行目录及清理记录 | id, run_id, workspace_id, agent_id, status, host_path, sandbox_ref, config_hash, cleanup_status, prepared_at, cleaned_at, last_error, created_at, updated_at | 028_user |
| skill_installations | 用户安装的技能版本 | id, user_id, workspace_id, skill_id, release_id, previous_release_id, status, granted_capabilities, installed_at, updated_at | 028_user |
| expert_skill_bindings | 专家智能体绑定已安装技能 | id, agent_id, installation_id, created_at | 028_user |
| credential_references | MCP 加密凭证及版本 | id, user_id, name, secret_encrypted, version, fingerprint, status, last_rotated_at, created_at, updated_at | 028_user |
| mcp_definitions | MCP 资源定义 | id, owner_user_id, scope, name, description, transport_type, status, source_mcp_service_id, created_at, updated_at | 028_user |
| mcp_revisions | MCP 配置版本 | id, definition_id, version, config_json, content_sha256, status, security_report_json, created_by, created_at | 028_user、029 |
| mcp_connections | 用户连接器实例 | id, user_id, workspace_id, definition_id, revision_id, credential_reference_id, name, config_overrides_json, tool_policy_json, status, last_tested_at, last_test_status, created_at, updated_at | 028_user、029 |
| expert_mcp_bindings | 专家智能体绑定连接器 | id, agent_id, connection_id, created_at | 028_user |
| asset_security_events | 资源扫描、审核、撤销记录 | id, asset_type, asset_id, action, actor_user_id, reason, details_json, created_at | 029 |
| system_skill_installations | 全员可用的系统技能 | id, skill_id, release_id, previous_release_id, granted_capabilities, status, created_by, installed_at, updated_at | 030 |
| platform_global_settings | 平台品牌设置 | id, brand_icon, brand_name, brand_subtitle, updated_by, created_at, updated_at | 033 |
| workspace_prompt_removals | 用户从工作台移除提示词的记录 | user_id, template_id, created_at | 034 |

`workspace_prompt_removals` 的主键是 `(user_id, template_id)`，不删除提示词管理中的源模板。

最终使用 DECIMAL(20,2) 的字段包括：`agent_runs` 的 reserved_points / charged_points；`platform_agent_settings` 的四个额度字段；`credit_accounts` 的两个余额字段；`credit_claim_records.amount`；`credit_ledger` 的 amount / available_after / reserved_after；`model_run_credentials` 的 max_points / consumed_points。模型单价字段仍为 BIGINT，配合 rate_scale 使用。

## 3. 新增环境配置

以下为 `backend/database.py` 的代码默认值，不是生产环境当前值。已有默认值的参数不必全部重复写入 `.env`，部署地址、路径和运行资源应按实际环境设置。

| 配置 | 默认值 | 用途 / 配置时机 |
| --- | --- | --- |
| USER_WORKSPACE_ROOT | /var/lib/aihub/user_workspaces | 用户工作区持久目录，需要可写和持久化 |
| USER_WORKSPACE_QUOTA_BYTES | 10737418240 | 新建工作区默认配额，10 GiB |
| USER_WORKSPACE_USER_PREFIX | aihub_user_ | native 模式的宿主机用户名前缀 |
| MODEL_GATEWAY_BASE_URL | http://127.0.0.1:15174/api/model-gateway | 非容器运行环境访问 AI Hub 内部模型网关的地址 |
| MODEL_GATEWAY_CONTAINER_BASE_URL | http://host.docker.internal:15174/api/model-gateway | 容器访问 AI Hub 内部模型网关的地址 |
| MODEL_GATEWAY_CREDENTIAL_TTL_SECONDS | 900 | 每次运行的模型凭证有效期，秒 |
| MODEL_GATEWAY_REQUEST_TIMEOUT_SECONDS | 600 | 模型网关请求超时，秒 |
| MODEL_GATEWAY_RECONCILIATION_GRACE_SECONDS | 86400 | 终态运行等待缺失用量事件的对账宽限期，秒；超时后按已记录用量结算 |
| CLAUDE_CODE_CONTAINER_IMAGE | aihub/claude-runtime:latest | Claude 容器镜像 |
| CLAUDE_CODE_CONTAINER_NETWORK | bridge | Docker 网络 |
| CLAUDE_CODE_CONTAINER_MEMORY | 2g | 单个运行容器内存 |
| CLAUDE_CODE_CONTAINER_CPUS | 2 | 单个运行容器 CPU 配额 |
| CLAUDE_CODE_CONTAINER_PIDS_LIMIT | 256 | 单个运行容器进程数量上限 |
| MCP_EGRESS_PROXY_URL | 空字符串 | 可选远程 MCP 出口代理 |
| MCP_ALLOWED_HOSTS | 空字符串 | 可选远程 MCP 域名白名单，逗号分隔，支持通配符 |
| MCP_STDIO_ALLOWED_COMMANDS | 空字符串 | 使用 stdio MCP 时需要配置允许的命令名 |

已有配置的使用要求发生变化：

- `CLAUDE_CODE_SANDBOX_TYPE`：示例由 `directory` 改成 `container`。企业工作区只接受 `container` / `native`。代码仍会回退读取旧 `AGENT_SANDBOX_TYPE`，因此只替换代码而沿用旧 directory 配置，会在工作区初始化时报错。
- `AGENT_CREDENTIAL_ENCRYPTION_KEY`：master 已有，不是新增项；本版保存平台模型 API Key 时要求已配置。原有密钥应保持一致，不能为了升级重新生成并覆盖已有密钥。
- `AGENT_CREDENTIAL_KEY_VERSION`：master 已有，继续沿用。
- 模型网关 URL 指向 AI Hub 后端，不是 DeepSeek 等模型上游地址；容器地址必须从容器内可达。上游地址和 API Key 在平台模型设置中填写。
- `.env.example` 关于“远程 HTTP MCP 默认关闭，必须配置代理和白名单”的注释与代码不一致。实际代码允许未配置代理/白名单时访问通过校验的公网 HTTP(S) 地址；内网和本地地址仍会被目标地址校验拒绝。本文记录现状，不调整策略。
- `MCP_STDIO_ALLOWED_COMMANDS` 为空时，stdio 连接器的配置校验不通过；命令名不能含路径分隔符。
- 未新增 `VITE_*` 配置，Vite 配置文件也没有变化。仓库跟踪的 `.env.prod` 相对 master 没有变化；这不代表线上环境已经补齐新配置。

## 4. 页面中的新配置

### 全局设置

`brand_icon`、`brand_name`、`brand_subtitle`，默认分别为 H、AI Hub、合趣网络。保存到 `platform_global_settings`，即时更新品牌信息，不需要发布助手配置。

### 智能体设置

| 分组 | 配置字段 | 默认值 / 说明 |
| --- | --- | --- |
| 助手身份 | assistant_name, assistant_icon, assistant_description, system_prompt | AI 助手、H，描述及系统提示词可空 |
| 执行设置 | runtime_type, default_model_id, max_turns, timeout_seconds, max_concurrent_runs | claude_code、模型需选择、50 轮、600 秒、1 并发 |
| 点数名称 | credit_display_name, credit_display_name_en | 算点、Credits，可在页面修改 |
| 领取与消费 | initial_claim_amount, daily_claim_amount, per_run_limit, low_balance_threshold, claim_timezone | 四个金额默认 0；时区 Asia/Shanghai |

助手设置采用草稿及发布版本，保存草稿后还需发布。当前发布校验要求：选中已启用且有 API Key 的兼容平台模型，runtime_type 为 claude_code，per_run_limit > 0，daily_claim_amount > 0，initial_claim_amount >= per_run_limit。数据库默认值本身不足以直接开箱运行。

平台模型新增了管理入口：填写模型名称、供应商、API Key、上游地址、协议、推理支持、备注、启用状态，以及 input_rate / output_rate / cache_read_rate / cache_creation_rate / rate_scale。协议等基础模型字段 master 已存在；平台管理入口、启停/范围字段和版本化计价是本次增量。rate_scale 默认 1000000，四种单价默认 0。

系统技能、系统提示词、系统 MCP 在智能体设置中配置；迁移不会自动将个人技能、个人模型或个人提示词全部提升为系统资源。

### 权限与浏览器偏好

- 新后端权限码：`aihub:assistant:settings:manage`、`aihub:assets:review`。对应接口同时接受超级管理员 / staff；前端系统设置菜单及相关路由仍要求超级管理员。若使用普通角色委派管理，需要同时核对前后端可见性，不能只添加权限码。
- 侧栏偏好新增浏览器 localStorage 项 `aihub:sidebar-collapsed`，值为 true / false；不需要数据库字段或服务器配置。

## 5. 迁移顺序

在已具备 master 数据库结构的前提下，按以下文件顺序执行。两个 `028` 是不同文件，都需要执行，不能只记录数字版本并跳过其中一个。

1. `backend/migrations/025_enterprise_assistant_credits.sql`
2. `backend/migrations/026_model_run_credentials.sql`
3. `backend/migrations/027_agent_config_pinning.sql`
4. `backend/migrations/028_credit_decimal_precision.sql`
5. `backend/migrations/028_user_workspace_and_assets.sql`
6. `backend/migrations/029_asset_security_policy.sql`
7. `backend/migrations/030_system_default_skills.sql`
8. `backend/migrations/031_system_resources.sql`
9. `backend/migrations/032_assistant_identity_icon.sql`
10. `backend/migrations/033_platform_global_settings.sql`
11. `backend/migrations/034_workspace_prompt_removals.sql`

后端启动中的 `Base.metadata.create_all()` 不会给已存在的表补列，不能代替这批迁移。仓库的 `backend/_run_migration.py` 逐个执行指定 SQL，并没有按版本自动补齐的记录机制。

迁移除了建表加列，还会写入以下历史数据：

- `028_credit`：只回填能唯一匹配助手消息的历史运行，其他 assistant_message_id 保持 NULL。
- `028_user`：按既有 agents 的 user_id 创建 user_workspaces，回填 agents / agent_sessions / agent_runs 的 workspace_id，创建 runtime_cells；旧用户工作区标记 migration_status=pending。
- 旧工作目录文件在后续运行准备阶段复制到用户工作区，不是在 SQL 中复制。迁移依赖旧 native 工作目录配置；上线时应保留旧目录并核对路径。container 的复制会合并且可能覆盖同名文件，native 使用不覆盖方式复制。
- SQL 创建的旧用户工作区 quota_bytes 默认 0；环境变量的 10 GiB 默认值在应用新建工作区时写入，不会自动回填已有行。
- 技能安全扫描已移除，scan_status / scan_report_json 仅保留用于旧数据库兼容。新版本直接发布；未经过人工审核或撤销、仅因旧扫描失败被拒绝的版本自动恢复可用。

## 6. 上线所需配置动作

1. 确认生产数据库具备 master 结构，备份数据库和原工作目录后执行上述增量迁移。
2. 明确选择 container 或 native，配置用户工作区持久目录。container 模式需准备 Docker 和 `backend/runtime_images/claude/Dockerfile` 对应镜像；默认构建参数 CLAUDE_CODE_VERSION=2.1.208，镜像用户为 65532:65532。
3. 沿用/补齐凭证加密配置，设置运行环境能访问的内部模型网关地址。
4. 在智能体设置中创建平台模型、填写计价和助手额度，选择默认模型并发布设置。
5. 按需配置系统技能、系统提示词、系统 MCP 和品牌信息。需要 stdio MCP 时配置命令白名单并准备对应运行镜像命令。
6. 核对新建对话、历史会话、旧工作区文件、技能安装、连接器和点数结算。本文是源码差异核对，不代表已验证生产库、网络或已执行上线操作。

## 7. 核对来源

- 字段定义：`backend/models.py`。
- 迁移 DDL：`backend/migrations/025_*` 至 `034_*`，包含两个 `028_*`。
- 环境项：`backend/database.py`、`.env.example`。
- 页面配置和发布条件：`backend/enterprise_schemas.py`、`backend/enterprise_routes.py`。
- 工作区及旧文件迁移：`backend/enterprise_workspace.py`、`backend/sandbox/container.py`、`backend/sandbox/native.py`。
- MCP 参数实际行为：`backend/asset_security.py`。
- 技能发布与历史版本兼容：`backend/asset_routes.py`、`backend/skill_release_policy.py`。
