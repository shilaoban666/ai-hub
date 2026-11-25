# 认证与令牌安全改造

> 状态：双 profile 兼容代码已实现；数据库迁移、密钥注入、客户端切换和生产发布尚未执行。
> 决策：`legacy_hs256` 与 `secure_rs256` 共用现有 OAuth endpoint，按客户端 profile 签发；迁移不清空 token，不强制用户重新登录。
> 涉及仓库：`aihub`、`service/api-gateway`、`service/iam-service`。

## 目标与兼容边界

`secure_rs256` 是目标状态：

```text
Browser -- RS256 access JWT --> Gateway
        Gateway -- JWKS --> IAM
        Gateway -- sub --> Redis/IAM authorization snapshot
        Gateway -- sanitized x-user-* headers --> AI Hub
        Gateway -- request-bound assertion --> IAM API
```

AI Hub 后端不持有 JWT 密钥、不验证 access token，也没有直连 fallback。它只接受网关清洗并重新注入的 `x-user-*` 身份头，因此生产网络必须禁止客户端绕过网关访问 AI Hub API 端口。

Access JWT 只包含：

```text
iss, sub, aud, exp, iat, nbf, jti, token_type, azp, scope
```

`sub` 是字符串形式的用户 ID；姓名、邮箱、用户名、超级管理员、角色和权限不再写入 access token。Gateway 不使用 token 内的授权信息，而是按 `sub` 加载 IAM 当前授权快照。

Refresh token 是 `rt_` 前缀的高熵 opaque token，没有可解码 payload。数据库只保存 SHA-256、client 绑定、过期时间、family、父子关系及使用/撤销状态。每次刷新进行原子轮换，重放已使用 token 会撤销整个 family。

兼容期保留 `legacy_hs256`：

| 场景 | Access token | Refresh token | Gateway |
|---|---|---|---|
| 旧客户端保持 legacy | HS256，历史 claim 结构 | HS256 JWT | 独立 legacy 验签，`user_id` 归一化为 `sub` |
| 客户端切到 secure 后首次刷新 | 签发 RS256 | 签发 opaque `rt_` | 新旧均可验签 |
| 新客户端 | RS256 | opaque `rt_` | RS256 + JWKS |

Gateway 的 RS256 和 HS256 验签是两个固定算法的代码路径，不会把两个算法同时交给同一个 decoder。legacy token 中的用户名、邮箱、角色、权限和超级管理员字段一律忽略。旧 `aud` 使用可变的客户端名称，兼容路径维持历史行为；新 token 使用稳定资源 audience。

PAT 新签发统一使用 RS256。历史 PAT 数据库没有保存可恢复的 `jti`，撤销时按已有 token hash 写入 Redis denylist；Gateway 对 legacy PAT 同时检查 `jti` 和 token hash。

## OAuth 2.1 定位

`secure_rs256` 流程采用 OAuth 2.1 的核心安全基线：Authorization Code、强制 PKCE S256、浏览器使用 public client 且不持有 secret、禁用 implicit/password、新 refresh token 轮换。当前不宣称完整 OAuth 2.1 合规认证；兼容期仍接受历史 HS256 token，属于有截止时间的迁移例外。

## 数据库迁移

Expand 脚本：

```text
service/iam-service/app/migrations/20260719_oauth_token_hardening.sql
```

它只增加列和回填，不删除 access、refresh 或 PAT。已有客户端和 token 标记为 `legacy_hs256`；新 IAM 代码显式把新客户端和新安全 token 写为 `secure_rs256`。脚本按历史默认值用 604800 秒回填 refresh 有效期；执行前必须确认生产旧配置也是 7 天，若历史配置不同，应先把脚本中的秒数改为实际值。

Expand 阶段数据库默认值暂时保留 legacy。这是 K8s 滚动发布保护：未升级的旧 IAM pod 不认识新列，但仍会签发 HS256，数据库不能把这类记录误标为 secure。所有旧 pod 退出后，应重新执行脚本中的 refresh metadata 回填语句。

Contract 脚本：

```text
service/iam-service/app/migrations/20260719_oauth_token_hardening_contract.sql
```

Contract 会先检查以下条件，任一不满足即 `SIGNAL` 终止：

- 没有 legacy 客户端；
- 没有未过期 legacy access、refresh 或 PAT；
- secure refresh 的过期时间和 family 完整；
- secure PAT 全部有 `jti`。

检查通过后才清理已失效 legacy 行、收紧非空约束，并把数据库默认值改为 `secure_rs256`。执行 Contract 后还要发布删除 HS256 代码和旧密钥的后续版本；不能仅靠 SQL 认为 legacy 已退役。

## K8s 发布顺序

1. 备份 IAM MySQL，验证恢复流程；记录 access、refresh、PAT 与客户端总数。
2. 生成 RSA 私钥/公钥并注入 IAM。如果历史环境配置过 JWT HMAC secret，把其实际值注入 IAM 和 Gateway 的 `JWT_LEGACY_SECRET_KEY`，不要生成新值代替；如果历史环境从未配置过密钥，则保持为空并按下文的空密钥迁移策略处理。
3. 仅在存在真实历史 HMAC secret 时，为 Gateway 配置明确的 `JWT_LEGACY_ACCEPT_UNTIL` Unix 时间戳。它应覆盖计划保留的旧 refresh/PAT 最长有效期；历史为空密钥时 Gateway 不得开启 legacy access/PAT 验签。
4. 执行一次 Expand 迁移。不要执行 Contract。
5. 先完成 Gateway 双验签版本滚动发布。旧 IAM 此时仍只签发 HS256，新 Gateway 可以正常接收。
6. 再滚动发布双 profile IAM。等待所有旧 IAM pod 退出，重新运行 refresh metadata 回填并核对空值为零。
7. 将 AI Hub 对应客户端一次性改为 `client_type=public`、`client_secret=NULL`、`token_profile=secure_rs256`，然后发布 AI Hub 前端。其他 confidential 客户端不要批量改成 public。
8. 按应用逐个把 `token_profile` 从 legacy 改为 secure。该操作禁止降级；已有 legacy refresh 下次刷新时自动升级，不要求重新登录。
9. 观察至所有 legacy token 自然过期或被替换，再运行 Contract preflight 和 Contract。
10. 发布移除 legacy 代码的版本，删除 IAM/Gateway 中的旧 HMAC secret，确认制品、CI 变量和部署清单不再包含它。

滚动发布期间，不允许 IAM 先于 Gateway 开始签发 RS256，否则尚未升级的 Gateway pod 会拒绝新 token。

## 环境变量

IAM：

```text
JWT_ALGORITHM=RS256
JWT_LEGACY_SECRET_KEY=<actual previous production JWT secret>
JWT_PRIVATE_KEY_PATH=/run/secrets/iam-jwt-private.pem
JWT_PUBLIC_KEY_PATH=/run/secrets/iam-jwt-public.pem
JWT_KEY_ID=iam-rs256-2026-01
JWT_DEFAULT_AUDIENCE=api-gateway
JWT_ALLOWED_AUDIENCES=api-gateway,mcp-server
SESSION_SECRET_KEY=<independent random value>
ALLOW_DIRECT_JWT_AUTH=false
```

Gateway：

```text
JWT_ALGORITHM=RS256
JWT_LEGACY_SECRET_KEY=<same previous production JWT secret>
JWT_LEGACY_ACCEPT_UNTIL=<explicit Unix timestamp>
JWT_JWKS_URL=http://iam-service:9001/.well-known/jwks.json
JWT_ALLOWED_AUDIENCES=api-gateway,mcp-server
```

旧 secret 只能通过 K8s Secret 等部署系统注入，不得写入仓库、日志或前端变量。RSA 私钥只能存在于 IAM；Gateway 只读取 JWKS 公钥。`SESSION_SECRET_KEY` 必须独立，不能复用旧 JWT secret。

迁移版本兼容旧部署变量名 `JWT_SECRET_KEY`，其值会作为 legacy HS256 密钥使用；`JWT_LEGACY_SECRET_KEY` 优先级更高。完成 Contract 后两个变量都应删除。

如果历史部署从未配置 `JWT_SECRET_KEY`，旧代码会落入空字符串默认值。Gateway 禁止接受这种可伪造的 HS256 access/PAT；不能通过重新设置一个空值来兼容。IAM 仅允许已经精确命中数据库 SHA-256、完成 client 绑定检查并持有行锁的旧 refresh 按 opaque token 处理，一次性轮换到 `secure_rs256`。这种环境必须先把客户端切到 secure；历史 PAT 需要重新生成。

## 观测与切换判定

发布前后至少监控以下维度：

- Gateway 按 `secure_rs256`、`legacy_hs256` 统计验签成功、失败和调用方；
- IAM 按客户端统计 code exchange、legacy refresh bridge、refresh reuse；
- JWKS 拉取失败、未知 `kid`、Redis denylist 不可用；
- 401/403、OAuth token endpoint 4xx 的基线变化。

数据库核对示例：

```sql
SELECT token_profile, COUNT(*) FROM oauth2_provider_application GROUP BY token_profile;
SELECT token_format, COUNT(*) FROM oauth2_provider_accesstoken GROUP BY token_format;
SELECT token_format, COUNT(*) FROM oauth2_provider_refreshtoken
WHERE revoked IS NULL AND (expires IS NULL OR expires > UTC_TIMESTAMP(6))
GROUP BY token_format;
SELECT token_format, COUNT(*) FROM oauth2_personal_accesstoken
WHERE expires_at > UTC_TIMESTAMP(6) GROUP BY token_format;
```

不能仅根据 access token 归零执行 Contract；refresh 和 PAT 生命周期更长，必须分别归零。

## 验收

- 旧 HS256 access 在截止时间前仍能通过 Gateway，且权限来自 IAM 当前快照；
- legacy token 中伪造或过时的超级管理员、角色、权限字段不影响授权；
- legacy 客户端继续刷新得到 legacy token；客户端切到 secure 后，同一旧 refresh 可换得 RS256 + opaque token；
- access JWT payload 不包含 PII、角色、权限和超级管理员字段；
- public client 不发送 secret 可以完成 code exchange 和 refresh；前端制品不包含 `VITE_OAUTH2_CLIENT_SECRET`；
- 错误 audience、未知 `kid`、算法混淆、refresh token 作为 bearer 均被拒绝；
- refresh 跨 client 使用失败，旧 refresh 重放撤销整个 family；
- legacy 截止时间到达后 Gateway 拒绝所有 HS256 token；
- PAT 撤销后 denylist 立即生效；Redis 不可用时撤销与 Gateway 鉴权失败关闭；
- Contract 在任何活跃 legacy token 存在时拒绝执行。

## 回滚约束

Expand 是前滚兼容结构，不应回滚删列。Gateway 双验签版本可在不签发 secure token 时回滚；一旦 IAM 已签发 RS256/opaque token，就不能回滚到只理解 HS256/JWT refresh 的旧版本。

客户端切到 `secure_rs256` 后不允许改回 legacy。出现问题应保留双 profile 代码，修复 RS256/JWKS/opaque 路径并前滚。Contract 属于不可逆收缩动作，必须在备份、preflight 和 legacy 流量归零后单独审批执行。
