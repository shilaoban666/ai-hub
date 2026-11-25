import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

from asset_routes import (
    create_system_mcp_definition, create_system_prompt, list_mcp_connections,
    list_mcp_definitions, list_system_mcp_definitions, list_system_prompts,
    list_workspace_prompts,
)
from asset_schemas import McpDefinitionCreateRequest, SystemPromptCreateRequest
from auth import CurrentUser
from models import (
    McpConnection, McpDefinition, McpRevision, McpService, McpUserHeaders,
    PromptTemplate, WorkspacePromptRemoval, WorkspacePromptReference,
)


class ResourceOriginTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            for model in (McpService, McpDefinition, McpRevision, McpConnection, McpUserHeaders, PromptTemplate, WorkspacePromptRemoval, WorkspacePromptReference):
                model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user = CurrentUser(user_id=7)
        self.admin = CurrentUser(user_id=7, is_superuser=True)
        for row_id, owner, public in ((1, 7, False), (2, 8, True), (3, 8, False)):
            self.db.add(McpService(id=row_id, user_id=owner, name=f"Service {row_id}", type="http", is_public=public))
        for row_id, owner, scope, source_id in (
            (11, 7, "user", None), (12, 7, "user", 2), (13, 7, "user", 1),
            (14, 8, "system", None), (15, 7, "system", 2), (16, 7, "user", 999),
            (17, 8, "public", None), (18, 7, "user", 3),
        ):
            self.db.add(McpDefinition(
                id=row_id, owner_user_id=owner, scope=scope, source_mcp_service_id=source_id,
                name=f"Connector {row_id}", transport_type="http", status="published",
            ))
            self.db.add(McpRevision(
                id=row_id * 10, definition_id=row_id, version=1, config_json="{}",
                content_sha256="a" * 64, status="published", created_by=owner,
            ))
            if scope != "system":
                self.db.add(McpConnection(
                    id=row_id, user_id=7, workspace_id=1, definition_id=row_id,
                    revision_id=row_id * 10, name=f"Connector {row_id}", status="active",
                ))
        for row_id, owner, public, system, source_id in (
            (1, 7, False, False, None), (2, 7, True, False, None),
            (3, 8, True, False, None), (4, 7, False, False, 3),
            (5, 7, False, False, 1), (6, 8, True, True, None),
            (7, 7, True, True, 3), (8, 7, False, False, 999),
            (9, 8, False, False, None), (10, 7, False, False, 9),
        ):
            self.db.add(PromptTemplate(
                id=row_id, user_id=owner, name=f"Prompt {row_id}", content="Example",
                is_public=public, is_system=system, source_template_id=source_id,
            ))
        self.db.commit()

    def test_connection_origins_follow_original_services_not_copy_owner(self):
        result = list_mcp_connections(db=self.db, current_user=self.user)
        self.assertEqual({row["definition_id"]: row["origin"] for row in result["items"]}, {
            11: "mine", 12: "public", 13: "mine", 14: "public", 15: "public",
            16: None, 17: "public", 18: None,
        })
        self.assertEqual({row["definition_id"]: row["origins"] for row in result["items"]}, {
            11: ["mine"], 12: ["public"], 13: ["mine"], 14: ["public"], 15: ["public"],
            16: [], 17: ["public"], 18: [],
        })
        system = next(row for row in result["items"] if row["definition_id"] == 15)
        self.assertTrue(system["is_system"])
        self.assertEqual(system["source"], "system_default")
        self.assertEqual(system["source_mcp_service_id"], 2)

    def test_mcp_definition_lists_include_origins(self):
        result = list_mcp_definitions(db=self.db, current_user=self.user)
        self.assertEqual(next(row for row in result["items"] if row["id"] == 12)["origin"], "public")
        system = list_system_mcp_definitions(db=self.db, current_user=self.admin)
        self.assertEqual({row["id"]: row["origin"] for row in system["items"]}, {14: "public", 15: "public"})
        own_system = list_system_mcp_definitions(db=self.db, current_user=CurrentUser(user_id=8, is_superuser=True))
        self.assertEqual({row["id"]: row["origin"] for row in own_system["items"]}, {14: "mine", 15: "mine"})
        self.assertEqual({row["id"]: row["origins"] for row in own_system["items"]}, {
            14: ["mine", "public"], 15: ["mine", "public"],
        })

    def test_mcp_lists_return_original_authors_and_follow_author_updates(self):
        self.db.get(McpService, 1).author = "  我的作者  "
        for author in ("公开资源作者", "更新后的作者"):
            with self.subTest(author=author):
                self.db.get(McpService, 2).author = author
                self.db.commit()
                for listing, id_key in ((list_mcp_connections, "definition_id"), (list_mcp_definitions, "id")):
                    result = listing(db=self.db, current_user=self.user)
                    authors = {row[id_key]: row["author"] for row in result["items"]}
                    self.assertEqual(authors[13], "我的作者")
                    self.assertEqual(authors[12], author)
                    self.assertEqual(authors[15], author)
                    self.assertIsNone(authors[14])
                    self.assertIsNone(authors[11])
                    self.assertIsNone(authors[16])
                system = list_system_mcp_definitions(db=self.db, current_user=self.admin)
                self.assertEqual({row["id"]: row["author"] for row in system["items"]}, {14: None, 15: author})

    def test_blank_source_authors_remain_empty_for_all_connectors(self):
        for author in (None, "", "   "):
            with self.subTest(author=author):
                self.db.get(McpService, 2).author = author
                self.db.commit()
                result = list_mcp_connections(db=self.db, current_user=self.user)
                authors = {row["definition_id"]: row["author"] for row in result["items"]}
                self.assertIsNone(authors[12])
                self.assertIsNone(authors[15])

    def test_own_public_connectors_have_both_labels_and_follow_visibility_changes(self):
        self.db.get(McpDefinition, 11).scope = "public"
        for public, expected in ((True, ["mine", "public"]), (False, ["mine"])):
            with self.subTest(public=public):
                self.db.get(McpService, 1).is_public = public
                self.db.commit()
                for listing, id_key in ((list_mcp_connections, "definition_id"), (list_mcp_definitions, "id")):
                    result = listing(db=self.db, current_user=self.user)
                    labels = {row[id_key]: row["origins"] for row in result["items"]}
                    self.assertEqual(labels[11], ["mine", "public"])
                    self.assertEqual(labels[13], expected)

    def test_prompt_origins_follow_original_templates_without_exposing_other_templates(self):
        result = list_workspace_prompts(db=self.db, current_user=self.user)
        self.assertEqual({row["id"]: row["origin"] for row in result["items"]}, {
            1: "mine", 2: "mine", 4: "public", 5: "mine", 6: "public",
            7: "public", 8: None, 10: None,
        })
        self.assertEqual({row["id"]: row["origins"] for row in result["items"]}, {
            1: ["mine"], 2: ["mine", "public"], 4: ["public"], 5: ["mine"],
            6: ["public"], 7: ["public"], 8: [], 10: [],
        })
        imported = next(row for row in result["items"] if row["id"] == 4)
        self.assertFalse(imported["is_system"])
        self.assertEqual(imported["source"], "personal")

    def test_system_prompt_origins_are_separate_from_admin_settings(self):
        result = list_system_prompts(db=self.db, current_user=self.admin)
        self.assertEqual({row["id"]: row["origin"] for row in result["items"]}, {6: "public", 7: "public"})
        own = list_system_prompts(db=self.db, current_user=CurrentUser(user_id=8, is_superuser=True))
        self.assertEqual({row["id"]: row["origin"] for row in own["items"]}, {6: "mine", 7: "mine"})
        self.assertEqual({row["id"]: row["origins"] for row in own["items"]}, {
            6: ["mine", "public"], 7: ["mine", "public"],
        })

    def test_imported_prompt_labels_follow_source_visibility_changes(self):
        for public, expected in ((True, ["mine", "public"]), (False, ["mine"])):
            with self.subTest(public=public):
                self.db.get(PromptTemplate, 1).is_public = public
                self.db.commit()
                result = list_workspace_prompts(db=self.db, current_user=self.user)
                labels = {row["id"]: row["origins"] for row in result["items"]}
                self.assertEqual(labels[1], expected)
                self.assertEqual(labels[5], expected)

    def test_system_mcp_import_preserves_source(self):
        self.db.get(McpDefinition, 15).status = "deleted"
        self.db.commit()
        with patch("asset_routes._validated_mcp_config", return_value=({"url": "https://example.com"}, {"status": "passed"})), patch("asset_routes.audit_asset"):
            result = create_system_mcp_definition(
                McpDefinitionCreateRequest(name="Imported", transport_type="http", config={}, source_mcp_service_id=2),
                db=self.db, current_user=self.admin,
            )
        self.assertEqual(self.db.get(McpDefinition, result["id"]).source_mcp_service_id, 2)
        listing = list_system_mcp_definitions(db=self.db, current_user=self.admin)
        self.assertEqual(next(row for row in listing["items"] if row["id"] == result["id"])["origin"], "public")

    def test_system_prompt_import_preserves_source(self):
        self.db.get(PromptTemplate, 7).is_deleted = True
        self.db.commit()
        with patch("asset_routes.audit_asset"):
            result = create_system_prompt(
                SystemPromptCreateRequest(name="Imported", content="Example", source_template_id=3),
                db=self.db, current_user=self.admin,
            )
        self.assertEqual(self.db.get(PromptTemplate, result["id"]).source_template_id, 3)
        listing = list_system_prompts(db=self.db, current_user=self.admin)
        self.assertEqual(next(row for row in listing["items"] if row["id"] == result["id"])["origin"], "public")

    def test_system_import_cannot_claim_an_inaccessible_source(self):
        for source_id in (3, 999):
            with self.assertRaises(HTTPException) as error:
                create_system_mcp_definition(
                    McpDefinitionCreateRequest(name="Invalid", transport_type="http", config={}, source_mcp_service_id=source_id),
                    db=self.db, current_user=self.admin,
                )
            self.assertEqual(error.exception.status_code, 404)
        for source_id in (9, 999):
            with self.assertRaises(HTTPException) as error:
                create_system_prompt(
                    SystemPromptCreateRequest(name="Invalid", content="Example", source_template_id=source_id),
                    db=self.db, current_user=self.admin,
                )
            self.assertEqual(error.exception.status_code, 404)

    def test_system_import_rejects_own_private_sources_without_creating_resources(self):
        definition_count = self.db.query(McpDefinition).count()
        prompt_count = self.db.query(PromptTemplate).count()
        with self.assertRaises(HTTPException) as error:
            create_system_mcp_definition(
                McpDefinitionCreateRequest(name="Private", transport_type="http", config={}, source_mcp_service_id=1),
                db=self.db, current_user=self.admin,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("公开 MCP", error.exception.detail)
        with self.assertRaises(HTTPException) as error:
            create_system_prompt(
                SystemPromptCreateRequest(name="Private", content="Example", source_template_id=1),
                db=self.db, current_user=self.admin,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("公开提示词", error.exception.detail)
        self.assertEqual(self.db.query(McpDefinition).count(), definition_count)
        self.assertEqual(self.db.query(PromptTemplate).count(), prompt_count)

    def test_system_import_accepts_own_sources_after_publication(self):
        self.db.get(McpService, 1).is_public = True
        self.db.get(PromptTemplate, 1).is_public = True
        self.db.commit()
        with patch("asset_routes._validated_mcp_config", return_value=({}, {"status": "passed"})), patch("asset_routes.audit_asset"):
            connector = create_system_mcp_definition(
                McpDefinitionCreateRequest(name="Own public", transport_type="http", config={}, source_mcp_service_id=1),
                db=self.db, current_user=self.admin,
            )
            prompt = create_system_prompt(
                SystemPromptCreateRequest(name="Own public", content="Example", source_template_id=1),
                db=self.db, current_user=self.admin,
            )
        self.assertEqual(self.db.get(McpDefinition, connector["id"]).scope, "system")
        self.assertTrue(self.db.get(PromptTemplate, prompt["id"]).is_system)

    def test_system_import_rejects_deleted_public_sources(self):
        self.db.get(McpService, 2).is_deleted = True
        self.db.get(PromptTemplate, 3).is_deleted = True
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            create_system_mcp_definition(
                McpDefinitionCreateRequest(name="Deleted", transport_type="http", config={}, source_mcp_service_id=2),
                db=self.db, current_user=self.admin,
            )
        self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as error:
            create_system_prompt(
                SystemPromptCreateRequest(name="Deleted", content="Example", source_template_id=3),
                db=self.db, current_user=self.admin,
            )
        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
