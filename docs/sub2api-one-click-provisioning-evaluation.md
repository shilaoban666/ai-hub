# sub2api 用户与 API Key 一键开通评估

## 1. 背景与目标

AI Hub 已接入 sub2api PostgreSQL，用于个人及全局 Token 用量统计。当前用户要使用公司内部模型时，仍需管理员手工创建 sub2api 账号，再由用户登录 sub2api 创建 API Key、选择分组，最后返回 AI Hub 创建模型。

目标是在 AI Hub 的模型管理页面提供一键开通能力：

1. 根据当前 IAM 用户查找或创建 sub2api 用户。
2. 用户不存在时，使用以下规则创建：
   - 邮箱：`{username}@fancyqube.com`
   - sub2api 用户名：IAM `first_name`
   - 角色：`user`
   - 状态：`active`
   - 初始余额：`100`
   - 并发数：`5`
3. 创建专用 API Key，并绑定名称为 `default` 的分组。
4. 将 API Key 返回给当前用户，自动带入 AI Hub 的新增模型表单。

## 2. 结论

该功能技术上可行。sub2api 已提供管理员创建用户、查询分组、查询用户 API Key，以及普通用户创建 API Key 的 HTTP API。

但当前版本没有“管理员代指定用户创建 API Key”的接口。因此有两种落地方式：

- 短期方案：完全使用现有 API。管理员创建新用户后，AI Hub 使用随机密码短暂登录该用户，再调用用户 API 创建 Key。
- 推荐方案：给 sub2api 增加一个受保护的管理员或集成端点，由服务端直接调用现有 `APIKeyService.Create(ctx, userID, req)` 创建 Key。

不建议让 AI Hub 直接写入 sub2api 的 `users` 和 `api_keys` 表。直写会绕过密码处理、分组权限校验、审计、缓存失效和后续版本中的业务规则。

## 3. AI Hub 当前状态

### 3.1 sub2api 数据源

AI Hub 当前通过 [sub2api_database.py](../backend/sub2api_database.py) 连接 sub2api PostgreSQL。帮助函数被定义为只读查询，生产连接账号实测为 `readonly_user`。

该账号对以下相关表只有 `SELECT` 权限：

- `users`
- `api_keys`
- `groups`
- `user_allowed_groups`

因此现有数据库连接不能创建用户或 API Key，也不应扩展成高权限通用连接。

### 3.2 模型管理

AI Hub 已有模型 CRUD：[main.py](../backend/main.py#L1005)。模型创建会保存用户填写的 API Key，并通过现有凭据加密机制落库。

模型列表中的“获取公司内部 API Key”目前仅打开内部文档：[ModelList.vue](../frontend/src/views/admin/ModelList.vue#L344)。该按钮可以替换为一键开通请求，成功后打开新增模型弹窗并填入返回的 Key。

### 3.3 身份匹配风险

当前个人用量接口通过 IAM username、邮箱和 sub2api 邮箱前缀进行模糊匹配：[dashboard_routes.py](../backend/dashboard_routes.py#L358)。这种做法在用户名变更、重名或跨系统 ID 不一致时存在串号风险。

项目审计文档已经记录该问题：[aihub-system-audit-and-roadmap.md](./aihub-system-audit-and-roadmap.md#L276)。一键开通应同时建立不可变的一对一映射，不能继续依赖邮箱前缀猜测身份。

## 4. sub2api 数据库实测

检查时间：2026-07-23。检查仅执行只读查询，没有创建或修改任何数据。

### 4.1 参考用户“吴张洁”

| 字段 | 实测值 |
| --- | --- |
| sub2api user ID | `12` |
| 邮箱 | `wuzhangjie@fancyqube.com` |
| 用户名 | `吴张洁` |
| 角色 | `user` |
| 状态 | `active` |
| 并发数 | `5` |
| 密码算法 | bcrypt |
| 余额 | 约 `88.33`，查询期间仍有消费 |

该用户存在多个 Key，其中名为 `claude` 的 active Key 绑定：

- `group_id = 1`
- 分组名：`default`
- `quota = 0`，表示不设置单 Key 配额上限
- 无过期时间
- Key 格式为 `sk-` 前缀，总长度 67

该用户在 `user_allowed_groups` 中没有记录。因此绑定普通的非专属 `default` 分组时，不需要额外写入 `user_allowed_groups`。

### 4.2 default 分组

实测 active 的 `default` 分组存在，当前 ID 为 `1`，并具有以下属性：

- `platform = anthropic`
- `subscription_type = standard`
- `is_exclusive = false`
- `claude_code_only = false`

实现时仍应按名称动态查询 active 的 `default` 分组，不能硬编码 ID `1`。

### 4.3 余额

`users.balance` 数据库默认值为 0。当前 45 个持有 active/default Key 的用户余额全部大于 0，参考用户的 `total_recharged` 为 0，但余额为正，说明现有余额主要是管理员直接授予。

本功能已确认新用户初始余额固定为 `100`。创建用户时应在 API 请求中显式传入 `balance: 100`，不依赖 sub2api 全局默认余额。

## 5. sub2api 仓库调研

调研仓库：[Wei-Shaw/sub2api](https://github.com/Wei-Shaw/sub2api)

调研基线：commit `2c76506e072af3aa1a853ef7da71fec7a9ad60d7`，提交时间 2026-07-23。

### 5.1 管理员认证

sub2api 管理接口支持两种认证方式：

- `x-api-key: <admin-api-key>`
- `Authorization: Bearer <admin JWT>`

源码：[admin_auth.go](https://github.com/Wei-Shaw/sub2api/blob/2c76506e072af3aa1a853ef7da71fec7a9ad60d7/backend/internal/server/middleware/admin_auth.go#L23)

Admin API Key 是全局高权限凭据，会映射到系统中的第一个管理员账号，不具备细粒度 scope。若 AI Hub 使用该凭据，必须仅保存在后端环境变量中，并限制网络访问与日志输出。

### 5.2 创建用户

接口：

```http
POST /api/v1/admin/users
x-api-key: <admin-api-key>
Content-Type: application/json
```

请求示例：

```json
{
  "email": "zhangsan@fancyqube.com",
  "password": "<server-generated-random-password>",
  "username": "张三",
  "notes": "Provisioned by AI Hub",
  "role": "user",
  "balance": 100,
  "concurrency": 5,
  "rpm_limit": 0,
  "allowed_groups": []
}
```

源码：

- [请求结构](https://github.com/Wei-Shaw/sub2api/blob/2c76506e072af3aa1a853ef7da71fec7a9ad60d7/backend/internal/handler/admin/user_handler.go#L61)
- [Handler](https://github.com/Wei-Shaw/sub2api/blob/2c76506e072af3aa1a853ef7da71fec7a9ad60d7/backend/internal/handler/admin/user_handler.go#L271)
- [Service](https://github.com/Wei-Shaw/sub2api/blob/2c76506e072af3aa1a853ef7da71fec7a9ad60d7/backend/internal/service/admin_user.go#L120)

管理员创建用户接口本身没有接入 sub2api 的 idempotency helper。AI Hub 必须先精确查询邮箱，并在并发冲突后重新查询，避免重复开户。

### 5.3 查询分组

管理员可使用：

```http
GET /api/v1/admin/groups/all
x-api-key: <admin-api-key>
```

AI Hub 应从响应中查找满足以下条件的唯一分组：

```text
name == "default"
status == "active"
deleted_at == null
```

找不到或命中多个时应停止开通并返回配置错误。

### 5.4 创建 API Key

现有创建接口属于用户接口，需要目标用户 JWT：

```http
POST /api/v1/keys
Authorization: Bearer <user-jwt>
Idempotency-Key: <stable-idempotency-key>
Content-Type: application/json
```

请求示例：

```json
{
  "name": "aihub",
  "group_id": 1,
  "quota": 0
}
```

路由源码：[user.go](https://github.com/Wei-Shaw/sub2api/blob/2c76506e072af3aa1a853ef7da71fec7a9ad60d7/backend/internal/server/routes/user.go#L64)

Handler 源码：[api_key_handler.go](https://github.com/Wei-Shaw/sub2api/blob/2c76506e072af3aa1a853ef7da71fec7a9ad60d7/backend/internal/handler/api_key_handler.go#L143)

注意：Handler 注释写的是 `/api/v1/api-keys`，但当前实际注册路由是 `/api/v1/keys`，应以路由文件为准。

API Key 服务会：

- 校验目标用户状态。
- 校验用户是否允许绑定目标分组。
- 使用安全随机数生成 Key。
- 写入 Key 记录。
- 失效认证缓存。
- 编译 IP 白名单及黑名单规则。

Key 生成使用 32 字节安全随机数，默认生成 `sk-` 加 64 位十六进制字符串：[api_key_service.go](https://github.com/Wei-Shaw/sub2api/blob/2c76506e072af3aa1a853ef7da71fec7a9ad60d7/backend/internal/service/api_key_service.go#L321)。

### 5.5 管理员 API Key 能力缺口

管理员目前可以：

- 查询指定用户的 Key：`GET /api/v1/admin/users/:id/api-keys`
- 修改已有 Key 的分组：`PUT /api/v1/admin/api-keys/:id`

管理员目前不能代指定用户创建 Key。现有 admin API Key handler 只有更新分组能力：[apikey_handler.go](https://github.com/Wei-Shaw/sub2api/blob/2c76506e072af3aa1a853ef7da71fec7a9ad60d7/backend/internal/handler/admin/apikey_handler.go#L25)。

管理员查询用户 Key 的响应包含完整 `key` 字段，因此 AI Hub 可以幂等复用已经存在的 `aihub` Key。

## 6. 当前 sub2api 部署状态

对 `https://sub2api.fancyqube.net` 进行了未认证只读探测：

| 路由 | 状态码 | 结论 |
| --- | --- | --- |
| `GET /api/v1/admin/users` | 401 | 管理路由在线，要求认证 |
| `GET /api/v1/keys` | 401 | 用户 Key 路由在线，要求 JWT |
| `GET /api/v1/groups/available` | 401 | 用户分组路由在线，要求 JWT |

数据库 settings 实测：

| 设置 | 当前值 |
| --- | --- |
| `admin_api_key` | 未配置 |
| `backend_mode_enabled` | `false` |
| `turnstile_enabled` | `false` |
| `default_balance` | `0` |

Turnstile 和 backend mode 当前不会阻止“创建用户后短暂登录”的兼容方案。Admin API Key 需要由 sub2api 管理员登录后台后生成一次，再通过 AI Hub 后端环境变量配置。

## 7. 推荐实现

### 7.1 AI Hub API

建议新增：

```http
POST /api/models/internal-api-key/provision
```

建议响应：

```json
{
  "created": true,
  "user_created": true,
  "key_created": true,
  "email": "zhangsan@fancyqube.com",
  "username": "张三",
  "group": "default",
  "api_key": "sk-...",
  "api_proxy_url": "https://sub2api.fancyqube.net"
}
```

响应必须设置：

```http
Cache-Control: no-store
```

### 7.2 身份规则

身份字段只能来自网关注入的可信 Header：

- 邮箱前缀：`CurrentUser.username`
- sub2api 用户名：`CurrentUser.first_name`
- AI Hub 主体：`CurrentUser.user_id`

校验规则：

- `username` 必须是合法邮箱 local-part，不允许包含 `@`、空白或路径字符。
- 邮箱统一转小写。
- `first_name` 不能为空。
- 邮箱冲突但本地映射不一致时返回 409，禁止自动认领。

### 7.3 显式映射

建议在 AI Hub MySQL 新增映射表，例如：

```text
sub2api_user_bindings
- id
- aihub_user_id          UNIQUE
- sub2api_user_id        UNIQUE
- sub2api_email          UNIQUE
- provisioned_key_id
- created_at
- updated_at
```

后续个人用量查询也应优先使用该映射，不再通过邮箱前缀模糊匹配。

### 7.4 短期兼容流程

在不修改 sub2api 的情况下：

1. AI Hub 使用 Admin API Key 查询 `default` 分组。
2. 按规范邮箱精确查找 sub2api 用户。
3. 用户不存在时生成随机密码，并调用管理员创建用户 API，显式传入余额 100。
4. 查询该用户的 API Key，若已有 active、名称为 `aihub`、绑定 `default` 的 Key，则直接返回。
5. 对本次新建用户，使用随机密码调用 `/api/v1/auth/login` 获取短期 JWT。
6. 使用 JWT 和稳定的 `Idempotency-Key` 调用 `POST /api/v1/keys`。
7. 丢弃随机密码、JWT 和 refresh token，不写日志、不落 AI Hub 数据库。
8. 保存 AI Hub 与 sub2api 用户及 Key 的映射。
9. 返回 API Key，并在前端打开新增模型弹窗。

该流程覆盖：

- 新用户首次开通。
- 已通过 AI Hub 开通、再次点击的用户。
- 已存在且已有可复用 default Key 的历史用户。

该流程不能覆盖“历史用户已存在、没有可复用 Key、AI Hub 不知道其密码”的情况。不能通过管理员重置密码解决，否则会破坏用户原有 sub2api 登录凭据。

### 7.5 推荐的 sub2api 补充接口

建议给 sub2api 增加：

```http
POST /api/v1/admin/users/:id/api-keys
```

请求：

```json
{
  "name": "aihub",
  "group_id": 1,
  "quota": 0
}
```

Handler 应调用现有 `APIKeyService.Create(ctx, userID, req)`，并接入 admin idempotency helper。这样可以复用全部业务校验与缓存处理，同时覆盖历史用户，不需要临时登录或直接写数据库。

更完整的方案是在 sub2api 提供原子化集成端点：

```http
POST /api/v1/integrations/aihub/provision
```

该端点在 sub2api 内部完成用户查找/创建、余额 100、default 分组解析和专用 Key 创建。它应使用独立、可撤销、仅允许 provisioning 的集成凭据，而不是全权限 Admin API Key。

## 8. 幂等与并发

一键开通必须满足：

- 同一 AI Hub 用户重复点击返回同一专用 Key。
- Key 名称固定为 `aihub`，不复用用户的其他业务 Key，除非专门设计了历史迁移策略。
- 用户查询必须做邮箱精确比较，不能只相信 sub2api 的 fuzzy search。
- 创建用户发生唯一键冲突时，应重新查询并校验映射，而不是直接失败或继续创建 Key。
- 创建 Key 使用稳定的 `Idempotency-Key`，例如基于 AI Hub user ID 和 provisioning 版本生成。
- 跨 AI Hub MySQL 与 sub2api 的操作无法组成单个数据库事务，重试必须能够从任意中间状态恢复。

## 9. 安全要求

- Admin API Key 只能配置在 AI Hub 后端，不得传给前端。
- API Key、随机密码、JWT 和 refresh token不得写入应用日志、错误详情或审计 payload。
- HTTP 客户端日志必须对 `Authorization`、`x-api-key` 和响应中的 `api_key` 脱敏。
- 一键开通接口必须要求已认证用户，并建议配置独立权限码或服务端限流。
- sub2api Admin API Key 权限范围很大；长期应改用细粒度集成凭据。
- 返回用户 Key 的响应应使用 `Cache-Control: no-store`。
- 前端拿到 Key 后只保存在内存中的模型表单；模型创建完成后由 AI Hub 现有凭据加密逻辑存储。

## 10. 上线前置条件

1. sub2api 管理员生成 Admin API Key。
2. AI Hub 增加 sub2api HTTP API 地址和管理凭据配置。
3. 建立 AI Hub 到 sub2api 的显式用户映射表。
4. 实现幂等的一键开通后端接口。
5. 将模型管理页面现有外链按钮替换为开通交互。
6. 明确历史用户 Key 迁移策略。
7. 优先为 sub2api 增加管理员代用户创建 Key 的接口。
8. 增加单元测试、并发测试和失败恢复测试，覆盖用户已存在、Key 已存在、default 分组缺失、余额设置失败、网络超时及跨库部分成功等场景。

