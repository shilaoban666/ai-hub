# AI Hub 智能体接入钉钉 ClawBot 设计方案

## 1. 文档信息

- **状态**：P0 已实现，待钉钉真机与第 5 节生产门禁验收
- **版本**：v1.2
- **日期**：2026-07-12
- **适用项目**：AI Hub
- **渠道标识**：`dingtalk`
- **Provider 标识**：`dingtalk_stream`
- **AgentSession 来源**：`dingtalk_clawbot`
- **产品显示名**：`钉钉ClawBot`
- **P0 范围**：扫码取得应用凭据、一次性配对、单聊文本收发、会话同步、可靠队列与解绑

## 2. 结论先行

本方案可以实现“在 AI Hub 为某个智能体绑定钉钉，在钉钉单聊机器人时把文本同步给该智能体，智能体完成后将结果回复到同一钉钉会话”。

但它与微信联系人体验存在本质差异：

1. 钉钉开放平台中的机器人是企业应用机器人，不是普通钉钉好友。
2. 扫码授权不保证机器人自动出现在普通联系人列表；用户通常需要在工作台、功能列表或搜索中打开已安装且对其可见的机器人。
3. 钉钉当前没有公开的机器人原生 `typing` / “对方正在输入”接口。
4. Hermes 使用的 `/app/registration/*` 扫码注册流程依赖服务端 `source` 模板。`source=openClaw` 不是 AI Hub 自有模板，也不是本方案能够承诺长期稳定的公开 API 契约。
5. P0 只支持人与机器人的单聊文本。群聊、图片、语音、视频、文件、富文本、AI 卡片和主动消息均不在 P0 承诺范围内。

因此生产环境必须在以下两条路径中选择一条，未满足时不得把 `source=openClaw` 方案作为正式商用能力发布：

- **路径 A：申请 AI Hub 专属注册模板**。向钉钉申请独立、可商用、品牌归属明确的 `source`，并取得接口稳定性、凭据生命周期和撤销方式的书面确认。
- **路径 B：使用官方预创建企业机器人**。管理员在钉钉开发者后台创建并发布企业机器人，AI Hub 使用预配置的 Client ID/Client Secret 接入 Stream Mode；用户侧改为官方 OAuth 扫码身份绑定，或在机器人内发送一次性配对码完成 sender 锁定。

## 3. 目标与非目标

### 3.1 目标

- 在智能体设置页提供钉钉绑定入口、二维码、状态查询、取消、重连、解绑和会话重置。
- 全局保证一个智能体最多绑定一个外部消息 bot，微信与钉钉之间也互斥。
- 保证同一个钉钉 bot 凭据最多被一个 AI Hub 智能体接管。
- 扫码成功后通过一次性配对码锁定唯一钉钉 sender，其他 sender 永远不能触发该智能体。
- 只接收人与机器人的钉钉单聊文本，可靠、幂等地写入专属 AgentSession。
- 智能体执行与 Stream 回调解耦；被接纳的入站消息只在 Inbox 数据库事务提交后 ACK，任务在后台队列执行。
- 最终文本通过持久化 Outbox 回复到触发本次任务的原始钉钉会话。
- 钉钉和 Web 端共享可审计的会话历史，但 Web 端不能向渠道专属会话伪造用户消息。
- 服务重启、Stream 断线、重复回调、任务失败和回复重试时不重复执行智能体任务。
- 所有 Client Secret、二维码内容、配对码、session webhook 和原始回调均加密或哈希保存。

### 3.2 非目标

- 不承诺扫码后生成一个普通钉钉好友，也不承诺自动加入普通联系人列表。
- P0 不支持群聊、群内 `@`、人与人会话中的机器人能力。
- P0 不支持图片、语音、视频、文件、富文本和混合消息。
- P0 不实现 ASR、OCR、文件解析、病毒扫描或媒体长期存储。
- P0 不实现钉钉原生“正在输入”；空实现不能在产品文案中描述为已支持。
- P0 不使用 AI 卡片流式更新冒充原生 typing。
- P0 不支持定时主动推送、无入站上下文的主动单聊或跨会话通知。
- 不复用 Hermes 的 Agent Runtime、会话和权限系统；只参考其钉钉接入机制。
- 不把 `source=openClaw` 描述成 AI Hub 品牌、官方通用注册源或长期稳定接口。

## 4. 参考实现与许可证

### 4.1 Hermes 固定参考提交

设计参考固定在 NousResearch Hermes Agent 提交：

```text
7b5ba2054721dde998ed47fd4a0f031955278e99
```

不得仅引用 `main`，否则上游行为变化后无法复现设计依据。主要参考文件：

- 二维码注册流程：<https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/hermes_cli/dingtalk_auth.py>
- Stream 适配器：<https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/plugins/platforms/dingtalk/adapter.py>
- 用户文档：<https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/website/docs/user-guide/messaging/dingtalk.md>
- 钉钉测试：<https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/tests/gateway/test_dingtalk.py>
- 项目许可证：<https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/LICENSE>

该提交中的 Hermes Agent 使用 MIT License，版权声明为：

```text
Copyright (c) 2025 Nous Research
```

MIT 允许使用、复制、修改和分发，但复制软件或其重要部分时必须保留版权声明和许可文本。AI Hub 应遵守以下规则：

- 仅参考协议和架构思想时，在本设计文档中保留固定提交和来源链接。
- 直接复制或实质性改写 Hermes 代码时，在仓库的第三方声明中保留 Nous Research 的 MIT 版权及完整许可文本。
- Hermes 的 MIT 许可不代表钉钉授予 `source=openClaw` 的使用权，也不消除钉钉平台条款、品牌和接口授权风险。
- Hermes 文档中对注册桥接“安全可用”的产品判断不能替代 AI Hub 自己的安全评审和钉钉书面授权。

### 4.2 官方能力参考

以下官方资料用于界定 Stream、单聊和机器人形态，不用于证明 `/app/registration/*` 是公开稳定接口：

- 机器人概述：<https://open.dingtalk.com/document/development/development-robot-overview>
- 单聊机器人概述：<https://open.dingtalk.com/document/development/single-chat-bot-overview>
- 企业机器人配置：<https://open.dingtalk.com/document/dingstart/configure-the-robot-application>
- 企业机器人单聊教程：<https://open.dingtalk.com/document/development/the-application-robot-in-the-enterprise-sends-a-single-chat>
- 机器人接收消息：<https://open.dingtalk.com/document/development/receive-message>
- 官方 Python Stream SDK：<https://github.com/open-dingtalk/dingtalk-stream-sdk-python>
- 网页 OAuth 扫码登录：<https://open.dingtalk.com/document/development/tutorial-obtaining-user-personal-information>

## 5. 接入路径与生产门禁

### 5.1 路径 A：Hermes/OpenClaw 注册桥接

该路径调用 `https://oapi.dingtalk.com` 下的三段注册接口，并以 `source=openClaw` 请求服务端模板。授权成功后返回一组 Client ID 和 Client Secret，随后使用官方 `dingtalk-stream` SDK 建立长连接。

优点：

- 用户体验接近微信绑定，可在 AI Hub 内直接显示二维码。
- 不要求用户手工进入开发者后台复制 Client ID/Client Secret。
- 每次成功注册可以得到独立应用凭据，便于维持“一个智能体一个 bot 凭据”的物理隔离。

风险：

- `/app/registration/init`、`begin`、`poll` 未在已核验的钉钉公开开发文档中形成稳定契约。
- `source` 是服务端预注册模板名，任意字符串不一定可用。
- `source=openClaw` 的授权页面可能显示 OpenClaw 名称、图标或授权说明，而不是 AI Hub。
- AI Hub 无权暗示与 OpenClaw、Hermes、Nous Research 或钉钉存在未获授权的品牌关系。
- 模板可能被限流、修改、下线、收回，或改变返回字段、凭据权限和生命周期。
- 扫码成功只证明应用注册授权完成，不证明扫描者就是后续消息 sender。
- 当前没有与该桥接凭据一一对应的公开远程撤销 API；本地解绑不能保证钉钉侧应用立即失效。

生产门禁：

1. 获得 AI Hub 专属 `source`，授权页面品牌、隐私政策、权限范围和回调域名均属于 AI Hub。
2. 取得接口可用范围、商用许可、SLA、限流、凭据轮换和注销方式的确认。
3. 完成安全、法务、隐私和品牌评审。
4. 在独立预生产租户完成全链路和灾难恢复验证。

任一条件未满足时，该路径只能作为本地开发或受控 PoC 功能，必须默认 `DINGTALK_ENABLED=false`。

### 5.2 路径 B：预创建企业机器人 + 官方 OAuth/配对

这是生产环境的保守替代方案：

1. 企业管理员在钉钉开发者后台创建企业内部应用或合规的第三方企业应用。
2. 开启机器人能力，消息接收模式选择 Stream Mode，配置机器人名称、图标和可见范围。
3. 发布机器人并发布应用，保存 Client ID、Client Secret 和 robotCode。
4. AI Hub 运维人员把凭据通过密钥管理系统注入，不把 Client Secret 暴露给浏览器。
5. 用户在 AI Hub 使用钉钉官方 OAuth 二维码完成身份授权，或打开机器人发送一次性配对码。
6. AI Hub 将 OAuth 身份或首条合法 sender 与目标智能体绑定。

这一方案使用官方公开能力，但产品体验有差异：

- 机器人通常由组织安装并按可见范围展示，用户通过搜索或功能列表进入单聊。
- OAuth 二维码用于身份授权，不会动态创建机器人，也不保证把机器人加入普通联系人。
- 如果多个智能体共享一组企业机器人凭据，就不再满足物理意义上的“一个智能体一个 bot”。必须按 sender 或命令二次路由，并作为另一种产品模型单独评审。
- 如果严格维持“一个智能体一个 bot”，则每个智能体都需要独立预创建应用/机器人凭据，运维成本较高。

### 5.3 上线决策

```text
有 AI Hub 专属 source 且通过生产评审？
  ├─ 是 -> 可使用路径 A
  └─ 否 -> 是否已有合规预创建企业机器人？
           ├─ 是 -> 使用路径 B
           └─ 否 -> 保持 DINGTALK_ENABLED=false，不上线
```

## 6. 产品关系模型

### 6.1 全局一智能体一 bot

AI Hub 当前采用全局唯一约束：

```text
AI Hub User 1 --- N Agent
Agent       1 --- 0..1 AgentChannelBinding
Binding     1 --- 1 Provider Bot Credential
Binding     1 --- 1 Locked DingTalk Sender
Binding     1 --- 1 Active ChannelConversation
Conversation 1 --- 1 AgentSession
```

关键规则：

- `agent_channel_bindings.agent_id` 全局唯一，不是 `(agent_id, provider)` 唯一。
- 同一智能体不能同时绑定微信ClawBot和钉钉ClawBot。
- `(provider, provider_bot_id)` 唯一，防止同一个钉钉应用凭据被两个智能体同时消费。
- 一个 binding 同时只能有一个 active conversation。
- bot 的展示名称不用于鉴权；鉴权使用 provider、Client ID、绑定 ID 和 sender 哈希。
- 当前数据库中的 `external_wechat_user_id_*` 是历史字段名；钉钉复用时语义是通用外部 sender。后续迁移可重命名为 `external_user_id_*`，但不能改变加密和哈希规则。

### 6.2 “一个 bot 服务一个用户”的实现

钉钉注册成功只返回应用凭据，不返回可直接信任的扫描用户 sender ID。因此不能在 `SUCCESS` 时直接把 binding 标记为 active。

AI Hub 使用两阶段绑定：

```text
扫码注册应用凭据
  -> pairing_required
  -> 用户在该机器人单聊发送一次性配对码
  -> 锁定 senderStaffId（必要时回退 senderId）
  -> active
```

绑定后：

- 只有 sender 哈希匹配的私聊消息才能创建 AgentRun。
- 其他 sender 的消息记录为 `rejected_sender`，不调用模型、不执行工具、不返回智能体结果。
- 重连时必须由原 sender 完成配对；不同 sender 不得接管原会话。
- 解绑后关闭 Stream、清除本地凭据和 active conversation；历史 AgentSession 保留为只读审计记录。

## 7. 二维码注册协议

### 7.1 三段流程

默认注册基址：

```text
https://oapi.dingtalk.com
```

第一步，初始化模板：

```http
POST /app/registration/init
Content-Type: application/json

{"source":"openClaw"}
```

成功响应至少需要：

```json
{
  "errcode": 0,
  "nonce": "..."
}
```

第二步，开始 device flow：

```http
POST /app/registration/begin
Content-Type: application/json

{"nonce":"..."}
```

成功响应至少需要：

```json
{
  "errcode": 0,
  "device_code": "...",
  "verification_uri_complete": "https://...",
  "expires_in": 7200,
  "interval": 3
}
```

AI Hub 将 `verification_uri_complete` 编码为二维码。浏览器只读取同一个 bind session 的二维码图像，不取得 nonce、device code 或任何最终凭据。

服务端把二维码内容和用于 registration poll 的 `device_code`（在 AI Hub Provider contract 中映射为 `provider_qr_id`）封装在同一个版本化 bind-session QR envelope 中，再使用 `bind-session:{bind_session_id}:qr` purpose/AAD 加密写入 `qr_content_encrypted`：

```json
{
  "v": 1,
  "qr_content": "https://...",
  "provider_qr_id": "<device_code>"
}
```

Worker 每次轮询前只在内存中解密 envelope 取得 `device_code`。`channel_bind_sessions.provider_qr_id` 明文字段仅用于滚动升级期间读取已存在的旧 bind session；新建记录不得写入该列。成功、过期、取消、解绑或错误等终态都必须清除加密 QR envelope 和遗留明文字段。

`begin` 返回的 `interval` 会解析为正整数，缺失时默认 3 秒，并限制最大为 60 秒。该值持久化到 `channel_bind_sessions.poll_interval_seconds`；Worker 实际轮询间隔取 provider interval、`CHANNEL_BIND_POLL_INTERVAL_SECONDS` 和 1 秒安全下限中的最大值，服务重启后仍遵守 provider 节奏。

第三步，轮询状态：

```http
POST /app/registration/poll
Content-Type: application/json

{"device_code":"..."}
```

状态映射：

| Provider 状态 | AI Hub 状态 | 处理 |
|---|---|---|
| `WAITING` | `waiting_scan` | 按服务端 interval 或本地安全下限继续轮询 |
| `SUCCESS` | `pairing_required` | 加密保存 Client Secret，生成配对码 |
| `EXPIRED` | `expired` | 清除二维码，要求创建新 bind session |
| `FAIL` | `error` | 记录脱敏错误，不自动无限重试 |
| 未知值 | `error` / 可重试 | 短暂重试后停止，不能当作成功 |

`SUCCESS` 响应必须同时包含：

```json
{
  "client_id": "...",
  "client_secret": "..."
}
```

缺任一字段均视为不可恢复错误。Client ID 作为 `provider_account_id`；在没有更稳定 bot ID 时可暂作 `provider_bot_id`，但 Stream 回调中的 `robotCode` 不保证始终等于 Client ID，不能因此误拒合法消息。

### 7.2 注册安全要求

- 注册基址只允许 HTTPS、443 端口、无用户名密码、无路径、无 query、无 fragment。
- 生产默认只允许 `oapi.dingtalk.com`；自定义基址必须显式加入部署级 allowlist。
- HTTP 客户端禁止跟随重定向，避免 allowlist 被 30x 绕过。
- 每次请求设置连接和总超时，网络失败只能做有上限、带抖动的重试。
- 响应必须是 JSON object，`errcode` 必须严格为 0。
- 二维码、device code、nonce、Client Secret 和 provider 原始错误不能写入普通日志。
- 新 bind session 的二维码内容和 device code 必须一起写入版本化加密 QR envelope，数据库不得新增任何明文 device code；`provider_qr_id` 只允许兼容升级前的存量记录。
- 二维码接口返回 `Cache-Control: no-store` 和 `Pragma: no-cache`。
- bind session 必须带随机 state 哈希、发起用户、目标 agent、过期时间和幂等键。
- 二维码过期后创建新 bind session，不能复用旧 device code。
- 前端显示授权页可能出现 OpenClaw 品牌的明确提示；PoC 不得将其隐藏成 AI Hub 自有授权。

## 8. 一次性配对与 sender 锁定

### 8.1 配对码

扫码注册成功后：

1. 生成 6 位随机数字配对码。
2. 数据库只用 HMAC 保存 `pair:<code>` 的状态哈希。
3. 为页面展示另存一份带 purpose/AAD 的 AES-256-GCM 密文。
4. 配对码默认 10 分钟过期。
5. 用户必须在目标钉钉机器人单聊中发送完全匹配的纯文本配对码。
6. 错误尝试写入独立的 `channel_pairing_attempts` 表，以 `(bind_session_id, sender_hash)` 为主键逐 sender 计数，不保存 sender 明文。
7. 单个 sender 累计错误 5 次后，在当前配对会话内被锁定；该 sender 的后续尝试被忽略，但 bind session 继续保持 `pairing_required`，不会因一个 sender 的错误终止全局绑定，其他 sender 仍可使用正确配对码完成绑定。
8. `pairing_attempt_count` 只保留全局审计计数，不参与全局熔断；配对会话的统一终止边界仍是成功、取消或 10 分钟过期。
9. 成功后立即清除可展示密文和该 bind session 的全部 `channel_pairing_attempts` 记录，原码不可再次读取或使用。
10. 同一清理动作覆盖配对过期、用户取消、解绑，以及能够定位 bind session 的错误终态；尚未产生错误尝试记录的路径执行删除时应安全地成为 no-op。

### 8.2 sender 选择

优先使用 Stream 回调中的 `senderStaffId`，仅在其为空时回退到 `senderId`。锁定值必须满足：

- 消息是 `conversationType=1` 的人与机器人单聊。
- 消息类型是 text。
- sender 非空，且不等于当前应用账号。
- 触发消息属于当前 binding 的 Stream 连接。
- 配对码使用常量时间比较验证。

成功后保存：

- sender 加密值：用于合法出站关联和运维审计。
- sender HMAC：用于每条入站消息的常量时间鉴权。
- 哈希密钥版本：用于轮换和历史校验。

不能使用昵称、头像、手机号、群名或显示名称做身份判断。

## 9. 总体架构

```text
┌───────────────────────┐
│ AI Hub Web            │
│ 绑定 / QR / 状态 / 解绑 │
└──────────┬────────────┘
           │ /aihub/api/agents/{id}/channels/dingtalk/*
           ▼
┌───────────────────────┐       ┌──────────────────────────┐
│ FastAPI Control Plane │──────▶│ MySQL                    │
│ owner / RBAC / no-store│       │ Binding / Inbox / Run    │
└───────────────────────┘       │ Conversation / Outbox    │
                                └────────────┬─────────────┘
                                             │ leases / fencing
                                             ▼
┌───────────────────────┐       ┌──────────────────────────┐
│ DingTalk Registration│◀──────│ Channel Worker           │
│ init / begin / poll   │       │ bind / Stream / queue    │
└───────────────────────┘       │ outbox / reconnect       │
                                └────────────┬─────────────┘
                                             │
                               Stream callback│ sessionWebhook
                                             ▼
                                ┌──────────────────────────┐
                                │ DingTalk Robot           │
                                │ 人与机器人单聊             │
                                └────────────┬─────────────┘
                                             │ queued AgentRun
                                             ▼
                                ┌──────────────────────────┐
                                │ Agent Execution Core     │
                                │ Sandbox / Skill / MCP    │
                                │ Claude Code / Runtime    │
                                └──────────────────────────┘
```

### 9.1 控制面

复用通用渠道 API：

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/agents/{agent_id}/channels/dingtalk` | 查询状态 |
| `POST` | `/api/agents/{agent_id}/channels/dingtalk/bind-sessions` | 创建二维码 |
| `GET` | `/api/agents/{agent_id}/channels/dingtalk/bind-sessions/{id}` | 查询扫码/配对状态 |
| `GET` | `/api/agents/{agent_id}/channels/dingtalk/bind-sessions/{id}/qr` | 读取二维码图像 |
| `POST` | `/api/agents/{agent_id}/channels/dingtalk/bind-sessions/{id}/cancel` | 取消绑定 |
| `POST` | `/api/agents/{agent_id}/channels/dingtalk/reconnect` | 重连/重新配对 |
| `DELETE` | `/api/agents/{agent_id}/channels/dingtalk` | 解绑 |
| `POST` | `/api/agents/{agent_id}/channels/dingtalk/session/reset` | 新建渠道会话 |

每个接口都必须同时验证当前用户身份、Agent owner 和 Agent 未删除状态。二维码和状态接口均禁止缓存。

### 9.2 数据面

独立 Channel Worker 负责：

- 领取 bind session 租约并调用 registration poll。
- 为每个 active 或 pairing binding 建立唯一 Stream 连接。
- 接收回调、幂等持久化 Inbox，并在数据库事务 commit 后 ACK。
- 把配对消息与普通文本消息分流。
- 为合法文本创建 queued AgentRun。
- 领取 Outbox，通过本次入站自己的 session webhook 发送最终回复。
- 处理 Stream 重连、租约续期、解绑和死信。

同一 binding 同时只能由一个 Worker 持有，依赖 `poller_owner`、`poller_lease_until` 和递增 fencing token 防止旧 Worker 继续写入。

## 10. Stream、ACK 与持久化队列

### 10.1 连接模型

- 使用官方 `dingtalk-stream` Python SDK，P0 固定并测试兼容版本。
- Client ID 和 Client Secret 创建 `Credential`。
- 注册 `ChatbotMessage.TOPIC`，底层机器人消息 topic 为 `/v1.0/im/bot/messages/get`。
- Stream 是由 AI Hub 主动建立的长连接，不要求暴露公网 webhook。
- 每个 Stream session 使用一个独立守护线程和独立 asyncio event loop，不共享固定容量线程池，避免第 33 个及后续 Bot 静默排队；同时隔离 SDK 的无限重连和同步连接请求，使其不能阻塞 Channel Worker 主事件循环中的微信轮询、租约心跳、AgentRun 和 Outbox。
- 单 Worker 默认最多维护 64 个 Stream session，由 `DINGTALK_MAX_STREAM_SESSIONS` 显式配置；达到上限时返回可重试错误 `dingtalk_stream_capacity_exhausted`，不创建半初始化连接。扩容前必须同时评估线程、文件描述符和钉钉侧连接配额。
- Channel Worker 为 `dingtalk_stream` 保留与 `DINGTALK_MAX_STREAM_SESSIONS` 相同数量的并发消费者，使每个已建立 Stream session 的回调能在 15 秒 ACK 窗口内进入持久化；微信及其他长轮询 Provider 仍独立限制为最多 16 个并发 poll task，两个配额互不挤占。
- SDK `open_connection()` 内部的同步 `requests.post` 由 AI Hub 代理包装，连接请求超时固定使用 `DingTalkStreamConfig.api_timeout_seconds`，当前默认 15 秒；HTTP 错误、200 业务鉴权错误、畸形 JSON 以及缺少安全 `wss` endpoint/ticket 的响应都会脱敏后回传到主事件循环。
- 解绑、租约丢失或 Worker 关闭时，通过 `call_soon_threadsafe` 在 SDK 所在线程取消长生命周期 task，并关闭 WebSocket/Client；SDK 0.24.3 吞掉首次取消时会重复取消直到 task 退出，主事件循环最多等待当前 15 秒请求超时再加 3 秒宽限，超时线程转入后台跟踪并记录告警。
- SDK 0.24.3 自身负责常规断线重连；若其 `start()` 意外退出，AI Hub 外层使用 `2s -> 5s -> 10s -> 30s -> 60s` 上限退避重启。生产监控必须覆盖持续建连失败，不能把 SDK 内部重试等同于健康连接。
- 凭据认证失败进入 `reconnect_required`，并终结仍处于 `pairing_required` 的旧 bind session，确保用户能够立即重新扫码，而不是被旧配对会话阻塞。

### 10.2 ACK 原则

Stream 回调线程不能执行 Agent Runtime。正确顺序是：

1. 做最小结构校验并提取 provider message ID。
2. 把完整回调交给容量上限为 1000 条的 ingress queue，并为该 message ID 登记待决 ACK future。
3. Channel Worker 在短事务内幂等插入 `channel_messages` Inbox，或确认该 message ID 已存在，同时校验 binding 租约与 fencing token。
4. 只有 `db.commit()` 成功后，Worker 才调用 Provider 的 `ack_messages(..., success=True)`，回调返回 `AckMessage.STATUS_OK, "OK"`。
5. 队列已满、数据库异常、binding 租约丢失或 fencing 校验失败时使用 `success=False`，返回系统异常/NACK，让 provider 有机会重投；不得把消息丢弃后返回成功。
6. SDK 回调最多等待 15 秒取得持久化结果；超时返回 `persist timeout` 系统异常并移除待决 ACK，迟到 commit 不再错误地补发成功 ACK。
7. ACK 后再异步创建/执行 AgentRun，Runtime 永远不在 Stream SDK 线程中执行。

因此当前实现已经消除“仅进入进程内队列便成功 ACK”的已知丢消息窗口。仍需依赖 provider 对系统异常的重投契约，并通过 Inbox 唯一键消除超时重投或重复回调产生的重复执行。

### 10.3 入站幂等

幂等键：

```text
(binding_id, direction='inbound', provider_message_id)
```

回调缺少 message ID 时，可对规范化原始 payload 计算 SHA-256 派生 ID，但必须记录 `derived` 标记并监控碰撞/格式变化。重复消息只 ACK，不创建第二个 AgentRun。

### 10.4 P0 文本过滤

只接受：

- `conversationType == "1"`
- `msgtype == "text"`
- `text.content` 非空
- sender 匹配 active conversation

其他消息不进入 Agent Runtime。对于已绑定 sender 的非文本消息，可以 best-effort 回复“当前仅支持文字消息”；未绑定 sender 不回复，避免信息泄漏和滥用。

## 11. Agent Run 流程

1. Inbox 事务提交后创建 `queued` AgentRun。
2. 同一 conversation 串行执行，后到消息不得提前进入 Agent 历史。
3. Run 开始时才把对应用户文本写入 AgentSession。
4. 加载截至本 run 的历史、Skill、MCP、模型、Sandbox 和权限快照。
5. 渠道任务使用 `non_interactive_safe` 策略；需要人工批准的危险操作必须失败，而不是在钉钉中静默授权。
6. 仅最终 assistant text 进入钉钉 Outbox；thinking、工具参数、原始工具输出和服务日志不得外发。
7. assistant 消息、出站 ChannelMessage、Outbox 和 run 成功状态在一致的事务边界内提交。
8. Runtime 已可能执行工具后发生超时或崩溃时，run 标为 unknown，不自动重跑整个任务。

限额沿用通用渠道配置：单 binding 待处理消息上限、每日 run 上限、任务 deadline 和 run lease。达到限额时不调用模型，向已绑定用户返回稳定的忙碌提示。

## 12. Outbox 与 session webhook

### 12.1 回复上下文

钉钉入站回调携带 `sessionWebhook` 和 `sessionWebhookExpiredTime`。P0 使用 session webhook 发送 markdown 文本：

```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "AI Hub",
    "text": "最终回复"
  }
}
```

当 `sessionWebhookExpiredTime` 可解析为 epoch 秒或毫秒时，Provider 将二者封装为版本化 context envelope，再由通用渠道链路以 `channel-context-token` purpose 加密持久化：

```json
{
  "v": 1,
  "webhook_url": "https://api.dingtalk.com/...",
  "expires_at": "2026-07-12T12:00:00+00:00"
}
```

未提供过期时间时，为兼容 provider 旧回调仅保留原始 webhook URL；如果字段存在但无法解析，则回调校验失败并 NACK，不能静默退化为无 TTL 保护的发送。

规则：

- 每个 run 必须使用触发该 run 的 source message 自己的 session webhook。
- 不能使用 conversation 中“最新”的 webhook 回复较早 run，否则并发消息会串上下文。
- session webhook envelope 和原始 payload 使用 AES-256-GCM 加密保存。
- 发送前解包 envelope；当 webhook 已过期或距离过期不足 5 秒时，返回非可重试错误 `dingtalk_session_webhook_expired`，Outbox 直接进入 dead letter，不做指数退避重试。
- 钉钉在发送期间以 HTTP 404/410 或业务错误明确返回 webhook 已过期时，同样归类为 `dingtalk_session_webhook_expired`；其他非限流 4xx 归类为不可重试的 `dingtalk_session_webhook_rejected`。
- P0 不使用无上下文主动发送 API作为自动兜底，因为其权限、有效会话和主动单聊开关另有要求。

### 12.2 SSRF 防护

`sessionWebhook` 是外部输入，绝不能直接交给通用 HTTP 客户端。发送前必须全部满足：

- scheme 严格为 `https`。
- 主机严格匹配部署 allowlist，默认仅 `api.dingtalk.com`、`oapi.dingtalk.com`。
- 禁止通配到整个 `*.dingtalk.com`，除非完成独立风险评审。
- 禁止用户名、密码、非 443 端口、控制字符和 fragment。
- path 必须非空；query 原样保留但不得记录到普通日志。
- 禁止 HTTP 重定向。
- 不能通过 Host header、代理参数或回调 payload 覆盖目标主机。
- 错误日志只记录 host、错误码和内部 outbox ID，不记录完整 URL/session。

即使 allowlist 限定为官方域名，也应限制环境代理配置、连接超时、响应大小和 JSON 类型，防止代理绕过及资源耗尽。

### 12.3 Outbox 状态

```text
pending -> sending -> sent
             ├-> retry -> sending
             └-> dead_letter
```

- Outbox 领取使用 lease 与 fencing token，防止多个 Worker 重复发送。
- 发送使用稳定 `client_message_id` 做本地幂等关联。
- 网络超时属于结果未知；不得立即高频重发。
- 仅对明确可重试的超时、连接错误和 5xx 做指数退避加抖动。
- 无效 webhook、SSRF 校验失败、凭据解密失败和已过期 webhook 直接 dead letter。
- 默认最大尝试次数为 8；达到上限后由运维明确重试或丢弃。
- P0 单条回复按钉钉渠道上限拆分，AI Hub 当前目标上限为 4000 字符，分片必须保持顺序。

P0 的出站回复语义是 **at-least-once（至少一次）**，不是 exactly-once。`client_message_id` 只能防止 AI Hub 本地重复建 Outbox；当前 session webhook 没有已确认可用的 provider 幂等键。若钉钉已经接收回复后 Worker 在本地标记 `sent` 前崩溃，或发送请求超时但实际已送达，后续重试可能让手机收到重复回复。运维和产品必须接受该边界，不能将“可靠回复”描述成“绝不重复”。

## 13. 数据与加密

### 13.1 敏感数据

必须加密：

- Client Secret
- 二维码内容、device code 和一次性配对码展示值
- sender 原值
- session webhook
- provider 原始回调

必须使用 keyed hash 而非明文索引：

- sender 身份匹配
- bind state
- 配对码校验

### 13.2 算法和密钥

AI Hub 渠道加密使用：

- AES-256-GCM：机密性与完整性。
- 每条密文独立 96-bit nonce。
- purpose 和 key version 组成 AAD，防止密文跨字段替换。
- HMAC-SHA-256：sender、state 和配对码哈希。
- 加密密钥与身份哈希密钥必须不同。

两个环境变量都必须编码恰好 32 字节，可生成如下：

```bash
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

分别执行两次，不能复用同一个值。密钥只能放在部署密钥系统或受保护的 `.env`，不得提交 Git、写入日志或返回前端。

### 13.3 密钥轮换

- `CHANNEL_CREDENTIAL_KEY_VERSION` 标识当前密钥版本。
- 轮换前必须实现旧版本解密、新版本重加密，不能只修改版本字符串。
- 失去旧密钥会导致已有绑定无法恢复，只能重新扫码。
- QR envelope 暂时解密失败时必须保留密文、释放租约并记录可恢复错误，不能把“密钥误配”当作数据损坏立即删除唯一 `device_code`；恢复正确密钥后应继续轮询，只有过期、取消或明确业务终态才清除。
- 轮换应先暂停 Channel Worker，完成重加密后再恢复，避免并发写入混用版本。

## 14. 配置与启动

### 14.1 P0 环境变量

| 变量 | 示例 | 说明 |
|---|---|---|
| `DINGTALK_ENABLED` | `false` | 总开关；未通过生产门禁必须为 false |
| `DINGTALK_REGISTRATION_BASE_URL` | `https://oapi.dingtalk.com` | registration 基址 |
| `DINGTALK_REGISTRATION_SOURCE` | `openClaw` | PoC 模板；生产必须改为专属 source |
| `DINGTALK_ALLOWED_WEBHOOK_HOSTS` | `api.dingtalk.com,oapi.dingtalk.com` | session webhook 精确主机 allowlist |
| `DINGTALK_QR_TTL_SECONDS` | `7200` | 本地二维码最长有效期；非法值安全回退到 7200，最小 60 秒，最终仍取不超过 provider expires_in 的期限 |
| `DINGTALK_MAX_STREAM_SESSIONS` | `64` | 单 Worker 的 Stream session 硬上限，最小为 1；达到上限显式返回容量错误 |
| `CHANNEL_CREDENTIAL_ENCRYPTION_KEY` | 32-byte key | AES-GCM 密钥 |
| `CHANNEL_CREDENTIAL_KEY_VERSION` | `v1` | 密钥版本 |
| `CHANNEL_ID_HASH_KEY` | 32-byte key | HMAC 密钥 |
| `CHANNEL_WORKER_ID` | 可留空 | 多实例时建议显式唯一 |
| `CHANNEL_POLLER_LEASE_SECONDS` | `60` | Stream/binding 租约 |
| `CHANNEL_RUN_LEASE_SECONDS` | `900` | AgentRun 租约 |
| `CHANNEL_BIND_POLL_INTERVAL_SECONDS` | `2` | bind poll 下限 |
| `CHANNEL_OUTBOX_MAX_ATTEMPTS` | `8` | 出站最大尝试次数 |
| `CHANNEL_MAX_TEXT_CHARS` | `4000` | 通用文本限制 |

P0 依赖：

```text
dingtalk-stream==0.24.3
aiohttp==3.10.11
requests==2.32.3
websockets==13.1
httpx==0.27.0
cryptography==43.0.1
qrcode[pil]==7.4.2
```

`aiohttp`、`requests` 和 `websockets` 是 `dingtalk-stream` 的运行时传递依赖，必须与 SDK 一起锁定，避免部署时被解析到未经验证的异步、HTTP 或 WebSocket 版本。固定版本变更必须跑全量渠道回归和真实 SDK compatibility smoke，至少校验发行版版本、`AckMessage`、`ChatbotMessage.TOPIC`、异步 `start()` 以及同步 `requests` 超时 instrumentation。

### 14.2 数据库迁移

本次加固迁移为 `backend/migrations/012_dingtalk_channel_hardening.sql`，必须在启动新版 Channel Worker 前执行。迁移使用 `information_schema`/`IF NOT EXISTS` 幂等执行，向 `channel_bind_sessions` 增加：

| 字段 | 类型 | 作用 |
|---|---|---|
| `poll_interval_seconds` | `INT NULL` | 持久化 provider 返回的二维码最小轮询间隔 |

迁移同时创建独立计数表：

| 表/字段 | 类型 | 作用 |
|---|---|---|
| `channel_pairing_attempts.bind_session_id` | `CHAR(32)` | bind session 外键及联合主键第一列 |
| `channel_pairing_attempts.sender_hash` | `CHAR(64)` | sender HMAC 及联合主键第二列，不保存 sender 明文 |
| `channel_pairing_attempts.attempt_count` | `INT` | 当前 sender 在当前配对会话中的错误次数 |
| `created_at` / `updated_at` | `DATETIME` | 审计时间 |

独立表不会受 JSON 分桶数量上限影响，新的 sender 也不能因为某个内存/JSON 桶已满而绕过次数限制。配对成功、过期、取消、解绑及可定位 bind session 的错误终态都会删除对应计数行；`channel_bind_sessions.pairing_attempt_count` 继续只作为全局审计计数。

`models.Base.metadata.create_all()` 不会为已有表补列，不能代替迁移 012。部署顺序为：备份 MySQL -> 执行 `012_dingtalk_channel_hardening.sql` -> 运行只读 schema 预检 -> 部署 API/Worker -> 回归扫码和 Stream -> 再按门禁开启 `DINGTALK_ENABLED`。旧记录的 `poll_interval_seconds` 为 `NULL` 时按全局轮询下限兼容处理。

已有微信渠道基础表的环境执行：

```bash
cd backend
python _run_migration.py migrations/012_dingtalk_channel_hardening.sql
```

全新环境若尚未创建六张渠道基础表，必须先执行 `migrations/011_weixin_clawbot_channel.sql`，再按顺序执行 012 创建第七张配对计数表；`aihub.sh` 不自动修改生产数据库。

只读预检命令为：

```bash
cd backend
python _verify_channel_tables.py --required-if-enabled
```

微信或钉钉任一渠道启用时，缺表或缺列必须以非零状态阻止 API/Worker 启动；两个渠道都关闭时允许跳过。预检只查询元数据，不执行 DDL，不能替代 011/012 迁移。

脚本随后通过同一 Settings 只读输出渠道启用状态：两个渠道都关闭时不启动 Channel Worker；任一渠道启用时，Worker 若在启动探活阶段退出，整次启动返回失败并停止本次刚启动的 Uvicorn，不能继续显示“启动成功”。`channel_worker.py` 自身在配置错误时也返回非零退出码。

### 14.3 启动

开发环境：

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
python channel_worker.py
```

项目脚本：

```bash
./aihub.sh start
./aihub.sh status
```

`aihub.sh` 必须保证只保留一个受管 Channel Worker PID，并把日志写入 `channel_worker.log`。启动成功至少验证：

- Backend 存活。
- Channel Worker 存活。
- `DINGTALK_ENABLED=true` 时依赖和两把 32-byte 密钥有效。
- active binding 能建立 Stream 连接。
- 日志中不存在 Client Secret、配对码或完整 session webhook。

路径 B 不使用 registration bridge 时，Client ID/Client Secret 应由部署密钥系统直接注入或由受控管理接口写入加密绑定记录，不能伪造 registration 成功响应。

## 15. 页面与用户体验

### 15.1 状态

页面至少显示：

```text
未绑定
正在生成二维码
等待扫码
等待授权
等待配对码
已连接
需要重新连接
错误
正在解绑
已解绑
```

“已连接”只在 Stream 凭据有效且 sender 已锁定后显示。仅扫描完成、尚未发送配对码时必须显示“等待配对码”，不能误报连接成功。

### 15.2 必须明确的产品文案

- `钉钉ClawBot` 是 AI Hub 的产品显示名，不保证是钉钉普通联系人名称。
- “扫码完成后，请在钉钉打开机器人单聊并发送页面上的一次性配对码。”
- PoC 使用 `openClaw` source 时：“授权页面可能显示 OpenClaw 品牌；该流程仅用于测试。”
- “当前仅支持文字消息。”
- 不展示“支持正在输入”“自动加好友”“个人专属联系人”等未经钉钉能力保证的描述。

### 15.3 机器人入口

扫码后若钉钉没有自动打开机器人，页面应提供实际可验证的下一步：

- 路径 A：展示 provider 返回或模板约定的机器人打开方式；没有可靠入口时，明确提示在钉钉搜索授权页显示的机器人名称。
- 路径 B：提示从工作台、功能列表或搜索打开管理员已安装的企业机器人。

不能凭空构造未公开的钉钉 deep link。

## 16. 能力分期

### 16.1 P0：文本闭环

- QR registration 或预创建凭据接入。
- 一次性配对并锁定 sender。
- 人与机器人单聊文本接收。
- Inbox 幂等、AgentRun 串行执行、Outbox 可靠回复。
- Web 端渠道会话只读展示。
- 重连、解绑、会话重置、死信和 unknown run 运维。

### 16.2 P1：媒体输入

官方回调可以提供 picture、audio、video、file、richText 等类型；audio 可能包含 `recognition`，媒体包含 `downloadCode`。后续实现必须先补齐：

- `POST /v1.0/robot/messageFiles/download` 的 access token 管理。
- 下载 URL 二次 SSRF 校验、禁止重定向和响应体大小限制。
- MIME sniffing、扩展名不可信处理、恶意文件扫描和隔离存储。
- 下载码、临时 URL、媒体文件的 TTL 与清理任务。
- 图片/文件进入 Runtime 前的权限和隐私策略。
- 音频优先使用钉钉 `recognition`；没有转写时再决定是否接 ASR。

完成这些安全前置条件前，Provider 应显式把媒体标记为 unsupported，不能静默丢弃附件后只执行其中的文字。

### 16.3 P2：体验增强

- AI 卡片流式更新。
- 思考/完成表情反馈。
- 受控主动消息和过期 webhook 的 OpenAPI fallback。

AI 卡片流式更新和表情反馈都不是原生“对方正在输入”，产品上必须使用准确名称。

## 17. 故障处理

| 故障 | 状态/动作 | 是否自动重试 |
|---|---|---|
| registration init/begin 超时 | 保留 bind session，记录脱敏错误 | 有限重试 |
| source 不存在或无权限 | bind error，提示改用专属 source/路径 B | 否 |
| 二维码过期 | expired，清除 QR | 否，用户重新创建 |
| poll `SUCCESS` 缺凭据 | error | 否 |
| Client Secret 解密失败 | reconnect_required | 否 |
| 缺少 `dingtalk-stream` | 配置错误，Worker 不接管 | 否 |
| Stream 短暂断线 | 续租并退避重连 | 是 |
| Stream 认证失败 | reconnect_required | 否 |
| ingress queue 满 | 返回系统异常/NACK，不成功 ACK，等待 provider 重投 | 是，由 provider 重投 |
| 重复 message ID | ACK，忽略重复 | 不创建 run |
| 配对码过期 | pairing_expired | 否 |
| 单个 sender 配对码错误 5 次 | 仅锁定该 sender 在当前配对会话内的后续尝试；binding 继续 `pairing_required` | 否，其他 sender 仍可配对 |
| 非绑定 sender | rejected_sender | 否，不回复 |
| Agent 队列满 | rate_limited，稳定提示 | 否 |
| Runtime 启动前失败 | 可按 run 策略重试 | 有限 |
| Runtime 已执行工具后中断 | unknown，人工处理 | 否 |
| session webhook 非 allowlist | dead_letter + 安全告警 | 否 |
| session webhook 过期 | dead_letter | 否 |
| 出站超时 | 结果未知，退避重试/人工确认；重试可能产生重复回复 | 有限 |
| 解绑 | 本地停流、清凭据、关会话 | 远端撤销需另行确认 |

## 18. 安全要求

### 18.1 身份与权限

- 所有绑定操作要求登录用户拥有目标 Agent。
- 死信重试、unknown run 处理要求 superuser、staff 或 `agent.channel.operate`。
- 前端隐藏按钮不是权限控制，后端必须重复校验。
- sender 锁定发生前不允许执行 Agent。
- 渠道会话为只读，Web 端不得伪造 `dingtalk_clawbot` 来源消息。

### 18.2 Agent 工具风险

- 钉钉 sender 一旦绑定，就具备触发该 Agent 已授权 Skill/MCP 的能力。
- P0 使用非交互安全策略，拒绝需要人工确认的危险工具。
- 对写操作、外部通知、采购、删除、部署等能力设置额外工具级授权和审计。
- 配置 pending/day 限额、执行超时和成本上限，防止消息轰炸。
- 不把 provider 文本当成可信系统指令，继续遵循 Agent 的提示注入防护。

### 18.3 数据与日志

- 原始回调只加密保存，普通日志不输出 payload。
- Client ID 可脱敏显示；Client Secret 永不回显。
- QR envelope、遗留 `provider_qr_id` 和配对码展示密文在成功、过期、取消、解绑或错误终态立即清除。
- session webhook 只记录内部引用，不记录完整 query。
- 错误返回前端使用稳定错误码，不透出 provider 原始响应和堆栈。
- 明确会话数据、媒体数据和审计数据的保留期限与删除流程。

## 19. 验收清单

### 19.1 功能验收

- [ ] 未配置两把 32-byte 密钥时，后端拒绝创建绑定而不是明文降级。
- [ ] `DINGTALK_ENABLED=false` 时页面显示未启用，Worker 不连接钉钉。
- [ ] 已执行迁移 012，`channel_bind_sessions.poll_interval_seconds` 和 `channel_pairing_attempts` 表均存在，启动只读 schema 预检通过。
- [ ] 创建 bind session 返回二维码，响应不可缓存，数据库不存二维码明文。
- [ ] 新 bind session 的 device code 只存在于加密 v1 QR envelope，`channel_bind_sessions.provider_qr_id` 保持 `NULL`，数据库不存在新增的明文 device code。
- [ ] 临时配置错误密钥时 QR envelope 不被删除；恢复正确密钥后同一 bind session 能继续轮询。
- [ ] init/begin/poll 请求字段与固定 Hermes 提交一致。
- [ ] 页面明确显示 `source=openClaw` 的测试品牌风险。
- [ ] 扫码 `SUCCESS` 后进入 `pairing_required`，不是直接 active。
- [ ] 正确配对码锁定 sender；错误尝试按 sender HMAC 分桶，单 sender 5 次后仅锁定该 sender，其他 sender 不受影响；10 分钟后配对会话统一失效。
- [ ] `channel_pairing_attempts` 在成功、过期、取消、解绑和可定位会话的错误终态均被清空。
- [ ] 非绑定 sender 不能触发模型或工具。
- [ ] 单聊文本在 Web 渠道会话中可见，并只执行一次。
- [ ] 智能体最终文本通过原 source message 的 session webhook 返回。
- [ ] 同一会话连续两条消息串行执行，不串 webhook。
- [ ] 一个智能体绑定钉钉后不能再绑定微信，反向同样成立。
- [ ] 同一 provider bot 凭据不能绑定两个智能体。
- [ ] 重置会话后旧会话只读，新消息进入新 AgentSession。
- [ ] 解绑后不再接收新消息，待发送 Outbox 被停止或死信。

### 19.2 可靠性验收

- [ ] 重复 Stream 回调只产生一条 Inbox 和一个 AgentRun。
- [ ] Stream 断线按上限退避重连，不产生重复连接风暴。
- [ ] 默认容量可并行建立 33 个以上 Stream session；将上限设为 2 时第 3 个账号明确返回 `dingtalk_stream_capacity_exhausted`。
- [ ] 多于 16 个钉钉 Bot 同时在线时，每个 Stream session 都有对应消费者；钉钉配额扩展不会突破微信 16 个长轮询任务的独立上限。
- [ ] 真实 `dingtalk-stream==0.24.3` compatibility smoke 通过，SDK API 和同步 HTTP instrumentation 未漂移。
- [ ] Worker 崩溃后租约过期可由另一实例接管。
- [ ] 被接纳的入站消息只在 Inbox 数据库事务 commit 后返回成功 ACK。
- [ ] 数据库 commit 失败、租约丢失、ingress queue 满和 15 秒持久化等待超时时返回系统异常/NACK，provider 重投后仍只产生一条 Inbox 和一个 AgentRun。
- [ ] Outbox 超时、5xx、永久 4xx 和 webhook 过期分类正确。
- [ ] 已验证出站 at-least-once 边界：发送成功后本地提交前崩溃或结果未知超时可能重复回复，监控和运维流程不会将其误判为重复执行 AgentRun。
- [ ] `sessionWebhookExpiredTime` 以 v1 context envelope 加密持久化；已过期或不足 5 秒即过期时直接 dead letter，不自动重试。
- [ ] Runtime 中断后的 unknown run 不自动重放已执行工具。
- [ ] 达到 pending/day 限额时不消耗模型额度。

### 19.3 安全验收

- [ ] registration 基址拒绝 HTTP、非 allowlist 主机、路径、userinfo、非 443 端口和重定向。
- [ ] session webhook 拒绝 HTTP、私网 IP、非 allowlist 主机、userinfo、非 443 端口、fragment 和重定向。
- [ ] 恶意 webhook 不能利用环境代理访问内网元数据服务。
- [ ] 日志、API、数据库查询结果和异常中无 Client Secret、配对码、完整 webhook。
- [ ] 修改密文 purpose、nonce 或 ciphertext 后解密失败。
- [ ] sender 哈希使用独立 HMAC 密钥且常量时间比较。
- [ ] 绑定、重连、解绑和运维接口均验证 Agent owner/RBAC。

### 19.4 真机验收

- [ ] 钉钉扫码页展示的真实品牌、权限和隐私链接已截图归档。
- [ ] 扫码后实际机器人入口与页面说明一致。
- [ ] 明确确认机器人不是普通好友，未出现“自动加好友”误导文案。
- [ ] 手机端发送文本后，PC Web 能看到同一条渠道消息。
- [ ] 长任务完成后手机能收到最终回复。
- [ ] 手机端不会出现原生“正在输入”时，页面和文档没有相反承诺。
- [ ] 图片、语音和文件在 P0 得到明确不支持提示，不会被静默当成文字执行。

### 19.5 生产门禁验收

- [ ] 已取得 AI Hub 专属 `source` 及书面平台授权；或已切换到预创建企业机器人 + 官方 OAuth/配对方案。
- [ ] 不再以 `source=openClaw` 面向正式用户提供 AI Hub 品牌授权。
- [ ] 完成法务、隐私、安全、限流、凭据撤销和灾备评审。
- [ ] 已在预生产组织验证安装、可见范围、搜索入口、Stream 和解绑。

## 20. 待决策事项

1. 生产采用专属 registration source，还是预创建企业机器人。
2. 路径 B 是否接受多个用户共享物理机器人、按 sender 路由；若不接受，如何自动化每智能体应用的创建和运维。
3. 钉钉侧应用/机器人远程撤销和删除的正式接口及责任人。
4. session webhook 的实际 TTL、限流、错误码分类和超长任务兜底。
5. 是否在 P1 使用钉钉语音 `recognition`，以及无转写时是否接入独立 ASR。
6. 是否为高并发场景引入可靠消息中间件，用于跨进程削峰和扩展吞吐；当前数据库 commit 后 ACK 与 Inbox 幂等已保证 P0 不因进程内 ingress queue 成功 ACK 而丢消息。
7. AI 卡片和表情反馈是否值得作为 typing 的替代体验，以及准确的产品命名。

在第 1 项未完成正式决策前，钉钉渠道必须保持默认关闭。
