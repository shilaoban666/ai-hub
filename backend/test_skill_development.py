import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker

from asset_routes import (
    change_skill_release, get_skill_development_files, install_skill, list_available_skills, list_skill_catalog,
    rollback_skill, uninstall_skill,
    set_skill_development_mode,
)
from asset_runtime import load_runtime_assets
from asset_security import AssetPolicyError
from asset_schemas import SkillChangeReleaseRequest, SkillDevelopmentRequest, SkillInstallRequest
from auth import CurrentUser
from models import ExpertSkillBinding, Skill, SkillCollaborator, SkillInstallation, SkillRelease
from skill_installation import materialize
import test_global_skill_installation as global_fixture


class SkillDevelopmentTests(unittest.TestCase):
    def setUp(self):
        global_fixture.GlobalSkillInstallationTests.setUp(self)
        self.root = self.archive.parent / "workspace-skills"
        self.enterContext(patch("skill_utils.SKILLS_DIR", str(self.root)))
        self.enterContext(patch("asset_routes.RELEASES_DIR", str(self.archive.parent)))
        self.draft = self.root / "1"
        self.draft.mkdir(parents=True)
        (self.draft / "SKILL.md").write_text("# Draft one\n", encoding="utf-8")
        (self.draft / "asset.bin").write_bytes(b"\x00\xff\x01")
        self.agent = SimpleNamespace(id=7, user_id=7, kind="personal_default")

    def toggle(self, enabled=True, user=None):
        return set_skill_development_mode(
            1, SkillDevelopmentRequest(enabled=enabled), self.db, user or self.user,
        )

    def runtime(self, user_id=7, agent=None):
        result = load_runtime_assets(self.db, agent or self.agent, user_id, skills_only=True)
        return next(skill for skill in result["skills"] if skill.id == 1), result

    def use_latest(self, agent_id=None):
        return change_skill_release(
            1,
            SkillChangeReleaseRequest(use_latest=True, agent_id=agent_id),
            self.db,
            self.user,
        )

    def test_only_author_can_toggle_or_read_draft_including_admin_and_collaborator(self):
        self.db.add(SkillCollaborator(skill_id=1, user_id=8, username="colleague", created_by=7))
        self.db.commit()
        for user in (CurrentUser(8), self.admin):
            with self.assertRaises(HTTPException) as error:
                self.toggle(user=user)
            self.assertEqual(error.exception.status_code, 404)
            with self.assertRaises(HTTPException):
                get_skill_development_files(1, self.db, user)
        self.assertTrue(self.toggle()["development_mode"])
        preview = get_skill_development_files(1, self.db, self.user)
        self.assertEqual(preview["version"], "latest")

    def test_catalog_preference_is_only_returned_to_author(self):
        self.toggle()
        for user in (self.user, CurrentUser(8), self.admin):
            result = list_skill_catalog(db=self.db, current_user=user)
            item = next(row for row in result["items"] if row["skill_id"] == 1)
            self.assertEqual("development_mode" in item, user.user_id == 7)
        result = list_skill_catalog(db=self.db, current_user=self.admin, system_mode=True)
        self.assertTrue(all("development_mode" not in row for row in result["items"]))

    def test_new_unreleased_skill_is_visible_only_in_author_catalog(self):
        draft = Skill(
            id=3,
            user_id=7,
            name="Unreleased draft",
            version="1.0",
            is_public=False,
            development_mode=False,
        )
        self.db.add(draft)
        self.db.commit()

        owner_catalog = list_skill_catalog(db=self.db, current_user=self.user)
        self.assertIn(3, [item["skill_id"] for item in owner_catalog["items"]])
        owner_item = next(item for item in owner_catalog["items"] if item["skill_id"] == 3)
        self.assertEqual(owner_item["releases"], [])
        self.assertIsNone(owner_item["latest_release"])
        self.assertEqual(owner_item["latest_workspace"]["version"], "latest")
        self.assertTrue(owner_item["latest_workspace"]["installable"])
        self.assertTrue(owner_item["is_mine"])

        collaborator_catalog = list_skill_catalog(db=self.db, current_user=CurrentUser(8))
        self.assertNotIn(3, [item["skill_id"] for item in collaborator_catalog["items"]])

    def test_unreleased_skill_is_visible_in_author_custom_agent_catalog(self):
        self.db.add_all([
            Skill(id=3, user_id=7, name="Unreleased draft", version="1.0", is_public=False),
            SkillCollaborator(skill_id=3, user_id=8, username="colleague", created_by=7),
        ])
        self.db.commit()
        for user in (self.user, CurrentUser(8), self.admin):
            with self.subTest(user_id=user.user_id), patch(
                "agent_access.get_usable_agent",
                return_value=SimpleNamespace(id=99, user_id=user.user_id, kind="expert"),
            ):
                # Eligibility must be applied before count and pagination.
                catalog = list_skill_catalog(
                    db=self.db, current_user=user, agent_id=99, skill_id=3, limit=1,
                )
                self.assertEqual(catalog["total"], int(user.user_id == 7))
                self.assertEqual(len(catalog["items"]), catalog["total"])
                if user.user_id == 7:
                    item = catalog["items"][0]
                    self.assertIsNone(item["latest_release"])
                    self.assertEqual(item["releases"], [])
                    self.assertTrue(item["latest_workspace"]["installable"])
                    self.assertIsNone(item["user_installation"])
        catalog = list_skill_catalog(db=self.db, current_user=self.admin, system_mode=True, skill_id=3)
        self.assertEqual(catalog, {"total": 0, "items": []})

    def test_author_can_install_and_run_unreleased_skill_in_custom_agent(self):
        self.db.add(Skill(id=3, user_id=7, name="Workspace draft", version="1.0", is_public=False))
        self.db.commit()
        draft_dir = self.root / "3"
        draft_dir.mkdir(parents=True)
        (draft_dir / "SKILL.md").write_text("# Custom agent draft\n", encoding="utf-8")
        expert = SimpleNamespace(id=99, user_id=7, kind="expert")
        with patch("asset_routes._agent", return_value=expert), patch(
            "asset_routes.bind_agent_workspace", return_value=(SimpleNamespace(id=99), None)
        ):
            result = install_skill(SkillInstallRequest(skill_id=3, agent_id=99), self.db, self.user)
        installation = self.db.get(SkillInstallation, result["id"])
        self.assertEqual(installation.scope_agent_id, 99)
        self.assertEqual(installation.workspace_id, 99)
        self.assertEqual(result["version"], "latest")
        self.assertIsNotNone(self.db.query(ExpertSkillBinding).filter_by(
            agent_id=99, installation_id=result["id"],
        ).first())
        with patch("agent_access.get_usable_agent", return_value=expert):
            catalog = list_skill_catalog(
                db=self.db, current_user=self.user, agent_id=99, installed_only=True, skill_id=3,
            )
        self.assertEqual(catalog["total"], 1)
        self.assertTrue(catalog["items"][0]["development_mode"])
        self.assertEqual(catalog["items"][0]["user_installation"]["id"], result["id"])
        assets = load_runtime_assets(self.db, expert, 7, skills_only=True)
        self.assertEqual([(row["skill_id"], row["source"]) for row in assets["skill_snapshot"]], [(3, "workspace")])
        self.assertIn("Custom agent draft", assets["skills"][0].files)
        (draft_dir / "SKILL.md").write_text("# Updated agent draft\n", encoding="utf-8")
        assets = load_runtime_assets(self.db, expert, 7, skills_only=True)
        self.assertIn("Updated agent draft", assets["skills"][0].files)
        default_assets = load_runtime_assets(self.db, self.agent, 7, skills_only=True)
        self.assertNotIn(3, [row["skill_id"] for row in default_assets["skill_snapshot"]])
        with self.assertRaises(HTTPException) as error:
            install_skill(SkillInstallRequest(skill_id=3, agent_id=100), self.db, CurrentUser(8))
        self.assertEqual(error.exception.status_code, 404)

    def test_author_can_install_unreleased_skill_from_workspace(self):
        draft = Skill(
            id=3,
            user_id=7,
            name="Workspace draft",
            version="1.0",
            is_public=False,
        )
        self.db.add(draft)
        self.db.commit()
        draft_dir = self.root / "3"
        draft_dir.mkdir(parents=True)
        (draft_dir / "SKILL.md").write_text("# Workspace draft\n", encoding="utf-8")
        with patch("asset_routes.RELEASES_DIR", str(self.archive.parent)), patch(
            "asset_routes.ensure_user_workspace", return_value=(SimpleNamespace(id=70), None)
        ):
            result = install_skill(SkillInstallRequest(skill_id=3), self.db, self.user)
        self.assertEqual(result["skill_id"], 3)
        self.assertEqual(result["version"], "latest")
        self.assertEqual(self.db.query(SkillRelease).filter(SkillRelease.skill_id == 3).one().status, "workspace")
        self.assertTrue(self.db.get(Skill, 3).development_mode)
        with self.assertRaises(HTTPException):
            set_skill_development_mode(3, SkillDevelopmentRequest(enabled=False), self.db, self.user)
        uninstall_skill(result["id"], self.db, self.user)
        self.assertFalse(self.db.get(Skill, 3).development_mode)

    def test_saved_edits_binary_files_and_deletions_refresh_next_run(self):
        self.use_latest()
        first, result = self.runtime()
        snapshot = next(row for row in result["skill_snapshot"] if row["skill_id"] == 1)
        self.assertEqual((snapshot["source"], snapshot["version"], snapshot["release_id"]),
                         ("workspace", "latest", None))
        installed = self.root / "installed"
        materialize({"directory": first.cached_files_dir, "release": first.installation_release}, installed)
        self.assertEqual((installed / "asset.bin").read_bytes(), b"\x00\xff\x01")
        unchanged, _ = self.runtime()
        self.assertEqual(first.cached_files_dir, unchanged.cached_files_dir)
        (self.draft / "SKILL.md").write_text("# Draft two\n", encoding="utf-8")
        (self.draft / "asset.bin").unlink()
        (self.draft / "script.py").write_text("print('new')\n")
        second, _ = self.runtime()
        self.assertNotEqual(first.installation_release["content_sha256"], second.installation_release["content_sha256"])
        self.assertEqual((Path(first.cached_files_dir) / "SKILL.md").read_text(), "# Draft one\n")
        materialize({"directory": second.cached_files_dir, "release": second.installation_release}, installed)
        self.assertEqual((installed / "SKILL.md").read_text(), "# Draft two\n")
        self.assertTrue((installed / "script.py").is_file())
        self.assertFalse((installed / "asset.bin").exists())
        self.assertEqual(json.loads((installed / ".aihub-installed.json").read_text())["release"]["source"], "workspace")

    def test_debug_toggle_does_not_change_latest_selection_or_grants(self):
        original = self.db.get(SkillInstallation, 1)
        original_release_id = original.release_id
        original_grants = original.granted_capabilities
        (self.draft / "aihub-manifest.json").write_text('{"capabilities":["network_access"]}')
        self.use_latest()
        dev, _ = self.runtime()
        installed = self.root / "installed"
        materialize({"directory": dev.cached_files_dir, "release": dev.installation_release}, installed)
        self.toggle(False)
        release, _ = self.runtime()
        materialize({"directory": release.cached_files_dir, "release": release.installation_release}, installed)
        self.assertEqual(release.version, "1.0")
        self.assertEqual(original_release_id, 11)
        self.assertEqual(original_grants, "[]")
        self.assertIn("# Sample", (installed / "SKILL.md").read_text())
        self.assertFalse((installed / "asset.bin").exists())

    def test_other_users_and_public_agent_visitors_keep_published_files(self):
        self.use_latest()
        other, _ = self.runtime(8, SimpleNamespace(id=8, user_id=8, kind="personal_default"))
        self.assertEqual(other.version, "2.0")
        shared, _ = self.runtime(8, SimpleNamespace(
            id=7, user_id=7, kind="personal_default", execution_user_id=8,
        ))
        self.assertEqual(shared.version, "1.0")
        self.assertNotIn("Draft", shared.files)

    def test_global_installation_keeps_global_release_when_author_has_workspace_latest(self):
        global_install = global_fixture.GlobalSkillInstallationTests.install_global(self)
        own, _ = self.runtime()
        other, _ = self.runtime(8, SimpleNamespace(id=8, user_id=8, kind="personal_default"))
        self.assertEqual(own.version, "2.0")
        self.assertEqual(other.version, "2.0")
        self.assertEqual(global_install["release_id"], 12)

    def test_author_expert_binding_uses_draft(self):
        self.db.get(SkillInstallation, 1).scope_agent_id = 99
        self.db.add(ExpertSkillBinding(agent_id=99, installation_id=1))
        self.db.commit()
        self.use_latest(agent_id=99)
        own, _ = self.runtime(agent=SimpleNamespace(id=99, user_id=7, kind="expert"))
        self.assertEqual(own.version, "latest")

    def test_debug_mode_is_scoped_to_the_current_agent(self):
        self.db.add(SkillInstallation(
            id=4, user_id=7, workspace_id=7, scope_agent_id=99,
            skill_id=1, release_id=11, status="active", granted_capabilities="[]",
        ))
        self.db.add(ExpertSkillBinding(id=4, agent_id=99, installation_id=4))
        self.db.commit()
        expert = SimpleNamespace(id=99, user_id=7, kind="expert")
        with patch("asset_routes._agent", return_value=expert):
            enabled = set_skill_development_mode(
                1, SkillDevelopmentRequest(enabled=True, agent_id=99), self.db, self.user,
            )
        self.assertTrue(enabled["development_mode"])
        default_skill, _ = self.runtime()
        expert_skill, _ = self.runtime(agent=expert)
        self.assertEqual(default_skill.version, "1.0")
        self.assertEqual(expert_skill.version, "latest")
        with patch("asset_routes._agent", return_value=expert):
            disabled = set_skill_development_mode(
                1, SkillDevelopmentRequest(enabled=False, agent_id=99), self.db, self.user,
            )
        self.assertFalse(disabled["development_mode"])
        self.assertEqual(self.runtime()[0].version, "1.0")
        self.assertEqual(self.runtime(agent=expert)[0].version, "1.0")

    def test_replacing_workspace_release_cleans_previous_archive(self):
        with TemporaryDirectory() as releases_dir, patch("asset_routes.RELEASES_DIR", releases_dir):
            self.use_latest()
            first = next(Path(releases_dir).glob("*.zip"))
            (self.draft / "SKILL.md").write_text("# Draft two\n", encoding="utf-8")
            self.use_latest()
            archives = list(Path(releases_dir).glob("*.zip"))
            self.assertFalse(first.exists())
            self.assertEqual(len(archives), 1)
            self.assertTrue(archives[0].is_file())

    def test_workspace_archive_is_removed_when_initial_flush_fails(self):
        with patch.object(self.db, "flush", side_effect=RuntimeError("database write failed")):
            with self.assertRaisesRegex(RuntimeError, "database write failed"):
                self.toggle()
        self.assertEqual(list(self.archive.parent.glob("skill-1-workspace-*.zip")), [])
        self.assertEqual(self.db.get(SkillInstallation, 1).release_id, 11)
        self.assertEqual(self.db.query(SkillRelease).filter_by(status="workspace").count(), 0)

    def test_failed_workspace_changes_preserve_previous_archive_and_installation(self):
        self.use_latest()
        self.toggle(False)
        release = self.db.query(SkillRelease).filter_by(status="workspace").one()
        previous_archive = Path(release.file_path)
        previous_content = previous_archive.read_bytes()
        actions = {
            "toggle": self.toggle,
            "change": self.use_latest,
            "rollback": lambda: rollback_skill(1, self.db, self.user),
            "install": lambda: install_skill(SkillInstallRequest(skill_id=1), self.db, self.user),
        }
        for name, action in actions.items():
            with self.subTest(action=name), patch(
                "asset_routes.normalize_grants", side_effect=AssetPolicyError("policy rejected")
            ):
                with self.assertRaises((HTTPException, AssetPolicyError)):
                    action()
            self.assertEqual([path.resolve() for path in self.archive.parent.glob("skill-1-workspace-*.zip")],
                             [previous_archive])
            self.assertEqual(previous_archive.read_bytes(), previous_content)
            self.assertEqual(self.db.get(SkillInstallation, 1).release_id, 11)
            self.assertEqual(self.db.get(SkillRelease, release.id).file_path, str(previous_archive))

    def test_commit_failure_removes_new_archive_and_keeps_previous_archive(self):
        self.use_latest()
        release = self.db.query(SkillRelease).filter_by(status="workspace").one()
        old_path = Path(release.file_path)
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                self.toggle()
        self.assertEqual([path.resolve() for path in self.archive.parent.glob("skill-1-workspace-*.zip")], [old_path])
        self.assertEqual(self.db.get(SkillRelease, release.id).file_path, str(old_path))

    def test_response_failure_keeps_committed_workspace_archive(self):
        with patch("asset_routes._installation_payload", side_effect=RuntimeError("response failed")):
            with self.assertRaisesRegex(RuntimeError, "response failed"):
                self.use_latest()
        self.db.rollback()
        release = self.db.get(SkillRelease, self.db.get(SkillInstallation, 1).release_id)
        self.assertEqual(release.status, "workspace")
        self.assertTrue(Path(release.file_path).is_file())

    def test_workspace_preparation_does_not_commit_installation_early(self):
        with patch("asset_routes.ensure_user_workspace", return_value=(SimpleNamespace(id=70), None)) as prepare:
            with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
                with self.assertRaisesRegex(RuntimeError, "commit failed"):
                    install_skill(SkillInstallRequest(skill_id=1), self.db, self.user)
        prepare.assert_called_once_with(self.db, 7, commit=False)
        self.assertEqual(self.db.get(SkillInstallation, 1).release_id, 11)
        self.assertEqual(list(self.archive.parent.glob("skill-1-workspace-*.zip")), [])

    def test_skill_lock_precedes_workspace_lookup_and_uses_current_read(self):
        statements = []

        def capture(execution):
            statements.append(str(execution.statement.compile(dialect=mysql.dialect())))

        event.listen(self.db, "do_orm_execute", capture)
        try:
            self.toggle()
        finally:
            event.remove(self.db, "do_orm_execute", capture)
        workspace_lookup = next(i for i, sql in enumerate(statements)
                                if "FROM skill_releases" in sql and "skill_releases.version =" in sql)
        self.assertIn("FOR UPDATE", statements[workspace_lookup])
        self.assertTrue(any("FROM skills" in sql and "FOR UPDATE" in sql
                            for sql in statements[:workspace_lookup]))

    def test_replacement_refreshes_archive_metadata_changed_by_another_agent(self):
        self.toggle()
        stale_release = self.db.query(SkillRelease).filter_by(status="workspace").one()
        original_path = stale_release.file_path
        self.db.add(SkillInstallation(
            id=4, user_id=7, workspace_id=7, scope_agent_id=99,
            skill_id=1, release_id=11, status="active", granted_capabilities="[]",
        ))
        self.db.add(ExpertSkillBinding(id=4, agent_id=99, installation_id=4))
        self.db.commit()
        # Keep an ORM object loaded before the other request replaces its archive.
        self.assertEqual(stale_release.file_path, original_path)
        expert = SimpleNamespace(id=99, user_id=7, kind="expert")
        other = sessionmaker(bind=self.engine, autoflush=False)()
        try:
            with patch("asset_routes._agent", return_value=expert):
                set_skill_development_mode(
                    1, SkillDevelopmentRequest(enabled=True, agent_id=99), other, self.user,
                )
        finally:
            other.close()
        self.assertEqual(stale_release.file_path, original_path)
        self.toggle()
        self.assertEqual(self.db.query(SkillRelease).filter_by(status="workspace").count(), 1)
        self.assertEqual(len(list(self.archive.parent.glob("skill-1-workspace-*.zip"))), 1)
        self.assertEqual(self.db.get(SkillInstallation, 1).release_id,
                         self.db.get(SkillInstallation, 4).release_id)
        with patch("agent_access.get_usable_agent", return_value=expert):
            catalog = list_skill_catalog(db=self.db, current_user=self.user, agent_id=99)
        self.assertTrue(next(row for row in catalog["items"] if row["skill_id"] == 1)["development_mode"])

    def test_picker_shows_latest_only_for_author(self):
        self.use_latest()
        for user, expected in ((self.user, "latest"), (CurrentUser(8), "2.0")):
            rows = list_available_skills(self.db, user)["items"]
            self.assertEqual(next(row for row in rows if row["skill_id"] == 1)["version"], expected)

    def test_missing_draft_fails_instead_of_silently_using_release(self):
        self.use_latest()
        for path in self.draft.iterdir():
            path.unlink()
        with self.assertRaises(RuntimeError):
            self.runtime()
        self.toggle(False)
        with self.assertRaises(HTTPException) as error:
            self.toggle()
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(self.db.get(Skill, 1).development_mode)

    def test_symlink_in_workspace_is_rejected(self):
        (self.draft / "outside").symlink_to(self.archive)
        with self.assertRaises(HTTPException):
            self.toggle()


if __name__ == "__main__":
    unittest.main()
