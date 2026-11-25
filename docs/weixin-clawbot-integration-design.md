# AI Hub 智能体接入微信 ClawBot 设计方案

## 1. 文档信息

- **状态**：P0 与 P0.1 已实现
- **版本**：v1.1
- **日期**：2026-07-12
- **适用项目**：AI Hub
- **目标渠道**：腾讯微信 iLink Bot API
- **用户可见联系人名称**：`微信ClawBot`

## 2. 已确认的产品约束

以下约束是本方案的固定前提，不作为待讨论项：

1. 用户在 AI Hub 中为某个智能体发起微信绑定，页面展示二维码。
2. 用户使用微信扫码，并在微信手机端确认绑定。
3. 绑定成功后，微信中出现名为 `微信ClawBot` 的联系人。
4. 一个 bot 只服务扫码绑定的一个微信用户，不接受其他微信用户使用。
5. 一个智能体最多绑定一个微信 bot。
6. 一个 AI Hub 用户可以拥有多个智能体，因此可以为不同智能体分别绑定不同 bot。
7. 微信用户发送给 `微信ClawBot` 的消息进入该智能体的专属微信会话。
8. 智能体完成任务后，最终结果返回同一个微信会话。
9. 微信消息和智能体回复同步保存到 AI Hub，用户可在 Web 端查看完整历史。
10. 当前支持单聊文本和 iLink 已提供文字转写的语音消息；不支持普通微信群、图片、文件及无文字转写的原始语音。

显示名 `微信ClawBot` 只用于产品展示。系统路由、鉴权和消息关联必须使用 iLink 返回的稳定 bot ID、account ID 和微信用户 ID，禁止使用显示名作为身份标识。

## 3. Hermes 机制核验

本方案参考 NousResearch Hermes Agent 的 Weixin 适配方式。已确认的机制包括：

1. 从腾讯 iLink Bot API 申请二维码。
2. 用户微信扫码并在手机端确认。
3. 服务端获得 bot 的 `account_id`、访问 token 和 `base_url` 等连接信息。
4. Gateway 通过 `getupdates` 长轮询接收微信消息。
5. 每个 token 同一时间只能有一个有效长轮询实例。
6. 回复消息时通过 `sendmessage` 发送，并依赖入站会话提供的 `context_token`。
7. token 或会话失效后需要重新扫码。
8. 私聊是主要支持场景，普通微信群事件不应作为第一阶段能力。
9. 可通过 `getconfig` 获取短期 `typing_ticket`，再用 `sendtyping(status=1/2)` 控制手机端的“对方正在输入”状态。

参考资料：

- <https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/messaging/weixin.md>
- <https://github.com/NousResearch/hermes-agent/blob/main/gateway/platforms/weixin.py>

AI Hub 只复用这一渠道机制，不引入 Hermes 的智能体执行体系。AI Hub 现有 Agent、Skill、MCP、Model、Sandbox 和会话仍是唯一智能体运行核心。

## 4. 目标与非目标

### 4.1 目标

- 为智能体提供二维码绑定、状态查询、重新绑定和解绑能力。
- 保证一个智能体最多一个 bot、一个 bot 最多一个微信用户。
- 微信消息可靠、按顺序、幂等地进入智能体。
- 智能体最终文本可靠回传微信。
- iLink 提供语音文字转写时，将转写作为用户输入可靠地送入智能体。
- 智能体执行期间 best-effort 展示手机端“对方正在输入”状态，提示失败不得影响主任务。
- 微信会话历史能够在现有 Agent Chat 中查看。
- 服务重启、网络抖动、重复更新和发送失败时不丢消息、不重复执行任务。
- 微信入口与智能体 Runtime 解耦，支持 Claude Code 及未来其他 Runtime。

### 4.2 非目标

- 第一阶段不支持微信群。
- 当前不支持图片、文件、视频、引用消息，以及需要下载、转码或 ASR 的无文字转写语音。
- 第一阶段不向微信暴露 thinking、工具参数、工具原始结果或内部日志。
- 第一阶段不支持一个 bot 路由到多个智能体。
- 第一阶段不支持一个 bot 服务多个微信用户。
- 第一阶段不在微信中进行交互式危险工具授权。

## 5. 当前项目基础与缺口

### 5.1 可复用能力

- `backend/models.py` 已有 `Agent`、`AgentSession`、`AgentMessage`。
- Agent 已关联 Model、Skill、MCP，并具有 Runtime、超时和最大轮次配置。
- `backend/runtimes/base.py` 已定义统一 `RuntimeEvent`。
- `backend/agent_memory.py` 已负责消息持久化和历史加载。
- `backend/agent_service.py` 已包含工作区、沙箱、MCP、Runtime 和消息保存编排。
- `frontend/src/views/admin/AgentChat.vue` 已能展示文本、工具执行和历史会话。

### 5.2 必须补齐的能力

- 二维码绑定状态机和 iLink 凭据管理。
- bot 与唯一微信用户的外部身份映射。
- `getupdates` 长轮询 Worker 和单实例租约。
- 持久化 Inbox、Agent Run 队列和 Outbox。
- 外部消息 ID 幂等、同一会话串行执行和可靠重试。
- 与 SSE 解耦的智能体执行核心。
- 非浏览器渠道的权限策略。
- 渠道状态、队列积压、错误和投递结果监控。

现有 `run_agent_chat` 直接生成 SSE，并持有请求级数据库 Session。微信任务不能通过模拟浏览器请求或解析 SSE 来实现，必须先拆出渠道无关的执行服务。

## 6. 总体架构

```text
┌──────────────┐
│  微信用户     │
└──────┬───────┘
       │ 私聊 微信ClawBot
       ▼
┌──────────────────────┐
│ 腾讯 iLink Bot API    │
│ QR / getupdates / send│
└──────────┬───────────┘
           │
           ▼
┌────────────────────────────┐
│ Weixin Gateway Worker       │
│ 绑定监控 / 长轮询 / 发送     │
└──────────┬─────────────────┘
           │ MySQL Inbox/Outbox
           ▼
┌────────────────────────────┐
│ Agent Task Worker           │
│ 串行锁 / Run 状态 / 事件收集 │
└──────────┬─────────────────┘
           │
           ▼
┌────────────────────────────┐
│ Agent Execution Core        │
│ Sandbox / Skill / MCP       │
│ Claude Code / Other Runtime │
└────────────────────────────┘

AI Hub Web
   │
   ├── 绑定管理 API -> QR、状态、解绑、重连
   └── Agent Chat -> 查看微信专属会话历史
```

### 6.1 控制面

控制面由 Web 页面和 FastAPI 管理接口组成，负责：

- 校验当前用户是否拥有目标智能体。
- 创建二维码绑定任务。
- 查询扫码和连接状态。
- 执行取消绑定、重新绑定和会话重置。
- 展示 bot、微信用户、最近轮询、最近收发消息和错误状态。

所有控制面接口继续经过网关认证，使用现有 `CurrentUser` 和 Agent owner 校验。

当前前端智能体功能仅向超级管理员开放，第一阶段微信接入继承这一限制。后续向普通用户开放时，应新增 `agent.channel.manage` 权限，同时继续执行 Agent owner 校验，不能只依赖菜单可见性。

### 6.2 数据面

数据面由独立 Worker 组成，负责：

- 监控未完成二维码绑定。
- 为每个 active binding 建立唯一长轮询。
- 将 iLink 更新持久化到 Inbox。
- 将消息排入 Agent Run 队列。
- 调用智能体执行核心。
- 将最终回复写入 Outbox 并调用 iLink 发送。

iLink 使用服务端主动长轮询，因此第一阶段不需要公开 Webhook，也不需要伪造网关的 `x-user-*` 请求头。

## 7. 一对一关系模型

固定关系如下：

```text
AI Hub User 1 ── N Agent
Agent       1 ── 0..1 Weixin Binding
Binding     1 ── 1 iLink Bot Identity
Binding     1 ── 1 WeChat User Identity
Binding     1 ── 1 Active Channel Conversation
Binding     1 ── 0..N Historical Channel Conversation
Conversation 1 ── 1 Current AgentSession
```

约束说明：

- `agent_id` 在微信绑定表中必须唯一，不能只依赖前端按钮禁用。
- `(provider, provider_bot_id)` 必须唯一，防止一个 bot 被两个智能体接管。
- 每个 binding 同一时间只能指向一个 active channel conversation，但允许保留多个 closed 历史 conversation。
- conversation 一旦锁定 `external_wechat_user_id_hash`，其他 sender 永远不能触发该智能体。
- 同一个微信用户是否为自己的多个智能体分别绑定多个 bot，不受本方案限制。
- 重新绑定复用同一 binding 记录并轮换凭据，不为同一智能体创建第二条活动绑定。

## 8. 绑定状态机

### 8.1 Binding 状态

```text
unbound
   │ create QR
   ▼
qr_pending
   ▼
waiting_scan
   ▼
waiting_confirm
   ├── provider returns stable user identity ──┐
   └── no stable user identity -> pairing_required
                                                │
                                                ▼
                                              active
                                                │
                  token/session invalid ────────┤
                                                ▼
                                      reconnect_required

active -> revoking -> revoked
任意中间状态 -> error
二维码状态 -> expired / cancelled
```

### 8.2 二维码绑定流程

1. 用户在智能体渠道页点击“绑定微信”。
2. 后端在事务中锁定该智能体的 binding 行，确认不存在 active 或进行中的绑定。
3. 后端创建一次性 bind session，生成随机 state，只保存 state 哈希。
4. Worker 调用 iLink 获取二维码内容、provider QR ID 和过期时间。
5. 前端只获取二维码图片、bind session ID、状态和过期时间，不获取 token。
6. Worker 轮询二维码状态并更新 `waiting_scan`、`waiting_confirm`。
7. 手机确认后，Worker 加密保存 iLink token、account ID、base URL 和 bot ID。
8. 系统将产品显示名固定为 `微信ClawBot`。
9. 如果确认响应包含稳定微信用户 ID，将该用户写入新 conversation 并进入 `active`。
10. 如果不能取得稳定微信用户 ID，则进入 `pairing_required`，AI Hub 显示一次性配对码；用户必须在微信中向 `微信ClawBot` 发送该配对码，验证成功后锁定 sender。
11. 激活时创建新的 active channel conversation 和专属 `AgentSession`，并由 binding 的 `active_conversation_id` 唯一指向。
12. Worker 获取 binding 轮询租约并启动 `getupdates`。

二维码过期后必须创建新的 bind session，不复用过期二维码或 state。

### 8.3 解绑与重新绑定

解绑流程必须：

1. 将状态设置为 `revoking`，阻止新 Agent Run 入队。
2. 停止长轮询并释放租约。
3. 调用 provider 的撤销或退出接口；如果 provider 无对应接口，至少删除本地凭据并使轮询失效。
4. 清除 token、context token、cursor 和微信身份映射的可用状态。
5. 将状态改为 `revoked`。
6. 保留原 AgentSession 和消息历史用于审计，不继续写入。

重新绑定复用 binding 主记录，但必须创建新的 bind session、新 conversation、新凭据和新的微信专属 AgentSession。旧 conversation 改为 closed，旧会话继续只读保留。

## 9. 入站消息流程

1. Weixin Gateway Worker 使用 binding token 调用 `getupdates`。
2. 收到一批更新后，先过滤非私聊和系统事件；带非空 `voice_item.text` 的语音进入正常处理链路，无转写语音返回重试或改发文字提示；图片、文件、视频及包含这些 item 的混合消息记录为 `unsupported`。
3. 根据 provider message ID 执行幂等插入。
4. 对 sender 做 keyed hash，校验是否等于 active conversation 锁定的 `external_wechat_user_id_hash`。
5. 非绑定用户消息标记为 `rejected_sender`，不创建 Agent Run，也不消耗模型额度。
6. 将入站原始记录和新 cursor 在同一个数据库事务中提交。
7. 只有事务成功后才能继续使用新 cursor 拉取下一批消息。
8. 为合法入站消息创建 `queued` Agent Run。
9. 入站消息此时只写入 `channel_messages`，不能提前写入 `AgentMessage`。

不能提前写入 `AgentMessage` 的原因：如果 run 1 正在执行而 run 2 已排队，run 1 加载历史时不能读到尚未开始处理的 run 2 用户消息。Agent Worker 只有在获得会话串行锁并开始 run 时，才幂等追加对应用户消息。

## 10. 智能体执行流程

1. Agent Worker 通过 `SELECT ... FOR UPDATE SKIP LOCKED` 或等价租约获取 queued run。
2. 获取 `binding_id` 对应的串行锁，确保同一个微信会话同一时间最多一个 active run。
3. 再次检查 binding 为 `active`、sender 合法、Agent 未删除、Model 有效。
4. 在 run 开始时将入站正文写入专属 `AgentSession`。
5. 加载截至当前 run 的历史消息。
6. 准备隔离沙箱、Skill、MCP 和 Runtime 配置。
7. 调用渠道无关的 Agent Execution Core。
8. 结构化收集 `RuntimeEvent`，但只将最终 assistant text 作为微信回复。
9. 持久化助手消息和 token usage。
10. 在同一事务中创建 outbound message 和 Outbox 记录。
11. 将 run 标记为 `succeeded`，释放会话锁。

如果 Runtime 已开始并可能执行过工具，不得自动重跑整个任务，避免产生重复写入、重复下单或重复外部调用。仅在明确确认尚未启动 Runtime 时允许任务级重试。

## 11. 出站消息流程

1. Weixin Gateway Worker 领取待发送 Outbox。
2. 使用触发本次 run 的入站消息所携带的 `context_token`，不能只读取 conversation 的最新 token。
3. 将 Markdown 转为微信可读的纯文本或有限格式。
4. 按 provider 实际长度限制拆分消息，保持原顺序。
5. 每个发送分片使用稳定的 client message ID 或本地幂等键。
6. 调用 `sendmessage`。
7. 成功后记录 provider message ID 和 `sent_at`。
8. 网络或限流错误采用指数退避加随机抖动重试。
9. 超过最大次数进入 `dead_letter` 并产生告警。

如果 Runtime 正常结束但没有可发送的最终文本，生成固定兜底消息并记录 `empty_result`，避免微信端无响应。

thinking、tool_use、tool_result、API 密钥、文件系统路径和内部异常栈不能发送到微信。智能体失败时只发送脱敏后的用户提示和可查询 run ID。

## 12. 会话同步规则

- 每个 active binding 有且只有一个当前微信专属 `AgentSession`。
- `AgentSession.source` 设置为 `weixin_clawbot`。
- `AgentSession.source_binding_id` 指向 binding。
- 入站微信文本保存为 `role=user`。
- 最终微信回复保存为 `role=assistant`，内容仍使用现有 blocks JSON 格式。
- Web 会话列表显示微信图标和 `微信ClawBot` 来源标签。
- 第一阶段 Web 端对微信专属会话只读，防止 Web 发消息后出现“不知道是否应同步微信”的路由歧义。
- 用户可在渠道管理页执行“新建微信会话”，创建新的 AgentSession 并保留旧历史。
- Web 自己创建的普通 AgentSession 不发送到微信。

## 13. 数据模型

建议迁移文件：`backend/migrations/011_weixin_clawbot_channel.sql`。

### 13.1 `agent_channel_bindings`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | BIGINT PK | 绑定主键 |
| `user_id` | INT NOT NULL INDEX | AI Hub owner，与现有用户 ID 类型一致 |
| `agent_id` | INT NOT NULL UNIQUE | 与 `agents.id` 类型一致，强制一个智能体最多一个微信绑定 |
| `provider` | VARCHAR(30) | 固定 `weixin_ilink` |
| `display_name` | VARCHAR(100) | 固定 `微信ClawBot` |
| `provider_bot_id` | VARCHAR(200) NULL | provider 稳定 bot identity |
| `provider_account_id` | VARCHAR(200) NULL | iLink account ID |
| `access_token_encrypted` | TEXT NULL | 加密 token |
| `credential_key_version` | VARCHAR(50) NULL | 凭据加密密钥版本 |
| `api_base_url` | VARCHAR(500) NULL | 校验 allowlist 后保存 |
| `active_conversation_id` | BIGINT NULL UNIQUE | 当前唯一活动渠道会话 |
| `status` | VARCHAR(30) NOT NULL | 绑定状态 |
| `poll_cursor` | LONGTEXT NULL | getupdates 恢复位置 |
| `poller_owner` | VARCHAR(100) NULL | 当前 Worker ID |
| `poller_lease_until` | DATETIME NULL | 单 poller 租约 |
| `poller_fencing_token` | BIGINT NOT NULL | 防止过期 Worker 回写 |
| `token_expires_at` | DATETIME NULL | 如 provider 提供 |
| `last_poll_at` | DATETIME NULL | 最近成功轮询 |
| `last_inbound_at` | DATETIME NULL | 最近入站 |
| `last_outbound_at` | DATETIME NULL | 最近出站 |
| `last_error_code` | VARCHAR(100) NULL | 最近错误码 |
| `last_error_message` | TEXT NULL | 脱敏错误摘要 |
| `bound_at` | DATETIME NULL | 激活时间 |
| `revoked_at` | DATETIME NULL | 解绑时间 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |
| `version` | INT NOT NULL | 乐观锁版本 |

约束：

- `UNIQUE(agent_id)`。
- `UNIQUE(provider, provider_bot_id)`，允许未绑定阶段为 NULL。
- 更新 token、bot identity 和状态时必须持有行锁或校验 version。
- token 只允许服务端解密，任何 API 响应都不得包含密文或明文。

### 13.2 `channel_bind_sessions`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | CHAR(32) PK | bind session ID |
| `binding_id` | BIGINT INDEX | 所属 binding |
| `initiated_by_user_id` | INT INDEX | 发起绑定的 AI Hub 用户 |
| `idempotency_key` | VARCHAR(100) NULL | 创建请求幂等键 |
| `state_hash` | VARCHAR(128) | 一次性 state 哈希 |
| `provider_qr_id` | VARCHAR(200) | provider 二维码 ID |
| `qr_content_encrypted` | LONGTEXT NULL | 必要时短期加密保存 |
| `status` | VARCHAR(30) | created/waiting/scanned/confirmed 等 |
| `expires_at` | DATETIME | 过期时间 |
| `scanned_at` | DATETIME NULL | 扫码时间 |
| `confirmed_at` | DATETIME NULL | 确认时间 |
| `cancelled_at` | DATETIME NULL | 取消时间 |
| `pairing_attempt_count` | INT | 配对码错误次数 |
| `poller_owner` | VARCHAR(100) NULL | QR 状态查询 Worker |
| `poller_lease_until` | DATETIME NULL | QR 查询租约 |
| `poller_fencing_token` | BIGINT | 防止迟到 Worker 回写 |
| `error_code` | VARCHAR(100) NULL | 错误码 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

同一 binding 同一时间只允许一个未结束 bind session。MySQL 无部分唯一索引时，使用 binding 行锁加事务保证。

同一发起用户和 binding 下的 `idempotency_key` 应唯一，用于返回原 bind session。

### 13.3 `channel_conversations`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | BIGINT PK | 渠道会话主键 |
| `binding_id` | BIGINT NOT NULL INDEX | 所属 binding，可保留历史会话 |
| `external_wechat_user_id_hash` | CHAR(64) NOT NULL | 唯一允许 sender 的 keyed hash |
| `external_wechat_user_id_encrypted` | TEXT NOT NULL | 加密保存的微信用户 ID |
| `external_user_hash_key_version` | VARCHAR(50) NOT NULL | sender hash 密钥版本 |
| `agent_session_id` | INT NOT NULL UNIQUE | 与 `agent_sessions.id` 类型一致 |
| `latest_context_token_encrypted` | TEXT NULL | 仅用于状态展示和非消息操作 |
| `status` | VARCHAR(30) | active/reset/closed |
| `closed_at` | DATETIME NULL | 关闭时间 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

`latest_context_token` 不能替代每条消息保存的 context token。

约束由 binding 的 `active_conversation_id` 实现：一个 binding 任意时刻只能指向一个 active conversation。重绑或重置会话时，在同一事务中关闭旧 conversation、创建新 conversation 并切换该指针。迁移中可在两个表创建完成后再添加此外键，避免循环建表问题。

### 13.4 `channel_messages`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | BIGINT PK | 本地消息 ID |
| `binding_id` | BIGINT INDEX | 所属绑定 |
| `conversation_id` | BIGINT INDEX | 所属唯一会话 |
| `agent_session_id` | INT INDEX | 对应 AgentSession |
| `agent_message_id` | INT NULL | 对应 AgentMessage |
| `agent_run_id` | CHAR(32) NULL | 对应执行 |
| `direction` | VARCHAR(10) | inbound/outbound |
| `provider_message_id` | VARCHAR(200) NULL | provider 消息 ID |
| `client_message_id` | VARCHAR(100) NULL | 出站幂等 ID |
| `message_type` | VARCHAR(30) | text/system/unsupported |
| `content` | LONGTEXT NULL | 规范化正文 |
| `raw_payload_encrypted` | LONGTEXT NULL | 可选短期保存原始事件 |
| `context_token_encrypted` | TEXT NULL | 该消息自己的 context token |
| `status` | VARCHAR(30) | received/queued/sent/dead_letter 等 |
| `attempt_count` | INT | 尝试次数 |
| `next_attempt_at` | DATETIME NULL | 下次尝试时间 |
| `error_code` | VARCHAR(100) NULL | 错误码 |
| `error_message` | TEXT NULL | 脱敏错误摘要 |
| `provider_created_at` | DATETIME NULL | provider 时间 |
| `created_at` | DATETIME | 本地创建时间 |
| `updated_at` | DATETIME | 更新时间 |

约束：

- 入站唯一键：`UNIQUE(binding_id, direction, provider_message_id)`。
- 出站唯一键：`UNIQUE(binding_id, client_message_id)`。
- raw payload 应设置短期保留策略，不长期保存无必要的微信隐私数据。

### 13.5 `agent_runs`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | CHAR(32) PK | run ID |
| `agent_id` | INT INDEX | 智能体，与 `agents.id` 类型一致 |
| `session_id` | INT INDEX | AgentSession，与 `agent_sessions.id` 类型一致 |
| `user_id` | INT INDEX | AI Hub owner |
| `source` | VARCHAR(30) | `web` 或 `weixin_clawbot` |
| `source_message_id` | BIGINT NULL UNIQUE | 入站 channel message |
| `status` | VARCHAR(30) | queued/running/succeeded/failed/timed_out/cancelled/unknown |
| `worker_id` | VARCHAR(100) NULL | 执行 Worker |
| `lease_until` | DATETIME NULL | 运行租约 |
| `heartbeat_at` | DATETIME NULL | 最近执行心跳 |
| `deadline_at` | DATETIME NULL | 最晚完成时间 |
| `cancel_requested` | BOOLEAN | 取消标记 |
| `config_snapshot` | LONGTEXT NULL | 开始写入本轮会话时观察到的安全配置 |
| `started_at` | DATETIME NULL | 开始持久化本轮用户消息的时间 |
| `finished_at` | DATETIME NULL | 结束时间 |
| `error_code` | VARCHAR(100) NULL | 错误码 |
| `error_message` | TEXT NULL | 脱敏错误 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

`config_snapshot` 只保存模型 ID、Runtime、Skill/MCP ID、权限策略、超时等非秘密配置，禁止包含模型 API key、channel token 或 context token。当前实现将其定义为执行开始时的审计观察值，不承诺冻结入队后发生的 Agent 配置修改。

### 13.6 `channel_outbox`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | BIGINT PK | Outbox ID |
| `binding_id` | BIGINT INDEX | 所属 binding |
| `run_id` | CHAR(32) INDEX | 对应 Agent Run |
| `channel_message_id` | BIGINT UNIQUE | 对应 outbound message |
| `part_no` | INT | 长回复分片序号 |
| `payload` | LONGTEXT | 已规范化的发送内容 |
| `context_token_encrypted` | TEXT | 触发消息自己的 context token |
| `status` | VARCHAR(30) | pending/sending/sent/retry/dead_letter/discarded |
| `attempt_count` | INT | 尝试次数 |
| `next_attempt_at` | DATETIME | 下次发送时间 |
| `lease_owner` | VARCHAR(100) NULL | 发送 Worker |
| `lease_until` | DATETIME NULL | 发送租约 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

约束：`UNIQUE(run_id, part_no)`，保证同一个回复分片只创建一次。

### 13.7 现有表扩展

`agent_sessions` 建议新增：

- `source VARCHAR(30) NOT NULL DEFAULT 'web'`
- `source_binding_id BIGINT NULL`

Web 会话列表据此展示渠道来源并控制微信专属会话只读。

所有引用现有表的外键列必须与被引用列保持完全相同的 MySQL 类型和 signed 属性。新增表主键可使用 BIGINT；时间统一保存 UTC，外键删除策略以软删除和显式生命周期编排为主，不使用级联删除微信历史。

## 14. API 设计

所有接口返回项目现有统一响应结构。

### 14.1 查询绑定

```http
GET /api/agents/{agent_id}/channels/weixin
```

返回：

- `status`
- `enabled`，表示当前部署是否开启微信渠道能力
- `display_name`，固定为 `微信ClawBot`
- `bot_id_masked`
- `wechat_user_masked`
- `bound_at`
- `last_poll_at`
- `last_inbound_at`
- `last_outbound_at`
- `last_error`
- `session_id`

### 14.2 创建二维码

```http
POST /api/agents/{agent_id}/channels/weixin/bind-sessions
```

行为：

- 校验 owner。
- 锁定 binding 行。
- 拒绝第二个 active bot。
- 创建一次性 bind session 和后台监控任务。
- 接受 `Idempotency-Key` 请求头，防止用户重复点击创建多个二维码。

已绑定或已有未结束 bind session 时返回 `409 Conflict`。同一个 `Idempotency-Key` 重试时返回原 bind session。

返回：

- `bind_session_id`
- `qr_image_url` 或受控图片端点
- `status`
- `expires_at`

JSON 响应不返回原始二维码内容，只返回受控 `qr_image_url`。二维码响应和受控图片端点必须设置 `Cache-Control: no-store`，并再次校验 bind session 所属用户。

### 14.3 查询二维码状态

```http
GET /api/agents/{agent_id}/channels/weixin/bind-sessions/{bind_session_id}
```

前端以 2 秒间隔轮询，页面关闭或进入终态后停止轮询。

已过期且不再可恢复的 bind session 返回 `410 Gone`，响应中仍可包含终态和过期时间。

### 14.4 取消二维码

```http
POST /api/agents/{agent_id}/channels/weixin/bind-sessions/{bind_session_id}/cancel
```

### 14.5 解绑

```http
DELETE /api/agents/{agent_id}/channels/weixin
```

解绑必须是幂等操作。接口返回 `202 Accepted`，由 Worker 完成停轮询、凭据吊销和队列清理；重复调用返回当前 revoking/revoked/unbound 状态。

### 14.6 重新连接

```http
POST /api/agents/{agent_id}/channels/weixin/reconnect
```

仅用于 `reconnect_required`，内部仍创建新的 bind session。

### 14.7 重置微信会话

```http
POST /api/agents/{agent_id}/channels/weixin/session/reset
```

关闭当前 conversation，创建使用同一 bot、同一微信用户的新 conversation 和 AgentSession，再原子切换 `active_conversation_id`；不改变 bot 和微信用户绑定。

### 14.8 运维死信处理

```http
GET  /api/channels/weixin/dead-letters
POST /api/channels/weixin/dead-letters/{outbox_id}/retry
POST /api/channels/weixin/dead-letters/{outbox_id}/discard
```

仅允许超级管理员或专用权限 `agent.channel.operate` 使用。响应必须脱敏，不返回 token、context token、完整微信 ID 或原始敏感 payload。`discard` 会将该分片及同一 run 的后续分片统一标记为不再投递，从而安全解除 conversation 的顺序阻塞。

### 14.9 运维处理 unknown run

```http
GET  /api/channels/weixin/unknown-runs
POST /api/channels/weixin/unknown-runs/{run_id}/resolve
```

解决动作仅允许 `cancel` 或 `acknowledge_no_reply`，禁止自动重跑。存在 `unknown` run 时，同一 binding 的后续任务保持阻塞，直到运维人员核查并显式处理。

## 15. Agent Service 重构

建议从 `backend/agent_service.py` 提取：

```python
@dataclass
class AgentRunResult:
    run_id: str
    session_id: int
    blocks: list[dict]
    final_text: str
    usage: dict | None
    runtime_session_id: str | None
    status: str
    error: str | None


async def execute_agent_turn(
    *,
    agent_id: int,
    user_id: int,
    session_id: int,
    user_input: str,
    source: str,
    on_event: EventCallback,
    model_id: int | None = None,
    skill_id: int | None = None,
    attached_files: list[str] | None = None,
    permission_policy: str = "non_interactive_safe",
) -> AgentRunResult:
    ...
```

设计要求：

- 核心函数处理 Agent、Session、Sandbox、MCP、Runtime、Memory 和结果保存。
- 核心函数只产生结构化事件，不生成 SSE 字符串。
- Web adapter 将事件序列化为 SSE。
- Weixin adapter 仅收集最终 text 和运行状态。
- Worker 自己创建和关闭 `SessionLocal`，不能复用 HTTP 请求依赖中的 Session。
- 数据库事务不能覆盖整个长时间 Runtime 执行；运行前后分别使用短事务。
- `run_id` 必须持久化，而不是只保存在进程内 dict。

## 16. Worker 与租约

### 16.1 Weixin Gateway Worker

职责：

- 处理二维码状态任务。
- 领取 active binding 的 poller lease。
- 执行 `getupdates`。
- 持久化更新和 cursor。
- 领取 Outbox 并执行 `sendmessage`。
- 识别 token 失效并切换 `reconnect_required`。

### 16.2 Agent Task Worker

职责：

- 领取 queued run。
- 获取 binding/session 串行锁。
- 调用 `execute_agent_turn`。
- 保存结果并创建 Outbox。
- 更新 run 状态和运行心跳。

第一阶段可将两个 Worker 放在同一进程的不同异步任务组中，但代码模块和队列必须分离，便于后续独立扩容。

### 16.3 单 poller 保证

- 每个 binding 使用 `poller_owner` 和 `poller_lease_until`。
- Worker 通过原子条件更新领取租约。
- 每次成功领取租约递增 `poller_fencing_token`。
- 活跃 Worker 定期续租。
- Worker 崩溃后，其他实例只能在租约过期后接管。
- cursor、状态和 Outbox 更新必须携带当前 fencing token；旧 Worker 即使恢复也不能继续回写。
- 同一个 token 绝不能由两个进程同时调用 `getupdates`。

## 17. 幂等、顺序和重试

### 17.1 入站幂等

- 以 `(binding_id, provider_message_id)` 唯一约束去重。
- 重复 update 返回已存在记录，不创建第二个 Agent Run。
- cursor 更新必须晚于或与 Inbox 插入同事务提交。

### 17.2 会话顺序

- 每个 binding 同时只允许一个 running run。
- queued run 按 provider 时间、channel message ID 排序。
- 后收到的消息不能提前进入 AgentSession 历史。
- 不同智能体的 run 可以并行。

### 17.3 重试边界

- QR 状态查询、长轮询和出站发送可以对安全的网络错误重试。
- Runtime 未开始前可重新领取过期 run。
- Runtime 开始后不自动完整重跑。
- Worker 在 Runtime 已可能产生外部副作用后失联时，将 run 标记为 `unknown`，等待人工核查，不能改回 queued。
- Outbox 使用稳定幂等键，避免发送成功但响应丢失时产生重复回复。

## 18. 权限与安全

### 18.1 所有权

- 管理接口必须调用现有 Agent owner 校验。
- Worker 只从 binding 读取 `user_id` 和 `agent_id`，不接受外部消息提供内部用户 ID。
- bot 只接受 keyed hash 匹配已锁定微信用户 ID 的 sender。

### 18.2 凭据

- access token、context token 和必要的 QR 内容使用 AES-GCM、KMS 或等价方案加密。
- 加密密钥只通过部署环境或密钥管理服务提供。
- 凭据记录保存 key version，支持密钥轮换；微信用户 ID 使用独立 keyed hash 做比较，不能使用普通无盐哈希。
- 日志、API、异常和监控标签禁止包含完整 token。
- provider 返回的 `base_url` 必须校验 scheme 和 host allowlist，防止 SSRF。

### 18.3 智能体执行安全

微信是外部不可信输入。生产环境启用前必须满足：

- Claude Code 智能体在 Linux/WSL 中使用 `CLAUDE_CODE_SANDBOX_TYPE=native`。
- 禁止使用 `directory` 模式承接微信外部消息。
- 只允许智能体已绑定的 Skill 和 MCP。
- MCP 继续采用“绑定即授权”，绑定操作由 AI Hub owner 完成。
- 需要浏览器弹窗确认的工具在微信渠道默认拒绝。
- 不允许自动切换到扩大权限的 `bypass` 模式。
- 对消息长度、频率、并发任务和每日 token 用量设置限制。
- 工具和 MCP 的网络访问遵守现有沙箱与 allowlist。

### 18.4 配对安全

如果 iLink 在扫码确认时不能提供稳定扫码用户 ID，必须启用一次性配对码：

- 配对码至少 6 位随机值，短时有效，只可使用一次。
- 只有发送正确配对码的第一个私聊 sender 被锁定。
- 错误次数达到阈值后使配对 session 失效。
- 未配对 sender 的普通消息不能进入 Agent Run。

## 19. 错误与恢复

| 场景 | 处理 |
| --- | --- |
| 二维码过期 | bind session -> expired，允许生成新二维码 |
| 用户取消确认 | bind session -> cancelled，不保存凭据 |
| token 失效 | binding -> reconnect_required，停止新 run |
| 长轮询网络错误 | 保留 cursor，指数退避后重试 |
| Worker 崩溃 | 租约过期后由其他 Worker 接管 |
| 重复微信 update | 唯一键去重，不重复执行 |
| 非绑定 sender | 标记 rejected_sender，不运行智能体 |
| Agent 配置失效 | run failed，发送脱敏错误提示 |
| Runtime 超时 | run failed，清理沙箱，禁止自动重跑 |
| Runtime 可能已产生副作用后 Worker 失联 | run unknown，人工核查，禁止自动重跑 |
| 微信发送限流 | Outbox 延迟重试 |
| 微信发送永久失败 | dead_letter + 告警 + Web 展示 |
| 用户解绑时存在 queued run | queued run 取消，running run 请求停止 |

历史会话与消息不因 token 失效、重新扫码或解绑而删除。

### 19.1 智能体删除联动

删除已绑定微信 bot 的智能体时，`delete_agent` 必须调用渠道清理服务：

1. 在同一事务中将 binding 改为 `revoking`，拒绝新的 Inbox 和 Agent Run。
2. 取消 queued run，并对 running run 设置 `cancel_requested`。
3. 使 poller lease 失效并阻止旧 fencing token 回写。
4. 创建 provider 凭据吊销任务。
5. 将智能体软删除后，Worker 不再执行该 agent 的任何排队消息。
6. provider 吊销失败进入可重试运维任务，但本地 token 立即不可用。
7. 工作区清理必须在 running run 退出后执行，不能在 Runtime 使用工作区时直接删除。

## 20. 前端设计

新增路由：

```text
/admin/agents/:id/channels
```

新增页面：

```text
frontend/src/views/admin/AgentChannels.vue
```

页面显示：

- 渠道名称：微信
- 联系人名称：`微信ClawBot`
- 状态：未绑定、等待扫码、已扫码待确认、配对中、已连接、需重连、错误
- 二维码和过期倒计时
- 微信用户脱敏标识
- bot 脱敏 ID
- 绑定时间、最近轮询、最近消息
- 绑定、刷新二维码、取消、重新连接、解绑、新建微信会话操作

交互要求：

- 二维码弹窗关闭或进入终态后清理轮询定时器。
- 以后端 `expires_at` 为准，不使用纯前端倒计时判断有效性。
- 页面刷新后能够恢复正在进行的 bind session。
- 解绑和新建微信会话必须二次确认。
- Agent 列表或详情页显示微信连接状态，但不在聊天页内塞入二维码流程。

Agent Chat 调整：

- 会话列表显示微信来源图标和标签。
- 微信专属会话第一阶段为只读。
- 显示消息投递状态和失败提示时，不展示 provider 原始错误。

## 21. 配置与部署

建议新增环境变量：

```dotenv
WEIXIN_ILINK_ENABLED=false
WEIXIN_ILINK_DEFAULT_BASE_URL=
WEIXIN_ILINK_ALLOWED_HOSTS=*.weixin.qq.com
CHANNEL_CREDENTIAL_ENCRYPTION_KEY=
CHANNEL_ID_HASH_KEY=
CHANNEL_WORKER_ID=
CHANNEL_POLLER_LEASE_SECONDS=60
CHANNEL_RUN_LEASE_SECONDS=900
CHANNEL_BIND_POLL_INTERVAL_SECONDS=2
CHANNEL_OUTBOX_MAX_ATTEMPTS=8
CHANNEL_MAX_TEXT_CHARS=4000
CHANNEL_MAX_PENDING_MESSAGES_PER_BINDING=20
CHANNEL_MAX_DAILY_RUNS_PER_BINDING=200
```

部署要求：

- Uvicorn API 进程与 Channel Worker 分开启动。
- 生产环境不使用 `--reload`。
- MySQL 需支持 `SELECT ... FOR UPDATE SKIP LOCKED`；若版本不支持，使用条件更新加 lease 实现任务领取。
- 第一阶段不强制引入 Redis/Celery，使用 MySQL Inbox/Outbox 和独立 Worker。
- 后续并发量增加时，可将队列适配器替换为 Redis/Celery，数据表仍保留审计和幂等职责。
- `aihub.sh`、`aihub.bat` 或生产进程管理配置需要增加 Worker 的启动、停止和状态检查。
- Worker 必须支持优雅停机：停止领取新任务、释放或停止续租、等待当前安全点、保存 cursor 后退出。
- `CHANNEL_WORKER_ID` 仅作为实例前缀，Worker 会追加进程 ID 和随机后缀，避免多个副本错误共享同一租约身份。
- iLink 动态重定向 host 必须匹配 HTTPS allowlist；当前默认允许官方 `*.weixin.qq.com`，自建代理 host 需显式配置。

### 21.1 数据库迁移与回滚

- `models.Base.metadata.create_all()` 不会修改已有表，不能代替 `011_weixin_clawbot_channel.sql`。
- 部署顺序为：备份数据库 -> 执行迁移 -> 部署兼容新表的 API -> 启动 Worker -> 开启 `WEIXIN_ILINK_ENABLED`。
- 新增列应提供安全默认值，确保旧 API 代码在滚动部署期间仍可运行。
- 回滚时先关闭渠道开关并停止 Worker，再回滚应用代码。
- 生产回滚默认保留新增表和审计数据，不直接 DROP 表；需要清理时另行执行经过确认的回滚脚本。
- 迁移必须在测试数据库验证重复执行保护、锁表时间和数据回填时间。

## 22. 日志、指标与告警

### 22.1 日志字段

- `binding_id`
- `bind_session_id`
- `channel_message_id`
- `provider_message_id_hash`
- `agent_id`
- `agent_session_id`
- `run_id`
- `worker_id`
- `event_type`
- `duration_ms`

禁止记录完整微信 ID、token、context token 和完整原始 payload。

### 22.2 指标

- active binding 数量
- reconnect_required 数量
- getupdates 成功率、延迟和连续失败次数
- Inbox/Agent Run/Outbox 队列深度
- 入站去重数量
- run unknown 数量
- rejected sender 数量
- Agent Run 成功率、耗时和超时数
- 微信发送成功率、重试数和 dead letter 数
- 从入站到最终回复的端到端延迟

### 22.3 告警

- active binding 长时间无成功轮询
- token 批量失效
- 队列持续积压
- dead letter 出现
- 同一 token 检测到多个 poller
- 凭据解密失败
- Agent Run 连续失败
- run unknown 持续未处理

## 23. 文件级实施范围

预计新增：

```text
backend/channels/__init__.py
backend/channels/base.py
backend/channels/weixin_ilink.py
backend/channel_routes.py
backend/channel_service.py
backend/channel_worker.py
backend/migrations/011_weixin_clawbot_channel.sql
backend/tests/test_channel_binding.py
backend/tests/test_weixin_ingress.py
backend/tests/test_channel_worker.py
backend/tests/test_channel_outbox.py
frontend/src/api/agent-channels.js
frontend/src/views/admin/AgentChannels.vue
```

预计修改：

```text
backend/models.py
backend/schemas.py
backend/main.py
backend/database.py
backend/agent_service.py
backend/agent_routes.py
backend/agent_memory.py
backend/requirements.txt
frontend/src/router/index.js
frontend/src/components/AdminLayout.vue
frontend/src/views/admin/AgentList.vue
frontend/src/views/admin/AgentDetail.vue
frontend/src/views/admin/AgentChat.vue
frontend/src/views/admin/components/ChatSidebar.vue
.env.example
aihub.sh
aihub.bat
```

## 24. 分阶段实施

### 阶段 0：协议验证

- 使用测试账号验证二维码申请、状态查询、凭据字段和过期行为。
- 验证 `getupdates` cursor、message ID、sender ID 和 `context_token`。
- 验证 `sendmessage` 长度、幂等和限流行为。
- 验证联系人实际显示为 `微信ClawBot`。
- 验证扫码确认响应能否直接提供稳定微信用户 ID。
- 如果不能直接证明扫码用户身份，验证一次性配对码能否满足产品的一 bot 一用户要求；未获得确认前不得上线。

### 阶段 1：Agent Core 解耦

- 提取 `execute_agent_turn`。
- Web SSE 改为适配器但保持现有行为不变。
- 增加持久化 `agent_runs`。
- 补充 Agent Service 集成测试。

### 阶段 2：绑定能力

- 增加数据表、iLink client、绑定 API 和前端渠道页。
- 完成二维码状态机、凭据加密、解绑和重连。
- 强制 Agent 和 bot 一对一约束。

### 阶段 3：消息闭环

- 实现单 poller lease、Inbox、sender 校验和 Agent Run 队列。
- 实现 Outbox、`context_token` 关联和结果发送。
- Web Agent Chat 展示微信会话。

### 阶段 4：生产加固

- 切换生产隔离沙箱。
- 增加限流、配额、监控、告警和死信处理。
- 完成故障恢复、并发、重复消息和安全测试。

### 阶段 5：后续能力

- 图片、文件和原始语音下载、转码及 ASR 适配。
- 微信状态查询和取消命令。
- 显式 Web 接管模式。
- 运营后台和批量健康检查。

## 25. 测试与验收标准

### 25.1 绑定

- 同一个智能体并发创建两个二维码时，只允许一个有效 bind session。
- 已 active 的智能体不能绑定第二个 bot。
- 二维码扫描、确认、过期、取消、重新绑定状态正确。
- API 从不返回 token、context token 或完整微信用户 ID。
- 绑定后联系人显示为 `微信ClawBot`。

### 25.2 用户隔离

- 绑定微信用户可正常触发智能体。
- 第二个微信用户向该 bot 发消息时不触发智能体。
- 非 owner 的 AI Hub 用户不能查看、重连或解绑。
- 一个 bot ID 不能关联两个智能体。

### 25.3 消息可靠性

- 同一 provider message 重复 10 次只执行一次 Agent Run。
- 同一微信用户连续发送多条消息时严格顺序处理。
- run 1 的历史不包含尚未开始的 run 2 消息。
- Worker 在 Inbox 提交前崩溃不会移动 cursor。
- Worker 在 Inbox 提交后崩溃可通过幂等恢复。
- API 或 Worker 重启后 queued run 和 Outbox 不丢失。

### 25.4 智能体执行

- 微信和 Web 使用同一 Agent 配置、Skill、MCP 和 Runtime。
- 微信只收到最终文本，不收到 thinking 和工具原始数据。
- Agent 超时、模型无效和沙箱失败时状态及用户提示正确。
- Runtime 开始后的失败不会自动完整重跑。
- Runtime 可能已产生副作用后 Worker 失联时进入 unknown，不能被其他 Worker 自动领取。

### 25.5 出站

- 使用触发消息自己的 `context_token` 回复。
- 长回复按顺序拆分。
- 临时失败会重试，永久失败进入 dead letter。
- 发送成功但响应丢失时不会无限重复发送。

### 25.6 安全与运行

- `directory` 沙箱配置下拒绝启用生产微信渠道。
- provider `base_url` 不在 allowlist 时拒绝连接。
- 日志中不存在 token 和 context token。
- 同一个 token 永远只有一个 active poller。
- 旧 poller 的 fencing token 失效后不能更新 cursor 或发送消息。
- 租约过期后备用 Worker 能够接管。
- 删除已绑定智能体会停止轮询、取消排队任务、吊销凭据并安全清理工作区。

### 25.7 语音与输入状态

- 非空 `voice_item.text` 以 `voice` 类型进入 Agent Run，并在会话正文中标记为微信语音转写。
- 无转写语音不启动 Agent Run，图片、文件、视频及包含这些 item 的混合消息保持 `unsupported`。
- 有效文字和语音 item 同时出现时，有效文字优先且不被错误拒绝。
- START、STOP、`getconfig` 超时或 provider 错误均不改变 Agent Run 与 Outbox 结果。
- START ticket 的缓存年龄达到 540 秒时会在 STOP 前刷新；刷新失败时仍 best-effort 使用 START 阶段取得的旧 ticket。

## 26. 风险与外部依赖

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| iLink API 变更 | 绑定或消息中断 | provider adapter 隔离、契约测试、版本监控 |
| token 频繁失效 | 用户需重新扫码 | reconnect_required 状态、前端明确提醒 |
| bot 显示名由 provider 控制 | 与产品名称不一致 | 阶段 0 验证，不使用显示名做身份 |
| 一个 token 单 poller | 多实例并发冲突 | 数据库租约和冲突告警 |
| 智能体工具具有副作用 | 重跑产生重复操作 | Runtime 开始后禁止自动完整重试 |
| 外部消息触发高成本任务 | 额度和资源风险 | 唯一 sender、限流、配额、队列上限 |
| context token 语义变化 | 回复失败或串话 | 每条消息保存、provider 契约测试 |
| MySQL 队列扩展受限 | 高并发积压 | 保留队列接口，后续切 Redis/Celery |

## 27. 最终决策摘要

1. 微信能力是 Channel，不是 Agent Runtime。
2. 直接实现 iLink Channel Adapter，不将 Hermes Agent 作为 AI Hub 的第二套智能体核心。
3. 联系人产品名称固定为 `微信ClawBot`，内部永远使用稳定 ID。
4. Agent、bot、微信用户采用严格一对一绑定。
5. 使用独立长轮询 Worker，不在 FastAPI 请求内运行长期任务。
6. 第一阶段使用 MySQL Inbox/Agent Run/Outbox 保证可靠性。
7. Agent Core 先从 SSE 解耦，再接入微信。
8. 同一微信会话严格串行，入站消息在 run 开始时才写入 AgentMessage。
9. 回复必须使用触发消息自己的 `context_token`。
10. 微信渠道上线前必须启用生产级沙箱隔离和非交互安全权限策略。

## 28. 当前实现与上线清单

截至 2026-07-12，本文 P0 与 P0.1 范围已落地：数据模型与 `011` 迁移、iLink 适配器、二维码绑定、单用户校验、独立 Worker、Inbox/Run/Outbox、Agent Core 复用、Web 只读会话、渠道管理页、语音转写、输入状态、启停脚本和专项测试均已实现。

### 28.1 语音转写与输入状态

P0.1 增加以下体验能力：

- 接收入站 `type=3` 的语音 item；当 iLink 提供非空 `voice_item.text` 时，将其标记为 `voice` 并以“微信语音转写”正文进入原有 Inbox/Run/Outbox 链路。
- 当 iLink 未提供语音转写时，不下载或执行 `.silk` 音频，消息标记为不支持并提示用户重试或改发文字。完整音频转码和 ASR 属于后续范围。
- Worker 在确认持有有效 run 租约并开始持久化本轮会话后，使用触发消息自己的 `context_token` 调用 `getconfig` 获取 `typing_ticket`，再调用 `sendtyping(status=1)` 显示“对方正在输入”。ticket 及其单调时钟获取时间仅缓存在当前 run 的内存目标中，不跨 run 复用。
- iLink ticket 的预期有效期约为 600 秒。STOP 时若 START 取得的 ticket 未满 540 秒，直接复用；达到 540 秒刷新阈值后，再用同一 `context_token` 调用 `getconfig` 刷新，以预留网络和调度余量。
- ticket 刷新抛错或返回空值时，只要 START 阶段存在旧 ticket，STOP 仍回退旧 ticket 并 best-effort 调用 `sendtyping(status=2)`；若没有任何 ticket，则跳过该状态信号。START 首次取票失败时，STOP 仍会再尝试一次取票。
- 单次 typing 状态处理总预算为 4 秒，其中取票阶段最多占 2 秒；任何 typing 超时或 provider 错误都只记录脱敏日志，不能改变 Agent run 或 Outbox 的结果。
- STOP 必须在 run 写入终态之前完成，使同一 binding 的下一条 run 不能先 START 后被上一条 run 的迟到 STOP 关闭。
- 图片、视频和文件 item 仍保持 `unsupported`；含这些 item 的混合消息不能静默忽略附件。
- Claude Runtime 必须通过 stdin 传递用户 prompt，不能把 prompt 拼入命令行参数；否则换行和 shell 元字符可能被二次解析。

上线顺序：

1. 备份 MySQL，执行 `backend/migrations/011_weixin_clawbot_channel.sql`。
2. 生成两把相互独立的 32 字节随机密钥，配置 `CHANNEL_CREDENTIAL_ENCRYPTION_KEY` 和 `CHANNEL_ID_HASH_KEY`。
3. 配置 `WEIXIN_ILINK_ALLOWED_HOSTS`；默认官方域规则为 `*.weixin.qq.com`，自建代理需追加精确 host。
4. Claude Code 智能体在 Linux/WSL 中将 `CLAUDE_CODE_SANDBOX_TYPE` 设置为 `native`，禁止 Claude Code 以 `directory` 承接微信消息。
5. 完成上述配置后设置 `WEIXIN_ILINK_ENABLED=true`，再重启 API 并启动 `backend/channel_worker.py`；确认 Worker 保持运行后才开放绑定入口。
6. 使用测试微信账号完成真实扫码、联系人名称、私聊收发、重连、解绑和第二用户拒绝测试。

本地回归命令：

```bash
cd backend
python test_agent_service.py
python test_auth_permissions.py
python test_channel_service.py
python test_channel_worker.py
python test_channel_routes.py
python test_weixin_channel.py

cd ../frontend
npm run build
```

代码无法控制微信客户端最终展示的联系人名称；上线验收必须确认 iLink 实际创建的联系人显示为 `微信ClawBot`。在真实账号验证完成前，保持 `WEIXIN_ILINK_ENABLED=false`。
