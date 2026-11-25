"""Regression checks for find searches inside workspaces under system directories."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from agent_hooks import pre_tool_use as hook


class FindWorkspacePathsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "reports").mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()

    def check(self, command, cwd=None):
        return hook.check_command(command, str(cwd or self.workspace), str(self.workspace))

    def test_explicit_and_relative_searches(self):
        for command in [
            "find . -name '*.py'", "find reports -type f", "find -name '*.py'",
            "find -P . reports -type f", "find -H reports -type f",
            "find -O2 -D tree . -type f", "find -- reports -type f",
            f"find {shlex.quote(self.workspace.as_posix())} -maxdepth 2 -type f",
            f"find {shlex.quote((self.workspace / 'directory with spaces').as_posix())} -type f",
            f"find {shlex.quote(self.workspace.as_posix())} -type f | head -10",
            "python3 script.py", ".venv/bin/python script.py",
        ]:
            with self.subTest(command=command):
                self.assertIsNone(self.check(command))

    @unittest.skipUnless(os.name == "posix", "Linux absolute path regression")
    def test_linux_workspace_prefixes_and_current_alias(self):
        for prefix in ["/var/lib/aihub", "/tmp", "/home", "/opt"]:
            ws = f"{prefix}/user_workspaces/owner/managed/runs/run/view"
            with self.subTest(workspace=ws):
                self.assertIsNone(hook.check_command(f"find {ws} -type f", ws, ws))
                self.assertIsNotNone(hook.check_command(f"find {prefix} -type f", ws, ws))
                self.assertIsNotNone(hook.check_command(f"find {ws}-other -type f", ws, ws))
        alias = self.root / "current"
        alias.symlink_to(self.workspace, target_is_directory=True)
        self.assertIsNone(self.check(f"find {shlex.quote(str(alias))} -type f"))

    def test_outside_searches(self):
        for command in [
            "find / -type f", "find /var -type f", "find /etc -type f",
            "find .. -type f", "find reports ../../outside -type f",
            f"find . {shlex.quote(self.outside.as_posix())} -type f",
            "find -H ../outside -type f", "find -P -- ../outside -type f",
        ]:
            with self.subTest(command=command):
                self.assertIsNotNone(self.check(command))
        self.assertIsNotNone(self.check("find . -type f", cwd=self.outside))

    @unittest.skipUnless(os.name == "posix", "Requires Linux symlink semantics")
    def test_symlink_search_roots(self):
        (self.workspace / "external").symlink_to(self.outside, target_is_directory=True)
        (self.workspace / "local").symlink_to(self.workspace / "reports", target_is_directory=True)
        (self.workspace / ".venv").mkdir()
        (self.workspace / ".venv" / "external").symlink_to(self.outside, target_is_directory=True)
        for target in ["external", "./external", ".venv/external"]:
            with self.subTest(target=target):
                self.assertIn("实际路径", self.check(f"find {target} -type f"))
        self.assertIsNone(self.check("find -H local -type f"))
        self.assertIsNotNone(self.check("find -L . -type f"))

    def test_indirect_roots_and_protected_actions(self):
        for command in [
            "find -files0-from roots.txt -type f", "find $SEARCH_ROOT -type f",
            "find ./links/* -type f", "find . -delete", "find . -exec rm {} +",
            "find . -type f && find /etc -type f",
        ]:
            with self.subTest(command=command):
                self.assertIsNotNone(self.check(command))
        self.assertIsNone(self.check("find reports -delete"))

    def test_hook_entrypoint(self):
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.workspace / ".claude"), "PYTHONIOENCODING": "utf-8"}
        for command, expected in [
            (f"find {shlex.quote(self.workspace.as_posix())} -type f", 0),
            ("find ../outside -type f", 2),
        ]:
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, hook.__file__], cwd=self.workspace, env=env,
                    input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
                    capture_output=True, text=True, encoding="utf-8", timeout=10,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertIn("find 搜索路径越界", result.stderr)


if __name__ == "__main__":
    unittest.main()
