"""Opt-in native checks using disposable Linux users and a temporary filesystem."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import mkdtemp
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

if sys.platform == "linux":
    import pwd

from database import settings
from sandbox.native import NativeSandbox
from workspace_provider import agent_workspace_snapshot, workspace_snapshot


@unittest.skipUnless(
    sys.platform == "linux" and os.environ.get("AIHUB_TEST_NATIVE") == "1",
    "Requires Linux, passwordless sudo and AIHUB_TEST_NATIVE=1",
)
class NativeWorkspaceIntegrationTests(unittest.TestCase):
    def test_permissions_quota_copyback_and_stale_discard(self):
        root = Path(mkdtemp(prefix="aihub-native-verify-", dir="/tmp"))
        self.assertEqual(root.parent, Path("/tmp"))
        self.assertFalse(root.is_symlink())
        prefix = "aih_verify_" + uuid4().hex[:8] + "_"
        users = [prefix + str(n) for n in (1, 2)]
        for username in users:
            with self.assertRaises(KeyError):
                pwd.getpwnam(username)
        with (patch.object(settings, "user_workspace_root", str(root)),
              patch.object(settings, "user_workspace_user_prefix", prefix),
              patch.object(settings, "claude_code_native_workspace_root", str(root / "legacy")),
              patch.object(settings, "skill_release_cache_root", str(root / "cache"))):
            provider = NativeSandbox()
            try:
                contexts = []
                workspaces = []
                agents = []
                for n in (1, 2):
                    workspace = workspace_snapshot(SimpleNamespace(
                        id=n, user_id=n, workspace_key="workspace-" + str(n),
                        migration_status="not_required", quota_bytes=64 * 1024 * 1024,
                    ))
                    agent = agent_workspace_snapshot(SimpleNamespace(
                        id=n, name="Native verification", description="", system_prompt="",
                        runtime_type="claude_code", runtime_skills=[], runtime_mcps=[],
                    ))
                    contexts.append(provider.prepare_execution(
                        agent, None, run_id="seed-" + str(n), workspace=workspace,
                    ))
                    workspaces.append(workspace)
                    agents.append(agent)
                first, second = contexts
                provider.write_file(workspaces[0], "original.txt", b"saved original")
                provider.write_file(workspaces[1], "private.txt", b"other user's file")
                first = provider.prepare_execution(
                    agents[0], None, run_id="run-1", workspace=workspaces[0],
                )
                script = """
import json, os, pathlib, sys
root = pathlib.Path(sys.argv[1])
os.chdir(root)
assert pathlib.Path('CLAUDE.md').is_file()
assert pathlib.Path('.venv/bin/python').is_file()
assert os.access('.claude', os.W_OK)
pathlib.Path('.claude/session-env').write_text('state')
pathlib.Path('.claude/projects/session.txt').write_text('persistent session')
for target in (root / '.claude/settings.json', pathlib.Path(sys.argv[2])):
    try:
        target.write_text('unauthorized')
    except PermissionError:
        pass
    else:
        raise AssertionError('protected or other-user file was writable')
try:
    pathlib.Path(sys.argv[2]).read_bytes()
except PermissionError:
    pass
else:
    raise AssertionError('other-user file was readable')
reports = pathlib.Path('reports')
reports.mkdir()
for n in range(128):
    (reports / ('part-' + str(n))).write_bytes(b'x' * (128 * 1024))
pathlib.Path('result.txt').write_text('generated result')
print(json.dumps({'files':128, 'bytes':128 * 128 * 1024}))
"""
                result = provider._run_root(
                    "runuser", "-u", users[0], "--", "python3", "-c", script,
                    first.workspace_root, str(Path(second.persistent_files_path) / "private.txt"),
                )
                self.assertEqual(json.loads(result.stdout)["bytes"], 16 * 1024 * 1024)
                first.handle["quota_bytes"] = 1
                with self.assertRaisesRegex(RuntimeError, "workspace quota exceeded"):
                    provider.cleanup(first)
                self.assertEqual(provider.read_file(workspaces[0], "original.txt")[0], b"saved original")
                self.assertNotEqual(provider._run_root(
                    "test", "-e", str(Path(first.persistent_files_path) / "result.txt"), check=False,
                ).returncode, 0)
                self.assertEqual(provider._run_root("test", "-d", first.execution_view_path).returncode, 0)
                first.handle["quota_bytes"] = 64 * 1024 * 1024
                started = time.monotonic()
                provider.cleanup(first)
                duration = time.monotonic() - started
                self.assertEqual(provider.read_file(workspaces[0], "result.txt")[0], b"generated result")
                self.assertEqual(provider.read_file(workspaces[0], "original.txt")[0], b"saved original")
                self.assertEqual(provider.read_file(workspaces[0], "reports/part-127")[0], b"x" * (128 * 1024))
                self.assertNotEqual(provider._run_root("test", "-d", first.handle["run_root"], check=False).returncode, 0)
                self.assertEqual(provider._run_root(
                    "cat", str(root / "workspace-1" / "sessions" / "projects" / "session.txt"),
                ).stdout, "persistent session")
                old = provider.prepare_execution(agents[0], None, run_id="stale", workspace=workspaces[0])
                current = provider.prepare_execution(agents[0], None, run_id="successor", workspace=workspaces[0])
                provider.discard_execution(old)
                self.assertEqual(os.readlink(current.workspace_root), current.execution_view_path)
                self.assertNotEqual(provider._run_root("test", "-d", old.handle["run_root"], check=False).returncode, 0)
                self.assertEqual(provider._run_root("test", "-d", current.execution_view_path).returncode, 0)
                self.assertEqual(provider.read_file(workspaces[0], "result.txt")[0], b"generated result")
                provider.discard_execution(current)
                provider.discard_execution(second)
                print(f"Native verified: permissions/isolation/quota/stale discard, 16 MiB copyback in {duration:.2f}s")
            finally:
                for username in users:
                    subprocess.run([*provider._privileged_prefix(), "userdel", username],
                                   capture_output=True, check=False)
                # This exact temporary root is created above and never inferred
                # from a production workspace or from a provider deletion API.
                self.assertEqual(root.parent, Path("/tmp"))
                provider._run_root("chattr", "-R", "-i", str(root), check=False)
                provider._run_root("rm", "-rf", str(root))
                self.assertFalse(root.exists())
                for username in users:
                    with self.assertRaises(KeyError):
                        pwd.getpwnam(username)


if __name__ == "__main__":
    unittest.main()
