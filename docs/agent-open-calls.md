# 自定义智能体开放调用

入口：自定义智能体 → 基本信息 → 开放调用。仅创建者可以配置，私有智能体也可以开通。默认关闭；开启时必须已经保存支持 Claude Code 的平台默认模型，并使用 container 或 native 隔离环境。

## 配置和密钥

- 只需开启「允许程序调用」，开关立即保存。开放调用自动沿用智能体已保存的主提示词、全部绑定技能和连接器，无需重复配置。
- 首次开启、关闭后重新开启、重置密钥都会生成新的 256 位随机密钥，仅当次显示。服务端仅存 SHA-256 摘要，刷新页面后显示「已配置」，不能找回明文。
- 修改智能体配置不会重置密钥。后续执行会读取当前已保存的配置；执行中的任务保持开始时的配置。关闭或重置后，旧密钥立即不能提交或查询，旧任务最迟在下一次控制轮询时停止。
- 技能加载、版本选择、连接器配置与权限校验复用普通智能体执行逻辑。绑定的作者 latest 技能也可使用；停用或解绑的技能不再加载，其他智能体的私有资源不会混入。
- 连接器沿用此智能体作用域内已保存的端点、凭据和工具范围，支持平台允许的传输方式；不再额外维护只读连接器名单。现有非交互限制仍适用：复用浏览器登录身份的连接器需要网页 Bearer Token，要求人工授权的工具需要网页交互，不能通过开放调用完成。
- 技能规则和脚本、Shell、工作区读写等能力沿用智能体执行环境与既有权限策略。每次调用仍使用独立会话和临时工作区。

## 查看调用记录

智能体左侧栏 → API 调用记录，位于「统计信息」下方。仅创建者开启开放调用后显示该菜单；关闭后隐藏，重新开启后仍可查看历史记录。基本信息页只保留调用设置。列表展示请求时间、运行 ID、请求内容、状态及耗时，可分页、刷新和按完整运行 ID 查询，每 5 秒自动更新。详情展示完整请求、指定技能、最终回复、失败原因、Token 和积分。关闭调用或重置密钥不会清除创建者的审计记录；此前创建的 API 请求也会显示。

记录接口只接受智能体创建者的登录身份：

- GET `/api/agents/{agent_id}/open-call/runs?skip=0&limit=20`
- GET `/api/agents/{agent_id}/open-call/runs/{run_id}`

原始调用参数保存在运行审计快照中，仅包含 prompt 和 skill，不含调用密钥。队列执行输入仍在结束后清空；旧记录从已存储的用户消息恢复请求内容。更新本地后端后重启 API、刷新前端页面即可使用，无需数据库迁移。

## 调用

推荐 Header + JSON，POST 发起一次独立任务。页面生成当前站点的完整 URL，并提供可复制的 curl 示例。

```bash
curl -X POST 'https://<AIHub站点>/aihub/api/open/agents/123/runs' \
  -H 'X-Agent-Key: <密钥>' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: order-123-analysis' \
  --data '{"skill":"test-skill","prompt":"告诉我这个东西是什么"}'
```

| 参数 | 含义 |
| --- | --- |
| skill | 可选；智能体已绑定的技能名称，或 `id:21` 这样的技能 ID。名称重复时请使用 ID。无效标识返回 422，不会静默回退。省略时加载全部当前绑定的技能供智能体按需选择。 |
| prompt | 可选；本次任务说明，不会覆盖智能体的主提示词。省略或仅含空白时，按智能体自身的主提示词和职责开始执行。最长 16000 字符。 |
| Idempotency-Key | 可选请求头，最长 100 字符；同一密钥下相同任务重试复用原运行，内容不同返回 409。每个新任务使用不同值。 |

外部接口保持原始 JSON，不套用站内的 `{code,message,data}` 成功包装。错误 HTTP 状态码保持 401、404、409、422、429 等，错误体为 `{"error":{"code":401,"message":"…"}}`。接口不接受会话 ID、模型覆盖、权限模式或附件参数。

8 秒内完成返回 HTTP 200：

```json
{"run_id":"aabbcc","status":"succeeded","result":"这是……"}
```

超过等待时间返回 HTTP 202，同时通过 Location 和 Retry-After 提供查询提示。任务继续执行，不依赖 HTTP 连接存活：

```json
{"run_id":"aabbcc","status":"running","status_url":"/aihub/api/open/agents/123/runs/aabbcc"}
```

```bash
curl 'https://<AIHub站点>/aihub/api/open/agents/123/runs/<run_id>' \
  -H 'X-Agent-Key: <同一密钥>'
```

查询返回 HTTP 200，`status` 为 queued、running、succeeded、failed、timed_out、cancelled 或 unknown。失败通过 `error` 字段返回，不暴露运行堆栈、工具明细或内部错误原文。unknown 表示执行进程失联，系统不会自动重跑，应核查后再决定是否提交新任务。

结果仅返回最终文本，可包含 Markdown，不提供原始工具输出、推理内容或工作区文件下载。新密钥无法查询旧密钥生成的任务。

## 拼 URL 参数

兼容原需求中的调用形式，但仍须 POST，GET 不执行任务：

```text
POST /aihub/api/open/agents/123/runs?session_key=<密钥>&skill=test-skill&prompt=<URL编码后的提示词>
```

查询参数模式由 `AGENT_OPEN_CALL_ALLOW_QUERY` 控制，默认 false。先完成网关、反向代理和外层访问日志的参数脱敏，再将其设为 true 并重启 API；页面随后会显示可复制的拼参 URL。AI Hub 自身的 Uvicorn 访问日志已对开放调用路径去除整个查询串。Header 和 URL 不能同时传密钥，JSON 和 URL 不能重复传同一个参数。

推荐程序通过 URL 编码库构建参数，不直接拼接中文、&、+ 等字符。关闭查询模式时，Header + JSON 调用仍可正常使用。

## 运行与隔离

任务和待执行输入先写入数据库队列，API 启动后自动消费，不额外依赖 Redis 或消息渠道 Worker。多个 API 实例使用行锁认领同一任务，运行租约与工作区执行锁复用现有机制。每个智能体最多 4 个未完成任务、每分钟最多创建 20 个任务；相同幂等请求不重复占用。

每次创建独立的 source=api 会话。审计和扣费属于创建者，运行计入「统计信息 → 开放调用」。调用不出现在普通网页聊天列表，不能从网页会话接口续聊或手工改写。

文件系统每次使用新的 open-<run_id> 根目录，native 下使用独立临时 Linux 用户，container 下使用独立容器及挂载。不会复制创建者的文件、Claude 会话历史或旧工作区，也不会注入平台全局运行环境；仅加载此智能体作用域内的连接器及其已保存凭据。结束时丢弃临时文件。发布模型通过现有 Run Credential 和积分结算服务计费。

队列等待最长 15 分钟。已开始的运行沿用智能体的执行时限，进程失联后标记 unknown 并进入已有积分对账流程，不自动重试，避免重复操作或扣费。队列输入在任务结束后清空，普通消息和运行记录保留用于审计。

## 上线配置

1. 数据库已完成 062 时，执行 `python backend/migrations/run_upgrade.py --from 063 --apply`；或单独执行 `backend/migrations/063_agent_open_calls.sql`。该迁移只增加 agent_open_calls 和 agent_open_requests 两张表，可重复执行。不要通过导入 main 来做离线结构检查。
2. 更新后端和前端并重启 API。native 环境需要既有的 useradd、userdel、runuser、pkill 和文件操作权限；container 环境需要可用的 Docker 及已配置的运行镜像。
3. 在 IAM 中完成 AIHub 的接口发现/路由同步。仅下面两个运行接口不要求浏览器登录，后端强制验证调用密钥：
   - POST `/aihub/api/open/agents/{agent_id}/runs`
   - GET `/aihub/api/open/agents/{agent_id}/runs/{run_id}`
4. 配置管理的 GET/PUT `/aihub/api/agents/{agent_id}/open-call`、POST `/aihub/api/agents/{agent_id}/open-call/rotate` 仍须经过原登录网关，并由后端再次核对创建者。不要将整个 /agents 前缀设为匿名。
5. 对新接口确认网关会转发 X-Agent-Key 和 Idempotency-Key，POST 超时大于 8 秒，响应禁止缓存。跨域访问时按调用方实际来源配置现有 CORS。开启 URL 查询模式前还需完成外层日志脱敏。

## 本地验证

```bash
cd backend
DATABASE_URL=sqlite:////private/tmp/aihub-open-call-test.sqlite .venv/bin/python -m pytest -q test_agent_open_calls.py
```

测试使用临时 SQLite、模拟运行器和本地子进程，不连接业务数据库或外部模型。覆盖密钥隔离、关闭/重置、独立会话、配置自动继承、动态绑定与版本、幂等、限流、超时回收、结果格式、共享执行链路和既有非交互权限策略。

浏览器验证：先启动 Vite，再执行 `OPEN_CALL_TEST_URL=http://127.0.0.1:15273 node browser-tests/agent-open-call.mjs`，可通过 PLAYWRIGHT_MODULE_PATH 指定 Playwright 包目录。浏览器请求使用测试桩，不修改线上智能体。
