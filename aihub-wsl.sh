#!/usr/bin/env bash
set -Eeuo pipefail

case "${1:-}" in
    start-all|stop-all|restart-all|status-all|doctor-all|install-all)
        stack_action=${1%-all}
        shift
        exec bash "$(dirname -- "${BASH_SOURCE[0]}")/scripts/aihub-stack.sh" "$stack_action" "$@"
        ;;
esac

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=${AIHUB_ROOT_DIR:-$SCRIPT_DIR}
DATA_DIR=${AIHUB_WSL_DATA_DIR:-$HOME/.local/share/aihub}
VENV_DIR=${AIHUB_WSL_VENV_DIR:-$DATA_DIR/venv}
RUNTIME_BIN_DIR=${AIHUB_WSL_BIN_DIR:-$DATA_DIR/bin}
PORT_BACKEND=${AIHUB_BACKEND_PORT:-15174}
BACKEND_HOST=${AIHUB_BACKEND_HOST:-0.0.0.0}

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
UVICORN="$VENV_DIR/bin/uvicorn"

BACKEND_PID_FILE="$ROOT_DIR/.wsl-backend.pid"
CHANNEL_WORKER_PID_FILE="$ROOT_DIR/.wsl-channel-worker.pid"
BACKEND_LOG="$ROOT_DIR/backend.wsl.log"
CHANNEL_WORKER_LOG="$ROOT_DIR/channel_worker.wsl.log"
BACKEND_SYSTEMD_UNIT="aihub-backend-${PORT_BACKEND}.service"

HOST_PATH="$PATH"
export PATH="$RUNTIME_BIN_DIR:$PATH"

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

fail() {
    status_line "$*" FAIL >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "未找到命令: $1"
}

process_pid() {
    local pid_file=$1
    local pattern=$2
    local pid command

    [ -f "$pid_file" ] || return 0
    pid=$(cat "$pid_file" 2>/dev/null || true)
    case "$pid" in
        ''|*[!0-9]*) return 0 ;;
    esac
    kill -0 "$pid" 2>/dev/null || return 0
    command=$(ps -p "$pid" -o args= 2>/dev/null || true)
    case "$command" in
        *"$pattern"*) echo "$pid" ;;
    esac
}

backend_pids() {
    local pid saved_pid
    saved_pid=$(process_pid "$BACKEND_PID_FILE" "uvicorn main:app")
    [ -z "$saved_pid" ] || echo "$saved_pid"
    project_process_pids "uvicorn main:app " " --port $PORT_BACKEND " \
        | while IFS= read -r pid; do
            [ "$pid" = "$saved_pid" ] || echo "$pid"
        done
}

channel_worker_pids() {
    local pid
    pid=$(process_pid "$CHANNEL_WORKER_PID_FILE" "channel_worker.py")
    [ -z "$pid" ] || echo "$pid"
    project_process_pids " channel_worker.py " \
        | while IFS= read -r found_pid; do
            [ "$found_pid" = "$pid" ] || echo "$found_pid"
        done
}

project_process_pids() {
    local required_pattern=$1
    local additional_pattern=${2:-}
    local proc pid cwd command
    for proc in /proc/[0-9]*; do
        pid=${proc##*/}
        cwd=$(readlink -f "$proc/cwd" 2>/dev/null || true)
        [ "$cwd" = "$ROOT_DIR/backend" ] || continue
        command=$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null || true)
        case " $command " in *"$required_pattern"*) ;; *) continue ;; esac
        if [ -n "$additional_pattern" ]; then
            case " $command " in *"$additional_pattern"*) ;; *) continue ;; esac
        fi
        echo "$pid"
    done
}

stop_process() {
    local pid=$1
    local attempt=0
    process_is_running "$pid" || return 0
    kill "$pid" 2>/dev/null || true
    while [ "$attempt" -lt 20 ]; do
        process_is_running "$pid" || return 0
        sleep 0.5
        attempt=$((attempt + 1))
    done
    kill -9 "$pid" 2>/dev/null || true
    attempt=0
    while [ "$attempt" -lt 10 ]; do
        process_is_running "$pid" || return 0
        sleep 0.2
        attempt=$((attempt + 1))
    done
    return 1
}

process_is_running() {
    local pid=$1 state
    kill -0 "$pid" 2>/dev/null || return 1
    state=$(ps -p "$pid" -o stat= 2>/dev/null || true)
    [ -n "$state" ] && [ "${state#Z}" = "$state" ]
}

stop_systemd_backend() {
    command -v systemctl >/dev/null 2>&1 || return 0
    systemctl --user is-active --quiet "$BACKEND_SYSTEMD_UNIT" 2>/dev/null || return 0

    local pid
    pid=$(systemctl --user show "$BACKEND_SYSTEMD_UNIT" --property=MainPID --value 2>/dev/null || true)
    systemctl --user stop "$BACKEND_SYSTEMD_UNIT" \
        || fail "无法停止 systemd 用户服务: $BACKEND_SYSTEMD_UNIT"
    systemctl --user reset-failed "$BACKEND_SYSTEMD_UNIT" >/dev/null 2>&1 || true
    status_line "后端 systemd 服务已停止${pid:+ [PID: $pid]}" OK
}

port_owner_details() {
    local pids pid command user
    pids=$(lsof -tiTCP:"$PORT_BACKEND" -sTCP:LISTEN 2>/dev/null | sort -u || true)
    [ -n "$pids" ] || return 0
    for pid in $pids; do
        user=$(ps -p "$pid" -o user= 2>/dev/null | xargs || true)
        command=$(ps -p "$pid" -o args= 2>/dev/null | xargs || true)
        printf '    PID: %s, 用户: %s, 命令: %s\n' "$pid" "${user:-未知}" "${command:-未知}"
    done
}

wait_for_port_release() {
    local attempt=0
    while [ "$attempt" -lt 20 ]; do
        lsof -tiTCP:"$PORT_BACKEND" -sTCP:LISTEN >/dev/null 2>&1 || return 0
        sleep 0.25
        attempt=$((attempt + 1))
    done
    return 1
}

ensure_venv() {
    require_command python3
    if [ ! -x "$PYTHON" ] || [ ! -x "$PIP" ]; then
        echo "  创建 WSL Python 虚拟环境: $VENV_DIR"
        mkdir -p "$DATA_DIR"
        python3 -m venv --clear "$VENV_DIR" || fail "创建虚拟环境失败，请安装 python3-venv"
    fi
    "$PIP" install --disable-pip-version-check -q -r "$ROOT_DIR/backend/requirements.txt" \
        || fail "安装后端依赖失败"
}

prepare_node_runtime() {
    local sandbox_type=${1:-directory}
    local native_claude_bin=${2:-}

    if [ "$sandbox_type" = "directory" ]; then
        local windows_node="/mnt/c/Program Files/nodejs/node.exe"
        [ -x "$windows_node" ] || fail "未找到 Node.js；Claude Code directory 模式无法运行"
        mkdir -p "$RUNTIME_BIN_DIR"
        ln -sfn "$windows_node" "$RUNTIME_BIN_DIR/node"
    fi

    local claude_cmd claude_real
    claude_cmd=$(PATH="$HOST_PATH" command -v claude 2>/dev/null || true)
    if [ -n "$claude_cmd" ]; then
        claude_real=$(readlink -f "$claude_cmd" 2>/dev/null)
        [ -n "$claude_real" ] && claude_cmd="$claude_real"
    fi

    if [ "$sandbox_type" = "native" ]; then
        local candidate
        require_command file
        if [ -z "$claude_cmd" ] || ! file -b "$claude_cmd" 2>/dev/null | grep -q '^ELF '; then
            claude_cmd=""
            for candidate in "$HOME"/.nvm/versions/node/*/bin/claude; do
                [ -e "$candidate" ] || continue
                claude_real=$(readlink -f "$candidate" 2>/dev/null)
                [ -n "$claude_real" ] || continue
                if file -b "$claude_real" 2>/dev/null | grep -q '^ELF '; then
                    claude_cmd="$claude_real"
                    break
                fi
            done
        fi
        [ -n "$claude_cmd" ] || fail "未找到可供 native 模式使用的 Linux Claude Code CLI"
        [ -n "$native_claude_bin" ] || fail "native 模式缺少 Claude Code 共享可执行路径"
        if [ "$claude_cmd" != "$native_claude_bin" ]; then
            sudo -n install -o root -g root -m 0755 "$claude_cmd" "$native_claude_bin" \
                || fail "无法安装 native 模式共享 Claude Code CLI: $native_claude_bin"
        fi
        sudo -n -u nobody env HOME=/tmp "$native_claude_bin" --version >/dev/null 2>&1 \
            || fail "智能体 Linux 用户无法执行 Claude Code CLI: $native_claude_bin"
        return
    fi

    [ -n "$claude_cmd" ] || fail "未找到 Claude Code CLI"
    # Claude Code v2.x uses a native binary (bin/claude.exe), no longer ships cli.js.
    # Create a wrapper that invokes the real claude binary directly.
    mkdir -p "$RUNTIME_BIN_DIR"
    printf '#!/usr/bin/env bash\nexec %q "$@"\n' "$claude_cmd" >"$RUNTIME_BIN_DIR/claude"
    chmod 700 "$RUNTIME_BIN_DIR/claude"
}

run_preflight() {
    local sandbox_type native_workspace_root native_claude_bin
    ensure_venv
    cd "$ROOT_DIR/backend"

    sandbox_type=$("$PYTHON" -c "from sandbox import get_configured_sandbox_type; print(get_configured_sandbox_type())")
    if [ "$sandbox_type" = "container" ]; then
        require_command docker
        docker version >/dev/null 2>&1 || fail "当前用户无法访问 Docker daemon"
    fi
    if [ "$sandbox_type" = "native" ]; then
        native_workspace_root=$("$PYTHON" -c "from database import settings; print(settings.claude_code_native_workspace_root)")
        case "$native_workspace_root" in
            /mnt/*) fail "native workspace must use the Linux filesystem, not $native_workspace_root" ;;
        esac
        if [ "$(id -u)" -ne 0 ]; then
            require_command sudo
            sudo -n true >/dev/null 2>&1 \
                || fail "native sandbox requires root or passwordless sudo; current user cannot run sudo -n"
        fi
        native_claude_bin=$("$PYTHON" -c "from database import settings; print(settings.claude_code_native_claude_bin or '/usr/local/bin/claude')")
        export CLAUDE_CODE_NATIVE_CLAUDE_BIN="$native_claude_bin"
    fi
    prepare_node_runtime "$sandbox_type" "$native_claude_bin"

    echo ""
    echo "[预检]"
    run_preflight_check "消息渠道数据库预检" \
        "$PYTHON" _verify_channel_tables.py --required-if-enabled \
        || fail "消息渠道数据库预检未通过"
}

wait_for_backend() {
    local pid=$1
    local attempt=0
    while [ "$attempt" -lt 30 ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 1
        fi
        if curl -fsS "http://127.0.0.1:$PORT_BACKEND/" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
        attempt=$((attempt + 1))
    done
    return 1
}

do_preflight() {
    echo "========================================"
    echo "  AI Hub WSL 启动预检"
    echo "========================================"
    [ "$(id -u)" -ne 0 ] || fail "请使用非 root 用户运行，例如: wsl -u aihub"
    require_command curl
    require_command lsof
    run_preflight
    status_line "WSL 启动预检" OK
}

do_start() {
    echo "========================================"
    echo "  AI Hub WSL 后端与 Worker 启动"
    echo "========================================"
    [ "$(id -u)" -ne 0 ] || fail "请使用非 root 用户运行，例如: wsl -u aihub"
    [ -f "$ROOT_DIR/.env" ] || fail "缺少配置文件: $ROOT_DIR/.env"
    require_command curl

    local pids
    pids=$(backend_pids | xargs || true)
    [ -z "$pids" ] || fail "后端已运行 [PID: $pids]，请使用 restart"
    pids=$(channel_worker_pids | xargs || true)
    [ -z "$pids" ] || fail "消息渠道 Worker 已运行 [PID: $pids]，请使用 restart"
    if lsof -tiTCP:"$PORT_BACKEND" -sTCP:LISTEN >/dev/null 2>&1; then
        status_line "端口 $PORT_BACKEND 已被其他进程占用" FAIL >&2
        port_owner_details >&2
        exit 1
    fi

    run_preflight

    cd "$ROOT_DIR/backend"
    local channel_state
    channel_state=$("$PYTHON" _verify_channel_tables.py --print-channel-state)

    echo ""
    echo "[服务]"
    local backend_process backend_attempt=1
    while [ "$backend_attempt" -le 3 ]; do
        nohup "$UVICORN" main:app --host "$BACKEND_HOST" --port "$PORT_BACKEND" \
            >"$BACKEND_LOG" 2>&1 &
        backend_process=$!
        echo "$backend_process" >"$BACKEND_PID_FILE"
        if wait_for_backend "$backend_process"; then
            break
        fi
        stop_process "$backend_process"
        rm -f "$BACKEND_PID_FILE"
        if [ "$backend_attempt" -ge 3 ]; then
            fail "后端连续 3 次启动失败，请检查 $BACKEND_LOG"
        fi
        status_line "后端启动失败，2 秒后重试 [$backend_attempt/3]" WARN
        sleep 2
        backend_attempt=$((backend_attempt + 1))
    done
    status_line "后端已启动 [PID: $backend_process, 端口: $PORT_BACKEND]" OK

    if [ "$channel_state" = "enabled" ]; then
        nohup "$PYTHON" channel_worker.py >"$CHANNEL_WORKER_LOG" 2>&1 &
        local channel_process=$!
        echo "$channel_process" >"$CHANNEL_WORKER_PID_FILE"
        sleep 1
        if ! kill -0 "$channel_process" 2>/dev/null; then
            stop_process "$backend_process"
            rm -f "$BACKEND_PID_FILE" "$CHANNEL_WORKER_PID_FILE"
            fail "消息渠道 Worker 启动失败，请检查 $CHANNEL_WORKER_LOG"
        fi
        status_line "消息渠道 Worker 已启动 [PID: $channel_process]" OK
    else
        rm -f "$CHANNEL_WORKER_PID_FILE"
        status_line "消息渠道 Worker（微信和钉钉均未启用）" SKIP
    fi

    echo ""
    status_line "WSL 服务启动完成" OK
    echo "后端: http://localhost:$PORT_BACKEND"
    echo "前端请在 Windows 终端运行: cd frontend && npm run dev"
}

do_stop() {
    echo "========================================"
    echo "  停止 AI Hub WSL 服务"
    echo "========================================"
    local pid pids
    require_command lsof

    stop_systemd_backend

    pids=$(channel_worker_pids)
    for pid in $pids; do
        if ! stop_process "$pid"; then
            fail "消息渠道 Worker 无法停止 [PID: $pid]"
        fi
        status_line "消息渠道 Worker 已停止 [PID: $pid]" OK
    done
    rm -f "$CHANNEL_WORKER_PID_FILE"

    pids=$(backend_pids)
    for pid in $pids; do
        if ! stop_process "$pid"; then
            fail "后端无法停止 [PID: $pid]"
        fi
        status_line "后端已停止 [PID: $pid]" OK
    done
    rm -f "$BACKEND_PID_FILE"

    if ! wait_for_port_release; then
        status_line "端口 $PORT_BACKEND 未释放" FAIL >&2
        port_owner_details >&2
        exit 1
    fi
}

do_status() {
    echo "========================================"
    echo "  AI Hub WSL 服务状态"
    echo "========================================"
    local backend_processes pids systemd_label

    backend_processes=$(backend_pids | xargs || true)
    systemd_label=""
    if command -v systemctl >/dev/null 2>&1 \
        && systemctl --user is-active --quiet "$BACKEND_SYSTEMD_UNIT" 2>/dev/null; then
        systemd_label=", systemd: active"
    fi
    if [ -n "$backend_processes" ]; then
        echo "  后端: 运行中 [PID: $backend_processes$systemd_label]"
    else
        echo "  后端: 未运行"
    fi
    pids=$(channel_worker_pids | xargs || true)
    [ -z "$pids" ] && echo "  消息渠道 Worker: 未运行" || echo "  消息渠道 Worker: 运行中 [PID: $pids]"
    if lsof -tiTCP:"$PORT_BACKEND" -sTCP:LISTEN >/dev/null 2>&1 \
        && [ -z "$backend_processes" ]; then
        echo "  端口 $PORT_BACKEND: 被未识别进程占用"
        port_owner_details
    fi
}

case "${1:-start}" in
    start) do_start ;;
    stop) do_stop ;;
    restart)
        do_stop
        do_start
        ;;
    status) do_status ;;
    preflight) do_preflight ;;
    *)
        echo "用法: $0 {start|stop|restart|status|preflight}"
        exit 1
        ;;
esac
