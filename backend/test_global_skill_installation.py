import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi import HTTPException
from sqlalchemy import Integer, MetaData, create_engine
from sqlalchemy.orm import sessionmaker

from asset_routes import (
    change_skill_release, change_system_skill_release, install_skill,
    install_system_skill, list_skill_catalog, list_skill_installations,
    list_available_skills,
    download_catalog_skill_release, get_catalog_skill_release_files,
    rollback_skill, rollback_system_skill, uninstall_skill, uninstall_system_skill,
)
from asset_runtime import load_runtime_assets
from asset_schemas import SkillChangeReleaseRequest, SkillInstallRequest, SystemSkillInstallRequest
from auth import CurrentUser
from skill_utils import load_release_file_tree
from models import (
    AssetSecurityEvent, CredentialReference, ExpertMcpBinding, ExpertSkillBinding,
    McpConnection, McpDefinition, McpRevision, McpUserHeaders, Skill,
    SkillInstallation, SkillRelease, SystemSkillInstallation, SkillCollaborator,
)


class GlobalSkillInstallationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        for table in Skill.metadata.tables.values():
            table.to_metadata(metadata)
        for model in (
            Skill, SkillRelease, SkillInstallation, SystemSkillInstallation, SkillCollaborator,
            ExpertSkillBinding, AssetSecurityEvent, CredentialReference,
            McpDefinition, McpRevision, McpConnection, McpUserHeaders, ExpertMcpBinding,
        ):
            table = metadata.tables[model.__tablename__]
            # SQLite requires INTEGER for generated primary keys.
            if "id" in table.c:
                table.c.id.type = Integer()
            table.create(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.archive = Path(temp.name) / "skill.zip"
        archive_root = patch("skill_utils.RELEASES_DIR", temp.name)
        archive_root.start()
        self.addCleanup(archive_root.stop)
        cache_setting = patch("skill_release_cache.settings.skill_release_cache_root", str(Path(temp.name) / "cache"))
        cache_setting.start()
        self.addCleanup(cache_setting.stop)
        with ZipFile(self.archive, "w") as archive:
            archive.writestr("SKILL.md", "---\nname: sample\ndescription: Sample skill\n---\n# Sample\nRead documentation.\n")
        self.admin = CurrentUser(user_id=9, is_superuser=True)
        self.user = CurrentUser(user_id=7)
        self.db.add_all([
            Skill(id=1, user_id=7, name="Sample", version="2.0", is_public=True),
            Skill(id=2, user_id=7, name="Other", version="1.0", is_public=True),
        ])
        for release_id, skill_id, version in ((11, 1, "1.0"), (12, 1, "2.0"), (21, 2, "1.0")):
            self.db.add(SkillRelease(
                id=release_id, skill_id=skill_id, version=version,
                status="published", scan_status="passed", manifest_json='{"capabilities":[]}',
                file_path=str(self.archive), file_url="/releases/skill.zip",
            ))
        for row_id, user_id, skill_id, release_id in ((1, 7, 1, 11), (2, 8, 1, 12), (3, 7, 2, 21)):
            self.db.add(SkillInstallation(
                id=row_id, user_id=user_id, workspace_id=user_id, skill_id=skill_id,
                release_id=release_id, previous_release_id=12 if row_id == 1 else None,
                status="active", granted_capabilities="[]",
            ))
            if row_id == 3:
                self.db.add(ExpertSkillBinding(id=row_id, agent_id=user_id, installation_id=row_id))
        self.db.commit()
        sandbox = patch("asset_routes.configured_sandbox_type", return_value="docker")
        sandbox.start()
        self.addCleanup(sandbox.stop)

    def install_global(self, release_id=12):
        return install_system_skill(
            SystemSkillInstallRequest(release_id=release_id), db=self.db, current_user=self.admin,
        )

    def prepare_legacy_scan_failure(self, release_id=12):
        with ZipFile(self.archive, "a") as archive:
            archive.writestr("aihub-manifest.json", '{"capabilities":["network_access"],"network_domains":[]}')
            archive.writestr("scripts/run.py", "import requests\nrequests.get(target)\n")
        release = self.db.get(SkillRelease, release_id)
        release.status = "rejected"
        release.scan_status = "failed"
        release.scan_report_json = '{"errors":["network_access requires at least one network_domains entry"]}'
        self.db.commit()
        return release

    def test_failed_scan_release_can_be_listed_downloaded_installed_and_run(self):
        self.prepare_legacy_scan_failure()
        catalog = list_skill_catalog(db=self.db, current_user=CurrentUser(user_id=42))
        item = next(row for row in catalog["items"] if row["skill_id"] == 1)
        release = next(row for row in item["releases"] if row["id"] == 12)
        self.assertTrue(release["installable"])
        self.assertIsNone(release["unavailable_reason"])
        self.assertNotIn("scan_status", release)
        self.assertNotIn("scan_report", release)
        self.assertEqual(download_catalog_skill_release(12, db=self.db, current_user=CurrentUser(user_id=42)).status_code, 200)
        with patch("asset_routes.ensure_user_workspace", return_value=(SimpleNamespace(id=42), None)):
            result = install_skill(SkillInstallRequest(release_id=12), db=self.db, current_user=CurrentUser(user_id=42))
        self.assertEqual(result["status"], "active")
        assets = load_runtime_assets(self.db, SimpleNamespace(id=42, kind="personal_default"), 42)
        self.assertEqual([row["release_id"] for row in assets["skill_snapshot"]], [12])
        self.assertEqual(self.db.query(AssetSecurityEvent).filter(AssetSecurityEvent.action.in_(["scanned", "scan_failed"])).count(), 0)

    def test_failed_scan_release_can_be_installed_globally_without_catalog_visit(self):
        self.prepare_legacy_scan_failure()
        result = self.install_global()
        self.assertEqual(result["release_id"], 12)
        self.assertEqual(self.db.get(SkillRelease, 12).status, "published")

    def test_installed_scan_rejection_can_run_without_catalog_visit(self):
        self.prepare_legacy_scan_failure(11)
        assets = load_runtime_assets(self.db, SimpleNamespace(id=7, kind="personal_default"), 7)
        self.assertIn(11, [row["release_id"] for row in assets["skill_snapshot"]])

    def test_new_release_with_network_code_without_domains_is_published(self):
        import asyncio
        from schemas import SkillReleaseCreate
        with patch("sqlalchemy.schema.MetaData.create_all"):
            import main
        tree = [
            {"type": "file", "label": "SKILL.md", "path": "SKILL.md", "content": "# Skill"},
            {"type": "file", "label": "run.py", "path": "run.py", "content": "import requests; requests.get(target)"},
            {"type": "file", "label": "aihub-manifest.json", "path": "aihub-manifest.json", "content": '{"capabilities":["network_access"]}'},
        ]
        with patch.object(main, "load_skill_files", return_value=tree), patch.object(main, "RELEASES_DIR", str(self.archive.parent)):
            release = asyncio.run(main.release_skill(1, SkillReleaseCreate(version="3.0"), db=self.db, current_user=self.user))
        self.assertEqual(release.status, "published")
        self.assertEqual(release.scan_status, "not_required")
        self.assertIsNone(release.scan_report_json)
        public = main.get_public_skill_releases(1, db=self.db)
        self.assertIn(release.id, [item.id for item in public])

    def test_owner_history_recovers_old_scan_failure_without_catalog_visit(self):
        self.prepare_legacy_scan_failure()
        with patch("sqlalchemy.schema.MetaData.create_all"):
            import main
        result = main.get_skill_releases(1, db=self.db, current_user=self.user)
        release = next(item for item in result if item.id == 12)
        self.assertEqual(release.status, "published")

    def test_public_history_recovers_old_scan_failure_without_catalog_visit(self):
        self.prepare_legacy_scan_failure()
        with patch("sqlalchemy.schema.MetaData.create_all"):
            import main
        result = main.get_public_skill_releases(1, db=self.db)
        release = next(item for item in result if item.id == 12)
        self.assertEqual(release.status, "published")

    def test_private_collaborator_can_preview_download_install_and_loses_access_when_removed(self):
        self.db.get(Skill, 1).is_public = False
        collaborator = CurrentUser(user_id=42)
        self.db.add(SkillCollaborator(skill_id=1, user_id=42, username='collaborator', created_by=7))
        self.db.commit()
        result = get_catalog_skill_release_files(12, db=self.db, current_user=collaborator)
        self.assertEqual(result['skill_id'], 1)
        self.assertEqual(download_catalog_skill_release(12, db=self.db, current_user=collaborator).status_code, 200)
        with patch('asset_routes.ensure_user_workspace', return_value=(SimpleNamespace(id=42), None)):
            installed = install_skill(SkillInstallRequest(release_id=12), db=self.db, current_user=collaborator)
        self.assertEqual(installed['skill_id'], 1)
        catalog = list_skill_catalog(source='collaboration', db=self.db, current_user=collaborator)
        self.assertIsNotNone(catalog['items'][0]['user_installation'])
        self.db.query(SkillCollaborator).filter(SkillCollaborator.user_id == 42).delete()
        self.db.commit()
        for user in (collaborator, CurrentUser(user_id=43)):
            for action in (get_catalog_skill_release_files, download_catalog_skill_release):
                with self.assertRaises(HTTPException) as error:
                    action(12, db=self.db, current_user=user)
                self.assertEqual(error.exception.status_code, 404)
            with self.assertRaises(HTTPException) as error:
                install_skill(SkillInstallRequest(release_id=12), db=self.db, current_user=user)
            self.assertEqual(error.exception.status_code, 404)

    def test_catalog_counts_active_personal_users_separately_from_downloads(self):
        self.db.get(SkillInstallation, 2).status = "uninstalled"
        self.db.get(Skill, 1).install_count = 12
        self.db.add_all([
            AssetSecurityEvent(asset_type="skill", asset_id=1, action="downloaded", actor_user_id=7),
            AssetSecurityEvent(asset_type="skill", asset_id=1, action="downloaded", actor_user_id=8),
            AssetSecurityEvent(asset_type="skill", asset_id=1, action="installed", actor_user_id=7),
            AssetSecurityEvent(asset_type="skill_release", asset_id=1, action="downloaded", actor_user_id=7),
        ])
        self.db.commit()
        result = list_skill_catalog(db=self.db, current_user=self.user)
        item = next(row for row in result["items"] if row["skill_id"] == 1)
        self.assertEqual(item["installed_user_count"], 1)
        self.assertEqual(item["download_count"], 2)
        self.assertEqual(item["install_count"], 12)
        self.install_global()
        item = list_skill_catalog(source="system_default", db=self.db, current_user=self.user)["items"][0]
        self.assertEqual(item["installed_user_count"], 0)
        self.assertIsNotNone(item["system_installation"])

    def test_market_download_returns_archive_and_counts_across_releases(self):
        for release_id in (11, 12):
            response = download_catalog_skill_release(release_id, db=self.db, current_user=self.user)
            self.assertEqual(Path(response.path).read_bytes(), self.archive.read_bytes())
            self.assertEqual(response.media_type, "application/zip")
            self.assertEqual(response.headers["cache-control"], "no-store")
        result = list_skill_catalog(db=self.db, current_user=self.user)
        item = next(row for row in result["items"] if row["skill_id"] == 1)
        self.assertEqual(item["download_count"], 2)
        self.assertEqual(item["install_count"], 0)
        self.assertEqual(item["installed_user_count"], 2)

    def test_market_file_preview_reads_requested_release_without_counting_downloads(self):
        newer_archive = self.archive.parent / "newer.zip"
        with ZipFile(newer_archive, "w") as archive:
            archive.writestr("sample/SKILL.md", "---\nname: sample\ndescription: Updated skill\n---\n# Updated\n")
            archive.writestr("sample/docs/guide.md", "# Version 2 guide\n")
        self.db.get(SkillRelease, 12).file_path = str(newer_archive)
        self.db.commit()

        old = get_catalog_skill_release_files(11, db=self.db, current_user=self.user)
        new = get_catalog_skill_release_files(12, db=self.db, current_user=CurrentUser(user_id=42))
        self.assertEqual((old["release_id"], old["version"]), (11, "1.0"))
        self.assertEqual((new["skill_id"], new["version"]), (1, "2.0"))
        self.assertIn("# Sample", old["files"][0]["content"])
        skill_file = next(node for node in new["files"] if node["label"] == "SKILL.md")
        self.assertIn("# Updated", skill_file["content"])
        folder = next(node for node in new["files"] if node["label"] == "docs")
        self.assertEqual(folder["children"][0]["path"], "docs/guide.md")
        self.assertEqual(folder["children"][0]["content"], "# Version 2 guide\n")
        self.assertEqual(self.db.query(AssetSecurityEvent).filter_by(action="downloaded").count(), 0)

    def test_market_file_preview_rejects_inaccessible_releases(self):
        skill = self.db.get(Skill, 1)
        release = self.db.get(SkillRelease, 12)
        for field, obj, value, status in (
            ("is_public", skill, False, 404),
            ("is_deleted", skill, True, 404),
            ("file_path", release, str(self.archive.parent / "missing.zip"), 409),
        ):
            original = getattr(obj, field)
            original_url = release.file_url
            if field == "file_path":
                release.file_url = "/releases/missing.zip"
            setattr(obj, field, value)
            self.db.commit()
            with self.subTest(field=field), self.assertRaises(HTTPException) as error:
                get_catalog_skill_release_files(12, db=self.db, current_user=CurrentUser(user_id=42))
            self.assertEqual(error.exception.status_code, status)
            setattr(obj, field, original)
            release.file_url = original_url
            self.db.commit()

        skill.is_public = False
        self.db.commit()
        # Owners retain access to their private releases.
        result = get_catalog_skill_release_files(12, db=self.db, current_user=self.user)
        self.assertTrue(result["files"])

    def test_preview_all_release_states_without_scanning_or_mutation(self):
        release = self.db.get(SkillRelease, 12)
        for status in ("draft", "pending_review", "rejected", "revoked", "published"):
            release.status = status
            release.scan_status = "failed"
            release.scan_report_json = '{"status":"failed"}'
            self.db.commit()
            with self.subTest(status=status):
                result = get_catalog_skill_release_files(12, db=self.db, current_user=CurrentUser(user_id=42))
                self.assertIn("# Sample", result["files"][0]["content"])
                self.assertFalse(self.db.dirty)
                self.db.refresh(release)
                self.assertEqual(release.status, status)
                self.assertEqual(release.scan_status, "failed")
                self.assertEqual(release.scan_report_json, '{"status":"failed"}')
        self.assertEqual(self.db.query(AssetSecurityEvent).count(), 0)

    def test_install_and_materialize_release_without_root_skill_md(self):
        from agent_workspace import install_skills

        for entry in ("sample/README.md", "sample/nested/SKILL.md", "sample/skill.md"):
            with self.subTest(entry=entry):
                with ZipFile(self.archive, "w") as archive:
                    archive.writestr(entry, "# Legacy release content")
                    archive.writestr("sample/scripts/example.py", "print('example')")
                result = get_catalog_skill_release_files(12, db=self.db, current_user=self.user)
                self.assertTrue(result["files"])
                self.assertIn("Legacy release content", json.dumps(result["files"]))
                self.assertEqual(load_release_file_tree(str(self.archive)), result["files"])
                # Each subtest represents a different immutable release archive.
                for release in self.db.query(SkillRelease).all():
                    release.content_sha256 = None
                self.db.commit()
                outsider = CurrentUser(user_id=42)
                with patch("asset_routes.ensure_user_workspace", return_value=(SimpleNamespace(id=42), None)):
                    installed = install_skill(SkillInstallRequest(release_id=12), db=self.db, current_user=outsider)
                self.assertEqual(installed["status"], "active")
                personal = load_runtime_assets(self.db, SimpleNamespace(id=42, kind="personal_default"), 42, skills_only=True)
                self.assertEqual(personal["skill_snapshot"][0]["source"], "user")
                self.assertEqual(self.install_global()["status"], "active")
                assets = load_runtime_assets(self.db, SimpleNamespace(id=42, kind="personal_default"), 42, skills_only=True)
                self.assertEqual(assets["skill_snapshot"][0]["source"], "system_default")
                with TemporaryDirectory() as workspace:
                    install_skills(workspace, assets["skills"])
                    for directory in (".claude/skills",):
                        root = Path(workspace) / directory / "Sample"
                        self.assertEqual((root / entry.split("/", 1)[1]).read_text(), "# Legacy release content")
                        self.assertEqual((root / "scripts/example.py").read_text(), "print('example')")
                uninstall_system_skill(1, db=self.db, current_user=self.admin)

    def test_preview_still_rejects_unsafe_or_corrupt_archives(self):
        for entry in ("../secret.txt", "/secret.txt", "C:/secret.txt"):
            with self.subTest(entry=entry):
                with ZipFile(self.archive, "w") as archive:
                    archive.writestr(entry, "invalid path")
                with self.assertRaises(HTTPException) as error:
                    get_catalog_skill_release_files(12, db=self.db, current_user=self.user)
                self.assertEqual(error.exception.status_code, 409)
        self.archive.write_bytes(b"not a zip archive")
        with self.assertRaises(HTTPException) as error:
            get_catalog_skill_release_files(12, db=self.db, current_user=self.user)
        self.assertEqual(error.exception.status_code, 409)

    def test_market_download_rejects_private_deleted_revoked_and_missing_releases_without_counting(self):
        skill = self.db.get(Skill, 1)
        release = self.db.get(SkillRelease, 12)
        outsider = CurrentUser(user_id=42)
        for field, obj, value, status in (
            ("is_public", skill, False, 404),
            ("is_deleted", skill, True, 404),
            ("status", release, "revoked", 409),
            ("file_path", release, str(self.archive.parent / "missing.zip"), 409),
        ):
            original = getattr(obj, field)
            original_url = release.file_url
            if field == "file_path":
                release.file_url = "/releases/missing.zip"
            setattr(obj, field, value)
            self.db.commit()
            with self.subTest(field=field), self.assertRaises(HTTPException) as error:
                download_catalog_skill_release(12, db=self.db, current_user=outsider)
            self.assertEqual(error.exception.status_code, status)
            setattr(obj, field, original)
            release.file_url = original_url
            self.db.commit()
        self.assertEqual(self.db.query(AssetSecurityEvent).filter_by(action="downloaded").count(), 0)

    def test_personal_install_count_tracks_successful_installs_not_updates(self):
        user = CurrentUser(user_id=42)
        skill = self.db.get(Skill, 1)
        updated_at = skill.updated_at
        with patch("asset_routes.ensure_user_workspace", return_value=(SimpleNamespace(id=42), None)):
            installed = install_skill(SkillInstallRequest(release_id=11), db=self.db, current_user=user)
            self.assertEqual(skill.install_count, 1)
            self.assertEqual(skill.updated_at, updated_at)
            install_skill(SkillInstallRequest(release_id=11), db=self.db, current_user=user)
            change_skill_release(installed["id"], SkillChangeReleaseRequest(release_id=12), db=self.db, current_user=user)
            rollback_skill(installed["id"], db=self.db, current_user=user)
            self.assertEqual(skill.install_count, 1)
            uninstall_skill(installed["id"], db=self.db, current_user=user)
            self.assertEqual(skill.install_count, 1)
            install_skill(SkillInstallRequest(release_id=12), db=self.db, current_user=user)
            self.assertEqual(skill.install_count, 2)
        catalog = list_skill_catalog(db=self.db, current_user=self.user)
        counts = {row["skill_id"]: row["install_count"] for row in catalog["items"]}
        self.assertEqual(counts, {1: 2, 2: 0})

    def test_global_install_count_is_shared_and_survives_uninstall(self):
        skill = self.db.get(Skill, 1)
        skill.install_count = 2  # Preserved historical personal installations.
        self.db.commit()
        installed = self.install_global()
        self.assertEqual(skill.install_count, 3)
        self.install_global()
        change_system_skill_release(installed["id"], SkillChangeReleaseRequest(release_id=11), db=self.db, current_user=self.admin)
        rollback_system_skill(installed["id"], db=self.db, current_user=self.admin)
        self.assertEqual(skill.install_count, 3)
        uninstall_system_skill(installed["id"], db=self.db, current_user=self.admin)
        self.assertEqual(skill.install_count, 3)
        self.install_global()
        self.assertEqual(skill.install_count, 4)

    def test_failed_personal_install_does_not_increment_count(self):
        with patch("asset_routes.ensure_user_workspace", return_value=(SimpleNamespace(id=42), None)):
            with patch("asset_routes._agent", side_effect=HTTPException(status_code=404)):
                with self.assertRaises(HTTPException):
                    install_skill(SkillInstallRequest(release_id=11, agent_id=999), db=self.db, current_user=CurrentUser(user_id=42))
        self.db.rollback()
        self.assertEqual(self.db.get(Skill, 1).install_count, 0)
        self.assertIsNone(self.db.query(SkillInstallation).filter_by(user_id=42).first())

    def test_catalog_ownership_and_public_visibility_are_independent(self):
        self.db.get(Skill, 2).is_public = False
        for skill_id, is_public, is_deleted in ((3, True, False), (4, False, False), (5, True, True)):
            self.db.add(Skill(
                id=skill_id, user_id=8, name=f"Skill {skill_id}", version="1.0",
                is_public=is_public, is_deleted=is_deleted,
            ))
            self.db.add(SkillRelease(
                id=skill_id * 10, skill_id=skill_id, version="1.0",
                status="published", scan_status="passed", manifest_json='{"capabilities":[]}',
                file_path=str(self.archive), file_url="/releases/skill.zip",
            ))
        self.db.commit()

        for source, expected_ids in (
            ("all", {1, 2, 3}), ("mine", {1, 2}),
            ("public", {1, 3}), ("enterprise", {1, 3}),
        ):
            with self.subTest(source=source):
                catalog = list_skill_catalog(source=source, db=self.db, current_user=self.user)
                self.assertEqual(catalog["total"], len(expected_ids))
                self.assertEqual({item["skill_id"] for item in catalog["items"]}, expected_ids)
                for item in catalog["items"]:
                    self.assertEqual(item["is_mine"], item["skill_id"] in {1, 2})
                    self.assertEqual(item["is_public"], item["skill_id"] in {1, 3})

        catalog = list_skill_catalog(q="Sample", source="public", db=self.db, current_user=self.user)
        self.assertEqual([item["skill_id"] for item in catalog["items"]], [1])

    def test_system_catalog_requires_public_even_for_mine_filter(self):
        self.db.get(Skill, 1).user_id = self.admin.user_id
        self.db.get(Skill, 2).user_id = self.admin.user_id
        self.db.get(Skill, 2).is_public = False
        self.db.commit()
        for source in ("all", "mine", "public"):
            with self.subTest(source=source):
                catalog = list_skill_catalog(
                    source=source, system_mode=True, db=self.db, current_user=self.admin,
                )
                self.assertEqual([item["skill_id"] for item in catalog["items"]], [1])
                self.assertTrue(catalog["items"][0]["is_mine"])
                self.assertTrue(catalog["items"][0]["is_public"])

    def test_global_catalog_filter_preserves_ownership_and_public_labels(self):
        self.install_global()
        catalog = list_skill_catalog(source="system_default", db=self.db, current_user=self.user)
        self.assertEqual([item["skill_id"] for item in catalog["items"]], [1])
        self.assertTrue(catalog["items"][0]["is_mine"])
        self.assertTrue(catalog["items"][0]["is_public"])
        self.assertIsNotNone(catalog["items"][0]["system_installation"])

    def assert_personal_copies_removed(self):
        rows = self.db.query(SkillInstallation).order_by(SkillInstallation.id).all()
        self.assertEqual([row.status for row in rows], ["uninstalled", "uninstalled", "active"])
        self.assertEqual([row.release_id for row in rows], [11, 12, 21])
        self.assertEqual([row.installation_id for row in self.db.query(ExpertSkillBinding).all()], [3])

    def test_global_install_replaces_only_workbench_versions(self):
        result = self.install_global()
        self.assertEqual(result["release_id"], 12)
        self.assert_personal_copies_removed()
        event = self.db.query(AssetSecurityEvent).one()
        self.assertEqual(json.loads(event.details_json)["personal_installations_removed"], 2)
        personal = list_skill_installations(db=self.db, current_user=self.user)
        self.assertEqual([item["skill_id"] for item in personal["items"]], [2])
        catalog = list_skill_catalog(db=self.db, current_user=self.user)
        skill = next(item for item in catalog["items"] if item["skill_id"] == 1)
        self.assertIsNone(skill["user_installation"])
        self.assertEqual(skill["effective_release_id"], 12)
        for kind in ("personal_default",):
            assets = load_runtime_assets(self.db, SimpleNamespace(id=7, kind=kind), 7)
            snapshots = [item for item in assets["skill_snapshot"] if item["skill_id"] == 1]
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0]["release_id"], 12)
            self.assertEqual(snapshots[0]["source"], "system_default")
            runtime_skill = next(item for item in assets["skills"] if item.id == 1)
            self.assertEqual(runtime_skill.installation_release, {
                key: snapshots[0][key] for key in ("skill_id", "release_id", "version", "content_sha256")
            })

    def test_personal_install_change_and_rollback_cannot_override_global(self):
        self.install_global()
        operations = [
            lambda: install_skill(SkillInstallRequest(release_id=11), db=self.db, current_user=self.user),
            lambda: install_skill(SkillInstallRequest(release_id=12), db=self.db, current_user=self.user),
            lambda: change_skill_release(1, SkillChangeReleaseRequest(release_id=12), db=self.db, current_user=self.user),
            lambda: rollback_skill(1, db=self.db, current_user=self.user),
        ]
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(HTTPException) as error:
                    operation()
                self.assertEqual(error.exception.status_code, 409)
                self.assertIn("已全局安装", error.exception.detail)
                self.db.rollback()
                self.assert_personal_copies_removed()

    def test_uninstall_global_does_not_restore_personal_versions(self):
        result = self.install_global()
        uninstall_system_skill(result["id"], db=self.db, current_user=self.admin)
        self.assert_personal_copies_removed()
        catalog = list_skill_catalog(db=self.db, current_user=self.user)
        skill = next(item for item in catalog["items"] if item["skill_id"] == 1)
        self.assertIsNone(skill["effective_release_id"])
        with patch("asset_routes.ensure_user_workspace", return_value=(SimpleNamespace(id=7), None)):
            personal = install_skill(SkillInstallRequest(release_id=11), db=self.db, current_user=self.user)
        self.assertEqual(personal["status"], "active")
        self.assertEqual(personal["release_id"], 11)

    def test_expert_does_not_inherit_global_and_keeps_its_version_through_global_changes(self):
        expert = SimpleNamespace(id=7, kind="expert")
        self.db.add(ExpertSkillBinding(id=1, agent_id=7, installation_id=1))
        self.db.get(SkillInstallation, 1).scope_agent_id = 7
        self.db.get(SkillInstallation, 3).scope_agent_id = 7
        self.db.commit()
        installed = self.install_global()
        for operation in (
            lambda: None,
            lambda: change_system_skill_release(installed["id"], SkillChangeReleaseRequest(release_id=11), db=self.db, current_user=self.admin),
            lambda: rollback_system_skill(installed["id"], db=self.db, current_user=self.admin),
            lambda: uninstall_system_skill(installed["id"], db=self.db, current_user=self.admin),
        ):
            operation()
            assets = load_runtime_assets(self.db, expert, 7)
            self.assertEqual({row["release_id"] for row in assets["skill_snapshot"]}, {11, 21})
            self.assertTrue(all(row["source"] == "user" for row in assets["skill_snapshot"]))
            self.assertEqual(load_runtime_assets(self.db, SimpleNamespace(id=99, kind="expert"), 7)["skills"], [])
        self.assertEqual(self.db.get(SkillInstallation, 1).status, "active")
        self.assertEqual(self.db.query(ExpertSkillBinding).filter_by(installation_id=1).count(), 1)

    def test_expert_can_install_and_upgrade_a_globally_installed_skill(self):
        self.install_global()
        expert = SimpleNamespace(id=99, user_id=7, kind="expert")
        with patch("asset_routes._agent", return_value=expert), patch("agent_access.get_usable_agent", return_value=expert), patch(
            "asset_routes.bind_agent_workspace", return_value=(SimpleNamespace(id=99), None),
        ):
            empty = list_skill_catalog(agent_id=99, db=self.db, current_user=self.user)
            sample = next(item for item in empty["items"] if item["skill_id"] == 1)
            self.assertIsNone(sample["system_installation"])
            self.assertIsNone(sample["user_installation"])
            installed = install_skill(SkillInstallRequest(release_id=11, agent_id=99), db=self.db, current_user=self.user)
            catalog = list_skill_catalog(agent_id=99, db=self.db, current_user=self.user)
            sample = next(item for item in catalog["items"] if item["skill_id"] == 1)
            self.assertEqual(sample["effective_release_id"], 11)
        change_skill_release(installed["id"], SkillChangeReleaseRequest(release_id=12, agent_id=99), db=self.db, current_user=self.user)
        rollback_skill(installed["id"], db=self.db, current_user=self.user, agent_id=99)
        assets = load_runtime_assets(self.db, expert, 7)
        self.assertEqual([row["release_id"] for row in assets["skill_snapshot"]], [11])
        self.assertEqual(self.db.get(SystemSkillInstallation, 1).release_id, 12)

    def seed_legacy_global(self):
        self.db.add(SystemSkillInstallation(
            id=1, skill_id=1, release_id=12, previous_release_id=11,
            created_by=9, status="active", granted_capabilities="[]",
        ))
        self.db.commit()

    def test_global_reinstall_cleans_legacy_personal_copies(self):
        self.seed_legacy_global()
        self.install_global()
        self.assert_personal_copies_removed()

    def test_global_upgrade_cleans_legacy_personal_copies(self):
        self.seed_legacy_global()
        result = change_system_skill_release(
            1, SkillChangeReleaseRequest(release_id=11), db=self.db, current_user=self.admin,
        )
        self.assertEqual(result["release_id"], 11)
        self.assert_personal_copies_removed()

    def test_global_rollback_cleans_legacy_personal_copies(self):
        self.seed_legacy_global()
        result = rollback_system_skill(1, db=self.db, current_user=self.admin)
        self.assertEqual(result["release_id"], 11)
        self.assert_personal_copies_removed()

    def test_global_uninstall_cleans_legacy_personal_copies(self):
        self.seed_legacy_global()
        uninstall_system_skill(1, db=self.db, current_user=self.admin)
        self.assert_personal_copies_removed()

    def test_failed_global_install_rolls_back_personal_cleanup(self):
        with patch("asset_routes.audit_asset", side_effect=RuntimeError("Audit failed")):
            with self.assertRaises(RuntimeError):
                self.install_global()
        self.db.rollback()
        self.assertEqual(self.db.get(Skill, 1).install_count, 0)
        self.assertEqual(self.db.query(SystemSkillInstallation).count(), 0)
        self.assertEqual(self.db.query(SkillInstallation).filter_by(status="active").count(), 3)
        self.assertEqual(self.db.query(ExpertSkillBinding).count(), 1)

    def test_invalid_archive_does_not_remove_personal_installations(self):
        self.archive.unlink()
        with self.assertRaises(HTTPException) as error:
            self.install_global()
        self.assertEqual(error.exception.status_code, 409)
        self.db.rollback()
        self.assertEqual(self.db.query(SystemSkillInstallation).count(), 0)
        self.assertEqual(self.db.query(SkillInstallation).filter_by(status="active").count(), 3)
        self.assertEqual(self.db.query(ExpertSkillBinding).count(), 1)

    def test_private_global_install_rejected_even_for_the_owner(self):
        for owner in (7, self.admin.user_id):
            with self.subTest(owner=owner):
                skill = self.db.get(Skill, 1)
                skill.user_id = owner
                skill.is_public = False
                self.db.commit()
                with self.assertRaises(HTTPException) as error:
                    self.install_global()
                self.assertEqual(error.exception.status_code, 409)
                self.assertIn("仅支持公开技能", error.exception.detail)
                self.db.rollback()
                self.assertEqual(self.db.query(SystemSkillInstallation).count(), 0)
                self.assertEqual(self.db.query(SkillInstallation).filter_by(status="active").count(), 3)

    def test_legacy_private_global_cannot_upgrade_or_rollback(self):
        self.seed_legacy_global()
        self.db.get(Skill, 1).is_public = False
        self.db.commit()
        for operation in (
            lambda: change_system_skill_release(1, SkillChangeReleaseRequest(release_id=11), db=self.db, current_user=self.admin),
            lambda: rollback_system_skill(1, db=self.db, current_user=self.admin),
        ):
            with self.assertRaises(HTTPException) as error:
                operation()
            self.assertEqual(error.exception.status_code, 409)
            self.db.rollback()
            self.assertEqual(self.db.get(SystemSkillInstallation, 1).release_id, 12)
        uninstall_system_skill(1, db=self.db, current_user=self.admin)
        self.assertEqual(self.db.get(SystemSkillInstallation, 1).status, "uninstalled")

    def test_runtime_does_not_load_legacy_private_global_skills(self):
        self.seed_legacy_global()
        self.db.get(Skill, 1).is_public = False
        self.db.commit()
        for kind in ("personal_default", "expert"):
            assets = load_runtime_assets(self.db, SimpleNamespace(id=42, kind=kind), 42)
            self.assertEqual(assets["skill_snapshot"], [])


    def test_private_foreign_installation_is_hidden_from_runtime_and_pickers(self):
        self.db.add(Skill(id=3, user_id=8, name="Private foreign", version="1.0", is_public=False))
        self.db.add(SkillRelease(
            id=31, skill_id=3, version="1.0", status="published", scan_status="passed",
            manifest_json='{"capabilities":[]}', file_path=str(self.archive), file_url="/releases/skill.zip",
        ))
        self.db.add(SkillInstallation(
            id=4, user_id=7, workspace_id=7, skill_id=3, release_id=31,
            status="active", granted_capabilities="[]",
        ))
        self.db.commit()

        runtime = load_runtime_assets(self.db, SimpleNamespace(id=7, kind="personal_default"), 7)
        self.assertNotIn(3, [row["skill_id"] for row in runtime["skill_snapshot"]])
        self.assertNotIn(3, [item["skill_id"] for item in list_available_skills(self.db, self.user)["items"]])
        self.assertNotIn(4, [item["id"] for item in list_skill_installations(self.db, self.user)["items"]])

    def test_warm_cache_does_not_keep_uninstalled_or_revoked_skills_active(self):
        result = self.install_global()
        agent = SimpleNamespace(id=42, kind="personal_default")
        first = load_runtime_assets(self.db, agent, 42)
        self.assertEqual([row["release_id"] for row in first["skill_snapshot"]], [12])
        with patch("skill_release_cache.load_release_file_tree", side_effect=AssertionError("unexpected unpack")):
            self.db.get(SkillRelease, 12).status = "revoked"
            self.db.commit()
            self.assertEqual(load_runtime_assets(self.db, agent, 42)["skills"], [])
            self.db.get(SkillRelease, 12).status = "published"
            self.db.commit()
            uninstall_system_skill(result["id"], db=self.db, current_user=self.admin)
            self.assertEqual(load_runtime_assets(self.db, agent, 42)["skills"], [])

    def test_installed_market_picker_and_workspace_follow_the_same_access(self):
        from agent_workspace import install_skills

        agent = SimpleNamespace(id=7, kind="personal_default")
        # Visible but uninstalled skills must never become available automatically.
        self.db.add(Skill(id=3, user_id=7, name="Uninstalled", version="1", is_public=False))
        self.db.add(SkillRelease(
            id=31, skill_id=3, version="1", status="published",
            file_path=str(self.archive), file_url="/releases/skill.zip",
        ))
        self.db.get(Skill, 1).user_id = 8
        self.db.commit()

        with TemporaryDirectory() as root:
            user_file = Path(root) / "report.txt"
            user_file.write_text("keep", encoding="utf-8")

            def check(expected):
                market = list_skill_catalog(installed_only=True, db=self.db, current_user=self.user)
                picker = list_available_skills(self.db, self.user)
                assets = load_runtime_assets(self.db, agent, 7, skills_only=True)
                self.assertEqual({s["skill_id"] for s in market["items"]}, expected)
                self.assertEqual({s["skill_id"] for s in picker["items"]}, expected)
                self.assertEqual({s.id for s in assets["skills"]}, expected)
                install_skills(root, assets["skills"])
                self.assertEqual(
                    {p.name for p in (Path(root) / ".claude" / "skills").iterdir()},
                    {s.name for s in assets["skills"]},
                )
                self.assertEqual(user_file.read_text(encoding="utf-8"), "keep")

            check({1, 2})
            self.db.get(Skill, 1).is_public = False
            self.db.commit()
            check({2})
            self.db.add(SkillCollaborator(skill_id=1, user_id=7, username="editor", created_by=8))
            self.db.commit()
            check({1, 2})
            self.db.query(SkillCollaborator).filter_by(skill_id=1, user_id=7).delete()
            self.db.commit()
            check({2})
            self.db.get(Skill, 1).user_id = 7
            self.db.commit()
            check({1, 2})

    def test_warm_cache_rechecks_grants_and_user_scope(self):
        agent = SimpleNamespace(id=7, kind="personal_default")
        first = load_runtime_assets(self.db, agent, 7)
        self.assertEqual({row["release_id"] for row in first["skill_snapshot"]}, {11, 21})
        with patch("skill_release_cache.load_release_file_tree", side_effect=AssertionError("unexpected unpack")):
            self.assertEqual(load_runtime_assets(self.db, agent, 42)["skills"], [])
            self.db.get(SkillRelease, 11).manifest_json = '{"capabilities":["network_access"]}'
            self.db.commit()
            with self.assertRaisesRegex(RuntimeError, "grant is incomplete"):
                load_runtime_assets(self.db, agent, 7)


if __name__ == "__main__":
    unittest.main()
