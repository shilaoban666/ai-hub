"""Public catalog display configuration must never become an MCP endpoint."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

from asset_routes import create_system_mcp_definition, inspect_system_mcp
from asset_runtime import load_runtime_assets
from asset_schemas import McpDefinitionCreateRequest
from auth import CurrentUser
from database import Base, settings
from mcp_headers import read_env, read_headers, store_headers
from mcp_source_config import McpSourceConfigError, system_mcp_config
from models import McpDefinition, McpRevision, McpService


class SystemMcpImportTests(unittest.TestCase):
    url = "https://knowledge.example.com/api/v1/indices/rag/mcp"
    redacted_url = "https://knowledge.example.com/REDACTED"

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.key = patch.object(settings, "agent_credential_encryption_key", "a" * 32)
        self.key.start()
        self.addCleanup(self.key.stop)
        self.admin = CurrentUser(8, is_superuser=True)
        self.source = McpService(
            id=55, user_id=7, name="合趣知识库", type="streamable_http", is_public=True,
        )
        self.source.store_config(json.dumps({
            "url": self.url,
            "headers": {"Authorization": "author-secret", "X-Tenant": "author-tenant"},
        }))
        self.db.add(self.source)
        self.db.commit()

    def import_source(self, config=None, headers=None):
        with patch("asset_routes.validate_mcp_config", return_value={}):
            result = create_system_mcp_definition(McpDefinitionCreateRequest(
                name="合趣知识库", transport_type="sse", source_mcp_service_id=55,
                config=config or {"url": self.redacted_url, "headers": {"Authorization": "隐藏"}},
                headers=headers,
            ), self.db, self.admin)
        definition = self.db.get(McpDefinition, result["id"])
        revision = self.db.get(McpRevision, result["latest_revision"]["id"])
        return definition, revision

    def legacy_definition(self, wrapped=False):
        config = {"url": self.redacted_url, "headers": {
            "Authorization": "{{credential}}", "X-Tenant": "隐藏",
        }}
        if wrapped:
            config = {"mcpServers": {"合趣知识库": {"type": "streamable-http", **config}}}
        definition = McpDefinition(
            id=21, owner_user_id=8, scope="system", name="合趣知识库",
            transport_type="json" if wrapped else "streamable_http",
            source_mcp_service_id=55, status="published",
        )
        revision = McpRevision(
            id=22, definition_id=21, version=1, config_json=json.dumps(config),
            content_sha256="a" * 64, status="published", security_report_json="{}", created_by=8,
        )
        self.db.add_all([definition, revision])
        self.db.commit()
        return definition, revision

    def test_import_uses_stored_url_and_transport_instead_of_public_projection(self):
        definition, revision = self.import_source()
        self.assertEqual("streamable_http", definition.transport_type)
        self.assertEqual({"url": self.url}, json.loads(revision.config_json))
        self.assertNotIn("author-secret", revision.config_json)
        self.assertNotIn("author-tenant", revision.config_json)

    def test_system_import_saves_selected_authentication_mode(self):
        with patch("asset_routes.validate_mcp_config", return_value={}):
            result = create_system_mcp_definition(McpDefinitionCreateRequest(
                name="合趣知识库", transport_type="streamable_http", source_mcp_service_id=55,
                config={}, headers={}, auth_mode="current_user",
            ), self.db, self.admin)
        self.assertEqual("current_user", self.db.get(McpDefinition, result["id"]).auth_mode)
        revision = self.db.get(McpRevision, result["latest_revision"]["id"])
        self.assertEqual({}, read_headers(json.loads(revision.config_json)))

    def test_import_unwraps_json_and_keeps_only_destination_credentials(self):
        self.source.type = "json"
        self.source.store_config(json.dumps({"mcpServers": {"合趣知识库": {
            "type": "streamable-http", "url": self.url,
            "headers": {"Authorization": "author-secret"}, "env": {"KEY": "author-env"},
        }}}))
        self.db.commit()
        definition, revision = self.import_source(headers={"Authorization": "123123"})
        config = json.loads(revision.config_json)
        self.assertEqual("streamable_http", definition.transport_type)
        self.assertEqual(self.url, config["url"])
        self.assertEqual({"Authorization": "123123"}, read_headers(config))
        self.assertNotIn("author-", revision.config_json)
        self.assertNotIn("env", config)

    def test_system_import_encrypts_explicit_stdio_environment(self):
        self.source.type = "json"
        self.source.store_config(json.dumps({"mcpServers": {"example": {
            "command": "node", "args": ["server.js"], "env": {"API_KEY": "author-env"},
        }}}))
        self.db.commit()
        with patch("asset_routes.validate_mcp_config", return_value={}):
            result = create_system_mcp_definition(McpDefinitionCreateRequest(
                name="Example", transport_type="json", source_mcp_service_id=55,
                config={}, env={"API_KEY": "destination-env"},
            ), self.db, self.admin)
        revision = self.db.get(McpRevision, result["latest_revision"]["id"])
        config = json.loads(revision.config_json)
        self.assertEqual("stdio", result["transport_type"])
        self.assertEqual("node", config["command"])
        self.assertEqual(["server.js"], config["args"])
        self.assertEqual({"API_KEY": "destination-env"}, read_env(config))
        self.assertNotIn("author-env", revision.config_json)
        self.assertNotIn("destination-env", revision.config_json)

    def test_legacy_url_recovery_preserves_saved_headers_and_historical_release(self):
        definition, revision = self.legacy_definition()
        config = store_headers(json.loads(revision.config_json), {"Authorization": "123123"})
        revision.config_json = json.dumps(config)
        self.db.commit()
        original_release = revision.config_json
        transport, restored = system_mcp_config(self.db, definition, config)
        self.assertEqual("streamable_http", transport)
        self.assertEqual(self.url, restored["url"])
        self.assertEqual({"Authorization": "123123"}, read_headers(restored))
        self.assertNotIn("headers", restored)
        self.assertEqual(self.redacted_url, config["url"])
        self.db.refresh(revision)
        self.assertEqual(original_release, revision.config_json)
        self.assertEqual(1, self.db.query(McpRevision).count())

    def test_inspection_posts_to_full_original_path_with_exact_saved_auth(self):
        _, revision = self.legacy_definition()
        revision.config_json = json.dumps(store_headers(
            json.loads(revision.config_json), {"Authorization": "123123"},
        ))
        self.db.commit()
        requests = []

        def handler(request):
            self.assertEqual("POST", request.method)
            self.assertEqual(self.url, str(request.url))
            self.assertEqual("123123", request.headers["Authorization"])
            payload = json.loads(request.content)
            requests.append(payload["method"])
            if payload["method"] == "notifications/initialized":
                return httpx.Response(202)
            result = {
                "protocolVersion": "2025-03-26", "serverInfo": {"name": "知识库"},
                "capabilities": {"tools": {}},
            } if payload["method"] == "initialize" else {"tools": [{"name": "retrieve"}]}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch("asset_routes.validate_mcp_config", return_value={}), patch(
            "mcp_inspector.httpx.AsyncClient", return_value=client,
        ):
            result = asyncio.run(inspect_system_mcp(21, self.db, self.admin, None))
        self.assertEqual([{"name": "retrieve"}], result["tools"])
        self.assertEqual(["initialize", "notifications/initialized", "tools/list"], requests)

    def test_legacy_wrapped_json_works_for_inspection_and_runtime(self):
        self.legacy_definition(wrapped=True)
        from unittest.mock import AsyncMock
        with patch("asset_routes.validate_mcp_config", return_value={}), patch(
            "asset_routes.inspect_mcp_server", new_callable=AsyncMock, return_value={},
        ) as inspect:
            asyncio.run(inspect_system_mcp(21, self.db, self.admin, None))
        inspect.assert_awaited_once_with("streamable_http", {"url": self.url, "headers": {}})
        with patch("asset_runtime.validate_mcp_config", return_value={}):
            runtime = load_runtime_assets(self.db, SimpleNamespace(kind="personal_default"), 8)
        self.assertEqual("streamable_http", runtime["mcps"][0].type)
        self.assertEqual(self.url, json.loads(runtime["mcps"][0].config)["url"])
        self.assertEqual({}, json.loads(runtime["mcps"][0].config)["headers"])
        self.assertEqual({}, runtime["secret_env"])

    def test_good_snapshot_does_not_follow_later_source_edits(self):
        definition, revision = self.import_source()
        config = json.loads(revision.config_json)
        self.source.store_config(json.dumps({"url": "https://other.example.com/new"}))
        self.db.commit()
        _, resolved = system_mcp_config(self.db, definition, config)
        self.assertEqual(self.url, resolved["url"])

    def test_recovery_requires_an_available_public_source_on_the_same_origin(self):
        definition, revision = self.legacy_definition()
        config = json.loads(revision.config_json)
        for change in ("private", "deleted", "missing", "different_origin", "still_redacted"):
            with self.subTest(change=change):
                self.source.is_public = change != "private"
                self.source.is_deleted = change == "deleted"
                definition.source_mcp_service_id = None if change == "missing" else 55
                url = "https://other.example.com/new" if change == "different_origin" else (
                    self.redacted_url if change == "still_redacted" else self.url
                )
                self.source.store_config(json.dumps({"url": url}))
                self.db.commit()
                with self.assertRaises(McpSourceConfigError):
                    system_mcp_config(self.db, definition, config)

    def test_unrecoverable_inspection_reports_configuration_error_before_network(self):
        self.legacy_definition()
        self.source.is_deleted = True
        self.db.commit()
        with patch("asset_routes.inspect_mcp_server") as inspect:
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(inspect_system_mcp(21, self.db, self.admin, None))
        self.assertEqual(409, caught.exception.status_code)
        self.assertIn("脱敏地址", caught.exception.detail)
        inspect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
