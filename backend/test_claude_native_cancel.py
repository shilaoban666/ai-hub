"""Native process groups, with opt-in real Linux user-switch cancellation."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import mkdtemp
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

if sys.platform == "linux":
    import pwd

from runtimes.base import RuntimeConfig
from runtimes.claude_code import ClaudeCodeRuntime
from sandbox.base import WorkspaceContext
from sandbox.native import NativeSandbox


class NativeRuntimeCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_launch_has_own_session_and_always_clears_group(self):
        for callback_fails in (False, True):
            with self.subTest(callback_fails=callback_fails):
                proc = SimpleNamespace(pid=1234, returncode=0, stdin=None,
                                       stdout=SimpleNamespace(read=AsyncMock(return_value=b"")),
                                       stderr=SimpleNamespace(read=AsyncMock(return_value=b"")),
                                       wait=AsyncMock(return_value=0), kill=Mock())
                runtime = ClaudeCodeRuntime()
                context = WorkspaceContext("native", "/workspace", "/workspace", [], is_isolated=True)
                emit = AsyncMock(side_effect=ValueError("callback failed") if callback_fails else None)
                with (patch("runtimes.claude_code.os.name", "posix"),
                      patch("runtimes.claude_code.os.geteuid", return_value=0, create=True),
                      patch("runtimes.claude_code.signal.SIGKILL", 9, create=True),
                      patch("runtimes.claude_code.os.killpg", create=True) as kill_group,
                      patch("runtimes.claude_code.asyncio.create_subprocess_exec", return_value=proc) as spawn):
                    if callback_fails:
                        with self.assertRaisesRegex(ValueError, "callback failed"):
                            await runtime.run(RuntimeConfig(), context, "test", [], emit)
                    else:
                        await runtime.run(RuntimeConfig(), context, "test", [], emit)
                    self.assertTrue(spawn.call_args.kwargs["start_new_session"])
                    kill_group.assert_called_once_with(1234, 9)
                    self.assertIsNone(runtime._process_group_id)
                    await runtime.cancel()
                    kill_group.assert_called_once()
                    proc.kill.assert_not_called()

    async def test_cancel_kills_group_when_parent_has_already_exited(self):
        runtime = ClaudeCodeRuntime()
        runtime._proc = SimpleNamespace(pid=1234, returncode=0, kill=Mock())
        runtime._process_group_id = 1234
        with (patch("runtimes.claude_code.signal.SIGKILL", 9, create=True),
              patch("runtimes.claude_code.os.geteuid", return_value=0, create=True),
              patch("runtimes.claude_code.os.killpg", create=True) as kill_group):
            await runtime.cancel()
        kill_group.assert_called_once_with(1234, 9)
        runtime._proc.kill.assert_not_called()
        self.assertIsNone(runtime._process_group_id)

    async def test_non_root_native_kills_only_its_group_with_existing_sudo(self):
        runtime = ClaudeCodeRuntime()
        runtime._proc = SimpleNamespace(pid=1234, returncode=0, kill=Mock())
        runtime._process_group_id = 1234
        with (patch("runtimes.claude_code.os.geteuid", return_value=1000, create=True),
              patch("runtimes.claude_code.subprocess.run", return_value=SimpleNamespace(returncode=0)) as terminate):
            await runtime.cancel()
        self.assertEqual(terminate.call_args.args[0], ["sudo", "-n", "kill", "-KILL", "--", "-1234"])
        self.assertIsNone(runtime._process_group_id)
        runtime._process_group_id = 1234
        with (patch("runtimes.claude_code.os.geteuid", return_value=1000, create=True),
              patch("runtimes.claude_code.subprocess.run", return_value=SimpleNamespace(returncode=1)),
              patch("runtimes.claude_code.os.killpg", side_effect=PermissionError, create=True)):
            with self.assertRaises(PermissionError):
                await runtime.cancel()
        self.assertEqual(runtime._process_group_id, 1234)

    async def test_non_native_and_windows_keep_direct_process_strategy(self):
        for system, sandbox in (("posix", "directory"), ("posix", "container"), ("nt", "native")):
            with self.subTest(system=system, sandbox=sandbox):
                proc = SimpleNamespace(pid=1234, returncode=0, stdin=None,
                                       stdout=SimpleNamespace(read=AsyncMock(return_value=b"")),
                                       stderr=SimpleNamespace(read=AsyncMock(return_value=b"")),
                                       wait=AsyncMock(return_value=0), kill=Mock())
                runtime = ClaudeCodeRuntime()
                context = WorkspaceContext(sandbox, "/workspace", "/workspace", [], is_isolated=True)
                with (patch("runtimes.claude_code.os.name", system),
                      patch("runtimes.claude_code.os.killpg", create=True) as kill_group,
                      patch("runtimes.claude_code.asyncio.create_subprocess_exec", return_value=proc) as spawn):
                    await runtime.run(RuntimeConfig(), context, "test", [], AsyncMock())
                    self.assertNotIn("start_new_session", spawn.call_args.kwargs)
                    proc.returncode = None
                    await runtime.cancel()
                    proc.kill.assert_called_once()
                    kill_group.assert_not_called()


CLI_SCRIPT = """#!/usr/bin/python3
import json, os, pathlib, subprocess
normal_exit = os.environ.get('AIHUB_TEST_NATIVE_MODE') == 'normal'
streams = {key: subprocess.DEVNULL for key in ('stdin', 'stdout', 'stderr')} if normal_exit else {}
child = subprocess.Popen(['/bin/sleep', '30'], **streams)
pathlib.Path(os.environ['AIHUB_AGENT_WORKSPACE'], 'pids.json').write_text(json.dumps({
    'cli': os.getpid(), 'leaf': child.pid, 'uid': os.getuid(), 'pgid': os.getpgrp(),
}))
print(json.dumps({'type':'system', 'subtype':'init', 'session_id':'cancel-probe'}), flush=True)
if not normal_exit:
    child.wait()
"""


@unittest.skipUnless(
    sys.platform == "linux" and os.environ.get("AIHUB_TEST_NATIVE") == "1",
    "Requires Linux, passwordless sudo and AIHUB_TEST_NATIVE=1",
)
class NativeProcessCancellationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_user_switch_cancel_stops_cli_and_leaf(self):
        await self._verify_native_process_tree(normal_exit=False)

    async def test_parent_exit_still_cleans_isolated_tool(self):
        await self._verify_native_process_tree(normal_exit=True)

    async def _verify_native_process_tree(self, *, normal_exit):
        root = Path(mkdtemp(prefix="aihub-cancel-verify-", dir="/tmp"))
        root.chmod(0o711)
        username = "ai_cpr_" + uuid4().hex[:8]
        provider = object.__new__(NativeSandbox)
        privilege = provider._privileged_prefix()
        with self.assertRaises(KeyError):
            pwd.getpwnam(username)
        created = False
        runtime = ClaudeCodeRuntime()
        task = None
        try:
            subprocess.run([*privilege, "useradd", "--no-create-home", "--home-dir", str(root / "home"),
                            "--shell", "/bin/bash", username], check=True)
            created = True
            uid = pwd.getpwnam(username).pw_uid
            home = root / "home"
            home.mkdir()
            home.chmod(0o700)
            subprocess.run([*privilege, "chown", f"{username}:{username}", str(home)], check=True)
            cli = root / "cli"
            cli.write_text(CLI_SCRIPT)
            cli.chmod(0o755)
            prefix = provider._run_as_user_prefix(username)
            context = WorkspaceContext("native", str(home), str(home), prefix, claude_bin=str(cli),
                                       env={"AIHUB_AGENT_WORKSPACE": str(home),
                                            "AIHUB_TEST_NATIVE_MODE": "normal" if normal_exit else "cancel"},
                                       is_isolated=True,
                                       tunnel_env_via_stdin=True)
            started = asyncio.Event()
            async def emit(event):
                if event.tool_use_id == "cancel-probe":
                    started.set()
            task = asyncio.create_task(runtime.run(RuntimeConfig(timeout_seconds=30), context, "test", [], emit))
            await asyncio.wait_for(started.wait(), 5)
            pids = json.loads(subprocess.check_output([*privilege, "cat", str(home / "pids.json")]))
            self.assertEqual(pids["uid"], uid)
            wrapper = runtime._proc.pid
            self.assertEqual(pids["pgid"], wrapper)
            if normal_exit:
                await asyncio.wait_for(task, 5)
            else:
                await runtime.cancel()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            deadline = asyncio.get_running_loop().time() + 3
            def active(pid):
                status = Path("/proc") / str(pid) / "stat"
                try:
                    return status.read_text().split(") ", 1)[1].split()[0] not in {"Z", "X"}
                except FileNotFoundError:
                    return False
            while any(active(pid) for pid in (wrapper, pids["cli"], pids["leaf"])):
                if asyncio.get_running_loop().time() >= deadline:
                    self.fail("native CLI or tool remained active after cancellation")
                await asyncio.sleep(0.05)
            self.assertTrue(task.done())
            self.assertIsNone(runtime._process_group_id)
            print(f"Native process cleanup verified: {prefix[0]}, mode={'normal' if normal_exit else 'cancel'}, CLI and leaf inactive")
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if created:
                subprocess.run([*privilege, "pkill", "-KILL", "-u", username], check=False)
            if runtime._proc is not None:
                await asyncio.wait_for(runtime._proc.wait(), 3)
            if created:
                subprocess.run([*privilege, "userdel", username], check=True)
            self.assertEqual(root.parent, Path("/tmp"))
            subprocess.run([*privilege, "rm", "-rf", str(root)], check=True)
            self.assertFalse(root.exists())
            with self.assertRaises(KeyError):
                pwd.getpwnam(username)


if __name__ == "__main__":
    unittest.main()
