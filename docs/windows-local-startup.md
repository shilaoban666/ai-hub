# Windows 一键启动（native / WSL）

双击根目录 `aihub.bat`，或执行 `./aihub.bat start`。
前端在 Windows；后端、IAM、Gateway 在同一个 WSL2 发行版。
Channel Worker 仅在自己的 `.env` 显式启用微信或钉钉渠道时启动。

## 项目与配置

只需配置 `ApiGatewayRoot` 和 `IamServiceRoot`，启动器会分别检查两个项目的
`app/main.py`。缺少时明确列出需安装/克隆的项目并退出：

```powershell
./aihub.bat start -ApiGatewayRoot ../service/api-gateway -IamServiceRoot ../service/iam-service
```

仓库中的 `aihub-local.example.json` 是可直接使用的默认配置，别人拿到代码后无需
额外复制文件即可启动。三个项目都提供可随仓库交付的 `.env.local` 默认配置；启动器
只在 `.env` 不存在时复制它，已有 `.env` 永远不会覆盖。需要个人路径、端口或 WSL
设置时，再复制为被 Git 忽略的 `aihub-local.json` 做覆盖。相对路径以 AI Hub 根目录
解析；命令参数优先于配置文件。

```json
{
  "Distro": "Ubuntu-24.04",
  "User": "aihub",
  "ApiGatewayRoot": "../service/api-gateway",
  "IamServiceRoot": "../service/iam-service",
  "PublicHost": "localhost",
  "Ports": { "frontend": 15173, "backend": 15174, "gateway": 8080, "iam": 9001 },
  "RouteTargetOverrides": {}
}
```

`ApiGatewayRoot`、`IamServiceRoot` 可以填写绝对 Windows 路径，也可以填写相对
AI Hub 根目录的路径。命令行也可以临时覆盖：

```powershell
./aihub.bat start -ApiGatewayRoot D:\workspace\gateway -IamServiceRoot D:\workspace\iam
```

未指定发行版时优先检测具备 native 权限的 Ubuntu-24.04，再检查其他发行版。

## 自动安装与边界

自动安装缺少的 Windows Node LTS（通过 winget）、WSL/发行版、Linux apt 包、
Python 项目依赖、前端 npm 依赖、Linux Claude CLI；失败后输出明确安装要求。
系统重启、发行版首次用户初始化需要用户完成。
Node 需要 >=22.12 或 20.19+，WSL Python 需要 3.10+。

三个 Python 服务各自使用 `~/.local/share/aihub/stack/<服务名>` 虚拟环境。
依赖清单变化才重新安装；日常启动不拉 Git 代码、不执行数据库迁移。
纯 native 不要求 Docker。全新 WSL 会自动安装系统包、创建专用非 root 用户（默认
`aihub`）并写入该新用户专用的 `sudoers.d` 规则；如果配置的用户原本就存在，脚本
不会修改它的权限，必须先具备 `sudo -n`。持久工作区保留在 Linux 文件系统。

各项目保留自己的 `.env` 加载规则，缺失时明确提示配置。
首次 `start/restart/install` 时，如果项目目录存在 `.env.local` 但不存在 `.env`，
启动器会复制 `.env.local` 为 `.env`；已有 `.env` 永远不会被覆盖。
数据库、Redis、JWT 文件及加密密钥不能由启动器自动猜测或生成替代值。
IAM 和 Gateway 的身份断言密钥必须一致，检查仅比较指纹，不输出密钥。
启动和重启还会检查 AI Hub/IAM 数据库连接、三个服务的 Redis，以及 IAM 的 RS256
公私钥是否有效且匹配。对话 Redis 会使用临时健康键验证实际读写，随后删除；
数据库仅执行查询，不自动建库、迁移或修改 OAuth 客户端。
失败时指出对应的依赖，保留连接异常和凭据不输出。

新 clone 的 AI Hub `.env.local` 默认关闭微信、钉钉渠道，因此只启动四个服务。
已有 `.env` 的渠道设置继续生效。需要开发渠道时，在自己的 `.env` 显式启用
`WEIXIN_ILINK_ENABLED=true` 或 `DINGTALK_ENABLED=true`，并使用独立开发数据库、
Redis 和机器人绑定。只修改 Worker ID 无法隔离同一数据库的消费任务；
多个启用渠道的实例连接同一数据库时会作为同一个 Worker 集群消费。

## 地址与 OAuth

默认入口 `http://localhost:15173`；宿主机可访问 IAM `9001`、Gateway `8080`、
后端 `15174`。WSL 服务监听 `0.0.0.0`，内部使用 `127.0.0.1` 通信；
Windows 通过 WSL localhost 转发访问，动态 WSL IP 不写入数据库。
成功后列出每个服务的 URL、WSL 实际 IP、Windows IPv4 和日志位置。

Vite 仅在本启动器的 serve 会话使用明确传入的端口及 PublicHost。
普通 dev 和生产构建保持读取根 `.env`，不改写 `.env`。
业务 API 仍经 Gateway、认证直连 IAM、静态文件经前端代理直达后端。

OAuth 客户端需登记精确回调 `http://localhost:15173/oauth/callback`。
localhost 与 127.0.0.1 是不同回调。脚本保留 OAuth Client ID，不改共享客户端记录。

PublicHost 默认 localhost。若改成 LAN 主机名/IP，需自行配置防火墙、WSL 转发、
精确 OAuth 回调及 HTTPS（非 localhost 的 PKCE 要求安全上下文）。
检测到的网卡 IP 仅用于诊断，不代表已经能从其他电脑访问。

## Gateway 通用目标覆盖

Gateway 需包含 `ROUTE_TARGET_OVERRIDES` 支持。启动器默认注入本机 `/aihub`、
`/iam` 目标，其他服务继续使用数据库 IP。个人 JSON 中可增加：

```json
"RouteTargetOverrides": { "/common-service": "http://127.0.0.1:8000" }
```

优先级：个人映射 > Gateway 已配置覆盖 > 启动器默认本机映射 > 数据库/fallback。
各层先使用 Gateway 的实际别名规则归一化，再合并；个人层 `/iam-service` 可以覆盖
默认层 `/iam`。同一层给同一服务配置两个不同目标仍会报错，避免歧义。
只更换目标，不新增路由、不改变鉴权、权限、HTTP 方法或剥离前缀。
每次刷新后继续生效，`/gateway/health` 显示覆盖目标及匹配状态。
启动检查要求 IAM 数据库路由已加载、AI Hub/IAM 本机覆盖已匹配。

## 操作

```powershell
./aihub.bat start
./aihub.bat status
./aihub.bat doctor
./aihub.bat install
./aihub.bat restart
./aihub.bat stop
```

doctor 不安装、不启动服务；install 只安装并预检。日志与进程身份在 `.local-launch/`。
重复 start 复用配置一致的已管理进程；配置变更要求 restart。
端口被未知进程占用时退出，不自动杀进程。stop 不执行 wsl --shutdown。
WSL 或宿主机就绪检查失败，只回滚本次新进程，保留复用的原有服务。
restart 会先完成前端配置、依赖、数据库、Redis、密钥、路由及端口预检，再停止
WSL 旧服务；任何预检失败都保留旧进程。Windows 前端会保留到新 WSL 服务可访问后
再重启。这不是零停机发布：切换后若新进程异常退出，会清理本次新进程并报告失败，
不会自动恢复旧版本或回滚数据库。

WSL 中也可执行：

```bash
bash aihub-wsl.sh start-all \
  --gateway-root /mnt/d/git_repo/service/api-gateway \
  --iam-root /mnt/d/git_repo/service/iam-service
```

原 aihub-wsl.sh start/stop/status 仍仅管理后端与 Worker。
