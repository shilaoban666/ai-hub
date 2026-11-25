import unittest
from unittest.mock import patch
from types import SimpleNamespace
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

from fastapi import HTTPException

from asset_routes import (
    create_mcp_connection, create_system_mcp_definition, create_system_prompt,
    get_resource_import_status, import_mcp_definition, import_prompt_snapshot,
    remove_workspace_prompt, list_mcp_connections, list_workspace_prompts, bind_prompt_template,
)
from asset_schemas import (
    McpConnectionCreateRequest, McpDefinitionCreateRequest, McpImportRequest,
    PromptImportRequest, SystemPromptCreateRequest, PromptBindingRequest,
)
from auth import CurrentUser
from models import McpConnection, McpDefinition, PromptTemplate, ExpertMcpBinding, agent_prompt_templates
import test_resource_origins as fixtures


class ResourceDuplicateTests(unittest.TestCase):
    setUp = fixtures.ResourceOriginTests.setUp

    def test_expert_prompt_import_references_without_creating_personal_templates(self):
        agent_prompt_templates.create(self.engine)
        before = self.db.query(PromptTemplate).count()
        with patch("asset_routes._agent", return_value=SimpleNamespace(id=99, kind="expert")):
            own = import_prompt_snapshot(PromptImportRequest(source_template_id=1, agent_id=99), db=self.db, current_user=self.user)
            self.assertEqual(own["id"], 1)
            imported = import_prompt_snapshot(PromptImportRequest(source_template_id=6, agent_id=99), db=self.db, current_user=self.user)
            self.assertEqual(imported["id"], 6)
            bind_prompt_template(imported["id"], PromptBindingRequest(agent_id=99), db=self.db, current_user=self.user)
            rows = self.db.execute(agent_prompt_templates.select()).all()
            self.assertEqual({row.prompt_template_id for row in rows}, {1, 6})
            self.assertTrue(all(row.snapshot_json is None for row in rows))
            self.assertEqual([row.position for row in rows], [0, 1])
            self.assertEqual(self.db.query(PromptTemplate).count(), before)

    @patch("asset_routes.validate_mcp_config", return_value={})
    @patch("asset_routes.audit_asset")
    def test_expert_mcp_import_is_independent_of_personal_connection(self, *_):
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            ExpertMcpBinding.__table__.create(self.engine)
        with patch("asset_routes._agent", return_value=SimpleNamespace(id=99, kind="expert")), patch(
            "asset_routes.bind_agent_workspace", return_value=(SimpleNamespace(id=99), None),
        ), patch(
            "agent_access.get_usable_agent", return_value=SimpleNamespace(id=99, user_id=7),
        ):
            definition = import_mcp_definition(McpImportRequest(source_mcp_service_id=2, agent_id=99), db=self.db, current_user=self.user)
            self.assertNotEqual(definition["id"], 12)
            ids = []
            for _ in range(2):
                connected = create_mcp_connection(McpConnectionCreateRequest(
                    definition_id=definition["id"], revision_id=definition["latest_revision"]["id"], name="Connector 12", agent_id=99,
                ), db=self.db, current_user=self.user)
                ids.append(connected["id"])
            self.assertEqual(ids[0], ids[1])
            self.assertNotEqual(ids[0], 12)
            self.assertEqual(self.db.get(McpConnection, ids[0]).scope_agent_id, 99)
            self.assertEqual(self.db.get(McpConnection, 12).scope_agent_id, 0)
            listed = list_mcp_connections(agent_id=99, db=self.db, current_user=self.user)
            self.assertEqual([row["id"] for row in listed["items"]], [ids[0]])

    def test_expert_import_rejects_unowned_agent_before_modifying_resources(self):
        with patch("asset_routes._agent", side_effect=HTTPException(status_code=404)):
            for action, payload in (
                (import_mcp_definition, McpImportRequest(source_mcp_service_id=2, agent_id=99)),
                (import_prompt_snapshot, PromptImportRequest(source_template_id=6, agent_id=99)),
            ):
                with self.assertRaises(HTTPException) as error:
                    action(payload, db=self.db, current_user=self.user)
                self.assertEqual(error.exception.status_code, 404)

    def assert_duplicate(self, operation):
        with self.assertRaises(HTTPException) as error:
            operation()
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("已添加", error.exception.detail)

    def test_personal_prompt_cannot_readd_present_owned_or_global_resources_even_renamed(self):
        before = self.db.query(PromptTemplate).count()
        for source_id in (1, 2, 4, 6):
            with self.subTest(source_id=source_id):
                self.assert_duplicate(lambda: import_prompt_snapshot(
                    PromptImportRequest(source_template_id=source_id, name="Different name"),
                    db=self.db, current_user=self.user,
                ))
        self.assertEqual(self.db.query(PromptTemplate).count(), before)

    def test_global_duplicates_are_rejected_for_every_administrator(self):
        for admin in (self.admin, CurrentUser(user_id=8, is_superuser=True)):
            self.assert_duplicate(lambda: create_system_prompt(
                SystemPromptCreateRequest(source_template_id=3, name="Different", content="Example"),
                db=self.db, current_user=admin,
            ))
            self.assert_duplicate(lambda: create_system_mcp_definition(
                McpDefinitionCreateRequest(source_mcp_service_id=2, name="Different", transport_type="http", config={}),
                db=self.db, current_user=admin,
            ))

    def test_personal_connector_import_cannot_readd_personal_or_global_sources(self):
        before = self.db.query(McpDefinition).count()
        self.db.get(McpConnection, 13).status = "inactive"
        self.db.commit()
        for source_id in (1, 2):
            self.assert_duplicate(lambda: import_mcp_definition(
                McpImportRequest(source_mcp_service_id=source_id), db=self.db, current_user=self.user,
            ))
        self.assertEqual(self.db.query(McpDefinition).count(), before)

    def test_direct_connection_endpoint_also_rejects_duplicates_with_different_names(self):
        for definition_id in (11, 12, 13):
            self.assert_duplicate(lambda: create_mcp_connection(
                McpConnectionCreateRequest(definition_id=definition_id, revision_id=definition_id * 10, name="Different"),
                db=self.db, current_user=self.user,
            ))

    def test_status_covers_all_resources_and_separates_personal_and_system_scopes(self):
        self.db.add_all([
            PromptTemplate(id=i, user_id=7, name=f"Prompt {i}", content="Example")
            for i in range(100, 305)
        ])
        self.db.commit()
        personal = get_resource_import_status(db=self.db, current_user=self.user)
        self.assertTrue({1, 2, 4, 6, 304}.issubset(personal["prompt_ids"]))
        self.assertNotIn(3, personal["prompt_ids"])
        self.assertEqual(personal["mcp_ids"], [1, 2, 3, 999])
        system = get_resource_import_status(system_mode=True, db=self.db, current_user=self.admin)
        self.assertEqual(system["mcp_ids"], [2])
        self.assertEqual({3, 6, 7}, set(system["prompt_ids"]))
        self.assertNotIn(304, system["prompt_ids"])
        with self.assertRaises(HTTPException) as error:
            get_resource_import_status(system_mode=True, db=self.db, current_user=self.user)
        self.assertEqual(error.exception.status_code, 403)

    def test_workbench_import_status_contains_only_visible_template_ids(self):
        remove_workspace_prompt(5, db=self.db, current_user=self.user)
        status = get_resource_import_status(db=self.db, current_user=self.user)
        listing = list_workspace_prompts(db=self.db, current_user=self.user)
        self.assertEqual(set(status["prompt_ids"]), {row["id"] for row in listing["items"]})

    def test_legacy_copy_does_not_mark_unadded_author_template_as_added(self):
        # Template 4 is a retained personal copy of the public template 3.
        # Merely retaining that copy must not prevent adding the author's row.
        status = get_resource_import_status(db=self.db, current_user=self.user)
        self.assertIn(4, status["prompt_ids"])
        self.assertNotIn(3, status["prompt_ids"])
        before = self.db.query(PromptTemplate).count()
        result = import_prompt_snapshot(PromptImportRequest(source_template_id=3), db=self.db, current_user=self.user)
        self.assertEqual(result["id"], 3)
        self.assertEqual(self.db.query(PromptTemplate).count(), before)
        status = get_resource_import_status(db=self.db, current_user=self.user)
        self.assertIn(3, status["prompt_ids"])
        self.assert_duplicate(lambda: import_prompt_snapshot(
            PromptImportRequest(source_template_id=3), db=self.db, current_user=self.user,
        ))

    def test_removed_template_can_be_restored_while_a_derived_template_remains(self):
        # Keep a visible template derived from the removed template. Neither
        # that provenance nor the removed row's own source reinstates it.
        self.db.add(PromptTemplate(id=20, user_id=7, name="Derived", content="changed", source_template_id=5))
        self.db.commit()
        remove_workspace_prompt(5, db=self.db, current_user=self.user)
        status = get_resource_import_status(db=self.db, current_user=self.user)
        self.assertNotIn(5, status["prompt_ids"])
        self.assertIn(1, status["prompt_ids"])
        self.assertIn(20, status["prompt_ids"])
        result = import_prompt_snapshot(PromptImportRequest(source_template_id=5), db=self.db, current_user=self.user)
        self.assertEqual(result["id"], 5)
        self.assertIn(5, get_resource_import_status(db=self.db, current_user=self.user)["prompt_ids"])

    def test_removed_imported_prompt_can_be_restored_without_creating_a_copy(self):
        self.db.get(PromptTemplate, 7).is_deleted = True
        self.db.commit()
        remove_workspace_prompt(4, db=self.db, current_user=self.user)
        before = self.db.query(PromptTemplate).count()
        status = get_resource_import_status(db=self.db, current_user=self.user)
        self.assertNotIn(3, status["prompt_ids"])
        self.assertNotIn(4, status["prompt_ids"])
        restored = import_prompt_snapshot(PromptImportRequest(source_template_id=3), db=self.db, current_user=self.user)
        self.assertEqual(restored["id"], 3)
        self.assertEqual(self.db.query(PromptTemplate).count(), before)
        self.assert_duplicate(lambda: import_prompt_snapshot(
            PromptImportRequest(source_template_id=3), db=self.db, current_user=self.user,
        ))

    def test_deleted_connection_can_be_added_again(self):
        self.db.get(McpConnection, 13).status = "deleted"
        self.db.commit()
        self.assertNotIn(1, get_resource_import_status(db=self.db, current_user=self.user)["mcp_ids"])
        with patch("asset_routes._validated_mcp_config", return_value=({}, {})), patch("asset_routes.audit_asset"):
            result = import_mcp_definition(McpImportRequest(source_mcp_service_id=1), db=self.db, current_user=self.user)
        self.assertEqual(result["source_mcp_service_id"], 1)


if __name__ == "__main__":
    unittest.main()
