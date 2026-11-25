# 智能体 Runtime 配置

AI Hub 将智能体行为配置与部署环境配置分开管理。Runtime 类型、模型、提示词、
Skills、MCP、最大轮次和运行超时存储在智能体记录中；环境变量只描述宿主机存储、
Claude Code 隔离方式。运行时抽象和注册机制保留，当前提供 Claude Agent。

## 共用工作区

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `AGENT_WORKSPACE_ROOT` | `backend/agent_workspaces` | Claude Code `directory` 模式工作区文件使用的宿主机目录。 |
| `USER_WORKSPACE_ROOT` | Linux：`/var/lib/aihub/user_workspaces`；macOS：项目内 `backend/user_workspaces` | 企业用户持久化文件、技能安装目录和每次运行的临时视图。留空时按系统选择默认值。 |

相对路径以项目根目录为基准解析。

## Claude Code

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `CLAUDE_CODE_SANDBOX_TYPE` | `.env.example` 为 `container` | 企业用户工作区支持 `container`、`native`。旧 `directory` 实现不适用于企业用户工作区。 |
| `CLAUDE_CODE_CONTAINER_IMAGE` | `aihub/claude-runtime:latest` | Claude Code 容器镜像，运行前需要构建或拉取。 |
| `CLAUDE_CODE_NATIVE_WORKSPACE_ROOT` | `/var/lib/aihub/agent_workspaces` | Linux 系统用户隔离的工作区根目录。 |
| `CLAUDE_CODE_NATIVE_USER_PREFIX` | `aihub_agent_` | native 隔离创建的 Linux 用户名前缀。 |
| `CLAUDE_CODE_NATIVE_CLAUDE_BIN` | 自动解析 `PATH` | native 智能体用户共用的 Claude Code CLI 绝对路径。 |

模式按后端进程实际运行的操作系统选择：

- 后端运行在 WSL 或普通 Linux 中时，直接使用 `native`，不需要再配置或调用另一个 WSL。
- macOS 后端使用 `container`，通过 Docker Desktop 运行 Linux 容器；`native` 依赖 Linux 用户管理，不支持 macOS。
- 当前企业用户工作区不支持 `directory`，不能通过切换到该模式绕过容器配置。

### macOS 本地运行

启动 Docker Desktop，并在项目根目录构建 Claude Runtime 镜像：

```bash
docker build -t aihub/claude-runtime:latest backend/runtime_images/claude
```

`.env` 使用 `CLAUDE_CODE_SANDBOX_TYPE=container`。`USER_WORKSPACE_ROOT` 留空或省略，
默认在项目内创建 `backend/user_workspaces`；也可以设置一个当前用户可写的绝对路径。
Docker Desktop 必须允许挂载该目录。Apple Silicon 默认构建本机架构的镜像，无需强制使用 amd64。
容器内模型网关默认通过 `host.docker.internal:15174` 访问宿主后端。

对话启动时，宿主 Docker CLI 保留后端账户的 `HOME`、`DOCKER_CONFIG`、`DOCKER_CONTEXT`
等连接配置；容器内的 `HOME` 使用 `/workspace`，模型凭据通过标准输入传入。
这两套环境独立构建，Docker Desktop 的宿主配置仅用于启动容器。

`./aihub-mac.sh start` / `restart` 会检查工作区是否可写、Docker 是否可用、镜像是否存在，
并在无网络、无宿主目录挂载的临时容器中验证镜像能创建带 pip 的虚拟环境。
修改代码或配置后需要重启后端及使用相同配置的 Worker。
从其他环境迁移时，还需复制 `backend/releases` 中绑定版本的发布 ZIP；数据库记录不包含这些文件。

### Linux native 运行

`native` 需要 root 权限，或为专用后端运行账户配置经过运维评审的免密 sudo 策略。
当前实现会进行系统用户管理、文件复制/权限/immutable flag 管理，并以智能体用户执行命令；
不要由应用自动写 sudoers。生产和 WSL 启动脚本会验证 `sudo -n` 和工作区位置，
不满足时阻止启动。工作区必须位于 Linux 文件系统（例如
`/var/lib/aihub/agent_workspaces`），不要放在 `/mnt/c`、`/mnt/d` 等 Windows 挂载盘上。
Claude Code CLI 必须可由所有智能体系统用户执行。默认从启动进程的 `PATH` 自动解析；
生产环境也可以通过 `CLAUDE_CODE_NATIVE_CLAUDE_BIN=/usr/bin/claude` 固定路径。

迁移期间仍兼容读取 `AGENT_SANDBOX_TYPE`、`AGENT_NATIVE_WORKSPACE_ROOT`、
`AGENT_NATIVE_USER_PREFIX`、`AGENT_LINUX_WORKSPACE_ROOT` 和
`AGENT_LINUX_USER_PREFIX`，新部署不应继续使用这些名称。

### 工作区 Python 与路径解析

每次运行生成的 `CLAUDE.md` 会明确当前运行环境内的工作区根目录，并要求脚本和依赖安装
使用同一解释器：`.venv/bin/python script.py`、`.venv/bin/python -m pip install <pkg>`。
Windows 的目录调试模式使用 `.venv\Scripts\python.exe`。
切换目录后应相应调整解释器路径，例如 `cd out && ../.venv/bin/python script.py`，
或直接使用工作区解释器的完整绝对路径。

运行环境会将工作区 `.venv/bin`（Windows 为 `.venv\Scripts`）放在 `PATH` 最前，
设置 `VIRTUAL_ENV`、`PIP_REQUIRE_VIRTUALENV=true`、`PYTHONNOUSERSITE=1`。
普通 `python`、`python3` 脚本调用因此优先使用工作区依赖；安装命令仍要求明确指定
工作区 `.venv` 的解释器或 pip，防止环境覆盖后误装到其他位置。
native 在用户持久化根目录复用 `.venv`，并确保隔离用户可写；container 将持久化目录
`managed/container-venv` 挂载到 `/workspace/.venv`，在容器内首次创建环境。
创建失败会终止准备过程并报告错误，避免悄悄回退到系统 Python。
初始化会验证解释器确实属于该虚拟环境且 pip 可导入；失败遗留的半成品环境会在重试时
原地补全，保留已有依赖。初始化输出进入错误日志，不混入智能体的 JSON 消息流。

路径检查以 SDK 提供的当前目录为起点，跟踪 `cd ... && ...` 后的目录，区分逻辑目录
与 `cd -P` 的物理目录，并保留条件分支中目录切换失败的可能性。
绝对路径不会因为 `/var`、`/tmp` 等前缀被拒绝；解析符号链接后必须属于当前工作区，
同一工作区的 `current` 别名和本轮 `view` 路径等价。native 的共享 `.venv` 只信任
当前用户的既定目录；其他符号链接仍执行越界检查。管道中的目录切换等无法确认的形式
会要求改用 `cd <目录> && <命令>`。

更新后需重启后端和使用同一代码的 Worker，新运行会重新生成提示词和钩子。
container 还需按上面的构建命令重建 Runtime 镜像，其中新增了 `python3-venv`；
native 宿主机也需具备 Python venv 支持。此变更不需要数据库迁移。

## 运行时扩展

`backend/runtimes/base.py` 定义统一的配置、事件、附件和执行接口。
`register_runtime(name, implementation, info=...)` 注册实现以及模型协议、推理能力等元数据。
当前注册 `claude_code`；后续可增加 Codex 等实现。模型 Provider 与运行时分别配置。
工作区隔离继续使用 `directory`、`native` 或 `container`。

## 技能共用环境变量

管理员可在「系统管理 → 全局设置 → 技能环境变量」中新增、修改或删除变量。
例如配置 `X_MCP_TOKEN` 和 `X_MCP_USER`，所有用户安装的技能脚本即可通过同名
环境变量读取，无需修改脚本、添加 `source` 命令或登录服务器修改配置。
变量名必须与脚本实际读取的名称一致，请使用字母、数字和下划线，不使用 HTTP 请求头里的连字符。

Python 脚本直接读取环境变量：

```python
import os

token = os.environ["X_MCP_TOKEN"]
user = os.environ.get("X_MCP_USER", "toolbox")
```

`os.environ["变量名"]` 在未配置时抛出异常；`os.environ.get("变量名", "默认值")` 在未配置时使用默认值。

配置保存在数据库中，每次对话运行重新读取；保存后下一次运行生效，无需重启后端或 Worker，
已经开始的运行保持原有环境。原生 Linux、容器和本地目录调试共用同一配置。
变量只注入运行进程，不写入技能发布包或工作区文件，不修改服务器全局环境。
环境变量的管理接口仅对管理员开放；用户脚本能够读取配置的值。
工作区路径、Python 解释器、模型认证及 AIHub 内部变量由系统管理，不能通过此处覆盖。

已有数据库在部署新代码前执行增量迁移（假定已完成 061）：

```bash
python backend/migrations/run_upgrade.py --from 062 --apply
```

## MCP 凭据

stdio MCP 使用 `env`，SSE、HTTP 和 Streamable HTTP MCP 使用 `headers`。
用户和智能体级覆盖由 `AGENT_CREDENTIAL_ENCRYPTION_KEY` 加密保存；配置文件使用
环境变量引用，实际凭据在执行时注入。技能、系统提示词及工具权限沿用现有工作区流程。

## 旧运行时数据升级

升级前完成 `backend/migrations/056_claude_runtime.py`，或使用统一升级入口从 056 执行。
迁移将旧智能体、全局策略、会话和运行单元切换到 Claude，清除不兼容的会话恢复标识，
保留数据库消息、历史运行审计与技能/MCP 绑定。跨运行时切换使用新的空工作区，不导入旧工作区文件。
必须先为受影响用户配置可用的 Anthropic Messages 模型；不会擅自改写模型协议或密钥。
运行中的任务须结束或经现有恢复流程处理后再迁移。旧实例记录仅用于历史审计，凭据清空并标记 retired。

自定义智能体保存时若发生运行时切换，会提示“更换runtime会导致工作区文件丢失，是否确认”。
取消不保存；确认后同时保存配置、更换工作区路径并清除会话恢复标识。旧目录不读取、不复制，
新工作区的生成配置和虚拟环境在下一次运行时重新准备。普通创建、保存和复制智能体不启动沙箱。
056 是停服数据升级，由部署人员执行；旧部署的独立 Worker 和容器由部署人员停用，应用不再启动它们。
若曾执行会导入旧文件的早期 056，可从 056 重新运行；仍处于待导入状态且有旧实例记录的工作区会改为空工作区，
同为 Claude 的沙箱迁移保留原有文件导入行为。

钉钉的 `DINGTALK_REGISTRATION_SOURCE` 是第三方扫码接口的注册模板标识，与智能体运行时无关。
为兼容已有扫码功能保留原值；后续如取得专属注册模板，可直接通过环境变量替换。
