"""macOS workspace defaults and host-independent container preparation."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from database import Settings, settings
from sandbox.container import ContainerSandbox


class WorkspaceSettingsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def configuration(self, **overrides):
        return Settings(_env_file=None, database_url="sqlite://", **overrides)

    def test_mac_default_is_inside_project_and_accepts_empty_config(self):
        expected = str(Path(__file__).resolve().parent / "user_workspaces")
        with patch("database.sys.platform", "darwin"):
            self.assertEqual(self.configuration().user_workspace_root, expected)
            self.assertEqual(self.configuration(user_workspace_root="  ").user_workspace_root, expected)

    def test_linux_default_is_preserved(self):
        with patch("database.sys.platform", "linux"):
            self.assertEqual(self.configuration().user_workspace_root, "/var/lib/aihub/user_workspaces")

    def test_explicit_and_relative_paths(self):
        self.assertEqual(self.configuration(user_workspace_root="/custom/workspaces").user_workspace_root,
                         "/custom/workspaces")
        expected = Path(__file__).resolve().parent.parent / "local workspaces"
        self.assertEqual(self.configuration(user_workspace_root="local workspaces").user_workspace_root,
                         str(expected))


class ContainerWorkspaceTests(unittest.TestCase):
    def test_empty_skills_clean_old_installations_and_prepare_writable_view(self):
        with TemporaryDirectory(prefix="aihub mac ") as temporary:
            self.enterContext(patch.object(settings, "user_workspace_root", temporary))
            self.enterContext(patch.object(ContainerSandbox, "_require_docker"))
            # A container must never depend on the Mac/Windows Python path.
            self.enterContext(patch("agent_workspace.sys.executable", "/host only/python"))
            workspace = SimpleNamespace(id=1, workspace_key="workspace-1", quota_bytes=0)
            agent = SimpleNamespace(id=9, name="Mac test", description="", system_prompt="",
                                    runtime_skills=[], runtime_mcps=[], mcp_overrides=[])
            sandbox = ContainerSandbox()
            old_install = Path(temporary) / "workspace-1/managed/skill-installations/9/removed"
            old_install.mkdir(parents=True)
            (old_install / "SKILL.md").write_text("old", encoding="utf-8")
            self.assertEqual(sandbox.sync_skill_installations(agent, workspace), [])
            self.assertFalse(old_install.exists())

            context = sandbox.prepare_execution(agent, None, run_id="mac-test", workspace=workspace)
            view = Path(context.execution_view_path)
            venv = Path(temporary) / "workspace-1/managed/container-venv"
            self.assertTrue(venv.is_dir())
            self.assertIn(f"type=bind,src={venv},dst=/workspace/.venv", context.argv_prefix)
            self.assertEqual(context.env["AIHUB_BOOTSTRAP_VENV"], "1")
            (venv / "retained-dependency").write_text("persistent")
            config = json.loads((view / ".claude/settings.json").read_text(encoding="utf-8"))
            for event, script in (("PreToolUse", "pre_tool_use.py"), ("PostToolUse", "post_tool_use.py")):
                command = config["hooks"][event][0]["hooks"][0]["command"]
                self.assertEqual(command, f"/usr/bin/python3 /workspace/.claude/hooks/{script}")
                self.assertTrue((view / ".claude/hooks" / script).is_file())
            (view / "note.txt").write_text("saved on Mac", encoding="utf-8")
            sandbox.cleanup(context)
            persistent = Path(temporary) / "workspace-1/files/note.txt"
            self.assertEqual(persistent.read_text(encoding="utf-8"), "saved on Mac")
            self.assertFalse(view.exists())
            self.assertEqual((venv / "retained-dependency").read_text(), "persistent")
            self.assertFalse((persistent.parent / ".venv").exists())


if __name__ == "__main__":
    unittest.main()
