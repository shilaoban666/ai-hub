# AI Hub 系统全量审计与演进建议

> 审计日期：2026-07-19  
> 文档性质：现状审计、风险清单与产品路线建议，不包含任何业务功能实现  
> 总体结论：**当前版本存在可被直接利用的身份冒充、敏感信息泄露和持久化 XSS，不应在修复 P0 项以前继续以现有入口暴露到公网。**

## 1. 执行摘要

AI Hub 已不再只是一个 Skill 管理页面，而是一个同时处理代码包、模型密钥、MCP 凭据、Agent 执行、主机文件、外部消息渠道和跨库用量数据的综合平台。它已经具备较丰富的业务能力，但安全边界、数据治理和工程保障仍停留在内部工具阶段，和当前系统的实际权限与数据敏感度不匹配。

本次审计确认的最高风险不是“代码风格”或“缺少功能”，而是以下可形成实际攻击链的问题：

1. Nginx 允许客户端直达后端，而后端直接信任客户端可伪造的 `x-user-*` 头；权限依赖函数又没有执行权限判断。攻击者可以冒充任意用户或超级管理员。
2. 无鉴权接口公开返回全平台用户邮箱和 Token 用量。
3. 公开 MCP 接口会解密并返回完整配置，模型接口会把完整 API Key 返回浏览器。
4. 公开提示词内容直接进入 `v-html`，令牌又存放在 `localStorage`，可形成持久化 XSS 到令牌窃取的完整链路。
5. Agent 子进程继承后端完整环境，默认目录沙箱没有隔离；生产部署账号还被建议加入 Docker 组并授予 `NOPASSWD: ALL`，一旦 Agent 或后端被利用，影响可扩大到数据库凭据和宿主机控制权。
6. Skill 发布文件名由用户输入直接拼接，缺少最终路径约束；上传和静态资源也缺少内容级校验及私有资源访问控制。

建议把后续工作分为两个明确阶段：

- **先完成平台止血和安全基线**：关闭直连、修复鉴权、停止泄密、收紧 Runtime、处理 XSS、补齐迁移与恢复能力。
- **再建设产品能力**：发布审核、Secret Vault、审计日志、评测与预算、团队协作、检索订阅等功能都应建立在可信基础之上。

## 2. 审计方法与边界

### 2.1 已覆盖内容

- FastAPI 路由、SQLAlchemy 模型、Pydantic Schema、文件存储、静态挂载和异常中间件。
- OAuth2 PKCE 前端流程、Axios 刷新逻辑、路由权限、公开页面和管理页面。
- Skill 导入、编辑、发布、GitLab/GitHub 同步。
- MCP、模型和 Agent 凭据的存储、序列化、传递和运行时注入。
- 微信、钉钉渠道的绑定、租约、幂等、Outbox、死信和 Worker。
- MySQL 与 sub2api PostgreSQL 的数据映射。
- Nginx、启动脚本、迁移脚本、日志、测试和构建流程。

### 2.2 验证方式

- 逐文件静态审查与调用链交叉检查。
- 后端语法编译：通过。
- 前端生产构建：通过。
- 选择 21 个不应调用真实 Claude、外部网关或 Docker 的本地测试脚本执行，19 个通过。
- `test_dingtalk_channel.py` 因当前沙箱无法读取 `multidict` 依赖文件未完成。这两项属于测试环境阻断，不能据此判断业务通过或失败。
- 未运行会调用真实 Claude、外部网关、Docker 或真实数据库的脚本。

### 2.3 未覆盖边界

- 未对正在运行的线上环境做渗透测试。
- 未读取或披露 `.env` 中的真实密钥值。
- 未验证 IAM 网关、sub2api 数据库和消息平台的服务端实现。
- 未做真实并发压测、故障注入、备份恢复演练和供应链漏洞联网扫描。

因此，本文中的“已确认”指代码路径可以直接证明；“潜在风险”表示需要在目标部署环境继续验证。

## 3. 系统能力地图

| 域 | 当前能力 | 主要数据/边界 |
|---|---|---|
| Skill | 导入、树形编辑、软删除、公开、版本发布、Git 同步 | MySQL 元数据 + `backend/skills/` 文件树 + release ZIP |
| MCP | stdio/SSE/HTTP/JSON 配置、公开分享、Agent 绑定 | 配置含环境变量、Header、命令和 URL，可能含密钥 |
| 模型 | 多协议模型、API Key、代理 URL、推理能力和 Runtime 兼容性 | 模型密钥与外部模型网关 |
| 提示词 | CRUD、变量、公开展示、Agent/聊天复用 | 用户可控富文本内容 |
| Agent | Skill/MCP/模型绑定、会话、工作区、流式执行、授权确认、取消 | 可执行 Bash、访问网络、读写文件和调用 MCP |
| Runtime | Claude Code directory/native/container，保留运行时扩展接口 | 主机用户、Docker、运行时密钥、网络出口 |
| 消息渠道 | 微信 iLink、钉钉 Stream，扫码绑定、租约、幂等、死信 | 外部用户标识、消息内容、渠道凭据 |
| Dashboard | 个人/汇总 Token 用量、服务和主体资源看板 | AI Hub 身份与 sub2api PostgreSQL 跨库映射 |
| IAM 管理 | 用户、角色、权限、服务、端点、PAT、OAuth Client 前端管理 | 前端调用 IAM API，后端依赖网关注入身份 |

### 3.1 当前做得较好的部分

- 大多数私有资源查询已按 `user_id` 和 `is_deleted == False` 过滤。
- Agent 工作区文件 API 对 realpath、符号链接和 `O_NOFOLLOW` 做了针对性防护。
- Channel 模块具备租约、fencing token、幂等、重试、Outbox、死信和较多并发测试。
- 聊天 Markdown 渲染使用 DOMPurify，方向正确。

这些基础可以保留，但不能抵消入口鉴权、明文回传和执行环境边界上的 P0 风险。

## 4. 风险分级

- **P0 / 上线阻断**：已确认可造成越权、密钥泄露、持久化代码执行或宿主机高影响，应立即止血。
- **P1 / 必须解决**：高概率造成数据损坏、隐私串读、拒绝服务、不可恢复或后续高成本事故，应在下一发布周期完成。
- **P2 / 重要优化**：主要影响稳定性、性能、可维护性和产品可信度，应纳入近期工程计划。
- **P3 / 产品演进**：值得新增的能力，不应早于 P0/P1 基线建设。

## 5. P0：上线阻断项

### P0-01 身份头可伪造，权限校验实际失效

> 2026-07-20 处置进度：IAM 负责签发 token，Gateway 负责验签、清洗外部身份头并重新注入 `x-user-*`；AI Hub 后端不验证 JWT。生产网络入口收口仍是上线前置条件，实施说明见 [认证与令牌安全改造](auth-security-hardening.md)。

**已确认事实**

- AI Hub 后端从 `x-user-*` 构造当前用户，身份可信边界位于 Gateway。
- Gateway 转发前删除客户端传入的全部 `x-user-*`，再根据已验证的 IAM 身份重新注入。
- AI Hub 已删除 direct JWT fallback 和全部 JWT 配置；绕过 Gateway 访问后端 API 必须由网络策略阻断。
- 前端路由权限只能隐藏页面，不能替代后端授权。

**影响**

攻击者可以冒充任意用户读取、修改或删除其 Skill、MCP、模型、Agent 和会话，也可以冒充超级管理员读取汇总看板或调用管理能力。若与 Runtime 或文件问题组合，影响可扩展到密钥和宿主机。

**立即措施**

1. 公网 Nginx 不得直连 AI Hub 后端 API；安全组、NetworkPolicy 或主机防火墙只允许 Gateway 访问后端 API 端口。
2. 保持 Gateway 对外部 `x-user-*` 头的删除与可信身份重注入，并为该行为保留回归测试。
3. 路由级权限在 Gateway fail-closed 校验；AI Hub 保留对象归属和敏感操作的后端校验。
4. AI Hub 不增加 direct JWT fallback、JWT 密钥或 auth mode 切换。

**验收标准**

- 公网无法直接连接 AI Hub 后端 API 端口；经 Gateway 提交的伪造 `x-user-*` 会被删除和覆盖。
- 普通用户无法通过伪造 header 访问其他用户资源或超级管理员接口。
- 每个敏感路由都有后端授权测试，前端菜单权限不计入安全验收。
- Gateway 未注入合法 `x-user-id` 时，后端拒绝请求而不是降级放行。

### P0-02 全平台邮箱与 Token 用量无鉴权公开

**已确认事实**

`GET /api/public/token-usage` 无任何身份依赖，直接复用全局汇总查询。代码注释明确说明会暴露全平台用户邮箱与用量，见 [backend/dashboard_routes.py](../backend/dashboard_routes.py#L341)。

**影响**

造成个人信息、用户规模、活跃度、模型消费和成本侧写泄露，也与系统约定的“汇总看板仅超级管理员/授权用户可见”直接冲突。

**立即措施与验收**

- 立即下线该公开路由，或改到经过服务认证且只返回不可逆匿名聚合数据的专用接口。
- 检查反向代理缓存、访问日志和调用方，确认历史响应是否已被外部获取。
- 如果已有公网暴露，按数据泄露事件处理，完成影响评估和必要通知。
- 未认证请求不得获得邮箱、用户名、单用户用量或可重新识别用户的数据。

### P0-03 公开 MCP 解密并返回完整凭据

**已确认事实**

- `McpService.config` 属性读取时会解密完整配置，见 [backend/models.py](../backend/models.py#L96)。
- 公开响应继承包含 `config` 的基础 Schema，见 [backend/schemas.py](../backend/schemas.py#L102) 和 [backend/schemas.py](../backend/schemas.py#L145)。
- 公开 MCP 页面展示和复制 `env`、`headers`、URL 及完整 JSON，见 [frontend/src/views/public/PublicMcpDetail.vue](../frontend/src/views/public/PublicMcpDetail.vue#L50) 和 [frontend/src/views/public/PublicMcpDetail.vue](../frontend/src/views/public/PublicMcpDetail.vue#L168)。

**影响**

API Token、Authorization Header、数据库 URL、私有 MCP 地址或命令参数可能被任何匿名访问者直接获取。数据库“已加密”不能防止应用层主动解密后公开返回。

**立即措施**

- 公开 MCP 只能包含安装模板和凭据占位符，绝不能返回实例凭据。
- 将“可公开的模板配置”和“用户私有 Secret override”拆成不同模型与 API。
- 私有管理接口也默认返回 redacted 配置；密钥字段采用 write-only 语义。
- 盘点所有已公开 MCP，立即轮换可能已经暴露的密钥。

**验收标准**

- 匿名和普通详情响应中不存在 Token、Header value、环境变量 value 或私有 URL。
- 日志、错误响应、导出和 Agent 配置快照同样不含未脱敏凭据。
- 安全测试使用 canary secret，扫描所有公开响应确认零命中。

### P0-04 模型 API Key 被列表和详情接口明文返回

**已确认事实**

- `AIModel.api_key` 属性返回解密后的完整 key，见 [backend/models.py](../backend/models.py#L151)。
- `ModelResponse` 强制包含 `api_key: str`，列表也使用该响应，见 [backend/schemas.py](../backend/schemas.py#L161) 和 [backend/schemas.py](../backend/schemas.py#L185)。
- 前端视觉遮罩不能改变完整 key 已进入浏览器、代理日志和调试工具的事实。

**影响**

任意前端 XSS、浏览器扩展、共享终端、代理日志或前端错误上报都可能拿到所有模型密钥。

**立即措施与验收**

- 响应只返回 `has_api_key`、`last_four`、`key_version` 等非敏感元数据。
- 更新时空 key 表示“不修改”，新 key 只允许写入，保存后不可再次读取。
- Agent 使用密钥时由服务端按运行实例临时注入，不通过浏览器中转。
- 轮换所有曾经通过现有 API 返回过的模型密钥。
- 抓取列表、详情、创建和更新响应，确认完整 key 从未出现。

### P0-05 存在持久化 XSS，上传目录还能承载同源主动内容

**已确认事实**

- 公开提示词和管理详情把用户内容直接传给 `v-html`，只替换变量标记，没有 HTML 转义或清洗，见 [frontend/src/views/public/PublicPromptTemplateDetail.vue](../frontend/src/views/public/PublicPromptTemplateDetail.vue#L67) 和 [frontend/src/views/admin/PromptTemplateDetail.vue](../frontend/src/views/admin/PromptTemplateDetail.vue#L85)。
- access token 和 refresh token 存放于 `localStorage`，见 [frontend/src/stores/auth.js](../frontend/src/stores/auth.js#L121) 和 [frontend/src/api/request.js](../frontend/src/api/request.js#L37)。
- 图片上传只相信客户端 `Content-Type` 前缀，并保留原扩展名；静态服务会按扩展名重新推断响应类型，见 [backend/main.py](../backend/main.py#L243)、[backend/main.py](../backend/main.py#L826) 和 [backend/main.py](../backend/main.py#L895)。攻击者可以声明 `image/*` 上传 `.html` 或主动 SVG，再通过同源 `/uploads/` 执行脚本。
- Nginx 未设置 CSP 和 `X-Content-Type-Options: nosniff`。

**影响**

可形成“写入公开提示词或上传主动文件 -> 其他用户访问 -> 窃取本地令牌 -> 冒充用户”的完整链路。

**立即措施**

- 提示词高亮先 HTML escape，再插入受控 `<mark>`；所有 `v-html` 必须经过 DOMPurify 白名单。
- 上传仅接受明确的 raster 格式，检查 magic bytes，并用图像库解码后重新编码；拒绝 SVG、HTML、XML 和双扩展名。
- 上传文件使用服务端生成的固定扩展名，设置 `nosniff`，非展示型附件使用 `Content-Disposition: attachment`。
- 增加严格 CSP，逐步移除 inline script/style 依赖。
- 中期采用 BFF 或 HttpOnly/Secure/SameSite Cookie，使 refresh token 不再暴露给 JavaScript。

**验收标准**

- `<img onerror>`, `<svg onload>`, `<script>` 等 payload 在公开和管理页面只显示为文本。
- 伪造 MIME 的 HTML/SVG 上传被拒绝，已上传历史文件完成扫描和清理。
- CSP 报告模式无关键违规后转为强制模式。

### P0-06 Agent 执行环境可读取后端 Secret，生产服务账号权限接近 root

**已确认事实**

- Claude Code Runtime 用 `**os.environ` 构造子进程环境，见 [backend/runtimes/claude_code.py](../backend/runtimes/claude_code.py#L569)；真正启动子进程时仍把该完整环境传入，见 [backend/runtimes/claude_code.py](../backend/runtimes/claude_code.py#L610)。
- native 模式虽然额外通过 stdin 转发白名单，但 runner 只 `os.environ.update()`，没有清空继承环境，见 [backend/sandbox/native.py](../backend/sandbox/native.py#L42)；root 分支使用 `runuser`，不能假设会自动清除全部环境，见 [backend/sandbox/native.py](../backend/sandbox/native.py#L395)。
- 默认 `directory` 沙箱明确没有文件系统隔离，见 [backend/sandbox/directory.py](../backend/sandbox/directory.py#L1)。
- Agent 默认允许 Bash、读写、WebFetch、WebSearch、Task 和全部已绑定 MCP，并使用 `acceptEdits`，见 [backend/agent_workspace.py](../backend/agent_workspace.py#L441)。
- 生产文档要求服务账号加入 Docker 组并配置 `NOPASSWD: ALL`，见 [docs/production-deployment.md](production-deployment.md#L17) 和 [docs/production-deployment.md](production-deployment.md#L39)。两者均接近宿主机 root 能力。

**影响**

模型提示注入、恶意 Skill/MCP、工具链漏洞或普通应用漏洞都可能读取 `DATABASE_URL`、加密主密钥、服务 Token、渠道密钥等，再通过网络外传。后端账号一旦被攻破，还可控制 Docker 或通过 sudo 接管主机。

**立即措施**

1. 子进程环境从空字典开始构造，只加入运行必需变量；native runner 在注入前执行 `os.environ.clear()` 或等效的 clean-env 启动。
2. 生产启动时拒绝 `directory` 沙箱，不允许静默回退。
3. Agent 工具策略改为按用途授权，默认拒绝 Bash 和任意网络出口；高风险操作需要每次确认。
4. 使用按 Agent/Run 作用域、短时有效的 Secret broker，不向运行时注入平台主密钥。
6. 用最小权限 helper/sidecar 代替 `NOPASSWD: ALL`；将 Docker 控制面和 Web API 进程分离。

**验收标准**

- 在 Agent 中执行 `env` 和读取 `/proc/self/environ` 看不到数据库、加密密钥、渠道密钥或服务 Token。
- directory 模式在 production profile 下启动失败。
- Agent 默认不能访问宿主机 metadata、MySQL、Docker socket、其他 Agent Cell 或未授权公网主机。
- Web API 账号不在 docker 组，也没有任意 sudo 权限。

### P0-07 Skill 发布路径和静态下载缺少安全边界

**已确认事实**

- 发布根目录名、ZIP entry 和服务器文件名直接拼接用户可控的 Skill name、version 和节点 label，见 [backend/main.py](../backend/main.py#L521)。服务器最终路径没有 realpath containment 校验。
- `SkillRelease` 没有 `(skill_id, version)` 唯一约束；先查询再插入存在并发竞态，见 [backend/models.py](../backend/models.py#L63)。
- `/releases` 和 `/uploads` 由 StaticFiles 全量公开，见 [backend/main.py](../backend/main.py#L58)。静态层不知道记录是否私有、已删除或已经撤回。
- Skill 软删除会清除当前文件树和封面，但不会删除历史 release ZIP 和 release 记录，见 [backend/main.py](../backend/main.py#L213)。

**影响**

恶意名称可能导致写出 release 目录；私有、撤回或已删除资产的旧 URL 仍可能长期访问；并发发布可能产生重复版本或孤儿文件。

**立即措施与验收**

- 数据库展示名与存储文件名彻底分离；存储键只使用服务端 UUID/数字 ID。
- 所有落盘前做 canonical path containment 校验，ZIP entry 统一使用 POSIX 安全相对路径。
- version 使用长度限制和 SemVer/受控格式，数据库增加唯一约束。
- 私有下载改为鉴权端点或短时签名 URL；静态目录只保存真正公开且不可变的制品。
- 发布采用临时文件、fsync/原子 rename、DB 状态机和失败补偿；删除/撤回时执行可审计清理。
- 使用绝对路径、`..`、盘符、斜杠和并发请求做回归测试，均不得越界或重复。

## 6. P1：必须解决的问题和高风险隐患

> 2026-07-19 处置进度：P1-02、P1-03 的代码修复已随认证改造完成；生产仍需转换 public client、替换前端制品并轮换历史 secret。下表保留原始审计事实用于追溯。

| ID | 问题 | 影响 | 证据 | 建议 |
|---|---|---|---|---|
| P1-01 | Agent internal permission request/decide 无服务认证 | 可伪造待授权事件、轮询决定、干扰运行并造成信息泄露/DoS | [backend/agent_permission.py](../backend/agent_permission.py#L109) | 使用独立 service identity、mTLS 或短时 run-scoped HMAC；限制为内部网络；加入速率限制和审计 |
| P1-02 | OAuth 请求未生成和校验 `state` | 登录 CSRF、回调混淆和流程完整性不足 | [frontend/src/stores/auth.js](../frontend/src/stores/auth.js#L41)、[frontend/src/views/AuthCallback.vue](../frontend/src/views/AuthCallback.vue#L38) | 每次登录生成高熵 state，session 绑定并一次性校验；失败立即清理 verifier |
| P1-03 | 前端支持 `VITE_OAUTH2_CLIENT_SECRET` | 一旦配置会被打进公开 JS，形成“公开客户端持有 secret”的错误模型 | [frontend/src/stores/auth.js](../frontend/src/stores/auth.js#L63)、[.env.example](../.env.example#L14) | PKCE SPA 不配置 client secret；如需 confidential client，迁到 BFF |
| P1-04 | Git access token 明文存库 | 数据库备份、只读账号或 SQL 注入可直接泄露仓库凭据 | [backend/models.py](../backend/models.py#L49)、[backend/git_routes.py](../backend/git_routes.py#L50) | 迁入统一凭据加密/Vault，write-only API，旧 token 重加密和轮换 |
| P1-05 | GitLab 仓库地址可指向任意主机 | 后端可被利用访问内网、云 metadata 或本机服务 | [backend/git_client.py](../backend/git_client.py#L426) | HTTPS-only、DNS/IP 解析后拒绝私网/环回/link-local、重定向逐跳校验、管理员 host allowlist |
| P1-06 | Git archive 和 Skill ZIP 缺少总量约束 | ZIP bomb、超大仓库、过多文件和内存耗尽 | [backend/git_client.py](../backend/git_client.py#L150)、[backend/main.py](../backend/main.py#L351) | 流式读取；限制压缩包、解压总量、文件数、深度、压缩比和单文件；超限立即中止 |
| P1-07 | Skill 文件保存先删旧目录，再逐项校验和写入 | 任一非法节点或写入失败会让原内容丢失 | [backend/skill_utils.py](../backend/skill_utils.py#L20) | 先完整校验，在同盘临时目录写完后原子切换；保留旧快照用于回滚 |
| P1-08 | DB 与文件系统操作不具事务性，部分异常被吞掉 | 数据库显示成功但文件缺失，或文件成功而 DB 回滚；长期产生孤儿数据 | [backend/main.py](../backend/main.py#L152)、[backend/main.py](../backend/main.py#L490) | 引入状态机/outbox/补偿任务；错误不得只 `print` 后继续成功；定期一致性巡检 |
| P1-09 | 上传 MIME 之外缺少像素、维度和解码限制 | 解压炸弹、畸形图片、磁盘/内存消耗 | [backend/main.py](../backend/main.py#L261) | 解码重编码、像素上限、维度上限、统一格式和恶意样本测试 |
| P1-10 | sub2api 个人身份按邮箱前缀/用户名模糊匹配 | 不同系统用户可能串读其他人的用量 | [backend/dashboard_routes.py](../backend/dashboard_routes.py#L358) | 建立不可变的一对一外部 subject 映射表；冲突时 fail closed，禁止猜测匹配 |
| P1-11 | 汇总用户详情把 AI Hub user ID 当 sub2api user ID | 两库 ID 不一致时返回错误用户数据 | [backend/dashboard_routes.py](../backend/dashboard_routes.py#L640) | 路由参数明确为 sub2api ID，并通过映射表授权；不要比较不同命名空间的整数 ID |
| P1-12 | `create_all()` 在 import 阶段运行，迁移由无版本表的 SQL 脚本管理 | 多实例启动竞态、半迁移、不可回滚、环境 schema 漂移 | [backend/main.py](../backend/main.py#L41)、[backend/migrations](../backend/migrations) | 使用 Alembic 或等效版本化迁移；部署先备份、单独 migrate、验证，再滚动发布 |
| P1-13 | 没有应用级 liveness/readiness/metrics | 进程存在不代表 DB、sub2api、Worker、Runtime 可用；无法自动摘流 | [backend/main.py](../backend/main.py#L98) | 增加 `/livez`、`/readyz`、受保护 `/metrics`；分别检查依赖、迁移版本和 Worker 心跳 |
| P1-14 | 生产账号同时拥有 Docker 和任意 sudo | 任一 Web/Worker RCE 可升级为宿主机 root | [docs/production-deployment.md](production-deployment.md#L17) | API、Runtime supervisor、Channel worker 分账号/进程；特权操作使用最小命令 allowlist |
| P1-15 | Nginx 缺安全头、限流且允许 2000 MB body | XSS 防线弱，登录/API/上传易被滥用和耗尽资源 | [aihub.nginx.conf](../aihub.nginx.conf#L26) | CSP、HSTS、nosniff、Referrer-Policy、合理 body 限制、连接/请求速率限制和超时分层 |
| P1-16 | 缺少业务审计日志和密钥访问审计 | 无法回答谁公开、下载、运行、改密钥或授权了高风险工具 | 全局缺失 | 建立 append-only 审计事件，记录 actor、resource、action、result、request/run ID，敏感值永不入日志 |
| P1-17 | 缺少数据库、文件、release、Runtime 状态的统一备份恢复方案 | 软删除同时物理删文件，故障或误操作后不可恢复 | [backend/main.py](../backend/main.py#L213)、[backend/skill_utils.py](../backend/skill_utils.py#L112) | 定义 RPO/RTO；数据库与对象文件一致性快照；定期恢复演练；删除先进入可恢复保留期 |
| P1-19 | 资源名称、release 版本等缺少数据库唯一约束 | 并发下重复、UI 歧义、同步覆盖和不可预测选择 | [backend/models.py](../backend/models.py#L27) | 按业务定义增加 `(user_id, normalized_name, active)`、`(skill_id, version)` 等约束和冲突响应 |
| P1-20 | Skill/MCP/模型列表的 `skip/limit` 多数没有边界 | 负值或超大 limit 可造成慢查询、内存压力和批量数据暴露 | [backend/main.py](../backend/main.py#L104) | 统一分页依赖：`skip >= 0`、`1 <= limit <= 100`、稳定排序和游标分页 |

## 7. P2：重要优化项

### 7.1 API 与数据模型

1. **拆分输入、私有响应和公开响应 Schema。** 当前多个 response 继承 create base，导致 `config`、`api_key`、`is_deleted`、评分等输入字段意外进入响应。每个边界应显式列字段。
2. **禁止客户端写平台统计字段。** `SkillBase` 允许客户端提交 `rating`、`comment_count`、`is_deleted`，会破坏市场数据可信度，见 [backend/schemas.py](../backend/schemas.py#L6)。
3. **统一软删除语义。** cover 上传/删除等子资源查询没有始终过滤 `is_deleted`，已删除记录仍可能被修改，见 [backend/main.py](../backend/main.py#L243) 和 [backend/main.py](../backend/main.py#L826)。
4. **定义级联与保留策略。** Agent、会话、消息、运行、绑定、release 和关联表目前混合使用软删、状态删除和物理文件删除，应按资源生命周期明确处理。
5. **增加乐观并发控制。** Skill 文件编辑、Agent 配置和 MCP 配置应带 `version`/ETag，避免两个页面互相覆盖。
6. **统一错误码。** 目前大量逻辑依赖中文 `detail` 文本；应返回稳定的 machine-readable `error_code` 和 request ID。
7. **谨慎使用全局响应包装。** [backend/middleware.py](../backend/middleware.py#L35) 会缓冲并再次序列化整个 JSON body，增加内存、延迟和 content-length 风险；204、文件、流式和大响应需要明确跳过。
8. **全局异常必须记录。** [backend/exception_handlers.py](../backend/exception_handlers.py#L40) 返回 500 但不记录异常和 request ID，生产故障无法定位。

### 7.2 性能与容量

1. 当前搜索使用前后 `%LIKE%`，数据增长后普通索引难以生效；应为公开目录增加全文检索或专用搜索索引。
2. 多个列表先 `count()` 再查 items，复杂关联和大表下成本较高；需要慢查询监控、复合索引和分页策略。
3. Skill import、release ZIP 和工作区上传仍在内存中聚合完整内容；应统一流式存储和配额。
4. 前端构建成功，但主入口约 1.22 MB、AgentChat chunk 约 1.01 MB（未压缩）；应按图标、编辑器、语言包和图表库分包，避免一次加载全部能力。
5. ignored 的 Agent workspace 内每个 Agent 都创建独立 `.venv`，会快速消耗 inode 和磁盘；应使用共享只读运行环境、镜像层或有配额的缓存。
6. Worker 需要公开队列深度、lease takeover、重试、死信、run latency、Token/费用和 Cell 数量等容量指标。

### 7.3 前端工程

1. `package.json` 只有 dev/build/preview，没有 lint、format check、typecheck、unit test 或 E2E test。
2. `ShareView.vue` 调用仓库中不存在的 `/api/public/share/*` 后端端点，属于可访问的死功能，见 [frontend/src/views/public/ShareView.vue](../frontend/src/views/public/ShareView.vue#L40)。应实现受控分享模型或删除路由。
3. `AssetList.vue` 仅显示“功能开发中”且未形成完整路由；`HelloWorld.vue` 等 Vite 示例资产仍残留。占位能力应从生产导航移除。
4. 多个 Vue 单文件超过 1000 行，`AdminSkillDetail.vue` 约 1845 行、`AgentChat.vue` 约 1338 行；应按数据获取、状态机和展示组件拆分。
5. 路由 permission 字符串与业务权限命名不一致，例如 Agent 页面使用 `aihub:skill:page:manage`，容易形成复制粘贴式授权错误，见 [frontend/src/router/index.js](../frontend/src/router/index.js#L100)。
6. 前端 permission wildcard 转换没有转义正则特殊字符，虽然只影响 UI，但会造成错误显示；统一使用后端返回的布尔能力或安全 matcher。

### 7.4 后端工程与依赖

1. Python 版本约定冲突：说明写 3.8+，`pyproject.toml` 要求 3.11，代码使用 `X | None` 等至少 3.10 的语法。建议统一为 Python 3.11 或 3.12。
2. Python 依赖只有 requirements，无锁文件哈希、依赖分组和自动升级策略；生产与测试依赖也未分离。
3. [backend/main.py](../backend/main.py)、`channel_worker.py`、`channel_service.py`、`agent_service.py` 等文件职责过重，应按路由、领域服务、仓储和集成适配器拆分。
4. 代码混用 `print` 和 logging，错误有时被吞掉；应使用结构化日志和统一 redaction filter。
5. 日志文件以追加方式长期写入，当前工作区已有 MB 级日志；应使用系统日志/容器日志和外部轮转，禁止无限增长。
6. OpenAPI 应区分 public、user、admin、internal API；internal 路由不应出现在公开文档和公网监听面。

## 8. 各业务域专项结论

### 8.1 Skill 与 Git

**必须先做**

- 修复发布路径、ZIP 配额、文件原子替换、Git SSRF、Git token 存储和静态下载授权。
- 发布版本必须不可变；编辑草稿不能悄悄改变已经发布的 ZIP。
- 导入前做结构、路径、总量、编码、必需文件和元数据校验。

**随后优化**

- 以 manifest 表达兼容 Runtime、依赖、入口、权限、许可证、维护者和最低平台版本。
- Git pull/push 使用 job 状态机，不让长请求占用 Web worker；展示 diff、冲突文件和可重试结果。
- 对公开 Skill 做恶意文件、Secret、许可证和依赖扫描。

### 8.2 MCP

**必须先做**

- 模板和 Secret 分离，所有 secret write-only。
- 对 stdio 命令、HTTP URL、Header、环境变量定义风险级别和允许范围。
- Runtime 只获得当前 Run 需要的 MCP Secret，不能获得整个用户 Secret 集合。

**随后优化**

- MCP capability discovery、健康检查、超时、版本、权限声明和最近成功时间。
- 安装向导要求用户为模板占位符填写自己的凭据。
- 公开目录显示“是否需要网络、文件、Shell、外部数据写入”等权限标签。

### 8.3 模型

**必须先做**

- 模型 key 改为 write-only，历史 key 轮换。
- proxy URL 执行和健康检查也要防 SSRF，应用 DNS/IP/rebind 防护。
- 模型调用记录不能包含 Authorization header 和完整 prompt 中的高敏数据。

**随后优化**

- 连接测试、延迟/错误率/费用健康面板。
- fallback、限流、最大上下文、模型能力和数据出境策略。
- 对 Agent 绑定做成本上限和协议兼容预检。

### 8.4 Agent、Runtime 与渠道

**必须先做**

- 清理进程环境、强制生产隔离、最小化工具和网络权限。
- internal API 服务认证、Run/Agent/用户三重归属校验。
- 主机特权从 Web API 拆出，Runtime Cell 网络隔离。
- 对消息内容、raw payload、工具输入、reasoning 和会话定义保留与删除策略。

**已有基础可继续利用**

- Run lease、fencing、cancel、Outbox、幂等和死信实现方向正确。

**随后优化**

- 每次 Run 的配置快照、模型版本、Skill 版本、MCP 版本和环境摘要，支持可复现执行。
- 队列优先级、用户并发、Token/费用预算、超时和取消 SLA。
- 渠道管理页统一展示绑定租约、积压、重试、死信和最近错误，并支持受控重放。

### 8.5 Dashboard 与 IAM

**必须先做**

- 删除公开全局用量接口。
- 建立 AI Hub subject 到 sub2api user 的显式映射，不再用邮箱前缀或整数 ID 猜测。
- 后端执行真实 RBAC，不把权限只放在网关配置和前端菜单。

**随后优化**

- 统一“超级管理员、staff、具体 permission”的权限语义和文档。
- 对成本数据设置最小粒度、导出权限、水印和访问审计。
- Dashboard 查询设置超时、缓存和熔断，避免 sub2api 故障拖垮主 API。

## 9. 值得新增的功能

下列建议按“风险降低与平台价值”排序。P3 功能不应抢占 P0/P1 资源。

| 优先级 | 功能 | 价值 | 关键设计前提 |
|---|---|---|---|
| F1 | Secret Vault 与引用式凭据 | 从根本上消除前端回传和跨资源复制 Secret | write-only API、作用域、轮换、审计、短时凭据 |
| F1 | 全局审计日志与安全事件中心 | 可追踪公开、下载、授权、运行、密钥变更和管理员操作 | append-only、actor/resource/request/run ID、脱敏与保留策略 |
| F1 | 发布审核与安全扫描 | 降低公开 Skill/MCP 的恶意代码、Secret、许可证和供应链风险 | 草稿/审核/发布状态机、扫描结果不可绕过 |
| F1 | 版本不可变、回滚和归档 | 解决当前发布物与编辑态耦合、不可恢复问题 | 内容寻址制品、SemVer、签名、原子发布 |
| F1 | 组织/团队/项目空间 | 当前只有“用户私有或全公开”，缺少企业协作层 | 明确 owner、member、viewer、publisher 和资源继承规则 |
| F2 | MCP 能力发现和健康中心 | 提高 MCP 可用性与安装成功率 | 模板/Secret 分离、探测隔离、SSRF 防护 |
| F2 | Agent 运行中心 | 统一查看排队、执行、取消、工具授权、错误、费用和重放 | 可复现 snapshot、状态机和审计事件 |
| F2 | Agent 评测与回归集 | 防止 Skill/模型/提示词更新导致效果回退 | 数据集权限、基线、评分器、成本控制和版本绑定 |
| F2 | 用户/团队预算和配额 | 控制 Token、费用、并发、运行时长、消息渠道滥用 | 实时计量、硬/软阈值、告警和管理员豁免审计 |
| F2 | 模型路由、健康与 fallback | 降低单模型故障并优化成本/延迟 | 密钥安全、能力矩阵、可观测性、数据地域策略 |
| F2 | 全局搜索与标签治理 | 提升 Skill/MCP/提示词发现效率 | 规范标签、全文索引、权限过滤和排序解释 |
| F2 | 收藏、订阅与变更通知 | 让用户感知公开资源新版本和安全公告 | 不可变版本、发布事件、通知偏好 |
| F3 | 评分、评论与举报 | 替代当前可由客户端填写的假评分字段 | 真实评价表、反滥用、审核、聚合一致性 |
| F3 | 受控分享链接 | 补全当前残留 ShareView | 随机 token hash、有效期、撤销、访问次数、权限范围和审计 |
| F3 | 数据导出、导入与租户生命周期 | 支持迁移、合规和账号删除 | Secret 排除/重加密、异步任务、保留与法律冻结 |
| F3 | 资产管理 | 若“数字资产”确为产品方向，可统一数据集、附件、评测集和制品 | 先明确资产类型、权限、版本、存储和生命周期；否则删除占位页 |

### 9.1 不建议现在优先做的事情

- 在鉴权和 Secret 泄露修复前扩大公开市场、外部分享或匿名访问。
- 在 Runtime 隔离前增加更多高权限工具、浏览器自动化或宿主机集成。
- 在迁移和备份体系建立前做大规模表结构扩展。
- 在真实评分模型建立前继续展示客户端可编辑的 rating/comment_count。
- 同时维护多个没有统一安全基线的 Runtime 实现；应先定义共同 Runtime contract。

## 10. 建议路线图

### 阶段 0：立即止血，0-3 天

1. 关闭后端公网直连，只保留可信网关入口；过滤外部身份头。
2. 下线 `/api/public/token-usage`。
3. 关闭公开 MCP config，模型响应移除 API key。
4. 暂停或清洗提示词 `v-html`，拒绝 HTML/SVG 主动上传。
5. 生产强制禁用 directory sandbox，临时限制 Agent Bash/网络工具。
6. 暂停存在路径风险的 Skill 发布，直到存储名与展示名分离。
7. 轮换已经可能暴露的 MCP、模型、Git 和平台凭据。

**阶段门禁**：身份伪造、公开泄密、XSS canary、Agent 读取平台环境和发布路径越界测试全部失败闭合，才允许恢复公网流量。

### 阶段 1：安全与数据基线，1-2 周

1. 完成后端 RBAC、可信身份协议、OAuth state 和 internal service auth。
2. 上线 Secret write-only API、统一 redaction 和最小运行时注入。
3. 修复 Skill 原子保存、ZIP 配额、Git SSRF、静态资源授权和 release 生命周期。
4. 建立显式 sub2api 身份映射。
5. 收紧 Nginx、安全头、限流和 body 大小。
6. 拆分 Web API 与特权 Runtime supervisor 的系统账号和权限。

**阶段门禁**：安全回归测试进入 CI；不存在 P0；P1 中权限、凭据、文件和 Runtime 项全部完成。

### 阶段 2：可靠性与可运营，2-4 周

1. 引入版本化迁移和 schema preflight。
2. 建立 liveness/readiness/metrics、结构化日志、trace/request/run ID 和告警。
3. 定义 RPO/RTO，完成数据库与文件一致性备份和恢复演练。
4. 增加容量配额、Worker/队列/死信监控和数据保留任务。
5. 建立统一 CI：后端、前端、安全、迁移和制品扫描。
6. 拆分超大模块并清理死路由、占位页和示例资产。

**阶段门禁**：可在预生产环境完成升级、回滚、依赖故障和恢复演练；关键告警能在 SLO 时间内触发。

### 阶段 3：产品治理与增长，4-8 周及以后

1. 发布审核、扫描、不可变版本、回滚和安全公告。
2. 团队空间、资源授权、审计中心和 Secret Vault 管理体验。
3. Agent 评测、运行中心、预算、配额和模型路由。
4. MCP 健康与能力发现、全局搜索、收藏、订阅和真实评价。
5. 受控分享、导入导出和租户生命周期。

## 11. 测试与 CI 建议

### 11.1 当前测试现状

- 后端有 26 个 `test_*.py` 文件、约 159 个函数式测试函数，覆盖 Agent、Runtime 和 Channel 较多。
- 测试主要通过每个文件的 `__main__` 手工串行调用，没有 pytest/unittest 统一发现、fixture、marker、coverage 和标准报告。
- Skill、MCP、模型、提示词、公开 API、身份伪造、上传和发布路径等核心 P0 区域缺少成体系的接口测试。
- 前端没有单元测试和 E2E 测试脚本。

### 11.2 应建立的测试层

1. **单元测试**：Schema、权限 matcher、路径规范化、Secret redaction、状态机、身份映射。
2. **API 集成测试**：真实 FastAPI app + 临时数据库 + 临时文件目录，覆盖 owner/public/admin/internal 四类边界。
3. **安全回归测试**：伪造 header/JWT、IDOR、XSS、HTML/SVG 上传、ZIP bomb、path traversal、SSRF、Secret canary、并发发布。
4. **迁移测试**：从每个受支持的历史 schema 升级到最新，重复执行幂等，失败可恢复。
5. **Runtime 合同测试**：环境变量、文件系统、网络、用户权限、资源限制、取消、超时、Secret 生命周期。
6. **前端测试**：Vitest + Vue Test Utils 覆盖 auth/refresh/权限与复杂状态；Playwright 覆盖 PKCE、公开详情、编辑发布和 Agent 聊天。
7. **故障注入**：DB commit 失败、文件写失败、Worker 宕机、lease 过期、sub2api 超时、Docker 不可用和模型超时。

### 11.3 CI 最低门禁

- Python compile、ruff/等效 lint、类型检查、统一测试和覆盖率阈值。
- 前端 lint、typecheck、unit、E2E smoke 和生产构建。
- dependency/SCA、secret scan、SAST、容器镜像和 SBOM 扫描。
- 迁移 dry-run、OpenAPI breaking-change 检查和 release 制品签名。
- P0 安全测试必须是 required check，不能手工跳过。

## 12. 可观测性、运维与数据治理基线

### 12.1 指标与告警

至少应提供：

- API 请求量、错误率、P50/P95/P99、请求体大小、认证失败和限流。
- DB pool、慢查询、连接失败、迁移版本和 sub2api 查询延迟。
- Agent queued/running/succeeded/failed/unknown/cancelled、排队时长、执行时长、Token 和费用。
- execution lease、poller lease、fencing takeover、Outbox backlog、retry、dead-letter。
- 上传、Skill/release、workspace、日志和备份的磁盘容量/inode。

告警应绑定 owner、runbook 和分级，不只发送原始异常。

### 12.2 日志与追踪

- 全链路生成 request ID；Agent/Channel 继续携带 run ID、session ID、binding ID。
- JSON 结构化日志，统一 UTC、level、service、instance、actor 和 error code。
- 建立 redaction filter，禁止记录 Authorization、Cookie、API Key、MCP env/header value、二维码和完整 webhook query。
- 工具输入、prompt、reasoning、消息内容属于业务数据，不应默认进入基础设施日志。
- 明确日志保留、访问权限、导出和删除规则。

### 12.3 备份、恢复与删除

- 数据库和文件制品需要一致时间点或可重放的关联清单，不能分别“有备份”就视为可恢复。
- Secret 备份必须加密，主密钥和密文分离保存，并测试 key rotation。
- 软删除设置可恢复窗口；窗口结束后异步清理 DB、对象、release、workspace、runtime、消息和审计允许删除的部分。
- 每季度至少做一次从空环境恢复演练，并记录 RPO/RTO 实测值。

## 13. 关键验收清单

### 13.1 安全上线门禁

- [ ] 后端端口不能从不可信网络访问。
- [ ] 外部 `x-user-*` 头被移除，身份具备可验证来源。
- [ ] 后端 RBAC 对所有敏感端点生效。
- [ ] public API 不包含邮箱、单用户用量、MCP Secret、模型 Key 或私有 URL。
- [ ] 所有用户内容输出经过上下文正确的 escape/sanitize。
- [ ] 上传不能承载 HTML/SVG/脚本，且有总量、像素和解压限制。
- [ ] Agent 无法读取平台环境、其他用户文件、Docker socket 和未授权网络。
- [ ] Web API 账号没有 Docker/root 等效权限。
- [ ] 发布/导入/Git 路径、SSRF、ZIP 和并发安全测试通过。
- [ ] 已轮换历史可能暴露的凭据。

### 13.2 可靠性上线门禁

- [ ] 数据库迁移有版本、回滚/前滚方案和自动验证。
- [ ] DB 与文件变更失败不会返回虚假成功，也不会破坏上一版本。
- [ ] liveness/readiness 能区分进程、数据库、迁移和关键依赖状态。
- [ ] 关键 Worker 有心跳、积压、死信和 lease 告警。
- [ ] 已完成一次数据库 + 文件 + Secret 的恢复演练。
- [ ] 日志有轮转、脱敏、request/run ID 和集中查询。

### 13.3 产品发布门禁

- [ ] public/private/team 权限模型明确且有测试。
- [ ] 发布物不可变，可撤回、归档和回滚。
- [ ] 公开资源经过 Secret、恶意内容和许可证扫描。
- [ ] 评分、评论、下载量等平台统计不能由资源作者直接填写。
- [ ] 占位页和无后端端点的路由不进入生产导航。

## 14. 证据索引

| 主题 | 关键文件 |
|---|---|
| 网关身份与权限 | [backend/auth.py](../backend/auth.py#L49)、[aihub.nginx.conf](../aihub.nginx.conf#L34)、[frontend/src/router/index.js](../frontend/src/router/index.js#L100) |
| OAuth 与令牌 | [frontend/src/stores/auth.js](../frontend/src/stores/auth.js#L41)、[frontend/src/views/AuthCallback.vue](../frontend/src/views/AuthCallback.vue#L38)、[frontend/src/api/request.js](../frontend/src/api/request.js#L37) |
| 公开 Token 用量 | [backend/dashboard_routes.py](../backend/dashboard_routes.py#L341) |
| MCP/模型凭据 | [backend/models.py](../backend/models.py#L77)、[backend/schemas.py](../backend/schemas.py#L100)、[backend/main.py](../backend/main.py#L709) |
| 提示词 XSS | [frontend/src/views/public/PublicPromptTemplateDetail.vue](../frontend/src/views/public/PublicPromptTemplateDetail.vue#L67)、[frontend/src/views/admin/PromptTemplateDetail.vue](../frontend/src/views/admin/PromptTemplateDetail.vue#L85) |
| 上传与静态资源 | [backend/main.py](../backend/main.py#L58)、[backend/main.py](../backend/main.py#L243)、[backend/main.py](../backend/main.py#L895) |
| Skill 导入/发布/文件树 | [backend/main.py](../backend/main.py#L351)、[backend/main.py](../backend/main.py#L521)、[backend/skill_utils.py](../backend/skill_utils.py#L20) |
| Git token/SSRF/archive | [backend/git_routes.py](../backend/git_routes.py#L50)、[backend/git_client.py](../backend/git_client.py#L150)、[backend/git_client.py](../backend/git_client.py#L426) |
| Agent 执行环境 | [backend/runtimes/claude_code.py](../backend/runtimes/claude_code.py#L569)、[backend/sandbox/directory.py](../backend/sandbox/directory.py#L1)、[backend/sandbox/native.py](../backend/sandbox/native.py#L42) |
| Agent 工具权限 | [backend/agent_workspace.py](../backend/agent_workspace.py#L441)、[backend/agent_permission.py](../backend/agent_permission.py#L109) |
| Channel 可靠性 | [backend/channel_worker.py](../backend/channel_worker.py)、[backend/channel_service.py](../backend/channel_service.py)、[backend/models.py](../backend/models.py#L377) |
| 数据库与迁移 | [backend/database.py](../backend/database.py#L8)、[backend/main.py](../backend/main.py#L41)、[backend/migrations](../backend/migrations) |
| 异常与响应包装 | [backend/exception_handlers.py](../backend/exception_handlers.py#L40)、[backend/middleware.py](../backend/middleware.py#L35) |
| 部署权限 | [docs/production-deployment.md](production-deployment.md#L10)、[aihub.sh](../aihub.sh)、[aihub.bat](../aihub.bat) |
| 工程与测试 | [backend/requirements.txt](../backend/requirements.txt)、[pyproject.toml](../pyproject.toml)、[frontend/package.json](../frontend/package.json)、[backend](../backend) |

## 15. 建议的决策顺序

在开始实现前，建议负责人按以下顺序明确决策，避免多条修复路线互相冲突：

1. **最终身份信任模型**：后端自验 JWT，还是网关签名身份/mTLS；后端是否彻底禁止公网直达。
2. **Secret 模型**：先做应用内加密 write-only，还是直接接入 Vault/KMS；Secret 如何按用户、资源和 Run 授权。
4. **公开资源模型**：公开的是可安装模板还是可运行实例；MCP 凭据必须由使用者自行提供。
5. **文件存储模型**：继续本地磁盘并做原子/备份，还是迁移对象存储和签名下载。
6. **租户与协作模型**：保持个人资源，还是引入组织/团队空间；这会决定唯一约束、审计和授权结构。
7. **迁移与发布流程**：选择 Alembic/等效工具、CI 门禁、灰度和回滚标准。

在这些决策完成前，应只做 P0 止血和不依赖架构选择的修复；新增产品功能应等待用户明确指定范围。
