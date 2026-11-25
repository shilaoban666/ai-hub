# 工具授权

托管会话使用 `claude-agent-sdk==0.2.176` 的 `ClaudeSDKClient`、自定义 `Transport` 和 `can_use_tool` 回调。现有运行器继续创建 directory/native/container 沙箱进程、注入最小环境、翻译模型输出并负责超时和取消；SDK 负责 initialize、工具授权请求和控制响应。SDK 安装在后端，沙箱镜像继续使用原有 Claude CLI。

## 权限模式

| 模式 | 行为 |
| --- | --- |
| 默认权限（acceptEdits） | 保持已有工作区工具与普通绑定 MCP 的 allow 规则；MCP 自身策略要求确认时走 SDK 回调 |
| 逐次确认（default） | Web 会话追加 Bash、Write、Edit、NotebookEdit 及每个绑定 MCP 服务的 ask 规则；读取文件不主动询问 |

`ask` 规则覆盖已有 `allow`，否则只传 `--permission-mode default` 仍会自动批准预授权工具。工作区隔离钩子先检查越界、危险命令和平台托管文件，拒绝操作不允许通过用户授权解除。

SDK 回调同时校验绑定 MCP 的工具白名单；未绑定服务或不在允许列表中的工具直接拒绝，不创建可批准的请求。

运行器以 `--input-format stream-json --permission-prompt-tool stdio` 启动 CLI。stdin 在收到本轮 result 前保持打开，供 SDK 返回授权决定。native/container 环境头仍在第一个控制帧之前写入。Windows 的线程式子进程路径使用同一套 SDK 回调。

## 用户决定

1. SDK 回调创建 `agent_permission_requests` 待处理记录，等待已有决定查询逻辑。
2. Web 控制轮询发送 `permission_request`；现有事件缓存支持刷新后的重放，前端展示参数和允许/拒绝按钮。
3. 仅运行所属用户能够决定；授权过期、运行取消、服务错误和不支持交互的渠道均拒绝工具调用。
4. “本轮始终允许”仅对当前 run 内相同工具键生效。Bash 沿用命令首词作为工具键；新一轮重新询问。决定不会写入持久化 Claude allow 规则。
5. 单次授权等待上限为 120 秒，等待时间计入原有运行总超时。运行结束清理待处理授权。

## 安装与验证

安装 `backend/requirements.txt` 后重启后端。SDK 的 MCP 依赖要求升级 Pydantic 至 2.11.10、httpx 至 0.27.2，MCP 固定为 1.23.0，以兼容现有 FastAPI/Starlette 版本。

`backend/test_sdk_permissions.py` 使用真实 SDK、真实本地子进程和 SQLite 校验暂停/允许/拒绝链路，不调用外部模型或业务数据库。

`AIHUB_TEST_CLAUDE_BIN=/path/to/claude .venv/bin/python -m pytest -q test_sdk_cli_permissions.py` 在 backend 目录运行真实 CLI 集成测试：模型由本机 HTTP 测试服务模拟，MCP 由本机 stdio 测试服务提供，覆盖默认权限、逐次确认、强制确认和越界拦截。

`frontend/browser-tests/chat-permissions.mjs` 覆盖允许/拒绝/本轮记住、参数展示、失败提交保留弹窗及刷新恢复。可用 `CHAT_TEST_URL`、`PLAYWRIGHT_MODULE_PATH` 指定前端服务与 Playwright 安装路径。

官方参考：

- https://platform.claude.com/docs/en/agent-sdk/permissions
- https://platform.claude.com/docs/en/agent-sdk/user-input
- https://github.com/anthropics/claude-agent-sdk-python/tree/v0.2.176
