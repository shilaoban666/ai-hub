import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from agent_routes import sync_agent_skill_installations
from sandbox.native import NativeSandbox
from skill_installation import materialize, reconcile
from agent_hooks import pre_tool_use as hook


class InstallationTests(unittest.TestCase):
    def test_release_identity_changes_even_when_content_and_source_are_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "release", root / "installed"
            source.mkdir()
            (source / "SKILL.md").write_text("identical content")
            identity = {"skill_id": 1, "release_id": 11, "version": "1.0", "content_sha256": "a" * 64}
            spec = {"directory": str(source), "release": identity}
            materialize(spec, destination)
            marker = destination / ".aihub-installed.json"
            unchanged_file = (destination / "SKILL.md").stat().st_mtime_ns
            # Each field is part of the identity; changes must refresh the record
            # despite identical file fingerprints (including same-version releases).
            for change in ({"release_id": 12}, {"version": "2.0"},
                           {"content_sha256": "b" * 64}, {"skill_id": 2},
                           {"skill_id": 1, "release_id": 11, "version": "1.0", "content_sha256": "a" * 64}):
                identity.update(change)
                with patch("skill_installation.content_inventory", wraps=__import__("skill_installation").content_inventory) as verify:
                    materialize(spec, destination, copy_function=MagicMock(side_effect=AssertionError("unnecessary copy")))
                    self.assertGreaterEqual(verify.call_count, 2)
                self.assertEqual(json.loads(marker.read_text())["release"], identity)
                self.assertEqual((destination / "SKILL.md").stat().st_mtime_ns, unchanged_file)
            before = marker.stat().st_mtime_ns
            materialize(spec, destination, copy_function=MagicMock(side_effect=AssertionError("unnecessary copy")))
            self.assertEqual(marker.stat().st_mtime_ns, before)

    def test_legacy_record_migrates_only_after_verifying_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "installed"
            source.mkdir()
            (source / "SKILL.md").write_text("published")
            materialize(source, destination)
            marker = destination / ".aihub-installed.json"
            old = json.loads(marker.read_text())
            old["format"] = 1
            old.pop("release")
            marker.write_text(json.dumps(old))
            identity = {"skill_id": 1, "release_id": 11, "version": "1.0", "content_sha256": "a" * 64}
            spec = {"directory": str(source), "release": identity}
            materialize(spec, destination, copy_function=MagicMock(side_effect=AssertionError("unnecessary copy")))
            self.assertEqual(json.loads(marker.read_text())["release"], identity)
            self.assertEqual(json.loads(marker.read_text())["format"], 2)
            # Matching version alone must never conceal damaged files.
            (destination / "SKILL.md").write_text("damaged")
            materialize(spec, destination)
            self.assertEqual((destination / "SKILL.md").read_text(), "published")

    def test_bad_release_identity_does_not_delete_existing_installations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "existing").mkdir()
            invalid = {"directory": "unused", "release": {"skill_id": 1}}
            with self.assertRaises(ValueError):
                reconcile(root, {"new": invalid})
            self.assertTrue((root / "existing").exists())

    def test_persistent_skill_paths_are_readable_but_protected_from_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, installed = root / "view", root / "persistent/skill"
            workspace.mkdir()
            installed.mkdir(parents=True)
            target = str(installed / "SKILL.md")
            with patch.object(hook, "_installed_skill_roots", return_value=[str(installed)]):
                self.assertTrue(hook.resolve_under_ws(target, str(workspace), str(workspace)))
                self.assertTrue(hook.is_protected_target(target, str(workspace), str(workspace)))
                self.assertTrue(hook.destroys_protected(str(installed), str(workspace), str(workspace)))
                self.assertFalse(hook.resolve_under_ws(str(root / "persistent/other"), str(workspace), str(workspace)))
                self.assertIsNone(hook.check_find_paths(["find", str(installed)], str(workspace), str(workspace)))

    def test_user_owned_links_cannot_grant_outside_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / ".claude/skills"
            directory.mkdir(parents=True)
            with patch.object(hook.os, "lstat", return_value=SimpleNamespace(st_uid=1000, st_mode=0o755)):
                self.assertEqual(hook._installed_skill_roots(str(root)), [])
            with patch.object(hook.os, "lstat", return_value=SimpleNamespace(st_uid=0, st_mode=0o777)):
                self.assertEqual(hook._installed_skill_roots(str(root)), [])

    def test_missing_extra_and_changed_files_are_reconciled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "release"
            source.mkdir()
            (source / "SKILL.md").write_text("v1")
            installed = root / "installed"
            reconcile(installed, {"skill": str(source)})
            target = installed / "skill"
            (target / "SKILL.md").unlink()
            reconcile(installed, {"skill": str(source)})
            self.assertEqual((target / "SKILL.md").read_text(), "v1")
            (target / "unexpected.txt").write_text("old")
            reconcile(installed, {"skill": str(source)})
            self.assertFalse((target / "unexpected.txt").exists())
            (source / "SKILL.md").write_text("v2")
            reconcile(installed, {"skill": str(source)})
            self.assertEqual((target / "SKILL.md").read_text(), "v2")
            reconcile(installed, {})
            self.assertFalse(target.exists())

    def test_invalid_metadata_recovers_without_recopying_valid_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, destination = Path(temporary) / "source", Path(temporary) / "dest"
            source.mkdir()
            (source / "SKILL.md").write_text("ok")
            materialize(source, destination)
            (destination / ".aihub-installed.json").write_text("broken")
            materialize(source, destination, copy_function=MagicMock(side_effect=AssertionError("copy")))
            self.assertEqual((destination / "SKILL.md").read_text(), "ok")

    def test_scopes_are_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("private")
            reconcile(root / "user-a/agent-1", {"skill": str(source)})
            reconcile(root / "user-b/agent-1", {})
            self.assertFalse((root / "user-b/agent-1/skill").exists())
            reconcile(root / "user-a/agent-2", {})
            self.assertTrue((root / "user-a/agent-1/skill/SKILL.md").exists())

    def test_native_uses_persistent_installations_and_selected_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / "stage"
            (stage / ".claude/skills").mkdir(parents=True)
            commands = []
            plans = []
            def command(*args, **kwargs):
                commands.append(args)
                if args[0] == "python3":
                    plans.append(json.loads(Path(args[-1]).read_text()))
                return SimpleNamespace(returncode=0)
            with patch("sandbox.native.sys.platform", "linux"):
                sandbox = NativeSandbox()
            sandbox._run_root = command
            spec = {"directory": str(root / "release"),
                    "release": {"skill_id": 1, "release_id": 11, "version": "1.0", "content_sha256": "a" * 64}}
            sandbox._sync_managed_files(
                str(stage), str(root / "run"), [(spec, ".claude/skills/example")],
                skill_root=str(root / "persist"), skill_owner="user7", selected_names=["example"],
            )
            self.assertEqual(plans[0]["root"], str(root / "persist"))
            self.assertEqual(plans[0]["sources"], {"example": spec})
            self.assertIn(
                (
                    "cp",
                    str(stage / ".claude/.claude.json"),
                    str(root / "run/.claude/.claude.json"),
                ),
                commands,
            )
            self.assertIn(("ln", "-s", str(root / "persist/example"), str(root / "run/.claude/skills/example")), commands)
            self.assertFalse(any(args[0] == "cp" and str(root / "release") in args for args in commands))


class ChatEntrySyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = MagicMock()
        self.agent = SimpleNamespace(id=1)
        self.user = SimpleNamespace(user_id=7)
        self.workspace = SimpleNamespace(id=8)
        self.lease = AsyncMock()
        self.lease.commit_workspace = MagicMock(side_effect=lambda operation: (operation(), True)[1])
        self.provider = MagicMock()
        self.provider.sync_skill_installations.return_value = ["sample"]
        patches = [
            patch("agent_routes._get_agent_or_404", return_value=self.agent),
            patch("agent_routes.bind_agent_workspace", return_value=(self.workspace, None)),
            patch("agent_routes.acquire_agent_execution_lease", AsyncMock(return_value=self.lease)),
            patch("agent_routes.load_runtime_assets", return_value={"skills": ["sample"]}),
            patch("agent_routes.get_workspace_provider", return_value=self.provider),
        ]
        self.mocks = [item.start() for item in patches]
        for item in patches:
            self.addCleanup(item.stop)

    async def test_entry_reconciles_without_starting_runtime(self):
        result = await sync_agent_skill_installations(1, self.db, self.user)
        self.assertEqual(result, {"status": "synced", "skills": ["sample"]})
        self.provider.sync_skill_installations.assert_called_once()
        agent, workspace = self.provider.sync_skill_installations.call_args.args
        self.assertIsNot(agent, self.agent)
        self.assertIsNot(workspace, self.workspace)
        self.assertEqual(agent.runtime_skills, ["sample"])
        self.assertEqual(workspace.id, 8)
        self.assertEqual(self.agent.runtime_skills, ["sample"])
        self.lease.__aexit__.assert_awaited_once()

    async def test_busy_workspace_defers_without_touching_files(self):
        self.mocks[2].side_effect = asyncio.TimeoutError
        result = await sync_agent_skill_installations(1, self.db, self.user)
        self.assertEqual(result["status"], "deferred")
        self.provider.sync_skill_installations.assert_not_called()

    async def test_permission_denial_happens_before_sync(self):
        self.mocks[0].side_effect = HTTPException(403)
        with self.assertRaises(HTTPException) as error:
            await sync_agent_skill_installations(1, self.db, self.user)
        self.assertEqual(error.exception.status_code, 403)
        self.mocks[2].assert_not_called()
        self.provider.sync_skill_installations.assert_not_called()

    async def test_failure_releases_lease_and_returns_retryable_error(self):
        self.provider.sync_skill_installations.side_effect = RuntimeError("disk full")
        with patch("agent_routes.logger.exception"), self.assertRaises(HTTPException) as error:
            await sync_agent_skill_installations(1, self.db, self.user)
        self.assertEqual(error.exception.status_code, 503)
        self.db.rollback.assert_called_once()
        self.lease.__aexit__.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
