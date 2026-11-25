"""Workspace Python selection and hook cwd/symlink boundary regressions."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_hooks import pre_tool_use as hook
from agent_workspace import build_claude_md
from runtimes.base import RuntimeConfig
from runtimes.claude_code import _build_runtime_env, _encode_tunneled_env
from sandbox.base import WorkspaceContext, WorkspacePreparationError
from sandbox.native import NativeSandbox, RUNNER_SCRIPT
from sandbox.directory import DirectorySandbox


@pytest.fixture
def workspace(tmp_path):
    user = tmp_path / "user_workspaces" / "owner"
    view = user / "managed" / "runs" / "run" / "view"
    (view / "out").mkdir(parents=True)
    (view / ".pylibs").mkdir()
    (view / "out" / "snapshot.json").write_text('{"ok":"workspace-python-ok"}')
    (user / ".venv" / "bin").mkdir(parents=True)
    (view / ".venv").symlink_to(user / ".venv", target_is_directory=True)
    (user / "current").symlink_to(view, target_is_directory=True)
    return user, view


def check(command, view, cwd=None):
    return hook.check_command(command, str(cwd or view), str(view))


def test_reported_cd_environment_and_python_command(workspace):
    _, view = workspace
    command = (
        'cd out && ls -la && PYTHONPATH="../.pylibs" ../.venv/bin/python -c '
        '"import json; print(json.load(open(\'snapshot.json\'))[\'ok\'])" 2>&1 | head -20'
    )
    assert check(command, view) is None
    assert check("cd out && cd .. && .venv/bin/python report.py", view) is None
    assert check("cd out && PYTHONPATH=../.pylibs ../.venv/bin/python -m pip install pandas", view) is None


@pytest.mark.parametrize("prefix", ["/var/lib/aihub", "/var/xx", "/tmp", "/opt"])
def test_absolute_workspace_prefixes_do_not_determine_access(prefix):
    root = prefix + "/user_workspaces/owner/managed/runs/run/view"
    for path in [root + "/out/report.json", root + "/.venv/bin/python"]:
        assert hook.resolve_under_ws(path, root, root)
    for path in [root + "-other/report.json", root + "/../../../../other/report.json", prefix + "/secrets"]:
        assert not hook.resolve_under_ws(path, root, root)


def test_stable_absolute_paths_and_shared_venv(workspace):
    user, view = workspace
    for root in [view, user / "current"]:
        assert check(f"cd {shlex.quote(str(root / 'out'))} && ../.venv/bin/python report.py", view) is None
        assert check(f"{shlex.quote(str(root / '.venv/bin/python'))} -c 'print(1)'", view) is None
        assert hook.resolve_under_ws(str(root / "out/report.json"), str(view), str(view))
    assert check("find .venv -name '*.py'", view) is None


@pytest.mark.parametrize("command", [
    "cd ../outside && cat secret", "cd out && cat ../../secret",
    "cd out; ../.venv/bin/python report.py",  # cd can fail; do not assume success after ;
    "cd out || ../.venv/bin/python report.py",
    "cd out | cat; ../.venv/bin/python report.py",
    "cd out && cat /etc/passwd", "cd out && cd ../../ && cat secret",
    "cd out && PYTHONPATH=../../outside ../.venv/bin/python report.py",
    "cd out && X=1 pip install pandas", "X=1 python3 -m pip install pandas",
    "env X=1 pip3.11 install pandas", "X=1 python3.11 -c 'print(1)'",
    "X=1 rm CLAUDE.md", "X=1 sh script.sh",
    "builtin cd .. && .venv/bin/python report.py",
    "command pip install pandas", "builtin rm CLAUDE.md",
])
def test_directory_changes_and_assignments_do_not_bypass_checks(workspace, command):
    _, view = workspace
    assert check(command, view) is not None


def test_symlink_escapes_are_checked_inside_and_outside_venv(workspace, tmp_path):
    user, view = workspace
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "deep").mkdir()
    (outside / ".venv/bin").mkdir(parents=True)
    (outside / ".venv/bin/python").symlink_to(sys.executable)
    (outside / "secret").write_text("not workspace data")
    (view / "escape").symlink_to(outside, target_is_directory=True)
    (view / "deep-escape").symlink_to(outside / "deep", target_is_directory=True)
    (user / ".venv" / "escape").symlink_to(outside, target_is_directory=True)
    (user / ".venv" / "bin" / "python").symlink_to(outside / "secret")
    for path in [view / "escape/secret", view / ".venv/escape/secret", view / ".venv/bin/python",
                 view / "deep-escape/..", view / "deep-escape/../.venv/bin/python"]:
        assert not hook.resolve_under_ws(str(path), str(view), str(view))
    assert check("cd escape && ls", view) is not None
    assert check("cd out && ../.venv/bin/python report.py", view) is not None


def test_cd_keeps_logical_symlink_parent_for_protected_paths(workspace):
    _, view = workspace
    (view / "nested/deep").mkdir(parents=True)
    (view / "link").symlink_to(view / "nested/deep", target_is_directory=True)
    assert check("cd link && cd .. && rm CLAUDE.md", view) is not None
    assert check("cd -P link && cd .. && rm CLAUDE.md", view) is None
    assert check("cd link && builtin cd .. && rm CLAUDE.md", view) is not None


def test_hook_uses_sdk_cwd_and_checks_file_tools(workspace):
    user, view = workspace
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(user / "current/.claude")}
    for name, inputs, expected in [
        ("Bash", {"command": '../.venv/bin/python -c "print(1)"'}, 0),
        ("Read", {"file_path": "snapshot.json"}, 0),
        ("Read", {"file_path": str(user / "current/out/snapshot.json")}, 0),
        ("Read", {"file_path": "../../../../secret"}, 2),
        ("Write", {"file_path": str(user / "current/.claude/settings.json")}, 2),
    ]:
        result = subprocess.run(
            [sys.executable, hook.__file__], cwd=view, env=env,
            input=json.dumps({"tool_name": name, "cwd": str(view / "out"), "tool_input": inputs}),
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == expected, result.stderr


def test_plain_python_from_subdirectory_uses_real_venv(workspace):
    user, view = workspace
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(user / ".venv")], check=True, timeout=30)
    ctx = WorkspaceContext("native", str(user / "current"), str(view), [],
                           env={"AIHUB_AGENT_WORKSPACE": str(user / "current")},
                           tunnel_env_via_stdin=True, is_isolated=True)
    env = _build_runtime_env(RuntimeConfig(), ctx)
    # A dependency installed only in this venv must remain importable after cd.
    packages = subprocess.check_output(
        [str(view / ".venv/bin/python"), "-c", "import site; print(site.getsitepackages()[0])"], text=True,
    ).strip()
    Path(packages, "workspace_only_dependency.py").write_text("VALUE = 'venv-dependency-ok'\n")
    for command in ["python", "python3"]:
        result = subprocess.run(
            [command, "-c", "import sys,json,workspace_only_dependency as dep;print(json.dumps({'prefix':sys.prefix,'base':sys.base_prefix,'dependency':dep.VALUE}))"],
            cwd=view / "out", env=env, capture_output=True, text=True, check=True, timeout=5,
        )
        data = json.loads(result.stdout)
        assert Path(data["prefix"]).resolve() == (user / ".venv").resolve()
        assert data["prefix"] != data["base"]
        assert data["dependency"] == "venv-dependency-ok"
    # Exercise the real environment tunnel used after switching native users.
    result = subprocess.run(
        [sys.executable, "-c", RUNNER_SCRIPT, "runner", "python3", "-c", "import sys; print(sys.prefix)"],
        input=_encode_tunneled_env(ctx, env), capture_output=True, check=True, timeout=5,
    )
    assert Path(result.stdout.decode().strip()).resolve() == (user / ".venv").resolve()


def test_container_runner_creates_venv_and_reuses_dependencies(tmp_path):
    ctx = WorkspaceContext("container", str(tmp_path), str(tmp_path), [],
                           env={"AIHUB_AGENT_WORKSPACE": str(tmp_path), "AIHUB_BOOTSTRAP_VENV": "1"},
                           tunnel_env_via_stdin=True, is_isolated=True)
    env = _build_runtime_env(RuntimeConfig(), ctx)
    runner = [sys.executable, "-c", RUNNER_SCRIPT, "runner", "python3", "-c"]
    result = subprocess.run(
        runner + ["import sys,pip; print(sys.prefix)"], input=_encode_tunneled_env(ctx, env),
        capture_output=True, check=True, timeout=30,
    )
    assert Path(result.stdout.decode().strip()).resolve() == tmp_path / ".venv"
    marker = tmp_path / ".venv/retained-dependency"
    marker.write_text("retained")
    subprocess.run(runner + ["print('reused')"], input=_encode_tunneled_env(ctx, env),
                   capture_output=True, check=True, timeout=5)
    assert marker.read_text() == "retained"


def test_container_runner_repairs_venv_left_without_pip(tmp_path):
    venv = tmp_path / ".venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=30)
    assert subprocess.run([str(venv / "bin/python"), "-I", "-c", "import pip"],
                          capture_output=True).returncode != 0
    marker = venv / "retained-dependency"
    marker.write_text("retained")
    ctx = WorkspaceContext("container", str(tmp_path), str(tmp_path), [],
                           env={"AIHUB_AGENT_WORKSPACE": str(tmp_path), "AIHUB_BOOTSTRAP_VENV": "1"},
                           tunnel_env_via_stdin=True, is_isolated=True)
    result = subprocess.run(
        [sys.executable, "-c", RUNNER_SCRIPT, "runner", "python3", "-c", "import pip; print('ready')"],
        input=_encode_tunneled_env(ctx, _build_runtime_env(RuntimeConfig(), ctx)),
        capture_output=True, check=True, timeout=30,
    )
    assert result.stdout == b"ready\n"
    assert marker.read_text() == "retained"


def test_container_bootstrap_reports_creation_error_on_stderr_only(tmp_path):
    import base64
    header = base64.b64encode(json.dumps({"AIHUB_AGENT_WORKSPACE": str(tmp_path),
                                         "AIHUB_BOOTSTRAP_VENV": "1"}).encode()) + b"\n"
    with patch("os.read", side_effect=[bytes([byte]) for byte in header]), \
            patch.dict(os.environ), patch("os.chdir"), patch("os.execvpe") as execute, \
            patch("os.path.isfile", return_value=False), \
            patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="ensurepip is not available")):
        with pytest.raises(SystemExit, match="ensurepip is not available"):
            exec(RUNNER_SCRIPT, {})
        execute.assert_not_called()


def test_directory_venv_failure_does_not_fall_back_to_system_python(tmp_path):
    with patch("sandbox.directory.subprocess.run", side_effect=subprocess.CalledProcessError(1, "venv")):
        with pytest.raises(WorkspacePreparationError, match=".venv 创建失败"):
            DirectorySandbox._ensure_venv(str(tmp_path))


def test_native_venv_failure_is_explicit_and_existing_root_owned_venv_is_repaired():
    with patch("sandbox.native.sys.platform", "linux"):
        sandbox = NativeSandbox()
    with patch.object(sandbox, "_run_root", return_value=SimpleNamespace(returncode=1)):
        with pytest.raises(WorkspacePreparationError, match=".venv 创建失败"):
            sandbox._ensure_venv("/workspace", username="agent")
    with patch.object(sandbox, "_run_root", side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]) as run:
        sandbox._ensure_venv("/workspace", username="agent")
        assert run.call_args.args == ("chown", "-R", "agent:agent", "/workspace/.venv")


def test_prompt_identifies_runtime_root_and_uses_same_interpreter_for_pip():
    prompt = build_claude_md(SimpleNamespace(name="Agent", description="", system_prompt=""),
                             runtime_workspace_root="/var/lib/aihub/user_workspaces/owner/current")
    assert ".venv/bin/python -m pip install" in prompt
    assert "cd out && ../.venv/bin/python" in prompt
    assert "/var/lib/aihub/user_workspaces/owner/current" in prompt
