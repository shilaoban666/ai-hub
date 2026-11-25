# 生产服务器部署

本文适用于使用 Claude Code `native` 或 `container` 沙箱的 Linux 生产服务器部署。示例路径与 `aihub.sh` 默认值一致：

- 项目目录：`/var/www/git_repo/aihub`
- Python 虚拟环境：`/var/www/git_repo/aihub-venv`
- AI Hub 服务账号：`aihub`
- Claude native 工作区：`/var/lib/aihub/agent_workspaces`

## 前端环境配置

前端开发和构建统一只读取根目录 `.env`。已关闭 Vite 的环境文件自动加载，
`.env.local`、`.env.prod`、`.env.production` 以及 shell 中的 `VITE_*` 均不会覆盖它。
只有 `.env` 内的 `VITE_*` 配置会写入浏览器代码，数据库和 Redis 等后端配置不会暴露。

由部署人员主动选择环境，生产部署时先复制，再构建：

```bash
cp .env.prod .env
cd frontend
npm run build
```

使用 `aihub.sh` 部署时，同样先在根目录完成复制，再运行部署脚本。
本地开发可先将 `.env.local` 复制为 `.env`，然后启动开发服务。

IAM 登录地址由 `VITE_AUTH_BASE` 决定，生产值为 `https://auth.fancyqube.net`。
该值在构建时写入前端静态资源；修改环境文件后需要重新构建并发布 `frontend/dist`，
仅重启后端不会改变已经发布的前端地址。

## 权限模型

AI Hub 后端和消息渠道 Worker 使用非 root 专用账号。Claude native 沙箱的特权操作通过 sudo 完成。
`aihub.sh` 支持 root 运维入口：检测到 root 后会自动通过 `runuser` 切换到
`AIHUB_SERVICE_USER`，默认值为 `aihub`。

## 首次初始化

以下命令在 root 终端执行。创建专用服务账号并禁止密码登录：

```bash
id aihub >/dev/null 2>&1 || useradd -m -s /bin/bash aihub
passwd -l aihub
usermod -aG docker aihub
```

确保服务账号拥有项目和虚拟环境。Claude native 工作区由沙箱
通过 sudo 单独管理，不要递归改成 `aihub` 所有：

```bash
chown -R aihub:aihub /var/www/git_repo/aihub
chown -R aihub:aihub /var/www/git_repo/aihub-venv
install -d -o root -g root -m 0755 /var/lib/aihub/agent_workspaces
```

前端使用 Vite 8，要求 Node.js `^20.19.0` 或 `>=22.12.0`，并且服务账号的
`PATH` 中必须同时存在 `node` 和 `npm`：

```bash
sudo -iu aihub node --version
sudo -iu aihub npm --version
```

native 沙箱当前会动态执行用户管理、文件权限管理和用户切换命令，因此服务账号是
root 等效的受信任平台账号。写入独立 sudoers 文件并检查语法：

```bash
printf '%s\n' 'aihub ALL=(ALL:ALL) NOPASSWD: ALL' > /etc/sudoers.d/aihub
chmod 0440 /etc/sudoers.d/aihub
visudo -cf /etc/sudoers.d/aihub
```

`NOPASSWD: ALL` 权限很高。`aihub` 账号只能用于 AI Hub 服务，不应配置密码、SSH
密钥或交互式外部登录。智能体使用单独的 `aihub_agent_*` 账号，不继承该 sudo 权限。

## Claude Code CLI

native 沙箱中的所有智能体用户必须能执行同一 Claude Code CLI。后端默认从服务进程
的 `PATH` 自动解析；生产环境建议在 `.env` 固定实际绝对路径：

```dotenv
CLAUDE_CODE_SANDBOX_TYPE=native
CLAUDE_CODE_NATIVE_WORKSPACE_ROOT=/var/lib/aihub/agent_workspaces
CLAUDE_CODE_NATIVE_USER_PREFIX=aihub_agent_
CLAUDE_CODE_NATIVE_CLAUDE_BIN=/usr/bin/claude
```

部署前分别验证服务账号和无特权用户能够执行：

```bash
sudo -iu aihub /usr/bin/claude --version
runuser -u nobody -- env HOME=/tmp /usr/bin/claude --version
```

如果旧版本代码仍固定查找 `/usr/local/bin/claude`，可临时创建兼容软链接；升级到支持
`CLAUDE_CODE_NATIVE_CLAUDE_BIN` 的版本后不再需要：

```bash
ln -s /usr/bin/claude /usr/local/bin/claude
```

目标已存在时不要用 `ln -sfn` 覆盖，应先检查现有文件来源。

## 部署前检查

认证系统升级或首次部署前，必须先完成 [认证与令牌安全改造](auth-security-hardening.md) 中的数据库迁移、RS256 密钥注入、service token 轮换和 public client 转换。`aihub.sh` 的后端默认监听地址实际为 `0.0.0.0`，不能将默认值视为网络隔离。Gateway 同机时应显式设置 `AIHUB_BACKEND_HOST=127.0.0.1`；不同机时绑定受防火墙保护的私网地址，并限制只有可信 Gateway 可以访问。网关必须清除客户端自带的身份头后重新注入。

技能版本包的 `/releases/*` 必须代理到 AI Hub 的受控下载路由，不能由 Nginx `alias`、对象存储公开目录或其他静态服务直接提供，也不能绕过后端缓存响应；切换时清除已有的共享缓存。该兼容入口只提供当前仍公开、未删除、未撤销的版本包；私有版本通过带登录身份的 `/api/assets/skills/releases/{id}/download` 接口下载。发布包只允许服务账号写入。工作区单文件下载上限为 20 MiB，超限返回 413；此限制不影响技能版本包下载。

在 root 终端执行以下检查。第一条必须输出非 `0`，其余命令必须成功：

```bash
sudo -iu aihub id -u
sudo -iu aihub sudo -n true
sudo -iu aihub docker version
sudo -iu aihub /usr/bin/claude --version
```

如果 `sudo -n true` 输出 `I'm afraid I can't do that`，说明 `/etc/sudoers.d/aihub`
尚未正确安装或未通过 `visudo` 检查。

## 启停服务

完成一次性初始化后，可以直接在 root 终端运行：

```bash
cd /var/www/git_repo/aihub
sh aihub.sh start
sh aihub.sh status
sh aihub.sh restart
sh aihub.sh stop
```

`start` 和 `restart` 会先拉取代码、安装依赖、执行预检并将前端编译到临时目录，
准备成功后才停止旧 Worker 和后端。准备失败时不主动停止现有进程。
后端使用 SIGTERM 并最多给 Uvicorn 30 秒完成请求，然后等待新后端的 HTTP 入口返回
200；Worker 启动检查通过后才发布前端入口。旧的 hash 静态资源会保留，避免已打开
页面的延迟加载资源因发布而丢失；磁盘清理应保留仍可能被旧页面引用的版本。

浏览器遇到网关 502/503/504 或网络连接失败时，GET/HEAD 读取请求会按
1、2、4、8、15 秒间隔自动重试，等待上限为两分钟。期间显示统一重连提示，
恢复后完成原来的数据加载，不自动刷新整个页面。写入请求不自动重发，错误提示会
提醒恢复后核实结果。后端标准格式的业务 503 不进入自动重连。

这仍是单实例、原目录内更新，共享目录里的代码和依赖会在准备阶段改变，
不提供版本隔离或失败自动回滚。停止旧后端到新后端就绪之间仍有短暂不可用，
运行中的长任务也可能受重启影响。需要连续服务时，应进一步使用独立版本目录、
独立依赖环境和多实例滚动切换，并单独验证长任务及数据库迁移兼容性。

即使 `aihub.sh` 没有可执行位，`sh aihub.sh restart` 也能运行。脚本会先切换到 Bash，
再自动转交给 `aihub` 服务账号。如果希望使用 `./aihub.sh restart`，需设置并在 Git 中
提交可执行位：

```bash
chmod 0755 aihub.sh
git update-index --chmod=+x aihub.sh
```

使用其他服务账号时，在 root 命令中显式指定：

```bash
AIHUB_SERVICE_USER=my_aihub sh aihub.sh restart
```

首次从旧的 root 进程迁移时，应先用旧版本脚本停止现有服务，再升级脚本并按本文修正
目录所有权；否则非 root 服务账号无法终止旧的 root 进程。

## 常见错误

### Claude CLI 路径错误

```text
[FAIL] native 沙箱要求所有智能体用户可执行 Claude Code CLI: /usr/local/bin/claude
```

检查 `which claude`，并将 `CLAUDE_CODE_NATIVE_CLAUDE_BIN` 设置为实际路径。随后用
`nobody` 执行 `--version`，确认目标文件及其所有父目录均可访问。

### 脚本 Permission denied

`./aihub.sh` 要求文件具有可执行位。可以设置 `chmod 0755 aihub.sh`，或直接使用不依赖
可执行位的 `sh aihub.sh restart`。

### 服务账号无法写入

如果 `git pull`、依赖安装、日志或 PID 文件写入失败，检查路径每一级权限：

```bash
namei -l /var/www/git_repo/aihub/aihub.sh
namei -l /var/www/git_repo/aihub-venv/bin/python
```

项目与虚拟环境应归 `aihub:aihub`。如果旧版脚本曾以 root 安装前端依赖，应修正遗留目录后重试：

```bash
chown -R aihub:aihub /var/www/git_repo/aihub/frontend
sudo -iu aihub npm config get cache
```

若 npm 报告缓存目录 `EACCES`，删除报错中列出的 root 所有缓存文件，或将该缓存目录
改为 `aihub:aihub`；不要把 npm 缓存设为全局可写。

## 运行时数据升级

已完成 055 的数据库在停止 API、消息渠道 Worker 和旧独立运行时 Worker 后执行：

```bash
python backend/migrations/run_upgrade.py --from 056 --apply
python backend/migrations/056_claude_runtime.py --check
```

先处理未完成任务，并为旧智能体所属用户配置可用的 Anthropic Messages 模型。
新版本启动脚本只启动后端与启用的消息渠道 Worker，Claude 在任务执行时使用配置的沙箱。
旧独立 Worker 与其容器应由原部署方式停用；旧远程服务中的文件须先备份并保存到宿主机旧工作区。
文件合并、会话恢复与历史审计保留规则见 [运行时配置](agent-runtime-configuration.md)。
