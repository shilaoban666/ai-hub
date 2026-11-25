#!/usr/bin/env bash
# Called as root by the Windows launcher. New accounts are dedicated local
# platform accounts, matching native's documented root-equivalent trust model.
set -Eeuo pipefail
fail() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }
[[ $(id -u) == 0 ]] || fail 'Run bootstrap through the Windows launcher (wsl -u root).'
account=${1:-aihub}
[[ "$account" =~ ^[a-z_][a-z0-9_-]{0,30}$ && "$account" != root ]] || fail 'Choose a valid non-root Linux service username.'
marker="/var/lib/aihub/.launcher-user-$account"
new_account=0
getent passwd "$account" >/dev/null || new_account=1
if (( !new_account )) && [[ ! -f "$marker" ]]; then
    runuser -u "$account" -- sudo -n true 2>/dev/null \
        || fail "Existing user '$account' lacks native sudo permissions. Choose a NEW dedicated User in aihub-local.json, or ask your administrator to configure this existing account. No existing user's sudo policy was changed."
fi
packages=()
for item in python3:python3 curl:curl git:git file:file sudo:sudo runuser:util-linux useradd:passwd chattr:e2fsprogs; do
    command -v "${item%%:*}" >/dev/null || packages+=("${item#*:}")
done
[[ -s /etc/ssl/certs/ca-certificates.crt ]] || packages+=(ca-certificates)
if ! command -v python3 >/dev/null || ! python3 -c 'import ensurepip, venv' 2>/dev/null; then
    packages+=(python3-venv)
fi
if ((${#packages[@]})); then
    command -v apt-get >/dev/null || fail "Automatic setup supports Debian/Ubuntu. Install these Linux packages: ${packages[*]}"
    printf '[INSTALL] WSL system packages: %s\n' "${packages[*]}"
    apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 update -qq \
        && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=2 install -y --no-install-recommends "${packages[@]}" \
        || fail "System package installation failed. Fix apt/network and install: ${packages[*]}"
fi
python3 -c 'import sys; assert sys.version_info >= (3,10)' || fail 'Install Ubuntu 22.04/24.04 with Python 3.10+.'
if (( new_account )); then
    useradd --create-home --shell /bin/bash "$account"
    # New, locked service accounts only. Existing accounts are never elevated.
    install -d -m 0755 /var/lib/aihub
    install -m 0600 /dev/null "$marker"
fi
if [[ -f "$marker" ]]; then
    policy="/etc/sudoers.d/aihub-launcher-$account"
    temporary=$(mktemp)
    trap 'rm -f "$temporary"' EXIT
    printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "$account" >"$temporary"
    visudo -cf "$temporary" >/dev/null || fail 'Generated service-account sudo policy failed validation.'
    install -o root -g root -m 0440 "$temporary" "$policy"
fi
runuser -u "$account" -- sudo -n true || fail "native sudo check failed for $account."
printf '[OK] WSL system dependencies and service account: %s\n' "$account"
