#!/usr/bin/env bash

# 允许运维从 root 终端使用 `sh aihub.sh ...`；实际脚本始终由 Bash 解释。
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -e

STATUS_LABEL_WIDTH=${AIHUB_STATUS_LABEL_WIDTH:-52}
if [ -z "${NO_COLOR:-}" ] && { [ -t 1 ] || [ "${FORCE_COLOR:-0}" = "1" ]; }; then
    COLOR_GREEN=$'\033[32m'
    COLOR_RED=$'\033[31m'
    COLOR_YELLOW=$'\033[33m'
    COLOR_CYAN=$'\033[36m'
    COLOR_RESET=$'\033[0m'
else
    COLOR_GREEN=""
    COLOR_RED=""
    COLOR_YELLOW=""
    COLOR_CYAN=""
    COLOR_RESET=""
fi

status_line() {
    local label=$1
    local status=${2:-OK}
    local color width dot_count dots

    case "$status" in
        OK) color=$COLOR_GREEN ;;
        FAIL|ERROR)
            status=FAIL
            color=$COLOR_RED
            ;;
        WARN|SKIP)
            color=$COLOR_YELLOW
            ;;
        *) color=$COLOR_CYAN ;;
    esac

    width=$(printf '%s' "$label" | wc -L)
    dot_count=$((STATUS_LABEL_WIDTH - width))
    [ "$dot_count" -ge 3 ] || dot_count=3
    printf -v dots '%*s' "$dot_count" ''
    dots=${dots// /.}
    printf '  %s %s %b%s%b\n' "$label" "$dots" "$color" "$status" "$COLOR_RESET"
}

format_check_output() {
    local output=$1
    local line label detail

    while IFS= read -r line; do
        [ -n "$line" ] || continue
        case "$line" in
            *": OK")
                status_line "${line%: OK}" OK
                ;;
            *": WARN")
                status_line "${line%: WARN}" WARN
                ;;
            *": SKIPPED"*)
                label=${line%%: SKIPPED*}
                detail=${line#*: SKIPPED}
                status_line "$label" SKIP
                [ -z "$detail" ] || printf '    %s\n' "${detail# }"
                ;;
            *": ERROR"*|*": FAILED"*|*": TABLE MISSING"|*": missing="*)
                label=${line%%:*}
                detail=${line#*: }
                status_line "$label" FAIL
                printf '    %s\n' "$detail"
                ;;
            *)
                printf '    %s\n' "$line"
                ;;
        esac
    done <<< "$output"
}

run_preflight_check() {
    local label=$1
    local output
    shift

    if output=$("$@" 2>&1); then
        format_check_output "$output"
        return 0
    fi

    format_check_output "$output"
    case "$output" in
        *": ERROR"*|*": FAILED"*|*": TABLE MISSING"|*": missing="*) ;;
        *) status_line "$label" FAIL ;;
    esac
    return 1
}

run_streaming_preflight_check() {
    local label=$1
    local command_status
    shift

    "$@" 2>&1 | while IFS= read -r line || [ -n "$line" ]; do
        format_check_output "$line"
    done
    command_status=${PIPESTATUS[0]}

    if [ "$command_status" -eq 0 ]; then
        return 0
    fi
    status_line "$label" FAIL
    return 1
}

# 所有服务进程统一由专用服务账号运行。服务账号直接执行；root 使用 runuser，
# 其他账号使用 sudo 切换。native Claude 沙箱所需的特权操作再由服务账号执行。
AIHUB_SERVICE_USER=${AIHUB_SERVICE_USER:-aihub}
id "$AIHUB_SERVICE_USER" >/dev/null 2>&1 || {
    status_line "AI Hub 服务账号不存在 [$AIHUB_SERVICE_USER]" FAIL
    echo "       请先按 docs/production-deployment.md 完成服务账号初始化"
    exit 1
}

AIHUB_SERVICE_UID=$(id -u "$AIHUB_SERVICE_USER")
[ "$AIHUB_SERVICE_UID" -ne 0 ] || {
    status_line "AIHUB_SERVICE_USER 必须是非 root 账号" FAIL
    exit 1
}

CURRENT_UID=$(id -u)
if [ "$CURRENT_UID" -ne "$AIHUB_SERVICE_UID" ]; then
    CURRENT_USER=$(id -un 2>/dev/null || printf 'UID %s' "$CURRENT_UID")
    status_line "切换服务账号 [$CURRENT_USER -> $AIHUB_SERVICE_USER]" INFO

    if [ "$CURRENT_UID" -eq 0 ]; then
        command -v runuser >/dev/null 2>&1 || {
            status_line "runuser（切换 AI Hub 服务账号）" FAIL
            exit 1
        }
        exec runuser -u "$AIHUB_SERVICE_USER" -- \
            env AIHUB_SERVICE_USER="$AIHUB_SERVICE_USER" bash "$0" "$@"
    fi

    command -v sudo >/dev/null 2>&1 || {
        status_line "sudo（从 $CURRENT_USER 切换到 $AIHUB_SERVICE_USER）" FAIL
        exit 1
    }
    exec sudo -u "$AIHUB_SERVICE_USER" -H -- \
        env AIHUB_SERVICE_USER="$AIHUB_SERVICE_USER" bash "$0" "$@"
fi

# ========================================
# 路径配置
# ========================================
ROOT_DIR="/var/www/git_repo/aihub"
VENV_DIR="/var/www/git_repo/aihub-venv"

# ========================================
# 端口 & 文件配置
# ========================================
PORT_BACKEND=15174
BACKEND_HOST=${AIHUB_BACKEND_HOST:-0.0.0.0}

BACKEND_PID_FILE="$ROOT_DIR/.backend.pid"
BACKEND_LOG="$ROOT_DIR/backend.log"
CHANNEL_WORKER_PID_FILE="$ROOT_DIR/.channel-worker.pid"
CHANNEL_WORKER_LOG="$ROOT_DIR/channel_worker.log"

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ========================================
# 工具函数
# ========================================

port_pid() {
    lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | sort -u || true
}

channel_worker_pid() {
    local pid command

    [ -f "$CHANNEL_WORKER_PID_FILE" ] || return 0
    pid=$(cat "$CHANNEL_WORKER_PID_FILE" 2>/dev/null || true)
    case "$pid" in
        ''|*[!0-9]*) return 0 ;;
    esac

    if kill -0 "$pid" 2>/dev/null; then
        command=$(ps -p "$pid" -o args= 2>/dev/null || true)
        case "$command" in
            *channel_worker.py*) echo "$pid" ;;
        esac
    fi
}

stop_channel_worker() {
    local pid="$1"
    local attempt=0

    kill "$pid" 2>/dev/null || true
    while [ "$attempt" -lt 40 ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
    ! kill -0 "$pid" 2>/dev/null
}

stop_backend() {
    local pid="$1" attempt=0
    kill "$pid" 2>/dev/null || true
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$attempt" -ge 35 ]; then
            kill -9 "$pid" 2>/dev/null || true
            break
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
}

wait_backend_ready() {
    local pid="$1" attempt=0
    while [ "$attempt" -lt 90 ]; do
        kill -0 "$pid" 2>/dev/null || return 1
        if "$PYTHON" - "$BACKEND_HOST" "$PORT_BACKEND" <<'PY'
import sys
from urllib.request import build_opener, ProxyHandler
try:
    host = '127.0.0.1' if sys.argv[1] == '0.0.0.0' else sys.argv[1]
    if ':' in host:
        host = '[%s]' % host
    with build_opener(ProxyHandler({})).open('http://%s:%s/' % (host, sys.argv[2]), timeout=1) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
        then
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    return 1
}

check_frontend_runtime() {
    local node_version npm_version

    command -v node >/dev/null 2>&1 || {
        status_line "Node.js（要求 ^20.19.0 或 >=22.12.0）" FAIL
        exit 1
    }
    command -v npm >/dev/null 2>&1 || {
        status_line "npm（服务账号: $AIHUB_SERVICE_USER）" FAIL
        exit 1
    }

    node_version=$(node -p "process.versions.node") || {
        status_line "读取 Node.js 版本" FAIL
        exit 1
    }
    if ! node -e '
        const [major, minor] = process.versions.node.split(".").map(Number)
        const supported = (major === 20 && minor >= 19) ||
            (major === 22 && minor >= 12) || major > 22
        process.exit(supported ? 0 : 1)
    '; then
        status_line "Node.js $node_version（要求 ^20.19.0 或 >=22.12.0）" FAIL
        exit 1
    fi

    npm_version=$(npm --version) || {
        status_line "npm 运行检查（请检查服务账号 PATH）" FAIL
        exit 1
    }
    status_line "Node.js $node_version / npm $npm_version" OK
}

# ========================================
# status
# ========================================
do_status() {
    echo "========================================"
    echo "  AIHub 服务状态"
    echo "========================================"
    echo ""

    local pid
    pid=$(port_pid $PORT_BACKEND)
    if [ -n "$pid" ]; then
        echo "  后端: 运行中 [PID: $pid, 端口: $PORT_BACKEND]"
    else
        echo "  后端: 未运行"
    fi

    pid=$(channel_worker_pid)
    if [ -n "$pid" ]; then
        echo "  消息渠道 Worker: 运行中 [PID: $pid]"
    else
        echo "  消息渠道 Worker: 未运行"
    fi
    echo ""
}

# ========================================
# stop
# ========================================
do_stop() {
    echo "========================================"
    echo "  停止 AIHub 服务"
    echo "========================================"
    echo ""

    local pid
    pid=$(channel_worker_pid)
    if [ -n "$pid" ]; then
        if stop_channel_worker "$pid"; then
            rm -f "$CHANNEL_WORKER_PID_FILE"
            status_line "消息渠道 Worker 已停止 [PID: $pid]" OK
        else
            status_line "消息渠道 Worker 停止 [PID: $pid]" FAIL
        fi
    else
        rm -f "$CHANNEL_WORKER_PID_FILE"
        status_line "消息渠道 Worker 未在运行" INFO
    fi

    pid=$(port_pid $PORT_BACKEND)
    if [ -n "$pid" ]; then
        stop_backend "$pid"
        status_line "后端已停止 [PID: $pid]" OK
    else
        status_line "后端未在运行" INFO
    fi

    rm -f "$BACKEND_PID_FILE"
    echo ""
}

# ========================================
# start
# ========================================
do_start() {
    echo "========================================"
    echo "  AIHub 一键启动"
    echo "========================================"
    echo ""

    cd "$ROOT_DIR"

    # ---- 环境检查 ----
    echo "[1/4] 检查运行环境..."
    command -v git >/dev/null 2>&1 || { status_line "git" FAIL; exit 1; }
    status_line "git" OK
    [ -f "$PYTHON" ] || { status_line "Python 虚拟环境 [$VENV_DIR]" FAIL; exit 1; }
    status_line "Python 虚拟环境" OK
    check_frontend_runtime

    # ---- 检查现有服务，准备期间继续提供服务 ----
    echo ""
    echo "[2/4] 检查端口占用..."
    local existing_worker_pid existing_backend_pid
    existing_backend_pid=$(port_pid $PORT_BACKEND)
    [ -z "$existing_backend_pid" ] || status_line "现有后端继续服务，准备完成后切换" INFO

    # ---- 拉取代码 ----
    echo ""
    echo "[3/4] 拉取最新代码..."
    git pull || status_line "git pull 失败，继续使用当前代码" WARN

    # ---- 安装依赖并启动 ----
    echo ""
    echo "[4/4] 安装依赖并启动服务..."
    cd "$ROOT_DIR/backend"
    $PIP install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/ --timeout=300 -q || { status_line "后端依赖安装" FAIL; exit 1; }
    status_line "后端依赖安装" OK

    local sandbox_type native_workspace_root native_claude_bin
    sandbox_type=$("$PYTHON" -c "from sandbox import get_configured_sandbox_type; print(get_configured_sandbox_type())")
    case "$sandbox_type" in
        directory)
            status_line "directory 沙箱（仅适合可信的本地开发）" WARN
            ;;
        native)
            native_workspace_root=$("$PYTHON" -c "from database import settings; print(settings.claude_code_native_workspace_root)")
            native_claude_bin=$("$PYTHON" -c "from sandbox.native import NATIVE_CLAUDE_BIN; print(NATIVE_CLAUDE_BIN)")
            case "$native_workspace_root" in
                /mnt/*) status_line "native 工作区位于 Windows 挂载盘 [$native_workspace_root]" FAIL; exit 1 ;;
            esac
            if [ "$(id -u)" -ne 0 ]; then
                command -v sudo >/dev/null 2>&1 || { status_line "native 沙箱需要 root 或免密 sudo" FAIL; exit 1; }
                sudo -n true >/dev/null 2>&1 || { status_line "native 沙箱 sudo -n 检查" FAIL; exit 1; }
            fi
            [ -x "$native_claude_bin" ] || {
                status_line "native Claude Code CLI [$native_claude_bin]" FAIL
                echo "       请安装 Claude Code，或设置 CLAUDE_CODE_NATIVE_CLAUDE_BIN 为实际绝对路径"
                exit 1
            }
            if [ "$(id -u)" -eq 0 ]; then
                command -v runuser >/dev/null 2>&1 || { status_line "native 沙箱 runuser" FAIL; exit 1; }
                runuser -u nobody -- env HOME=/tmp "$native_claude_bin" --version >/dev/null 2>&1 || {
                    status_line "智能体 Linux 用户执行 Claude Code CLI" FAIL
                    exit 1
                }
            else
                sudo -n -u nobody env HOME=/tmp "$native_claude_bin" --version >/dev/null 2>&1 || {
                    status_line "智能体 Linux 用户执行 Claude Code CLI" FAIL
                    exit 1
                }
            fi
            status_line "native Claude Code CLI [$native_claude_bin]" OK
            ;;
        *)
            status_line "CLAUDE_CODE_SANDBOX_TYPE [$sandbox_type]" FAIL
            exit 1
            ;;
    esac

    echo ""
    echo "[预检]"
    run_preflight_check "消息渠道数据库预检" \
        "$PYTHON" _verify_channel_tables.py --required-if-enabled || {
        status_line "消息渠道数据库预检（请检查数据库连接及迁移）" FAIL
        exit 1
    }

    local channel_worker_state
    if ! channel_worker_state=$("$PYTHON" _verify_channel_tables.py --print-channel-state); then
        status_line "读取消息渠道启用状态" FAIL
        exit 1
    fi
    case "$channel_worker_state" in
        enabled|disabled) ;;
        *)
            status_line "消息渠道启用状态 [$channel_worker_state]" FAIL
            exit 1
            ;;
    esac

    cd "$ROOT_DIR/frontend"
    if [ ! -w "$ROOT_DIR/frontend" ] || { [ -d node_modules ] && [ ! -w node_modules ]; }; then
        status_line "服务账号 $AIHUB_SERVICE_USER 写入前端目录" FAIL
        echo "       请由 root 执行: chown -R $AIHUB_SERVICE_USER:$AIHUB_SERVICE_USER $ROOT_DIR/frontend"
        exit 1
    fi
    npm install --registry=https://registry.npmmirror.com --no-audit --no-fund --loglevel=error || {
        status_line "前端依赖安装（npm 原始错误见上方）" FAIL
        exit 1
    }
    status_line "前端依赖安装" OK

    echo "  正在编译前端项目..."
    local frontend_build_dir
    frontend_build_dir=$(mktemp -d "$ROOT_DIR/frontend/.deploy-build.XXXXXX")
    npm run build -- --outDir "$frontend_build_dir" || {
        rm -rf -- "$frontend_build_dir"
        status_line "前端项目编译" FAIL
        exit 1
    }
    status_line "前端项目编译" OK

    # 依赖、预检和编译成功后才停止旧进程，缩短接口不可用的窗口。
    existing_worker_pid=$(channel_worker_pid)
    if [ -n "$existing_worker_pid" ] && ! stop_channel_worker "$existing_worker_pid"; then
        rm -rf -- "$frontend_build_dir"
        status_line "停止现有消息渠道 Worker [PID: $existing_worker_pid]" FAIL
        return 1
    fi
    rm -f "$CHANNEL_WORKER_PID_FILE"
    existing_backend_pid=$(port_pid $PORT_BACKEND)
    if [ -n "$existing_backend_pid" ]; then
        stop_backend "$existing_backend_pid"
    fi

    cd "$ROOT_DIR/backend"
    echo ""
    echo "[服务]"
    nohup $VENV_DIR/bin/uvicorn main:app --host "$BACKEND_HOST" --port $PORT_BACKEND --timeout-graceful-shutdown 30 > "$BACKEND_LOG" 2>&1 &
    local backend_pid=$!
    echo "$backend_pid" > "$BACKEND_PID_FILE"
    if wait_backend_ready "$backend_pid"; then
        status_line "后端已就绪 [PID: $backend_pid, 端口: $PORT_BACKEND]" OK
    else
        kill "$backend_pid" 2>/dev/null || true
        rm -f "$BACKEND_PID_FILE"
        rm -rf -- "$frontend_build_dir"
        status_line "后端启动（日志: $BACKEND_LOG）" FAIL
        return 1
    fi

    if [ "$channel_worker_state" = "enabled" ]; then
        nohup "$PYTHON" channel_worker.py > "$CHANNEL_WORKER_LOG" 2>&1 &
        local channel_worker_process_pid=$!
        echo "$channel_worker_process_pid" > "$CHANNEL_WORKER_PID_FILE"
        sleep 1
        if kill -0 "$channel_worker_process_pid" 2>/dev/null; then
            status_line "消息渠道 Worker 已启动 [PID: $channel_worker_process_pid]" OK
        else
            rm -f "$CHANNEL_WORKER_PID_FILE"
            status_line "消息渠道 Worker 启动（日志: $CHANNEL_WORKER_LOG）" FAIL
            kill "$backend_pid" 2>/dev/null || true
            wait "$backend_pid" 2>/dev/null || true
            rm -f "$BACKEND_PID_FILE"
            rm -rf -- "$frontend_build_dir"
            status_line "已回滚本次启动的后端服务" INFO
            return 1
        fi
    else
        rm -f "$CHANNEL_WORKER_PID_FILE"
        status_line "消息渠道 Worker（微信和钉钉均未启用）" SKIP
    fi

    # 保留旧 hash 资源，避免已打开的页面在切换后加载旧 chunk 时出现 404。
    # 最后原子替换入口文件，让新页面使用已准备好的新资源。
    mkdir -p "$ROOT_DIR/frontend/dist"
    local frontend_entry
    for frontend_entry in "$frontend_build_dir"/* "$frontend_build_dir"/.[!.]*; do
        [ -e "$frontend_entry" ] || continue
        [ "${frontend_entry##*/}" = "index.html" ] && continue
        cp -R "$frontend_entry" "$ROOT_DIR/frontend/dist/"
    done
    cp "$frontend_build_dir/index.html" "$ROOT_DIR/frontend/dist/.index.html.next"
    mv -f "$ROOT_DIR/frontend/dist/.index.html.next" "$ROOT_DIR/frontend/dist/index.html"
    rm -rf -- "$frontend_build_dir"
    status_line "前端资源已发布" OK

    echo ""
    status_line "AIHub 服务启动完成" OK
    echo "  后端: http://localhost:$PORT_BACKEND"
    echo ""
    echo "使用 $0 status 查看状态"
    echo "使用 $0 stop   停止服务"
    echo ""
}

# ========================================
# 主入口
# ========================================
case "${1:-start}" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_start
        ;;
    status)
        do_status
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        echo "  start   启动服务（默认）"
        echo "  stop    停止服务"
        echo "  restart 重启服务"
        echo "  status  查看服务状态"
        echo ""
        exit 1
        ;;
esac
