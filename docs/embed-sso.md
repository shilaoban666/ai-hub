# 业务系统嵌入 AI 助手：用户无感登录

业务系统后端用 `client_id + client_secret + user_id` 向 IAM 申请用户 JWT，宿主页面通过 postMessage 交给 AI Hub iframe，后者在内存中保存并以 Bearer 方式请求现有接口。

这是新增的可信系统代用户授权接口，不是代表应用自身的标准 client_credentials 授权。普通 OAuth 登录、工作台刷新和网关鉴权保持原有流程。

## 注册与配置

在 IAM 客户端管理中为 fancyqube 注册独立客户端：`client_type=confidential`、`token_profile=secure_rs256`，保存注册时返回的 client_id 和 client_secret。新接口不使用重定向地址或授权码；不要将 AI Hub 的 public SPA 客户端改成 confidential。

IAM 统一在 `.env` 中配置受信任应用，填写注册返回的 client_id（不是应用记录编号），多个 ID 用英文逗号分隔。`app/config.py` 只保留空默认值，未配置时关闭代用户登录：

```ini
EMBED_SSO_ALLOWED_CLIENT_IDS=<fancyqube的client_id>,<另一系统的client_id>
```

fancyqube `Project/settings.py` 最下方读取：

```ini
AIHUB_EMBED_CLIENT_ID=<fancyqube的client_id>
AIHUB_EMBED_CLIENT_SECRET=<注册时返回的client_secret>
```

环境变量优先，其次为未纳入版本管理的 `.aihub-embed-sso.json`。助手地址、部门、姓名白名单沿用现有配置，IAM 地址沿用 env_settings.iam_service_url。AI Hub 的 VITE_OAUTH2_CLIENT_ID 继续使用工作台原有 public client，无需与 fancyqube 相同。

本地可运行配置工具，按提示隐藏输入已注册的密钥：

```powershell
python scripts/configure_embed_sso.py --fancyqube-root D:\git_repo\fancyqube --iam-root D:\git_repo\service\iam-service --client-id <fancyqube的client_id>
```

工具保存 fancyqube 私有配置，向 IAM 白名单追加 ID，保留其他系统配置。它不注册或验证客户端，也不重启服务。修改配置后按需要重启服务并发布新版 AI Hub 前端。

client_secret 只存后端，不能进入 HTML、iframe URL、VITE 变量或浏览器存储。线上服务间请求使用 HTTPS 或受保护的内部传输。

## IAM 接口

业务后端调用 `POST /o/embed/user-token/`，JSON 请求：

```json
{"client_id":"业务系统客户端ID","client_secret":"注册密钥","user_id":7}
```

IAM 校验已注册 confidential client、现有哈希密钥、代用户授权白名单、secure_rs256 签名配置及启用中的 IAM 用户。user_id 必须从业务后端登录态读取，不能由浏览器指定。接口拒绝 scope、权限等额外字段。

成功响应的 data 内容（生产 IAM 中间件增加 code/message/timestamp/data 外层）：

```json
{"access_token":"IAM签发的用户JWT","token_type":"bearer","expires_in":900,"user_id":7}
```

有效期沿用 JWT_ACCESS_TOKEN_EXPIRE（默认 900 秒）。JWT 的 sub 为用户 ID、azp 为业务 client_id、aud 沿用网关 audience。仅保存 access token 哈希，不生成/返回 refresh token，权限由 IAM 及原网关/后端决定。aihub_embed scope 是通道标记，现有网关不会仅凭该标记限制令牌只能访问 AI Hub。

错误状态：400 参数不合法；401 client 凭据错误或 public client；403 client 未获授权、签名配置不符或用户不存在/停用。成功及这些错误响应禁止缓存。签发日志只记 client_id 和 user_id，不记录密钥或 JWT。

## 页面与会话

宿主脚本先向同源业务后端确认用户和会话指纹，再携带 CSRF、Cookie 及指纹申请 JWT。fancyqube 检查账号和部门/姓名资格。宿主与 iframe 双向验证 postMessage 来源、窗口和随机请求标识；iframe 接收后再次确认业务会话未变化。

JWT 短暂经过宿主脚本，所以宿主页也是可信边界。令牌只保存在 iframe 内存中，不放 URL、Cookie 或 localStorage，不覆盖独立工作台身份。新通道无需浏览器直接连接 IAM 换票。

业务请求复用 15 秒内的身份校验结果，并合并并发检查；没有固定周期的免登轮询。抽屉关闭或页面隐藏时使缓存失效，重新打开或返回前台时校验；普通聚焦事件复用有效缓存。Token 临近过期或遇到 401 时按需续签，签发前后仍强制检查身份。切换账号会清除旧凭据、卸载旧聊天、阻断旧请求重试/响应并取消旧流式接收。退出后不再获取新令牌。

闲置时不主动检查宿主退出或切换账号，下一次打开、返回页面或缓存过期后的业务请求会检查；已开始的后台任务仍可产生业务请求。退出、撤销 client 白名单或轮换密钥会阻止后续签发，已发 JWT 仍遵循现有撤销机制及到期时间，不保证立即失效，也不改变已启动的模型任务。

## 接入另一个系统

注册独立 confidential / secure_rs256 client 并加入 IAM 白名单，后端实现同源登录桥接接口，验证登录态、CSRF 和使用资格后，调用上述统一接口。引入同一份脚本：

```html
<script src="https://ai.example.com/embed/assistant.js"
        data-aihub-url="https://ai.example.com/embed/chat"
        data-aihub-auth-url="/api/ai-assistant/auth"
        data-aihub-csrf="服务端输出的CSRF令牌"></script>
```

桥接地址必须同源，缺省兼容 fancyqube 的 /func_process_app/aihub_embed_auth/。脚本通过 X-CSRFToken 传 CSRF，其他框架需适配。接口协议：

- 收到 action=status，返回 `{code:0,data:{user_id,session_id}}`。
- 收到 action=authorize，验证传入 session_id，再在 data 中增加 access_token、token_type、expires_in。
- session_id 是随登录会话变化的 64 位十六进制指纹，不能直接暴露会话密钥。
- 失败返回非 2xx 以及 `{code:-1,msg:"可展示的错误信息"}`。

AI Hub 的 VITE_EMBED_PARENT_ORIGINS 配置新系统完整 origin（含协议，逗号分隔），并按部署要求配置允许 iframe 的 CSP。

**身份约束：** user_id 是 IAM 统一用户 ID。fancyqube 当前按共享用户 ID 对接；独立用户库必须先映射为 IAM 用户，不能因本地 ID 也为 7 就当作 IAM 的 7，也不能根据姓名自动映射。白名单意味着信任该系统后端声明 IAM 用户身份，不能对普通自助注册 client 开放。

## 验证

- fancyqube：`python -B func_process_app/test_aihub_embed_sso.py`、`python -B extra_apps/xadmin/test_aihub_tags.py`。
- IAM：`python -m unittest app.test_embed_sso app.test_oauth_security`。隔离 SQLite 和测试 RSA 密钥，覆盖真实 JWT 验签、凭据、白名单、用户绑定及普通 OAuth 回归。
- AI Hub：`node --test tests/embed-sso.test.mjs tests/embed-context.test.mjs tests/online-preview-session.test.mjs`。
- 浏览器：`node browser-tests/embed-sso.mjs` 测用户免登；`node browser-tests/embed-chat.mjs` 测聊天。PLAYWRIGHT_MODULE_PATH 指定 Playwright，EMBED_TEST_URL 指定前端地址。

浏览器测试模拟业务登录及 IAM 响应，覆盖跨来源交付、无弹窗、凭据隔离、401 续期、切换账号、退出及工作台刷新。真实联调需要先完成客户端注册及配置。
