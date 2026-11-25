import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from asset_routes import (
    _added_prompt_ids, import_prompt_snapshot, list_prompt_catalog, list_workspace_prompts,
    remove_workspace_prompt, unbind_prompt_template,
)
from asset_schemas import PromptImportRequest
from auth import CurrentUser
from main import get_prompt_templates, update_prompt_template, delete_prompt_template
from models import (
    Base, Agent, PromptTemplate, WorkspacePromptReference, WorkspacePromptRemoval,
    agent_prompt_templates,
)
from schemas import PromptTemplateUpdate


spec = importlib.util.spec_from_file_location(
    "workspace_prompt_migration",
    Path(__file__).parent / "migrations/054_workspace_prompt_references.py",
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
spec = importlib.util.spec_from_file_location(
    "expert_prompt_migration",
    Path(__file__).parent / "migrations/055_expert_prompt_references.py",
)
expert_migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(expert_migration)


class WorkspacePromptReferenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine, tables=[
            Agent.__table__, PromptTemplate.__table__, WorkspacePromptReference.__table__,
            WorkspacePromptRemoval.__table__, agent_prompt_templates,
        ])
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.user = CurrentUser(user_id=7)
        self.source = PromptTemplate(id=1, user_id=8, name="作者模板", author="作者",
                                     content="v1 {{topic}}", variables='[{"name":"topic"}]', is_public=True)
        self.db.add(self.source)
        self.db.commit()

    def add(self, user=None):
        return import_prompt_snapshot(PromptImportRequest(source_template_id=1), self.db, user or self.user)

    def listing(self, user=None, **params):
        return list_workspace_prompts(db=self.db, current_user=user or self.user, **params)

    def test_catalog_filters_and_installation_are_scoped(self):
        self.db.add_all([
            Agent(id=99, user_id=7, name="Expert"),
            PromptTemplate(id=2, user_id=7, name="我的公开提示词", content="mine", is_public=True),
            PromptTemplate(id=3, user_id=8, name="其他人的私有提示词", content="private"),
            PromptTemplate(id=4, user_id=8, name="系统提示词", content="default", is_system=True),
            PromptTemplate(id=5, user_id=8, name="已删除提示词", content="deleted", is_public=True, is_deleted=True),
        ])
        self.db.commit()

        def catalog(**params):
            return list_prompt_catalog(db=self.db, current_user=self.user, **params)

        def states(**params):
            return {row["id"]: row["installed"] for row in catalog(**params)["items"]}

        self.assertEqual(states(), {1: False, 2: True, 4: True})
        self.assertEqual(states(source="system_default"), {4: True})
        self.assertEqual(states(source="mine"), {2: True})
        self.assertEqual(states(source="public"), {1: False, 2: True})
        self.assertEqual(catalog(source="public", limit=1)["total"], 2)
        self.assertEqual(states(source="public", q="{{topic}}"), {1: False})
        self.assertEqual(catalog(q="我的公开")["items"][0]["origins"], ["mine", "public"])
        self.assertEqual(states(agent_id=99), {1: False, 2: False, 4: False})
        self.add()
        import_prompt_snapshot(PromptImportRequest(source_template_id=1, agent_id=99), self.db, self.user)
        self.assertEqual(states(installed_only=True), {1: True, 2: True, 4: True})
        self.assertEqual(states(agent_id=99, installed_only=True), {1: True})
        remove_workspace_prompt(1, self.db, self.user)
        self.assertEqual(states(), {1: False, 2: True, 4: True})
        self.assertEqual(states(agent_id=99, installed_only=True), {1: True})
        self.add()
        unbind_prompt_template(1, 99, self.db, self.user)
        self.assertEqual(states(agent_id=99, installed_only=True), {})
        self.assertEqual(states(installed_only=True), {1: True, 2: True, 4: True})

    def test_system_catalog_exposes_public_candidates_and_one_row_per_installation(self):
        system_copy = self.copy(2, user_id=9, is_system=True, is_public=True)
        self.db.add(PromptTemplate(id=3, user_id=7, name="我的私有提示词", content="private"))
        self.db.commit()
        reviewer = CurrentUser(user_id=7, is_superuser=True)

        def catalog(**params):
            result = list_prompt_catalog(db=self.db, current_user=reviewer, system_mode=True, **params)
            return {row["id"]: row["installed"] for row in result["items"]}

        self.assertEqual(catalog(), {2: True})
        self.assertEqual(catalog(installed_only=True), {2: True})
        system_copy.is_deleted = True
        self.db.commit()
        self.assertEqual(catalog(), {1: False})
        self.assertEqual(catalog(installed_only=True), {})
        with self.assertRaises(HTTPException) as denied:
            list_prompt_catalog(db=self.db, current_user=self.user, system_mode=True)
        self.assertEqual(denied.exception.status_code, 403)

    def test_add_is_a_reference_and_uses_live_author_fields(self):
        added = self.add()
        self.assertEqual(added["id"], self.source.id)
        self.assertEqual(self.db.query(PromptTemplate).count(), 1)
        self.assertEqual(get_prompt_templates(db=self.db, current_user=self.user)["total"], 0)
        self.assertEqual(self.listing()["items"][0]["source"], "reference")
        self.assertEqual(self.listing(CurrentUser(9))["total"], 0)
        self.source.name = "作者新标题"
        self.source.content = "v2 {{topic}}"
        self.source.variables = '[{"name":"topic","required":true}]'
        self.db.commit()
        item = self.listing()["items"][0]
        self.assertEqual((item["name"], item["content"], item["variables"]),
                         (self.source.name, self.source.content, self.source.variables))
        self.assertEqual(item["origins"], ["public"])
        self.assertEqual(self.listing(q="新标题")["total"], 1)
        self.assertEqual(self.listing(q="不存在")["total"], 0)

    def test_repeat_remove_restore_and_user_isolation(self):
        self.add()
        self.add(CurrentUser(9))
        with self.assertRaises(HTTPException) as error:
            self.add()
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn(1, _added_prompt_ids(self.db, 7))
        for _ in range(2):
            remove_workspace_prompt(1, self.db, self.user)
        self.assertNotIn(1, _added_prompt_ids(self.db, 7))
        self.assertEqual(self.listing()["total"], 0)
        self.assertEqual(self.listing(CurrentUser(9))["total"], 1)
        # Re-adding, including a legacy optional name, never renames the author.
        restored = import_prompt_snapshot(PromptImportRequest(source_template_id=1, name="别名"), self.db, self.user)
        self.assertEqual(restored["name"], "作者模板")
        self.assertEqual(self.listing()["total"], 1)
        self.assertEqual(self.db.query(PromptTemplate).count(), 1)
        self.assertEqual(self.db.query(WorkspacePromptReference).count(), 2)
        self.assertEqual(self.db.query(WorkspacePromptRemoval).count(), 0)

    def test_reference_never_grants_edit_or_private_access(self):
        self.add()
        for action in (
            lambda: update_prompt_template(1, PromptTemplateUpdate(content="overwrite"), self.db, self.user),
            lambda: delete_prompt_template(1, self.db, self.user),
        ):
            with self.assertRaises(HTTPException) as error:
                action()
            self.assertEqual(error.exception.status_code, 404)
        self.source.is_public = False
        self.db.commit()
        self.assertEqual(self.listing()["total"], 0)
        with self.assertRaises(HTTPException) as error:
            self.add(CurrentUser(9))
        self.assertEqual(error.exception.status_code, 404)
        self.source.is_public = True
        self.source.is_deleted = True
        self.db.commit()
        self.assertEqual(self.listing()["total"], 0)
        self.assertEqual(self.source.content, "v1 {{topic}}")

    def copy(self, row_id, **overrides):
        fields = {key: getattr(self.source, key) for key in
                  ("name", "category", "content", "variables", "description", "author")}
        canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        values = dict(user_id=7, source_template_id=1,
                      source_snapshot_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                      imported_at=datetime.now(timezone.utc), **fields)
        values.update(overrides)
        row = PromptTemplate(id=row_id, **values)
        self.db.add(row)
        self.db.flush()
        return row

    def test_migration_preserves_bytes_and_redirects_expert_bindings_and_is_repeatable(self):
        self.db.add(Agent(id=99, user_id=7, name="Expert"))
        copy = self.copy(2)
        self.db.execute(agent_prompt_templates.insert().values(
            agent_id=99, prompt_template_id=2, snapshot_json='{"content":"frozen"}', position=1,
        ))
        self.db.commit()
        # A changed author template is read live after conversion.
        self.source.content = "author v2"
        self.db.commit()
        migration.apply_schema(self.engine)
        self.assertEqual(migration.backfill(self.db), {"converted": 1, "retained": 0})
        self.db.commit()
        self.assertTrue(copy.is_deleted)
        self.assertEqual(copy.content, "v1 {{topic}}")
        self.assertEqual(self.listing()["items"][0]["content"], "author v2")
        self.assertEqual(get_prompt_templates(db=self.db, current_user=self.user)["total"], 0)
        # Also works when the original 054 was already applied before upgrading.
        self.assertEqual(expert_migration.backfill(self.db), {"converted": 1, "retained": 0})
        binding = self.db.execute(agent_prompt_templates.select()).one()
        self.assertEqual((binding.prompt_template_id, binding.position, binding.snapshot_json), (1, 1, None))
        self.assertEqual(migration.backfill(self.db), {"converted": 0, "retained": 0})
        self.assertEqual(expert_migration.backfill(self.db), {"converted": 0, "retained": 0})
        self.assertEqual(self.db.query(WorkspacePromptReference).count(), 1)

    def test_migration_merges_duplicate_expert_references_preserving_order(self):
        self.db.add(Agent(id=99, user_id=7, name="Expert"))
        self.copy(2)
        self.db.execute(agent_prompt_templates.insert(), [
            dict(agent_id=99, prompt_template_id=1, position=5),
            dict(agent_id=99, prompt_template_id=2, position=1),
        ])
        self.db.commit()
        migration.backfill(self.db)
        expert_migration.backfill(self.db)
        self.db.commit()
        binding = self.db.execute(agent_prompt_templates.select()).one()
        self.assertEqual((binding.prompt_template_id, binding.position), (1, 1))

    def test_expert_migration_preserves_edited_copies_and_private_source_access(self):
        self.db.add(Agent(id=99, user_id=7, name="Expert"))
        self.copy(2, content="Expert's edited template")
        self.db.execute(agent_prompt_templates.insert().values(agent_id=99, prompt_template_id=2))
        self.db.commit()
        self.assertEqual(expert_migration.backfill(self.db), {"converted": 0, "retained": 1})
        self.db.rollback()
        copy = self.db.get(PromptTemplate, 2)
        copy.content = self.source.content
        self.source.is_public = False
        self.db.commit()
        self.assertEqual(expert_migration.backfill(self.db), {"converted": 0, "retained": 1})
        self.db.rollback()
        self.source.is_public = True
        self.db.commit()
        self.assertEqual(expert_migration.backfill(self.db), {"converted": 1, "retained": 0})
        self.db.rollback()
        binding = self.db.execute(agent_prompt_templates.select()).one()
        self.assertEqual(binding.prompt_template_id, 2)

    def test_migration_retains_edited_published_and_unverifiable_copies(self):
        for row_id, changes in enumerate((
            {"content": "用户编辑"}, {"name": "用户重命名"}, {"is_public": True},
            {"source_snapshot_hash": None}, {"imported_at": None}, {"source_template_id": 999},
        ), start=2):
            self.copy(row_id, **changes)
        self.db.commit()
        self.assertEqual(migration.backfill(self.db), {"converted": 0, "retained": 6})
        self.assertEqual(self.db.query(WorkspacePromptReference).count(), 0)
        self.assertEqual(get_prompt_templates(db=self.db, current_user=self.user)["total"], 6)

    def test_migration_preserves_removals_and_does_not_reveal_private_sources(self):
        self.copy(2)
        self.db.add(WorkspacePromptRemoval(user_id=7, template_id=2))
        self.db.commit()
        self.source.is_public = False
        self.db.commit()
        self.assertEqual(migration.backfill(self.db), {"converted": 0, "retained": 1})
        self.source.is_public = True
        self.db.commit()
        self.assertEqual(migration.backfill(self.db), {"converted": 1, "retained": 0})
        self.db.commit()
        self.assertEqual(self.listing()["total"], 0)
        self.add()
        self.assertEqual(self.listing()["total"], 1)

    def test_migration_maps_legacy_removal_when_source_belongs_to_same_user(self):
        self.source.user_id = 7
        self.db.commit()
        self.copy(2)
        self.db.add(WorkspacePromptRemoval(user_id=7, template_id=2))
        self.db.commit()
        self.assertEqual(migration.backfill(self.db), {"converted": 1, "retained": 0})
        self.db.commit()
        self.assertEqual(self.listing()["total"], 0)
        self.assertIsNotNone(self.db.get(WorkspacePromptRemoval, (7, 1)))

    def test_migration_rollback_restores_copies_and_references(self):
        self.copy(2)
        self.db.commit()
        migration.backfill(self.db)
        self.db.rollback()
        self.assertFalse(self.db.get(PromptTemplate, 2).is_deleted)
        self.assertEqual(self.db.query(WorkspacePromptReference).count(), 0)


if __name__ == "__main__":
    unittest.main()
