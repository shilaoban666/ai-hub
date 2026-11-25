import base64
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import channel_service
import workspace_provider
from database import settings
from sandbox import get_configured_sandbox_type, get_sandbox
from sandbox.native import (
    NATIVE_CLAUDE_BIN,
    RUNNER_SCRIPT,
    NativeSandbox,
    resolve_native_claude_bin,
)


def test_claude_code_uses_configured_sandbox_provider():
    agent = SimpleNamespace(runtime_type="claude_code")
    expected = object()
    with patch.object(
        workspace_provider, "get_sandbox", return_value=expected
    ) as sandbox_factory:
        provider = workspace_provider.get_workspace_provider(agent)
    assert provider is expected
    sandbox_factory.assert_called_once_with()


def test_new_claude_code_sandbox_setting_precedes_legacy_name():
    original_new = settings.claude_code_sandbox_type
    original_legacy = settings.agent_sandbox_type
    try:
        settings.claude_code_sandbox_type = "native"
        settings.agent_sandbox_type = "directory"
        assert get_configured_sandbox_type() == "native"
    finally:
        settings.claude_code_sandbox_type = original_new
        settings.agent_sandbox_type = original_legacy


def test_legacy_claude_code_sandbox_setting_remains_readable():
    original_new = settings.claude_code_sandbox_type
    original_legacy = settings.agent_sandbox_type
    try:
        settings.claude_code_sandbox_type = ""
        settings.agent_sandbox_type = "native"
        assert get_configured_sandbox_type() == "native"
    finally:
        settings.claude_code_sandbox_type = original_new
        settings.agent_sandbox_type = original_legacy


def test_removed_claude_code_sandboxes_are_rejected():
    assert get_sandbox("container").type_name == "container"
    for removed in ("wsl",):
        try:
            get_sandbox(removed)
        except ValueError as exc:
            assert removed in str(exc)
        else:
            raise AssertionError(f"{removed} sandbox must not be available")


def test_native_sandbox_is_linux_only():
    with patch("sandbox.native.sys.platform", "darwin"):
        try:
            get_sandbox("native")
        except RuntimeError as exc:
            assert "requires Linux" in str(exc)
        else:
            raise AssertionError("native sandbox must reject macOS")


def test_native_sandbox_uses_shared_claude_executable():
    agent = SimpleNamespace(id=7, skills=[], mcps=[])
    model = SimpleNamespace()
    with patch("sandbox.native.sys.platform", "linux"), \
            patch.object(NativeSandbox, "_ensure_user"), \
            patch.object(NativeSandbox, "_sync_managed_files"), \
            patch.object(NativeSandbox, "_ensure_venv"), \
            patch.object(NativeSandbox, "_apply_permissions"), \
            patch("sandbox.native.install_skills", return_value=[]), \
            patch("sandbox.native.install_hooks"), \
            patch("sandbox.native.build_claude_md", return_value=""), \
            patch("sandbox.native.build_settings_json", return_value={}), \
            patch("sandbox.native.build_mcp_json", return_value=({}, [])):
        ctx = NativeSandbox().prepare(agent, model)

    assert ctx.claude_bin == NATIVE_CLAUDE_BIN
    assert ctx.tunnel_env_via_stdin is True


def test_native_sandbox_does_not_depend_on_preserved_sudo_environment():
    with patch("sandbox.native.sys.platform", "linux"), \
            patch.object(NativeSandbox, "_is_root", return_value=False):
        prefix = NativeSandbox()._run_as_user_prefix("aihub_agent_7")

    assert prefix[:5] == ["sudo", "-n", "-u", "aihub_agent_7", "--"]
    assert "-E" not in prefix
    assert "-p" not in prefix
    assert RUNNER_SCRIPT in prefix


def test_native_workspace_keeps_runtime_directories_writable():
    with patch("sandbox.native.sys.platform", "linux"):
        sandbox = NativeSandbox()
    calls = []

    def record(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    sandbox._run_root = record
    workspace = "/var/lib/aihub/agent_workspaces/8"
    sandbox._apply_permissions("aihub_agent_8", workspace)

    claude_dir = os.path.join(workspace, ".claude")
    venv_dir = os.path.join(workspace, ".venv")
    settings_path = os.path.join(workspace, ".claude/settings.json")
    trust_path = os.path.join(workspace, ".claude/.claude.json")
    assert ("chown", "aihub_agent_8:aihub_agent_8", claude_dir) in calls
    immutable_targets = {
        args[-1]
        for args in calls
        if len(args) >= 3 and args[0] == "chattr" and "+i" in args
    }
    assert claude_dir not in immutable_targets
    assert venv_dir not in immutable_targets
    assert settings_path in immutable_targets
    assert trust_path in immutable_targets


def test_native_runner_consumes_only_the_environment_header():
    if not sys.platform.startswith("linux"):
        return
    runtime_env = {
        "AIHUB_AGENT_WORKSPACE": os.getcwd(),
        "AIHUB_TEST_VALUE": "available",
    }
    header = base64.b64encode(json.dumps(runtime_env).encode("utf-8")) + b"\n"
    child_script = (
        "import os,sys;"
        "print(os.getcwd());"
        "print(os.environ['AIHUB_TEST_VALUE']);"
        "print(sys.stdin.read(),end='')"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            RUNNER_SCRIPT,
            "aihub-agent-run",
            sys.executable,
            "-c",
            child_script,
        ],
        input=header + b"prompt-body",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    lines = result.stdout.decode("utf-8").splitlines()
    assert os.path.normcase(lines[0]) == os.path.normcase(os.getcwd())
    assert lines[1:] == ["available", "prompt-body"]


def test_native_claude_bin_prefers_configuration_then_path():
    with patch("sandbox.native.shutil.which", return_value="/usr/bin/claude"):
        assert resolve_native_claude_bin(" /opt/claude/claude ") == "/opt/claude/claude"
        assert resolve_native_claude_bin() == "/usr/bin/claude"
    with patch("sandbox.native.shutil.which", return_value=None):
        assert resolve_native_claude_bin() == "/usr/local/bin/claude"


def test_unknown_claude_code_sandbox_is_rejected():
    try:
        get_sandbox("unknown")
    except ValueError as exc:
        assert "Unknown Claude Agent sandbox type" in str(exc)
    else:
        raise AssertionError("unknown sandbox must be rejected")


if __name__ == "__main__":
    test_claude_code_uses_configured_sandbox_provider()
    test_new_claude_code_sandbox_setting_precedes_legacy_name()
    test_legacy_claude_code_sandbox_setting_remains_readable()
    test_removed_claude_code_sandboxes_are_rejected()
    test_native_sandbox_is_linux_only()
    test_native_sandbox_uses_shared_claude_executable()
    test_native_sandbox_does_not_depend_on_preserved_sudo_environment()
    test_native_workspace_keeps_runtime_directories_writable()
    test_native_runner_consumes_only_the_environment_header()
    test_native_claude_bin_prefers_configuration_then_path()
    test_unknown_claude_code_sandbox_is_rejected()
    print("runtime configuration tests passed")
