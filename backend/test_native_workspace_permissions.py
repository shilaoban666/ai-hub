import base64
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from sandbox.native import NativeSandbox, RUNNER_SCRIPT, WORKSPACE_ACCESS_SCRIPT
from workspace_provider import workspace_snapshot


class NativeWorkspacePermissionTests(unittest.TestCase):
    def prepare(self, root, fail_path=None, access_error=None):
        calls = []

        def run_root(*args, check=True):
            calls.append((args, check))
            if args == ("chmod", "711", fail_path) and check:
                raise RuntimeError("permission setup failed")
            if args[0] == "runuser" and access_error:
                return SimpleNamespace(returncode=1, stdout="", stderr=access_error)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with ExitStack() as stack:
            stack.enter_context(patch("sandbox.native.sys.platform", "linux"))
            stack.enter_context(patch("sandbox.native.settings.user_workspace_root", root))
            for name in ("_ensure_user", "_sync_managed_files", "_ensure_venv", "_apply_permissions"):
                stack.enter_context(patch.object(NativeSandbox, name))
            for name, value in (("install_skills", []), ("install_hooks", None),
                                ("build_claude_md", ""), ("build_settings_json", {}),
                                ("build_mcp_json", ({}, []))):
                stack.enter_context(patch("sandbox.native." + name, return_value=value))
            sandbox = NativeSandbox()
            sandbox._run_root = run_root
            ctx = sandbox.prepare_execution(
                SimpleNamespace(id=1, skills=[], mcps=[]), SimpleNamespace(),
                run_id="run1",
                workspace=workspace_snapshot(SimpleNamespace(id=1, user_id=7, workspace_key="user7")),
            )
        return ctx, calls

    def test_shared_root_is_traversable_and_private_directories_stay_private(self):
        with tempfile.TemporaryDirectory() as root:
            ctx, calls = self.prepare(root)
            self.assertIn((("chmod", "o+x", root), True), calls)
            self.assertNotIn((("chmod", "777", root), True), calls)
            user_root = os.path.join(root, "user7")
            self.assertIn((("chmod", "700", os.path.join(user_root, "files"),
                            os.path.join(user_root, "sessions"), ctx.execution_view_path), True), calls)
            for path in (user_root, os.path.join(user_root, "managed"),
                         os.path.join(user_root, "managed", "runs"), ctx.handle["run_root"]):
                self.assertIn((("chmod", "711", path), True), calls)
            self.assertEqual(calls[-3], (("chown", "aihub_user_7:aihub_user_7", ctx.execution_view_path), True))
            self.assertEqual(calls[-2], (("chmod", "700", ctx.execution_view_path), True))
            self.assertEqual(calls[-1][0][0], "runuser")
            self.assertEqual(calls[-1][0][-2:], (ctx.execution_view_path, ctx.workspace_root))

    def test_access_failure_reports_runtime_user_and_denied_directory(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "工作区目录权限异常.*cannot traverse /private/managed"):
                self.prepare(root, access_error="uid=1001 gid=1001: cannot traverse /private/managed")

    def test_access_probe_identifies_physical_parent_before_entering_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            managed = os.path.join(root, "managed")
            view = os.path.join(managed, "view")
            os.makedirs(view)
            with patch("sys.argv", ["probe", view, os.path.join(root, "current")]), \
                    patch("os.getuid", return_value=1001, create=True), \
                    patch("os.getgid", return_value=1001, create=True), \
                    patch("os.access", side_effect=lambda path, mode: path != managed), \
                    patch("os.chdir") as change_dir:
                with self.assertRaises(SystemExit) as error:
                    exec(WORKSPACE_ACCESS_SCRIPT, {})
                self.assertIn("cannot traverse " + managed, str(error.exception))
                self.assertIn("owner=", str(error.exception))
                change_dir.assert_not_called()

    def test_parent_permission_failure_aborts_preparation(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "permission setup failed"):
                self.prepare(root, fail_path=os.path.join(root, "user7", "managed"))

    def test_runner_reports_permission_error_without_traceback(self):
        header = base64.b64encode(json.dumps({"AIHUB_AGENT_WORKSPACE": "/private/current"}).encode()) + b"\n"
        with patch("os.read", side_effect=[bytes([byte]) for byte in header]), \
                patch.dict(os.environ), \
                patch("os.chdir", side_effect=PermissionError("denied")), \
                patch("os.execvpe") as execute:
            with self.assertRaisesRegex(SystemExit, "Runtime user cannot access workspace: /private/current"):
                exec(RUNNER_SCRIPT, {})
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
