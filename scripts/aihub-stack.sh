#!/usr/bin/env bash
set -Eeuo pipefail
action=${1:-start}
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
fail() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }

if [[ "$action" == start || "$action" == restart || "$action" == install ]]; then
    [[ $(id -u) != 0 ]] || fail 'Use the dedicated non-root WSL service user.'
    command -v sudo >/dev/null && sudo -n true 2>/dev/null \
        || fail 'Run aihub.bat start from Windows first to initialize the WSL service account.'
    sudo -n bash "$root/scripts/aihub-wsl-bootstrap.sh" "$(id -un)"
fi
command -v python3 >/dev/null || fail 'Install Python 3.10 or later in WSL.'
exec python3 "$root/scripts/aihub_stack.py" "$action" "${@:2}"
