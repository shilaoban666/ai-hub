# AI Hub 开箱即用智能体、专家与合趣算点体系设计

## 1. 文档信息

- **状态**：产品规则已确认，待实施
- **版本**：v0.2
- **日期**：2026-08-31
- **适用项目**：AI Hub
- **部署形态**：合趣网络科技有限公司单企业私有部署
- **默认 Runtime**：Claude Code（`claude_code`）
- **核心目标**：用户登录后无需创建模型、智能体或工作区即可直接对话

## 2. 结论先行

AI Hub 应从“先配置资产，再创建智能体，最后进入对话”调整为“登录即进入 AI 工作台”。系统为每个用户自动提供一个默认 AI 助手、一个持久工作区、一个隔离运行容器、一个算点账户和可直接使用的平台模型。

建议采用以下产品概念：

- **AI 工作台**：登录后的默认入口，承载会话、输入框、工作区文件和用量信息。
- **AI 助手**：每个用户自动拥有的默认对话实例，不允许删除。
- **专家**：系统或用户配置的角色能力包，包含身份提示词、Skills、MCP 和模型偏好。
- **Runtime**：底层执行引擎，普通用户无需感知，平台默认使用 Claude Code。
- **智能体**：保留为技术概念，适用于渠道机器人、定时任务、自主运行实例等具有独立生命周期的对象。
- **合趣算点**：系统内部模型调用额度，界面简称“算点”；每日固定额度由用户主动领取，永久有效、可累计、不设余额上限，不涉及支付或兑换。

现有后端 `Agent`、会话、运行记录和执行链路可以继续复用，不应为了产品改名立即重命名数据库表和代码类。用户界面中的现有“智能体”建议改为“专家”，默认实例展示为“AI 助手”，不使用“智能体/专家”这种过渡名称。

## 3. 背景与现状

当前流程存在以下门槛：

1. 登录后默认进入技能管理，而不是对话。
2. 用户必须先创建自己的模型配置，并提供模型密钥。
3. 用户必须创建 Agent、绑定模型后才能开始对话。
4. Agent 页面仍受管理权限控制，不能作为所有用户的基础入口。
5. 当前工作区以 `agent_id` 建目录，每个 Agent 拥有独立工作区。
6. Agent 创建和更新时会把身份、Skills 和 MCP 写入工作区中的 `CLAUDE.md`、`.claude/` 和 `.mcp.json`。
7. 当前 `AIModel` 完全属于单个用户，不存在所有用户可使用的平台模型。
8. 当前已有 Token 用量统计，但没有业务算点账户、领取、预占和结算体系。

相关实现位置：

- `backend/models.py`：`AIModel`、`Agent`、`AgentSession`、`AgentRun`
- `backend/agent_workspace.py`：以 `agent_id` 管理目录并生成 Runtime 配置
- `backend/agent_service.py`：校验模型归属并执行 Agent Run
- `frontend/src/router/index.js`：登录后管理后台默认进入技能管理
- `frontend/src/components/AdminLayout.vue`：智能体仍作为内测管理模块

## 4. 目标与非目标

### 4.1 目标

- 所有已登录用户默认拥有对话权限。
- 用户首次进入系统时自动完成本地业务资源供应。
- 每个用户只有一个持久工作区，默认助手和专家共享用户文件。
- 平台提供默认 Claude Code Runtime 和默认系统模型。
- 用户无需配置 API Key 即可使用平台模型。
- 管理员可以在“系统设置 > 智能体设置”中配置默认助手、平台模型、算点领取策略、显示名称和工作区限制。
- 每次会话固定 Runtime、模型和配置版本，避免对话过程中发生隐式变化。
- 每次运行保存模型、配置和算点费率快照，保证审计与扣减可解释。
- 保留用户自带模型（BYOK）和高级专家配置能力。
- 技能支持按不可变版本安装、卸载、升级和回滚；MCP 定义与用户凭据分离；提示词支持导入个人库。
- 微信和钉钉支持绑定者个人私聊，统一复用其工作区、专家配置和算点账户。

### 4.2 非目标

- 首期不重命名数据库中的 `agents` 表或后端 `Agent` 类。
- 首期不允许普通用户在每轮对话中随意切换 Runtime。
- 首期同一用户工作区只允许一个写任务；仍必须使用独立的本次运行执行视图，不能直接覆盖共享工作区的受管配置。
- 不用简单的用户余额字段替代算点流水和结算记录。
- 不让 AI Hub 与 sub2api 同时维护两套可写余额；AI Hub 钱包是唯一权威。
- 不在平台默认模型配置中向用户暴露 API Key 或上游代理凭据。
- 不建设充值、订单、支付、退款或现金兑换体系。
- 单企业私有部署首期不引入组织、多租户和跨企业资源隔离模型。

## 5. 产品信息架构

### 5.1 普通用户入口

登录后默认进入 `/chat` 或等价的 AI 工作台路由，而不是 `/admin/skills`。建议主导航为：

```text
AI 工作台
├── 对话
├── 工作区文件
├── 专家
├── 技能与 MCP
├── 算点与用量
└── 管理中心
```

Skills、MCP、模型、提示词模板等配置进入“高级设置”或独立管理区，不再阻塞首次对话。

### 5.2 对话界面

对话界面建议包含：

- 左侧：历史会话和新建会话。
- 中间：对话内容和输入框。
- 顶部：当前专家选择器，默认值为“AI 助手”。
- 右侧：用户工作区文件。
- 用量区域：算点余额、今日领取状态和本次预计/实际消费。
- 高级选项：模型选择、推理等级和单次 Skill 选择，默认折叠。

普通用户不需要看到 Runtime 类型、模型协议、代理地址或密钥等部署概念。

### 5.3 “专家”命名判断

在“一名用户一个工作区”的目标架构下，当前 Agent 不再拥有独立文件空间，它主要表达角色、提示词和能力组合，因此用户侧称为“专家”更准确。

建议长期区分：

| 名称 | 含义 | 是否拥有独立工作区 |
| --- | --- | --- |
| AI 助手 | 每个用户自动创建的默认实例 | 否，使用用户工作区 |
| 专家 | 可选择的身份和能力配置 | 否，使用用户工作区 |
| 智能体 | 有独立生命周期、渠道或自主任务的运行实体 | 按场景决定 |
| Runtime | Claude Code 等执行引擎 | 不直接面向普通用户 |

现有微信、钉钉等渠道绑定具有独立生命周期，仍可在技术层继续绑定 `Agent`；产品层可描述为“将该专家接入渠道”。

## 6. 首次进入与自动供应

### 6.1 Bootstrap 接口

前端认证完成后调用幂等接口：

```http
POST /api/bootstrap
```

该接口在一个可重试的业务流程中完成：

1. 创建或获取本地用户工作区记录。
2. 创建或获取算点账户。
3. 按已发布策略幂等发放一次性新用户开箱算点。
4. 创建或获取默认 AI 助手。
5. 关联平台默认模型和 Claude Code Runtime。
6. 初始化工作区元数据；物理目录可延迟到首次访问文件或首次运行时创建。
7. 返回默认助手、最近会话、工作区状态、可用专家、默认模型、算点余额和今日领取状态。

建议响应示意：

```json
{
  "workspace": {"id": "ws_xxx", "status": "ready"},
  "assistant": {"id": 1001, "name": "AI 助手", "kind": "personal_default"},
  "recent_session_id": null,
  "runtime_type": "claude_code",
  "model": {"id": 10, "name": "平台默认模型"},
  "credits": {
    "display_name": "算点",
    "balance": 1000,
    "daily_claim_amount": 100,
    "daily_claimed": false
  }
}
```

### 6.2 幂等与并发

- `user_workspaces.user_id` 必须唯一。
- 每个用户只能有一个未删除的 `personal_default` Agent。
- 新用户开箱算点流水使用唯一业务键，防止重复发放。
- 两个浏览器同时首次进入时，数据库唯一约束负责最终去重。
- Bootstrap 可以重复调用，已存在的资源不得被重置或覆盖。

### 6.3 权限边界

- 对话、查看自己的会话、使用自己的工作区属于所有已登录用户的基础权限。
- 创建和管理专家可以使用独立权限，不复用当前技能页面管理权限。
- 平台默认设置、平台模型和算点策略只允许超级管理员或专用权限访问。
- Bootstrap 只能为当前网关注入的 `current_user.user_id` 创建资源。

## 7. 用户工作区设计

### 7.1 所有权

目标状态下工作区属于用户，而不是 Agent：

```text
User 1 --- 1 UserWorkspace
UserWorkspace 1 --- N Agent/Expert
UserWorkspace 1 --- N AgentSession
```

建议使用不可枚举的 `workspace_key` 或 UUID 作为物理目录名，不直接使用用户名。数据库仍以 `user_id` 做唯一归属校验。

### 7.2 目录结构

```text
user_workspaces/{workspace_key}/
├── files/                         # 用户永久文件，所有专家共享
├── sessions/                      # Runtime 会话状态或映射
└── managed/                       # AI Hub 管理，用户不可直接覆盖
    ├── experts/{expert_id}/       # 专家配置快照
    └── runtime/                   # Runtime 管理状态
```

用户文件与受管配置必须分离：

- `files/` 是用户可见、可编辑、可下载的持久空间。
- `managed/` 保存生成配置、密钥引用、会话状态和版本信息。
- API 必须继续执行路径规范化、受管路径保护和文件类型限制。
- 删除专家不得删除 `files/`。
- 只有用户注销清理或管理员明确执行工作区回收时才能删除整个工作区。

### 7.3 Claude Code 配置冲突

当前 Claude Code 会从工作区读取 `CLAUDE.md`、`.claude/skills` 和 `.mcp.json`。如果多个专家直接共享同一个目录，切换专家会覆盖这些文件；并发运行时还会互相污染。

目标方案是为每次运行构造执行视图：

```text
持久 files/ + 专家受管配置 + 会话状态 -> 本次 Runtime 执行视图
```

每次运行必须使用目录 overlay、挂载视图或等价的隔离执行视图。专家系统提示词应优先通过 Runtime 参数或运行配置传入，不得反复重写用户根目录中的 `CLAUDE.md`、`.claude/skills` 或 `.mcp.json`。仅依赖“运行前覆盖、运行后清理”无法承受进程崩溃、超时和多入口并发，不作为可交付方案。

MVP 阶段采用以下约束：

1. 一个用户工作区同一时间只允许一个写任务。
2. 执行锁从 `agent_id` 迁移为 `workspace_id`。
3. 每个 Run 创建独立受管配置层，并与持久 `files/` 组合成执行视图。
4. Runtime 只能写入本次执行视图和用户文件层，不能修改其他专家或会话的受管配置。
5. Run 结束或崩溃恢复时销毁临时层，用户文件单独持久化。

后续需要并行写入时，再引入文件分支、冲突检测或 Copy-on-Write 合并机制。

### 7.4 用户容器生命周期

“预分配容器”采用逻辑预分配、物理可休眠的方式：

- Bootstrap 同步创建 `UserWorkspace` 和 `RuntimeCell` 记录。
- 容器从预热池分配或异步启动，状态为 `unprovisioned | provisioning | ready | hibernated | error`。
- 用户文件存储在持久卷中，容器空闲后可休眠，不影响下次恢复。
- 一个用户的默认助手、专家、Web 会话和个人渠道共享该用户容器。
- 企业版进程启动时必须拒绝 `directory`；只支持 `container` 和满足下述隔离契约的 `native`。
- `container` 是默认模式，必须使用非 root 用户、只读基础镜像、capability drop、CPU/内存/PID/磁盘限制和默认拒绝的网络出口。
- `native` 只能用于企业信任的技能集，且必须为每个用户分配独立 Linux UID、清洁环境变量、文件 ACL、cgroup、进程/网络 namespace；运行用户不得拥有 sudo、Docker socket 或后台服务账号权限。
- 未审核企业市场技能、外部渠道输入或开放网络工具默认只能在 `container` 中运行，不能自动降级到 `native`。

### 7.5 专家记忆

共享用户文件不代表所有专家必须共享全部记忆。建议区分：

- 用户文件：所有专家可访问，受权限策略控制。
- 会话上下文：按 `session_id` 隔离。
- 专家长期记忆：按 `expert_id` 隔离。
- 用户通用偏好：存放在用户级资料或共享记忆中。

这样可以避免不同专家的角色记忆互相污染，同时保留对同一批工作文件的协作能力。

### 7.6 Runtime 与模型兼容层

Runtime 和模型 Provider 是两个独立维度：

- Runtime：当前 `claude_code`，后续可扩展 `codex` 等实现。
- Model Provider：Anthropic、OpenAI、DeepSeek 或企业内部兼容 API。
- Model Gateway：AI Hub 内置的协议兼容代理，统一保管平台/BYOK 凭据、标记用户/Run、计量原始 Token 并执行硬额度。

现有 Runtime Factory 继续保留，但 Runtime Adapter 必须声明 `capabilities`，并提供 `provision`、`health_check`、`prepare_execution`、`start`、`resume`、`cancel`、`install_assets`、`normalize_events` 和 `normalize_usage` 契约。前端和业务服务不得通过散落的 Runtime 名称判断实现兼容逻辑。

平台模型的上游 API Key 禁止写入 Runtime。Claude Code 只接收 AI Hub 网关地址和一次性 Run Credential；网关首期实现 Anthropic Messages 兼容接口，后续按 Runtime 能力增加 OpenAI Responses/Completions 等协议。Run Credential 至少绑定 `user_id`、`run_id`、`model_id`、`charge_mode`、最大预算、过期时间和随机 nonce，只能用于一个活动 Run，可立即撤销。

BYOK 同样建议经过网关，区别仅是 `charge_mode=free`：网关从 Vault 读取用户密钥，不扣算点，但仍实施地址校验、用量统计、超时、审计和网络出口策略。任何真实上游密钥都不进入 Runtime。

## 8. 系统设置中的智能体设置

新增管理员页面“系统设置 > 智能体设置”，设置采用草稿/发布模式，至少分为四组。

### 8.1 默认助手

- 是否启用开箱即用对话。
- 默认名称、图标和描述。
- 默认系统提示词。
- 默认 Skills 和 MCP。
- 默认最大轮次和执行超时。
- 默认推理等级和推理过程可见性。
- 默认工具权限模式。
- 是否允许用户覆盖模型、Skills、MCP 和系统提示词。

### 8.2 Runtime

- 默认 Runtime：`claude_code`。
- 可供专家覆盖的 Runtime 列表。
- 同一工作区并发写任务数，MVP 默认 `1`。
- 单用户运行并发数和排队上限。
- 工作区容量、单文件大小和允许文件类型。
- Runtime 健康检查与不可用时的用户提示。

普通用户界面不显示 Runtime 选择；管理员或高级专家配置可以选择允许的 Runtime。

### 8.3 平台模型

- 模型显示名、Provider 和真实模型名。
- API 协议、代理地址和加密凭据。
- 兼容 Runtime。
- 是否启用、是否为默认模型。
- 输入、输出、缓存 Token 的算点费率。
- 单次最大上下文或输出限制。
- 健康状态、最近检测时间和故障信息。

平台模型密钥只保存一份，不能为每个用户复制模型记录或密钥。用户自带模型仍保持用户私有。

### 8.4 算点与用量

- 显示名称，默认“算点”；正式名称为“合趣算点”，英文名称默认 `Credits`。
- 显示名称只影响 UI，数据库表、API 字段和错误码统一使用稳定的 `credit` 命名。
- 新用户一次性开箱算点，由 Bootstrap 自动发放。
- 每日固定领取额度，由用户主动点击领取。
- 当日未领取不可补领；已领取算点永久有效、可累计、不设余额上限。
- 领取和结算时区固定为 `Asia/Shanghai`，后续允许管理员配置。
- 单次运行最大可消费算点、低余额提醒值和并发运行上限。
- 平台模型按费率扣减算点；用户自带 API Key 不扣算点，但仍记录原始用量并受运行限制。
- 管理员调整、冻结和豁免策略；管理员调账必须填写原因。

## 9. 配置继承与版本

### 9.1 优先级

所有有效配置按以下优先级计算：

```text
平台默认 -> 用户策略 -> 专家覆盖 -> 会话选择
```

建议字段支持 `inherit` 语义。默认助手大部分字段保持继承，使管理员调整平台默认配置后，新会话自动使用新版本，而无需批量更新每个用户的 Agent 记录。

### 9.2 固定规则

- 新会话创建时固定 Runtime、模型和有效配置版本。
- 已有会话不因平台默认模型变化而在中途切换模型。
- 专家提示词或 Skills 更新默认从新会话生效。
- 每个 Agent Run 保存最终有效配置摘要和内容哈希。
- 每个 Agent Run 保存算点费率版本，后续调整费率不追溯历史运行。
- 平台设置采用草稿/发布模式，发布生成递增版本号。

### 9.3 模型选择优先级

```text
会话已固定模型
  -> 专家显式模型
  -> 用户默认模型
  -> 平台默认模型
```

模型故障切换只应发生在新会话创建或运行尚未开始时。已建立 Runtime 会话后不应静默切换到另一模型，否则上下文、行为和计费难以解释。

## 10. 平台模型与用户模型

### 10.1 模型作用域与扣减规则

当前 `AIModel.user_id` 为必填，执行时也要求模型属于当前用户。目标状态需要支持两类模型：

| 作用域 | 所有者 | 密钥来源 | 可见范围 |
| --- | --- | --- | --- |
| `platform` | 平台 | 管理员统一配置 | 被策略授权的用户 |
| `user` | 用户 | 用户自带密钥 | 仅所有者 |

建议为 `AIModel` 增加 `scope`，并允许平台模型使用平台所有权记录。所有模型查询和执行校验统一通过“当前用户可用模型”辅助函数，不能在不同接口中重复拼接不一致的过滤条件。

平台模型返回给普通用户时必须隐藏：

- API Key 和密文。
- 上游代理内部地址。
- 管理备注和故障细节。
- 供应商账户信息。

用户自带模型必须使用独立 Vault 凭据引用和受控 API Base URL。BYOK 调用通过 AI Hub 网关执行并标记 `charge_mode=free`，不扣算点，但必须记录输入、输出、缓存 Token、调用次数和运行耗时，并继续受容器资源、并发、超时、网络出口和工具权限限制。

### 10.2 技能版本安装

技能市场在单企业私有部署中分为“我的”和“企业市场”；匿名外部公开属于独立发布能力，不能与企业市场复用鉴权边界。技能安装模型为：

```text
SkillPackage -> SkillVersion（不可变）-> SkillInstallation -> ExpertSkillBinding
```

- 发布版本必须具有内容哈希，发布后不可原地修改。
- 安装固定具体版本；升级显式选择目标版本，失败可回滚。
- 卸载只删除用户安装实例，不删除来源技能和历史 Run 快照。
- 默认助手和专家只能绑定已安装技能；每个 Run 记录实际技能版本。
- Skill Manifest 必须声明文件写入、命令执行、网络域名和 MCP 依赖等能力；安装时由用户或管理员授权，Runtime 按声明强制执行，不能只做界面提示。
- 企业市场采用 `draft -> scanning -> review -> published -> revoked` 状态机；进入 Runtime 前必须通过路径穿越/符号链接、Secret、恶意脚本、依赖和许可证扫描及管理员审核。
- 禁止安装阶段执行任意脚本；依赖构建只能在无凭据、无业务网络的受控构建环境中完成，并生成内容寻址制品。
- 已撤销版本禁止新安装和新 Run；安全撤销可强制停用既有安装，并保留审计和回滚记录。

### 10.3 MCP 定义、连接与凭据

MCP 必须拆分为定义、版本化配置、用户连接和凭据引用：

```text
McpDefinition -> McpRevision -> McpConnection -> CredentialReference
```

- 企业市场只发布无密钥 MCP 定义，不能包含真实 Token、Header 或环境变量值。
- 用户从“我的/企业市场”导入定义后创建自己的连接，可新增、替换、删除和轮换 Token。
- Token 进入统一 Vault，读取接口只返回掩码和元数据，Runtime 启动时通过短时引用或受控 Secret 注入。
- 默认助手和专家只能绑定当前用户可用的 MCP 连接，不能直接使用市场源记录。
- 每个 Run 固定 MCP Revision 和凭据版本引用，但配置快照不得包含明文凭据。
- HTTP MCP 统一经过企业出口代理；每次 DNS 解析、重定向和连接都重新校验目标 IP，拒绝 loopback、私网、链路本地、组播、云元数据地址和 URL userinfo。
- stdio MCP 只能在用户容器内执行经过审核的命令/制品，不得访问宿主机可执行文件、Docker socket 或平台服务账号环境。
- 企业管理员维护允许域名和例外审批；应用层 URL 校验不能替代容器/网络层出口策略。

### 10.4 提示词导入

提示词不进入 Runtime 安装体系。用户可从“我的/企业市场”导入个人提示词库，默认采用内容快照；来源后续更新不得静默修改用户已导入内容。对话时选择提示词只负责填充或组合输入，不改变专家的长期系统提示词。

## 11. 合趣算点与额度设计

### 11.1 产品规则

- 正式名称为“合趣算点”，界面默认简称“算点”，英文名称默认 `Credits`。
- 管理员可修改显示名称；前端不得硬编码名称，数据库和 API 始终使用 `credit`。
- 算点是系统内部调用额度，不涉及充值、支付、退款、提现或现金兑换。
- 新用户开箱算点自动发放；每日固定额度必须由用户主动领取。
- 当日未领取不可补领；已领取算点永久有效、可累计、不设余额上限。
- 平台模型消耗算点；用户自带 API Key 不消耗算点。
- AI Hub 钱包是唯一余额权威；sub2api 或其他模型网关只提供原始用量和硬额度执行，不维护独立业务余额。

### 11.2 数据结构

```text
credit_accounts
- user_id (unique)
- available_balance
- reserved_balance
- status
- version

credit_claim_policies
- id
- display_name
- display_name_en
- initial_claim_amount
- daily_claim_amount
- per_run_limit
- low_balance_threshold
- timezone
- byok_charge_mode
- effective_from
- effective_to
- version

credit_claim_records
- id
- user_id
- claim_type
- claim_date
- amount
- policy_version
- business_key (unique)
- created_at

credit_ledger
- id
- user_id
- entry_type
- amount
- available_after
- reserved_after
- run_id
- business_key (unique)
- operator_user_id
- reason
- metadata
- created_at

model_usage_events
- id
- run_id
- provider_request_id (unique)
- model_id
- input_tokens
- output_tokens
- cache_read_tokens
- cache_creation_tokens
- occurred_at
- raw_usage

model_pricing_versions
- id
- model_id
- input_rate
- output_rate
- cache_read_rate
- cache_creation_rate
- effective_from
- version

model_run_credentials
- token_hash (unique, never store plaintext)
- run_id (unique)
- user_id
- model_id
- pricing_version_id
- max_points
- consumed_points
- request_count
- request_in_flight
- status
- expires_at
```

`credit_accounts` 用于并发读写余额，`credit_ledger` 是不可变审计依据；任意时点余额必须能够由流水重建。由于算点永久有效，不需要赠送批次和过期任务。

### 11.3 开箱与每日领取

开箱额度由 Bootstrap 幂等发放；每日额度只能通过显式领取接口发放：

```text
initial business_key = initial-claim:{user_id}
daily business_key   = daily-claim:{user_id}:{local_date}
```

数据库同时对业务键和 `(user_id, claim_type, claim_date)` 建唯一约束，保证多实例、并发点击以及当日策略切换时最多成功一次。策略版本保存于领取记录用于审计，但不进入领取幂等键，避免同日发布新策略导致重复领取；首次开箱键不含策略版本，保证用户终身只发放一次开箱额度。每日领取日期按策略时区计算；接口必须区分 `CREDIT_ALREADY_CLAIMED` 和普通冲突。微信、钉钉等渠道不能代替用户领取，余额不足时返回固定提示，引导用户进入 AI Hub。

### 11.4 平台模型运行结算

```text
检查账户状态
  -> 按本次最大预算原子预占算点
  -> 创建 AgentRun 和费率快照
  -> 签发带 user_id/run_id/model_id/预算/TTL 的一次性 Run Credential
  -> Runtime 只携带网关地址和 Run Credential
  -> 网关使用平台上游密钥调用模型
  -> 网关按 provider_request_id 写入幂等用量事件
  -> 每次模型子调用前后原子校验并累计 Run 预算
  -> 按费率快照计算实际算点
  -> 扣除实际算点并释放预占差额
  -> 写入幂等结算流水
```

费率使用整数最小单位计算，禁止浮点余额：

```text
points = ceil(
  input_tokens * input_rate
  + output_tokens * output_rate
  + cache_read_tokens * cache_read_rate
  + cache_creation_tokens * cache_creation_rate
)
```

- Runtime 未启动：释放全部预占，不扣算点。
- 已产生可靠用量后失败或取消：按可靠用量结算。
- 上游未返回用量：标记 `pending_reconciliation`，不能按零用量直接完结。
- 重复用量或结算回调必须由唯一业务键消重。
- 网关用量事件、Run 聚合和钱包流水需要定期自动对账。

### 11.5 BYOK 运行

BYOK 不创建算点预占和扣减流水，但仍创建 AgentRun、Run Credential、用量事件和审计记录。网关从 Vault 读取用户密钥并执行协议、DNS、私网地址、重定向和出口白名单校验；真实 BYOK 密钥不注入 Runtime。BYOK 仍受单用户并发、最大轮次、超时、容器资源、网络出口和工具权限限制。

### 11.6 硬限制

严格防止平台模型超支必须同时具备：

- Runtime 单次最大轮次、超时和输出上限。
- 每次 Run 可识别、短时有效且带最大预算的平台网关身份。
- 模型网关侧在请求前执行预算校验，在每次模型调用后原子累计用量。
- AI Hub 侧算点预占、工作区租约和并发控制。

所有用户共享一个无法区分用户和 Run 的上游 API Key 不满足交付条件，只能事后统计，不能阻止余额穿透。

## 12. 建议数据模型变更

### 12.1 新增表

- `user_workspaces`
- `runtime_cells`
- `platform_agent_settings`
- `credit_accounts`
- `credit_claim_policies`
- `credit_claim_records`
- `credit_ledger`
- `model_usage_events`
- `model_pricing_versions`
- `skill_versions`
- `skill_installations`
- `expert_skill_bindings`
- `mcp_revisions`
- `mcp_connections`
- `credential_references`
- `user_prompt_imports`

### 12.2 现有表调整

`agents`：

- 增加 `kind`：`personal_default | expert | autonomous`。
- 增加 `workspace_id`。
- 增加配置继承字段或配置版本引用。
- 为每个用户唯一的默认助手增加数据库约束。

`ai_models`：

- 增加 `scope`：`platform | user`。
- 增加启用状态、费率版本和健康状态。
- 调整平台模型所有权表达方式。

`agent_sessions`：

- 增加 `workspace_id`。
- 固定 `runtime_type`、`model_id` 和 `config_version`。

`agent_runs`：

- 增加 `pricing_snapshot`。
- 增加 `reserved_points`、`charged_points` 和 `settlement_status`。
- 保留现有 Token 用量字段作为计费输入和运行统计。

`agent_channel_bindings`：

- 唯一约束从仅 `agent_id` 调整为 `(agent_id, provider)`，允许同一专家分别绑定微信和钉钉。
- 绑定记录只允许个人私聊，所有渠道 Run 使用绑定者的工作区、钱包和专家配置。
- 配对成功时固定并加密保存绑定者外部账号标识，同时保存不可逆哈希用于消息匹配；后续拒绝其他发送者、群聊和无法验证签名的消息。

`agent_execution_leases`：

- 目标状态改为按 `workspace_id` 竞争执行租约，至少对写任务如此。

## 13. API 草案

### 13.1 普通用户

```text
POST /api/bootstrap
GET  /api/chat-context
GET  /api/workspace
GET  /api/credits/me
GET  /api/credits/me/ledger
POST /api/credits/me/daily-claim
GET  /api/experts
GET  /api/skill-market
GET  /api/skill-installations
POST /api/skill-installations
POST /api/skill-installations/{id}/upgrade
DELETE /api/skill-installations/{id}
GET  /api/mcp-market
POST /api/mcp-connections
PUT  /api/mcp-connections/{id}/credentials
DELETE /api/mcp-connections/{id}/credentials/{key}
POST /api/prompt-library/import
```

现有 `/api/agents/{id}/...` 对话、会话和运行接口可以继续作为底层兼容接口。前端通过 Bootstrap 获得默认 Agent ID 后复用现有链路。

### 13.2 管理员

```text
GET  /api/admin/agent-settings
PUT  /api/admin/agent-settings/draft
POST /api/admin/agent-settings/publish
GET  /api/admin/workbench-settings
PUT  /api/admin/workbench-settings/draft
POST /api/admin/workbench-settings/publish
GET  /api/admin/platform-models
POST /api/admin/platform-models
PUT  /api/admin/platform-models/{id}
POST /api/admin/users/{user_id}/credits/adjust
```

智能体设置和工作台设置独立保存、独立生成版本；新运行读取已发布的智能体设置，默认助手身份和默认模型读取已发布的工作台设置。旧的 `/api/admin/assistant-settings` 仅保留兼容读取，写入接口返回 HTTP 410。普通用户接口和平台管理接口必须保持权限边界。

## 14. 安全与审计

- 平台模型和 MCP 凭据必须加密存储，普通用户响应永不返回密钥。
- 工作区 API 必须按 `current_user.user_id` 校验归属。
- 专家切换不能绕过模型、Skill、MCP 和工具权限策略。
- 企业市场接口要求登录；现有匿名 `/api/public/*` 不能作为企业市场安装源。
- Skill 发布物必须不可变、有内容哈希、权限声明和安全扫描结果；未审核版本不能进入企业市场。
- MCP 定义与凭据严格分离，凭据通过 Vault 引用和短时注入进入 Runtime。
- 平台模型和 BYOK 的所有出口地址必须经过 SSRF 防护和容器网络策略校验。
- 工具权限统一分为只读、工作区写入、外部写入、破坏性操作和费用操作；容器隔离不能替代业务授权。
- Web 端高风险操作需要 Run 级确认；微信/钉钉首期默认拒绝外部写入、删除、发送和产生额外费用的工具，除非用户预先授予明确范围。
- 渠道入站必须校验 Provider 签名、绑定者身份、消息幂等键和个人私聊类型，不能只根据机器人 ID 接受消息。
- 每次运行保存用户、工作区、专家、会话、模型、Runtime 和配置版本。
- 每笔算点流水保存业务键、操作者、原因和关联 Run。
- 管理员手工加减算点必须填写原因并进入审计日志。
- 配置快照只记录必要字段和哈希，不记录明文密钥。
- Bootstrap、每日领取、用量上报和运行结算必须具备幂等键。
- 额度不足、账户冻结和工作区异常应使用稳定错误码，方便前端展示和重试。

## 15. 兼容与迁移

### 15.1 新用户

新用户直接使用新流程：Bootstrap 创建用户工作区、算点账户和默认助手，不需要接触旧的 Agent 创建流程。

### 15.2 现有用户

现有 Agent 和工作区不能直接自动合并，因为多个 Agent 目录可能存在同名用户文件。

建议规则：

- 没有 Agent：创建全新的默认助手和用户工作区。
- 只有一个 Agent：可将其用户文件迁移为用户工作区，并保留该 Agent 为专家。
- 有多个 Agent：创建新用户工作区，将旧目录分别放入 `files/legacy/{agent_id}/`，不自动覆盖同名文件。
- 所有旧 Agent 保留原 ID、会话和运行历史。
- 迁移完成前保留旧工作区只读备份和迁移状态，验证后再按运维流程清理。

默认助手不应通过“选择一个历史 Agent 并改名”产生，避免意外继承旧提示词、MCP 凭据和渠道绑定。

### 15.3 路由兼容

- 新入口使用 `/chat`。
- 旧 `/admin/agents/:id/chat` 在迁移期继续可访问。
- 旧“智能体”页面改为“专家管理”。
- 登录后的默认重定向从 `/admin/skills` 调整为 `/chat`。

## 16. 分阶段实施

### P0：上线阻断验证

- 完成生产级用户容器、每 Run 执行视图和网络出口隔离验证。
- 打通平台模型网关的 Run 身份、硬预算、幂等用量事件和对账契约。
- 验证 Claude Code 能安全注入专家提示词、技能目录和 MCP 凭据引用。
- 确认企业市场与匿名公开 API 的鉴权隔离。

### P1：平台默认能力与算点

- 平台模型作用域、全局凭据和管理员配置。
- “系统设置 > 智能体设置”及配置版本发布。
- 默认 Runtime 设置为 Claude Code。
- 算点账户、领取策略、领取记录、不可变流水、预占结算和管理员调账。

### P2：登录即可对话与用户容器

- Bootstrap、默认助手和新 `/chat` 工作台。
- `UserWorkspace`、`RuntimeCell`、持久卷和每 Run 执行视图。
- 所有登录用户的基础对话权限。
- 算点余额、今日领取状态、额度不足和运行结算。
- 现有 Agent 工作区迁移工具和验证报告。

### P3：资产安装与专家产品化

- 技能不可变版本、企业市场、安装、卸载、升级和回滚。
- MCP Definition/Revision/Connection/Vault 凭据管理。
- 提示词导入个人库。
- UI 将“智能体”调整为“专家”，支持选择、创建、复制和能力绑定。

### P4：渠道与多 Runtime

- 微信、钉钉个人私聊统一进入用户工作区、钱包和 Run 链路。
- 渠道余额不足固定回复和 Web 领取引导。
- 通过 Runtime Adapter 接入 Codex 和 DeepSeek Harness。
- Runtime 健康、版本、容量和异常运行管理。

## 17. 验收标准

### 17.1 开箱即用

- 新用户首次登录后无需任何配置即可在 10 秒内进入可发送消息的对话页。
- 并发触发 Bootstrap 不会创建重复工作区、默认助手、容器记录或开箱流水。
- 平台模型密钥不会出现在前端响应、工作区文件或运行日志中。

### 17.2 工作区

- 每个用户只有一个有效工作区。
- 切换专家后仍能看到同一批用户文件。
- 删除专家不会删除用户文件。
- 两个专家不能在未隔离的情况下同时写同一工作区。
- 任意 Run 崩溃或超时后都不会把专家配置、MCP Secret 或临时文件残留到其他专家执行视图。
- 任意工作区路径都不能越权访问其他用户目录。

### 17.3 配置

- 新会话使用当时已发布的平台设置。
- 已有会话不会因默认模型变化而隐式切换模型。
- 每个 Run 能查询到有效 Runtime、模型、配置版本和费率版本。

### 17.4 算点

- 每日算点必须由用户主动领取，同一自然日最多成功一次，未领取不可补领。
- 已领取算点永久有效、可以累计且不受余额上限限制。
- 并发运行不会重复消费或使可用余额失真。
- 失败、取消和成功运行均有明确、幂等的结算结果。
- 余额变化可以完全由算点流水重建，并可与模型网关用量自动核对。
- 达到硬额度后新运行被稳定拒绝，并返回可识别错误码。
- BYOK Run 不产生算点扣减，但保留完整原始 Token 和运行审计。

## 18. 已确认产品决策

- 合趣网络科技有限公司单企业私有部署，首期不做多租户。
- 登录后直接进入 AI 工作台，当前 AI Hub 后台作为管理中心继续保留。
- 默认 Runtime 为 Claude Code，后续接入 Codex、DeepSeek Harness 和其他 Runtime。
- 每个用户拥有一个共享持久工作区和逻辑预分配、物理可休眠的隔离容器。
- 算点每日固定额度、主动领取、不可补领、永久有效、可累计且不设余额上限。
- 算点不涉及支付；AI Hub 钱包是唯一余额权威。
- 算点显示名称可配置，默认“算点”，正式名称“合趣算点”，英文名 `Credits`。
- 平台模型消耗算点；用户允许配置 BYOK，BYOK 不消耗算点。
- 技能按版本安装、卸载、升级和回滚；MCP 支持导入定义并独立管理个人 Token；提示词仅导入个人库。
- 微信和钉钉仅支持绑定者个人私聊，统一使用绑定者的工作区、专家和钱包。

每日领取数、新用户开箱数和各模型换算费率是管理员发布的运营参数，不作为代码常量。

## 19. 交付前必须闭环的五项

以下问题不是一般优化；任一未解决都不能按企业版交付：

1. **Runtime 隔离必须成为启动时硬约束。** 企业版拒绝 `directory`；容器作为默认模式。`native` 只有满足独立 UID、clean env、ACL、cgroup、namespace、无 sudo/无 Docker socket 和受控出口时才可启用，并且不能承载未审核技能或外部渠道输入。
2. **AI Hub 简单网关必须承担硬预算和唯一计量。** 平台/BYOK 真实密钥均保留在网关和 Vault；Runtime 只拿一次性 Run Credential。网关必须逐次原子校验预算、记录幂等用量事件并与钱包自动对账，否则算点仍可能穿透或重复扣减。
3. **每 Run 隔离执行视图不可省略。** 共享用户文件不能意味着共享 `CLAUDE.md`、技能目录和 `.mcp.json`。只加工作区锁无法处理崩溃残留、Web/渠道竞态和专家切换，可能造成提示词或凭据串用。
4. **扩展供应链和网络出口必须同时强制执行。** 技能/MCP 需要不可变版本、内容哈希、权限 Manifest、扫描、审核、撤销和安装快照；BYOK/HTTP MCP 需要网关/出口代理、DNS 重绑定防护、私网拒绝和域名审批。只做页面提示或应用层 URL 正则不构成安全边界。
5. **个人渠道身份和工具授权仍是独立风险。** 微信/钉钉必须锁定绑定者并拒绝群聊、其他发送者和伪造消息；同时对外部写入、删除、发送、费用和敏感 MCP 工具实施服务端策略。否则攻击者可消耗绑定者算点，或让智能体修改其工作区和企业数据。

## 20. 2026-09-01 实现落点

- `UserWorkspace` 是用户唯一持久空间；默认助手、专家、Web、微信和钉钉共享该工作区与 AI Hub 钱包。
- `RuntimeCell` 记录逻辑预分配状态；每次运行创建唯一 `WorkspaceRunView`，完成后原子同步用户文件并记录清理审计。
- 并发租约以 `workspace_id` 为粒度，Web 与渠道入口不能并发写同一用户空间。
- 企业 Bootstrap 硬拒绝 `directory`，仅允许 `native` 或 `container`。
- 容器镜像定义位于 `backend/runtime_images/claude/Dockerfile`，构建命令：

```bash
docker build -t aihub/claude-runtime:latest backend/runtime_images/claude
```

- 容器 Run 使用非 root UID、只读根文件系统、`cap-drop=ALL`、`no-new-privileges`、CPU/内存/PID 限制和临时 `/tmp`，不挂载 Docker socket。
- 技能安装固定 `SkillRelease` 及内容哈希，支持安装、版本切换、回滚和卸载；运行快照记录 installation/release/hash。
- MCP 按 Definition、Revision、Connection、CredentialReference 分层；Vault 密钥加密保存，响应不返回明文，运行快照只记录凭据引用与版本。
- 提示词导入保存独立内容快照和来源哈希，不跟随市场来源静默更新。
- 运行审计记录工作区、来源渠道、模型/配置版本、技能版本、MCP Revision、执行视图和清理状态。
- 技能发布会解析 `aihub-manifest.json` 并执行路径、体积、明文 Secret、脚本和网络能力扫描；安装必须显式覆盖声明能力。企业市场版本需管理员审核，撤销会立即停用现有安装，新 Run 会重新校验状态、哈希与授权。
- 管理端新增技能审核队列与资产安全事件审计；审核可分别批准容器运行和受信任 `native` 运行，审核、撤销和 MCP 策略变化均保留操作人、原因与时间。
- MCP Definition/Revision 保存和每个 Run 启动前都会重新解析 URL、DNS 和目标 IP，拒绝 userinfo、loopback、私网、链路本地、组播及保留地址。公网 HTTP(S) MCP 默认可用；配置 `MCP_ALLOWED_HOSTS` 后才启用企业域名白名单，配置 `MCP_EGRESS_PROXY_URL` 后流量才通过企业出口代理。stdio 命令仍必须进入 `MCP_STDIO_ALLOWED_COMMANDS` 制品白名单。
- MCP 连接按 `read | write | delete | notify | cost` 分类。高风险连接必须声明具体工具名，只允许交互式 Web Run，并强制使用 Runtime 的交互权限模式；微信、钉钉和其他无交互执行会在服务端资产解析阶段拒绝。
- `native` 已具备独立 UID、clean env、受管文件权限和每 Run 执行视图；第三方技能必须额外取得 `native_approved`。完整 native 网络 namespace/cgroup 出口策略仍属于部署能力，未启用时不得承载未审核公开技能。生产默认继续使用 `container`。
- 启用 `MCP_EGRESS_PROXY_URL` 时，代理仍需负责 CONNECT、重定向和 DNS 重绑定防护；未配置代理时由 AI Hub 保留 URL、DNS 和目标 IP 的基础校验。
