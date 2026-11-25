#!/usr/bin/env bash
# macOS / Bash 3.2+: ./aihub-mac.sh {start|stop|restart|status|install}
# 三个项目独立使用 Python 3.11，只安装各自 requirements.txt 中的依赖。
# 默认目录布局：git_repo/{aihub,api-gateway,iam-service}；前端手动启动。
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=${AIHUB_ROOT_DIR:-$SCRIPT_DIR}
REPO_DIR=$(dirname -- "$ROOT_DIR")
GATEWAY_DIR=${AIHUB_GATEWAY_DIR:-$REPO_DIR/api-gateway}
IAM_DIR=${AIHUB_IAM_DIR:-$REPO_DIR/iam-service}
BACKEND_DIR="$ROOT_DIR/backend"
STATE_DIR="$BACKEND_DIR/.cache/aihub-mac"
LOCK_DIR="$STATE_DIR/lock"
PYTHON_VERSION=3.11
STARTED_SERVICES=""
LOCK_HELD=0
STARTING=0

# 避免调用者已激活的环境及 Python 路径影响三个独立项目。
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV
export PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1

fail() { printf '错误：%s\n' "$*" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "未找到命令：$1"; }

service_config() {
    SERVICE=$1
    PORT=""
    HEALTH=""
    case "$SERVICE" in
        backend)
            LABEL="AIHub 后端"; PROJECT_DIR="$BACKEND_DIR"
            ENTRY="main:app"; PORT=15174; HEALTH=/ ;;
        gateway)
            LABEL="API Gateway"; PROJECT_DIR="$GATEWAY_DIR"
            ENTRY="app.main:app"; PORT=8080; HEALTH=/gateway/health ;;
        iam)
            LABEL="IAM Service"; PROJECT_DIR="$IAM_DIR"
            ENTRY="app.main:app"; PORT=9001; HEALTH=/health ;;
        channel-worker)
            LABEL="消息渠道 Worker"; PROJECT_DIR="$BACKEND_DIR"
            ENTRY=channel_worker.py ;;
        *) fail "未知服务：$SERVICE" ;;
    esac
    PYTHON="$PROJECT_DIR/.venv/bin/python"
    PID_FILE="$STATE_DIR/$SERVICE.pid"
    LOG_FILE="$STATE_DIR/$SERVICE.log"
}

process_alive() {
    local state
    kill -0 "$1" 2>/dev/null || return 1
    state=$(ps -p "$1" -o stat= 2>/dev/null) || return 1
    case "$state" in *Z*|'') return 1 ;; esac
}

# PID 必须同时匹配本项目解释器、入口及端口，避免误停其他服务。
service_pid() {
    local pid args
    [ -f "$PID_FILE" ] || return 0
    IFS= read -r pid < "$PID_FILE" || return 0
    case "$pid" in ''|*[!0-9]*) return 0 ;; esac
    [ "$pid" -gt 1 ] || return 0
    process_alive "$pid" || return 0
    args=$(ps -ww -p "$pid" -o args= 2>/dev/null) || return 0
    case "$args" in *"$PYTHON "*) ;; *) return 0 ;; esac
    if [ -n "$PORT" ]; then
        case "$args " in
            *" -m uvicorn $ENTRY --host 0.0.0.0 --port $PORT "*) printf '%s\n' "$pid" ;;
        esac
    else
        case "$args " in *" $ENTRY "*) printf '%s\n' "$pid" ;; esac
    fi
}

port_pids() { lsof -nP -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | sort -u || true; }

stop_service() {
    local pid attempt
    service_config "$1"
    pid=$(service_pid)
    if [ -z "$pid" ]; then
        rm -f "$PID_FILE"
        printf '  %s：未运行\n' "$LABEL"
        return 0
    fi
    kill "$pid" 2>/dev/null || true
    for ((attempt=0; attempt<40; attempt++)); do
        process_alive "$pid" || break
        sleep 0.25
    done
    if process_alive "$pid"; then
        # 再次核对进程归属后才强制结束。
        [ "$(service_pid)" = "$pid" ] || return 1
        kill -9 "$pid" 2>/dev/null || true
        for ((attempt=0; attempt<20; attempt++)); do
            process_alive "$pid" || break
            sleep 0.1
        done
    fi
    if process_alive "$pid"; then
        printf '  %s：停止失败 [PID: %s]\n' "$LABEL" "$pid" >&2
        return 1
    fi
    rm -f "$PID_FILE"
    printf '  %s：已停止\n' "$LABEL"
}

cleanup() {
    local result=$? service
    trap - EXIT INT TERM
    if [ "$STARTING" -eq 1 ]; then
        printf '\n启动未完成，正在停止本次启动的进程。\n' >&2
        for service in $STARTED_SERVICES; do
            stop_service "$service" || result=1
        done
    fi
    if [ "$LOCK_HELD" -eq 1 ]; then
        rm -f "$LOCK_DIR/pid"
        rmdir "$LOCK_DIR" 2>/dev/null || true
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

acquire_lock() {
    mkdir -p "$STATE_DIR"
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        fail "另一个操作正在执行。若上次被强制中断，请核对 $LOCK_DIR/pid 后移除锁目录再重试。"
    fi
    LOCK_HELD=1
    printf '%s\n' "$$" > "$LOCK_DIR/pid"
}

check_projects() {
    local service
    for service in backend gateway iam; do
        service_config "$service"
        [ -d "$PROJECT_DIR" ] || fail "项目目录不存在：$PROJECT_DIR"
        [ -f "$PROJECT_DIR/requirements.txt" ] || fail "缺少依赖文件：$PROJECT_DIR/requirements.txt"
    done
}

check_idle() {
    local service pid owners
    for service in backend gateway iam channel-worker; do
        service_config "$service"
        pid=$(service_pid)
        [ -z "$pid" ] || fail "$LABEL 已运行 [PID: $pid]，请使用 restart。"
        if [ -n "$PORT" ]; then
            owners=$(port_pids "$PORT")
            [ -z "$owners" ] || fail "端口 $PORT 已被 PID $owners 占用，请自行处理后重试。"
        fi
    done
}

install_dependencies() {
    local interpreter service version
    require_command uv
    check_projects
    interpreter=$(uv python find --no-project --system --managed-python \
        --no-python-downloads "$PYTHON_VERSION") \
        || fail "未找到 uv 管理的 Python $PYTHON_VERSION，请执行：uv python install $PYTHON_VERSION --no-bin"
    for service in backend gateway iam; do
        service_config "$service"
        if [ -e "$PROJECT_DIR/.venv" ] || [ -L "$PROJECT_DIR/.venv" ]; then
            [ -x "$PYTHON" ] && [ -f "$PROJECT_DIR/.venv/pyvenv.cfg" ] \
                || fail "现有环境无效，请手动检查：$PROJECT_DIR/.venv（不会自动覆盖）"
            version=$("$PYTHON" -I -c 'import sys; print("%s.%s" % sys.version_info[:2]); sys.exit(sys.prefix == sys.base_prefix)') \
                || fail "无法验证虚拟环境：$PROJECT_DIR/.venv"
            [ "$version" = "$PYTHON_VERSION" ] \
                || fail "$PROJECT_DIR/.venv 使用 Python $version，需要 $PYTHON_VERSION；请手动迁移旧环境。"
            if ! "$PYTHON" -I -c 'import pathlib, sys; cfg = pathlib.Path(sys.prefix, "pyvenv.cfg").read_text().lower().replace(" ", ""); sys.exit("include-system-site-packages=true" in cfg)'; then
                fail "环境启用了系统 site-packages，请手动重建隔离环境：$PROJECT_DIR/.venv"
            fi
        else
            uv venv --no-project --no-config --no-python-downloads --python "$interpreter" \
                "$PROJECT_DIR/.venv"
        fi
        printf '\n安装 %s 依赖 → %s/.venv\n' "$LABEL" "$PROJECT_DIR"
        (
            cd "$PROJECT_DIR"
            uv pip install --no-config --no-python-downloads --python "$PYTHON" -r requirements.txt
            "$PYTHON" -I -c 'import uvicorn'
        )
    done
}

backend_check() {
    "$BACKEND_DIR/.venv/bin/python" "$@"
}

preflight() {
    [ -f "$ROOT_DIR/.env" ] || fail "缺少配置文件：$ROOT_DIR/.env"
    cd "$BACKEND_DIR"
    local sandbox_type
    sandbox_type=$(backend_check -c 'from sandbox import get_configured_sandbox_type; print(get_configured_sandbox_type())')
    case "$sandbox_type" in
        native|linux_user)
            fail "native/linux_user 沙箱仅支持 Linux；Mac 请配置 CLAUDE_CODE_SANDBOX_TYPE=container。" ;;
        directory)
            fail "企业用户工作区不支持 directory 沙箱；Mac 请配置 CLAUDE_CODE_SANDBOX_TYPE=container。" ;;
        container) ;;
        *) fail "未知沙箱类型：$sandbox_type" ;;
    esac
    backend_check -c '
from pathlib import Path
import tempfile
from database import settings
root = Path(settings.user_workspace_root)
try:
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=root):
        pass
except OSError as exc:
    raise SystemExit(f"用户工作区不可写：{root}；请将 USER_WORKSPACE_ROOT 设置为当前用户可写的目录。原因：{exc}")
print(f"用户工作区：{root}")
'
    require_command docker
    docker info >/dev/null 2>&1 || fail "Claude Code container 模式需要运行 Docker Desktop。"
    local claude_image
    claude_image=$(backend_check -c 'from database import settings; print(settings.claude_code_container_image)')
    docker image inspect "$claude_image" >/dev/null 2>&1 \
        || fail "缺少 Claude Runtime 镜像 $claude_image；请先执行：docker build -t '$claude_image' '$BACKEND_DIR/runtime_images/claude'"
    docker run --rm --network none --read-only --cap-drop ALL \
        --security-opt no-new-privileges:true --tmpfs /tmp:rw,noexec,nosuid,size=128m \
        "$claude_image" /usr/bin/python3 -I -c \
        'import subprocess, sys; subprocess.run([sys.executable, "-I", "-m", "venv", "/tmp/aihub-venv-check"], check=True, stdout=sys.stderr); subprocess.run(["/tmp/aihub-venv-check/bin/python", "-I", "-c", "import pip"], check=True)' \
        || fail "Claude Runtime 镜像无法创建带 pip 的虚拟环境；请重建：docker build -t '$claude_image' '$BACKEND_DIR/runtime_images/claude'"
    backend_check _verify_channel_tables.py --required-if-enabled
    CHANNEL_STATE=$(backend_check _verify_channel_tables.py --print-channel-state)
    case "$CHANNEL_STATE" in enabled|disabled) ;; *) fail "无法读取消息渠道状态" ;; esac
}

start_service() {
    local service=$1 pid attempt owners
    service_config "$service"
    (
        cd "$PROJECT_DIR"
        export VIRTUAL_ENV="$PROJECT_DIR/.venv"
        export PATH="$VIRTUAL_ENV/bin:$PATH"
        if [ -n "$PORT" ]; then
            exec nohup "$PYTHON" -m uvicorn "$ENTRY" --host 0.0.0.0 --port "$PORT"
        else
            exec nohup "$PYTHON" "$ENTRY"
        fi
    ) < /dev/null >> "$LOG_FILE" 2>&1 &
    pid=$!
    printf '%s\n' "$pid" > "$PID_FILE"
    STARTED_SERVICES="$service $STARTED_SERVICES"
    if [ -n "$PORT" ]; then
        for ((attempt=0; attempt<60; attempt++)); do
            process_alive "$pid" || break
            owners=$(port_pids "$PORT")
            if [[ $'\n'"$owners"$'\n' == *$'\n'"$pid"$'\n'* ]] \
                && curl --noproxy '*' -fsS --connect-timeout 1 --max-time 2 \
                    "http://127.0.0.1:$PORT$HEALTH" >/dev/null 2>&1; then
                printf '  %s：已启动 [PID: %s, 端口: %s]\n' "$LABEL" "$pid" "$PORT"
                return 0
            fi
            sleep 0.5
        done
    else
        sleep 1
        if process_alive "$pid"; then
            printf '  %s：已启动 [PID: %s]\n' "$LABEL" "$pid"
            return 0
        fi
    fi
    fail "$LABEL 启动失败或健康检查超时，请查看：$LOG_FILE"
}

do_start() {
    require_command lsof
    require_command curl
    check_projects
    [ -f "$ROOT_DIR/.env" ] || fail "缺少配置文件：$ROOT_DIR/.env；请先根据 .env.example 或本地配置文件准备 .env。"
    check_idle
    install_dependencies
    preflight
    check_idle
    STARTING=1
    # IAM 就绪后再启动需要从 IAM 获取路由的网关。
    start_service iam
    start_service backend
    start_service gateway
    if [ "$CHANNEL_STATE" = enabled ]; then start_service channel-worker; fi
    STARTING=0
    printf '\n启动完成：AIHub :15174 / API Gateway :8080 / IAM :9001\n'
    printf '日志目录：%s\n前端请手动启动。\n' "$STATE_DIR"
}

do_stop() {
    local service result=0
    for service in channel-worker gateway backend iam; do
        stop_service "$service" || result=1
    done
    return "$result"
}

do_status() {
    local service pid owners
    require_command lsof
    for service in backend gateway iam channel-worker; do
        service_config "$service"
        pid=$(service_pid)
        if [ -n "$pid" ]; then
            printf '  %s：运行中 [PID: %s%s]\n' "$LABEL" "$pid" "${PORT:+, 端口: $PORT}"
        else
            printf '  %s：未运行\n' "$LABEL"
        fi
        if [ -n "$PORT" ]; then
            owners=$(port_pids "$PORT")
            if [ -n "$owners" ] && [ -z "$pid" ]; then
                printf '    端口 %s 被非本脚本管理的进程占用 [PID: %s]\n' "$PORT" "$owners"
            fi
        fi
    done
    printf '日志目录：%s\n' "$STATE_DIR"
}

usage() {
    printf '用法：%s {start|stop|restart|status|install}\n' "$0"
    printf '  start    安装项目依赖并启动（默认）；前端手动启动\n'
    printf '  stop     停止本脚本管理的服务及 Worker\n'
    printf '  restart  停止后重新启动\n'
    printf '  status   查看状态，不安装依赖\n'
    printf '  install  仅创建 Python 3.11 虚拟环境、安装项目依赖\n'
    printf '可覆盖目录：AIHUB_ROOT_DIR / AIHUB_GATEWAY_DIR / AIHUB_IAM_DIR\n'
}

case "${1:-start}" in
    -h|--help|help) usage; exit 0 ;;
    start|stop|restart|status|install) ;;
    *) usage >&2; exit 2 ;;
esac
[ "$(uname -s)" = Darwin ] || fail "此脚本仅用于 macOS。"
case "${1:-start}" in
    status) do_status ;;
    start) acquire_lock; do_start ;;
    stop) acquire_lock; do_stop ;;
    restart) acquire_lock; do_stop; do_start ;;
    install) acquire_lock; require_command lsof; check_idle; install_dependencies ;;
esac
