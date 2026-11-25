import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import event

from asset_routes import (
    create_system_mcp_definition, get_mcp_headers, update_mcp_headers,
    get_mcp_secrets, update_mcp_secrets,
    import_mcp_definition, create_mcp_connection,
    _sanitize_mcp_config, _definition_payload, _system_mcp_payload,
    update_mcp_connection_status, list_mcp_connections, sync_owned_mcp_source,
)
from asset_schemas import (
    McpDefinitionCreateRequest, McpHeadersUpdateRequest,
    McpImportRequest, McpConnectionCreateRequest,
    McpSecretUpdateRequest,
    McpConnectionStatusRequest,
)
from asset_runtime import load_runtime_assets
from agent_workspace import build_mcp_json
from auth import CurrentUser
from database import settings
from mcp_headers import ENCRYPTED_ENV, ENCRYPTED_HEADERS, read_env, read_headers, store_headers
from models import Agent, AssetSecurityEvent, ExpertMcpBinding, ExpertSkillBinding, McpConnection, McpDefinition, McpRevision, McpService, McpUserHeaders, SkillCollaborator, UserWorkspace
from test_asset_runtime_system_mcp import SystemMcpRuntimeTests


class ConnectorHeaderTests(SystemMcpRuntimeTests):
    @patch("asset_runtime.validate_mcp_config", return_value={})
    @patch("asset_routes._agent")
    def test_agent_connection_status_is_isolated_and_controls_runtime(self, agent_lookup, _validate):
        self.add_definition(31, 32, "Shared tool", "user", "https://mcp.example.com", 7)
        self.add_connection(51, 31, 32, "Shared tool")
        self.add_connection(52, 31, 32, "Agent 99 tool")
        self.add_connection(53, 31, 32, "Agent 100 tool")
        self.db.get(McpConnection, 52).scope_agent_id = 99
        self.db.get(McpConnection, 53).scope_agent_id = 100
        self.db.add_all([
            ExpertMcpBinding(id=61, agent_id=99, connection_id=52),
            ExpertMcpBinding(id=62, agent_id=100, connection_id=53),
        ])
        self.db.commit()

        def runtime_ids(agent_id=None, source="web"):
            agent = SimpleNamespace(kind="expert" if agent_id else "personal_default", id=agent_id or 1)
            return [item.id for item in load_runtime_assets(self.db, agent, 7, source=source)["mcps"]]

        result = update_mcp_connection_status(52, McpConnectionStatusRequest(status="disabled", agent_id=99), self.db, self.user)
        agent_lookup.assert_called_with(self.db, 7, 99)
        self.assertEqual("disabled", result["status"])
        self.assertEqual("active", self.db.get(McpConnection, 51).status)
        self.assertEqual([], runtime_ids(99))
        self.assertEqual([], runtime_ids(99, "weixin_clawbot"))
        self.assertEqual([], runtime_ids(99, "dingtalk_clawbot"))
        self.assertEqual([53], runtime_ids(100))
        self.assertEqual([51], runtime_ids())
        rows = list_mcp_connections(db=self.db, current_user=self.user, agent_id=99)["items"]
        self.assertEqual([(52, "disabled")], [(row["id"], row["status"]) for row in rows])

        update_mcp_connection_status(51, McpConnectionStatusRequest(status="disabled"), self.db, self.user)
        update_mcp_connection_status(52, McpConnectionStatusRequest(status="active", agent_id=99), self.db, self.user)
        self.assertEqual([], runtime_ids())
        self.assertEqual([52], runtime_ids(99))
        self.assertEqual([53], runtime_ids(100))

        with self.assertRaises(HTTPException) as unbound:
            update_mcp_connection_status(51, McpConnectionStatusRequest(status="disabled", agent_id=101), self.db, self.user)
        self.assertEqual(404, unbound.exception.status_code)
        with self.assertRaises(HTTPException) as foreign:
            update_mcp_connection_status(51, McpConnectionStatusRequest(status="disabled", agent_id=99), self.db, CurrentUser(8))
        self.assertEqual(404, foreign.exception.status_code)
        self.assertEqual("active", self.db.get(ExpertMcpBinding, 61).status)

    def setUp(self):
        super().setUp()
        AssetSecurityEvent.__table__.create(self.engine)
        McpService.__table__.create(self.engine)
        SkillCollaborator.__table__.create(self.engine)
        Agent.__table__.create(self.engine)
        self.db.add_all([Agent(id=ident, user_id=7, name=f"Agent {ident}", kind="expert") for ident in (99, 100)])
        self.key_patch = patch.object(settings, "agent_credential_encryption_key", "a" * 32)
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        # SQLite does not autoincrement the production MySQL BIGINT columns.
        self.next_id = 1000
        def assign_test_ids(session, *_):
            for row in session.new:
                if getattr(row, "id", None) is None:
                    self.next_id += 1
                    row.id = self.next_id
        event.listen(self.db, "before_flush", assign_test_ids)
        self.admin = CurrentUser(8, is_superuser=True)
        self.user = CurrentUser(7)

    def runtime(self, request_authorization=None, source="web"):
        with patch("asset_runtime.validate_mcp_config", return_value={}):
            return load_runtime_assets(
                self.db,
                SimpleNamespace(kind="personal_default"),
                7,
                source=source,
                request_authorization=request_authorization,
            )

    def update(self, resource, ident, headers, user=None, auth_mode="manual"):
        return update_mcp_headers(
            resource,
            ident,
            McpHeadersUpdateRequest(headers=headers, auth_mode=auth_mode),
            self.db,
            user or self.user,
        )

    def import_source(self, config, *, owner=7, public=False, transport="http", encrypted=True, agent_id=None, headers=None, env=None, auth_mode="manual"):
        source = McpService(user_id=owner, name="Imported MCP", type=transport, is_public=public)
        self.db.add(source)
        self.db.flush()
        source.name = f"Imported MCP {source.id}"
        if encrypted:
            source.store_config(json.dumps(config))
        else:
            source.config = json.dumps(config)
        self.db.commit()
        with patch("asset_routes.validate_mcp_config", return_value={}):
            return import_mcp_definition(
                McpImportRequest(
                    source_mcp_service_id=source.id,
                    agent_id=agent_id,
                    auth_mode=auth_mode,
                    secrets={kind: values for kind, values in (("headers", headers), ("env", env)) if values is not None} or None,
                ), self.db, self.user,
            )

    def connect_import(self, definition, *, agent_id=None, headers=None, env=None, auth_mode="manual"):
        with patch("asset_routes.validate_mcp_config", return_value={}), patch(
            "asset_routes.ensure_user_workspace",
            return_value=(self.db.get(UserWorkspace, 1), None),
        ):
            return create_mcp_connection(McpConnectionCreateRequest(
                definition_id=definition["id"],
                revision_id=definition["latest_revision"]["id"],
                name=definition["name"], agent_id=agent_id,
                auth_mode=auth_mode,
                config_overrides={kind: values for kind, values in (("headers", headers), ("env", env)) if values is not None},
            ), self.db, self.user)

    def test_import_editor_can_add_and_remove_headers_without_copying_source_values(self):
        source_headers = {"Authorization": "source-secret", "X-Remove": "source-tenant"}
        selected_headers = {"X-Custom": "destination-value"}
        result = self.import_source(
            {"url": "https://mcp.example.com/mcp", "headers": source_headers},
            owner=8, public=True, headers=selected_headers,
        )
        revision = self.db.get(McpRevision, result["latest_revision"]["id"])
        self.assertNotIn("headers", json.loads(revision.config_json))
        connection = self.connect_import(result, headers=selected_headers)
        overrides = json.loads(self.db.get(McpConnection, connection["id"]).config_overrides_json)
        self.assertEqual(selected_headers, read_headers(overrides))
        source = self.db.get(McpService, result["source_mcp_service_id"])
        self.assertEqual(source_headers, json.loads(source.config)["headers"])

    def test_import_editor_can_switch_authentication_without_source_authorization(self):
        for mode in ("none", "current_user"):
            with self.subTest(mode=mode):
                result = self.import_source(
                    {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "source-secret"}},
                    owner=8, public=True, headers={}, auth_mode=mode,
                )
                connection = self.connect_import(result, headers={}, auth_mode=mode)
                saved = self.db.get(McpConnection, connection["id"])
                self.assertEqual(mode, saved.auth_mode)
                self.assertEqual({}, read_headers(json.loads(saved.config_overrides_json)))
                runtime = self.runtime(request_authorization="Bearer current-session")
                mcp = next(item for item in runtime["mcps"] if item.id == connection["id"])
                config = json.loads(mcp.config)
                headers = config["headers"]
                if mode == "none":
                    self.assertEqual({}, headers)
                else:
                    self.assertEqual("Bearer current-session", runtime["secret_env"][headers["Authorization"][2:-1]])
                self.assertNotIn("source-secret", json.dumps(runtime["secret_env"]))

    def test_import_headers_are_entered_for_destination_connection(self):
        source_headers = {"Authorization": "Bearer source-secret", "X-Tenant": "source-tenant"}
        headers = {"Authorization": "Bearer import-secret", "X-Tenant": "tenant-seven"}
        for transport in ("http", "sse", "streamable_http", "streamable-http"):
            for encrypted in (False, True):
                with self.subTest(transport=transport, encrypted=encrypted):
                    result = self.import_source(
                        {"url": "https://mcp.example.com/mcp", "headers": source_headers},
                        transport=transport, encrypted=encrypted, headers=headers,
                    )
                    revision = self.db.get(McpRevision, result["latest_revision"]["id"])
                    self.assertNotIn(ENCRYPTED_HEADERS, revision.config_json)
                    self.assertNotIn("{{credential}}", revision.config_json)
                    connection = self.connect_import(result, headers=headers)
                    overrides = json.loads(self.db.get(McpConnection, connection["id"]).config_overrides_json)
                    self.assertEqual(headers, read_headers(overrides))
                    runtime = self.runtime()
                    mcp = next(item for item in runtime["mcps"] if item.name == result["name"])
                    for name, ref in json.loads(mcp.config)["headers"].items():
                        self.assertEqual(headers[name], runtime["secret_env"][ref[2:-1]])
                    for secret in headers.values():
                        self.assertNotIn(secret, revision.config_json)
                        self.assertNotIn(secret, json.dumps([result, connection, runtime["mcp_snapshot"]]))
                        self.assertNotIn(secret, mcp.config)
                        for audit in self.db.query(AssetSecurityEvent).all():
                            self.assertNotIn(secret, audit.details_json)

    def test_import_requires_headers_when_source_has_headers(self):
        with self.assertRaises(HTTPException) as caught:
            self.import_source({
                "url": "https://mcp.example.com/mcp",
                "headers": {"X-MCP-Token": "source-token", "X-MCP-User": "source-user"},
            })
        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual("MCP_SECRETS_REQUIRED", caught.exception.detail["code"])
        self.assertEqual(["X-MCP-Token", "X-MCP-User"], caught.exception.detail["fields"]["headers"])

    def test_json_mcp_export_is_unwrapped_before_import(self):
        values = {"Authorization": "Bearer destination-secret"}
        result = self.import_source(
            {
                "mcpServers": {
                    "Imported MCP": {
                        "type": "streamable-http",
                        "url": "https://mcp.example.com/mcp",
                        "headers": {"Authorization": "Bearer source-secret"},
                    },
                },
            },
            transport="json", headers=values,
        )
        definition = self.db.get(McpDefinition, result["id"])
        revision = self.db.get(McpRevision, result["latest_revision"]["id"])
        self.assertEqual("streamable_http", definition.transport_type)
        self.assertNotIn("{{credential}}", revision.config_json)
        connection = self.connect_import(result, headers=values)
        overrides = json.loads(self.db.get(McpConnection, connection["id"]).config_overrides_json)
        self.assertEqual(values, read_headers(overrides))

        source = self.db.get(McpService, result["source_mcp_service_id"])
        source.store_config(json.dumps({"mcpServers": {"example": {
            "url": "https://mcp.example.com/updated",
            "headers": {"Authorization": "Bearer rotated-source-secret"},
        }}}))
        with patch("asset_routes.validate_mcp_config", return_value={}):
            self.assertEqual(1, sync_owned_mcp_source(self.db, source))
        self.db.commit()
        runtime = self.runtime()
        mcp = next(item for item in runtime["mcps"] if item.name == result["name"])
        config, warnings = build_mcp_json([mcp])
        self.assertEqual([], warnings)
        server, = config["mcpServers"].values()
        self.assertEqual("https://mcp.example.com/updated", server["url"])
        self.assertEqual("Bearer destination-secret", runtime["secret_env"][server["headers"]["Authorization"][2:-1]])
        self.assertNotIn("source-secret", json.dumps(config))

    def test_json_import_requests_destination_secrets_before_creating_definition(self):
        with self.assertRaises(HTTPException) as caught:
            self.import_source({"mcpServers": {"example": {
                "url": "https://mcp.example.com/mcp", "headers": {"Authorization": "source-secret"},
            }}}, transport="json")
        self.assertEqual("MCP_SECRETS_REQUIRED", caught.exception.detail["code"])
        self.assertEqual({"headers": ["Authorization"]}, caught.exception.detail["fields"])
        self.assertEqual(0, self.db.query(McpDefinition).count())

    def test_json_stdio_import_stores_destination_environment(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                config = {"command": "node", "args": ["server.js"], "env": {"API_KEY": "source-key"}}
                result = self.import_source(
                    {"mcpServers": {"example": config}} if wrapped else config,
                    transport="json", env={"API_KEY": "destination-key"},
                )
                self.assertEqual("stdio", result["transport_type"])
                connection = self.connect_import(result, env={"API_KEY": "destination-key"})
                overrides = json.loads(self.db.get(McpConnection, connection["id"]).config_overrides_json)
                self.assertEqual({"API_KEY": "destination-key"}, read_env(overrides))
                revision = self.db.get(McpRevision, result["latest_revision"]["id"])
                self.assertNotIn("{{credential}}", revision.config_json)
                runtime = self.runtime()
                mcp = next(item for item in runtime["mcps"] if item.name == result["name"])
                config, warnings = build_mcp_json([mcp])
                self.assertEqual([], warnings)
                server, = config["mcpServers"].values()
                self.assertEqual("node", server["command"])
                self.assertEqual("destination-key", runtime["secret_env"][server["env"]["API_KEY"][2:-1]])

    def test_json_import_rejects_ambiguous_or_invalid_server_wrappers(self):
        for servers in ({}, {"one": {}, "two": {}}, {"one": None}, []):
            with self.subTest(servers=servers), self.assertRaises(HTTPException) as caught:
                self.import_source({"mcpServers": servers}, transport="json")
            self.assertEqual(400, caught.exception.status_code)
        self.assertEqual(0, self.db.query(McpDefinition).count())

    def test_import_stdio_environment_values_are_entered_for_destination(self):
        values = {"API_KEY": "personal-key", "REGION": "cn-shanghai"}
        result = self.import_source(
            {"command": "node", "args": ["server.js"], "env": {"API_KEY": "source-key", "REGION": "source-region"}},
            transport="stdio", env=values,
        )
        revision = self.db.get(McpRevision, result["latest_revision"]["id"])
        self.assertNotIn(ENCRYPTED_ENV, revision.config_json)
        connection = self.connect_import(result, env=values)
        overrides = json.loads(self.db.get(McpConnection, connection["id"]).config_overrides_json)
        self.assertEqual(values, read_env(overrides))
        runtime = self.runtime()
        self.assertEqual(set(values.values()), set(runtime["secret_env"].values()))

    def test_stdio_environment_editor_preserves_blank_and_rotates_values(self):
        result = self.import_source(
            {"command": "node", "env": {"API_KEY": "source", "REGION": "source-region"}},
            transport="stdio", env={"API_KEY": "personal", "REGION": "cn-shanghai"},
        )
        connection = self.connect_import(result, env={"API_KEY": "personal", "REGION": "cn-shanghai"})
        fields = get_mcp_secrets("connections", connection["id"], self.db, self.user)["fields"]
        self.assertEqual({"API_KEY", "REGION"}, {item["name"] for item in fields})
        update_mcp_secrets(
            "connections", connection["id"],
            McpSecretUpdateRequest(values={"API_KEY": None, "REGION": "new-region"}),
            self.db, self.user,
        )
        runtime = self.runtime()
        self.assertEqual({"personal", "new-region"}, set(runtime["secret_env"].values()))

    def test_import_foreign_public_headers_does_not_copy_credential(self):
        result = self.import_source({
            "url": "https://mcp.example.com/mcp",
            "headers": {"Authorization": "Bearer other-user-secret"},
        }, owner=8, public=True, headers={"Authorization": "Bearer personal-secret"})
        revision = self.db.get(McpRevision, result["latest_revision"]["id"])
        self.assertNotIn("other-user-secret", revision.config_json)
        self.assertNotIn("{{credential}}", revision.config_json)
        connection = self.connect_import(result, headers={"Authorization": "Bearer personal-secret"})
        self.assertEqual({"Authorization": "Bearer personal-secret"}, read_headers(json.loads(self.db.get(McpConnection, connection["id"]).config_overrides_json)))

    def test_owner_source_header_changes_sync_to_workbench_copy(self):
        result = self.import_source({
            "url": "https://mcp.example.com/mcp",
            "headers": {"X-Tenant": "tenant-before"},
        }, headers={"X-Tenant": "tenant-workbench"})
        connection = self.connect_import(result, headers={"X-Tenant": "tenant-workbench"})
        source = self.db.get(McpService, result["source_mcp_service_id"])
        source.store_config(json.dumps({
            "url": "https://mcp.example.com/mcp",
            "headers": {"X-Tenant": "tenant-after"},
        }))
        with patch("asset_routes.validate_mcp_config", return_value={}):
            self.assertEqual(1, sync_owned_mcp_source(self.db, source))
        self.db.commit()

        runtime = self.runtime()
        self.assertEqual({"tenant-workbench"}, set(runtime["secret_env"].values()))
        self.assertNotEqual(connection["revision_id"], self.db.get(McpConnection, connection["id"]).revision_id)

    def test_expert_import_uses_destination_headers(self):
        with patch("asset_routes._agent", return_value=SimpleNamespace(id=99, kind="expert")):
            result = self.import_source(
                {
                    "url": "https://mcp.example.com/mcp",
                    "headers": {"aaa": "234", "ddd": "Bearer source-secret"},
                },
                agent_id=99, headers={"aaa": "agent-value", "ddd": "agent-secret"},
            )
        revision = self.db.get(McpRevision, result["latest_revision"]["id"])
        config = json.loads(revision.config_json)
        self.assertNotIn(ENCRYPTED_HEADERS, config)
        with patch("asset_routes._agent", return_value=SimpleNamespace(id=99, kind="expert")), patch(
            "asset_routes.bind_agent_workspace", return_value=(SimpleNamespace(id=1), None),
        ):
            connection = self.connect_import(
                result,
                agent_id=99,
                headers={"aaa": "agent-value", "ddd": "agent-secret"},
            )
        with patch("asset_routes._agent", return_value=SimpleNamespace(id=99, kind="expert")):
            self.assertEqual(
                {"aaa", "ddd"},
                {item["name"] for item in get_mcp_headers("connections", connection["id"], self.db, self.user, agent_id=99)["headers"]},
            )

    def test_import_foreign_private_source_remains_inaccessible(self):
        with self.assertRaises(HTTPException) as caught:
            self.import_source({"url": "https://mcp.example.com/mcp"}, owner=8)
        self.assertEqual(404, caught.exception.status_code)

    def test_import_without_headers_does_not_require_encryption_key(self):
        with patch.object(settings, "agent_credential_encryption_key", ""):
            result = self.import_source({"url": "https://mcp.example.com/mcp"}, encrypted=False)
            self.connect_import(result)

    def test_import_config_values_replace_legacy_placeholders(self):
        for config in (
            {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "{{credential}}"}},
            {"url": "https://mcp.example.com/mcp", "headers": {"X-Tenant": "demo"},
             "env": {"API_KEY": "{{credential}}"}},
        ):
            with self.subTest(config=config):
                result = self.import_source(
                    config,
                    headers={name: "Bearer personal-secret" for name in config.get("headers", {})},
                )
                self.connect_import(
                    result,
                    headers={name: "Bearer personal-secret" for name in config.get("headers", {})},
                )
                revision = self.db.get(McpRevision, result["latest_revision"]["id"])
                self.assertNotIn("{{credential}}", revision.config_json)

    def test_system_create_encrypts_headers_and_runtime_receives_exact_bearer(self):
        with patch("asset_routes.validate_mcp_config", return_value={}):
            result = create_system_mcp_definition(McpDefinitionCreateRequest(
                name="GitLab", transport_type="streamable_http",
                config={"url": "http://172.26.36.234:3333/mcp"},
                headers={"Authorization": "Bearer test-token", "X-Tenant": "demo"},
            ), self.db, self.admin)
        revision = self.db.get(McpRevision, result["latest_revision"]["id"])
        self.assertNotIn("test-token", revision.config_json)
        self.assertNotIn("test-token", json.dumps(result))
        response = get_mcp_headers("definitions", result["id"], self.db, self.admin)
        self.assertEqual({
            "auth_mode": "manual",
            "headers": [
                {"name": "Authorization", "value": "", "configured": True},
                {"name": "X-Tenant", "value": "", "configured": True},
            ]
        }, response)
        runtime = self.runtime()
        self.assertIn("Bearer test-token", runtime["secret_env"].values())
        self.assertNotIn("test-token", runtime["mcps"][0].config)
        self.assertNotIn(ENCRYPTED_HEADERS, runtime["mcps"][0].config)
        config = json.loads(runtime["mcps"][0].config)
        ref = config["headers"]["Authorization"][2:-1]
        self.assertEqual("Bearer test-token", runtime["secret_env"][ref])
        claude_config, warnings = build_mcp_json(runtime["mcps"])
        self.assertEqual([], warnings)
        self.assertEqual(config["headers"], claude_config["mcpServers"]["GitLab"]["headers"])

    def test_personal_update_preserve_rotate_delete_and_isolation(self):
        self.add_definition(31, 32, "GitLab", "user", "http://127.0.0.1/mcp", 7)
        self.add_connection(51, 31, 32, "GitLab", {"timeout": 15})
        self.db.commit()
        self.update("connections", 51, {"Authorization": "Bearer first", "Private-Token": "second"})
        self.update("connections", 51, {"Authorization": None, "Private-Token": "rotated"})
        self.assertEqual({
            "auth_mode": "manual",
            "headers": [
                {"name": "Authorization", "value": "", "configured": True},
                {"name": "Private-Token", "value": "", "configured": True},
            ]
        }, get_mcp_headers("connections", 51, self.db, self.user))
        runtime = self.runtime()
        self.assertEqual({"Bearer first", "rotated"}, set(runtime["secret_env"].values()))
        self.assertEqual(15, json.loads(runtime["mcps"][0].config)["timeout"])
        with self.assertRaises(HTTPException) as caught:
            self.update("connections", 51, {}, CurrentUser(9))
        self.assertEqual(404, caught.exception.status_code)
        self.update("connections", 51, {})
        self.assertEqual({}, json.loads(self.runtime()["mcps"][0].config)["headers"])
        for row in self.db.query(AssetSecurityEvent).all():
            self.assertNotIn("Bearer first", row.details_json)
            self.assertNotIn("rotated", row.details_json)

    def test_system_edit_publishes_revision_and_requires_admin(self):
        self.add_definition(21, 22, "GitLab", "system", "http://127.0.0.1/mcp", 8)
        self.db.commit()
        with self.assertRaises(HTTPException):
            self.update("definitions", 21, {"Authorization": "Bearer denied"})
        self.update("definitions", 21, {"Authorization": "Bearer allowed"}, self.admin)
        self.assertEqual(2, self.db.query(McpRevision).filter_by(definition_id=21).count())
        self.assertNotIn(ENCRYPTED_HEADERS, self.db.get(McpRevision, 22).config_json)
        self.assertIn("Bearer allowed", self.runtime()["secret_env"].values())

    def test_invalid_headers_rejected_and_ciphertext_not_accepted_from_config(self):
        for headers in [
            {"Authorization": "a\r\nb"}, {"Bad Name": "test"},
            {"Authorization": "a", "authorization": "b"}, {"Authorization": None},
        ]:
            with self.subTest(headers=list(headers)), self.assertRaises(ValueError):
                store_headers({}, headers)
        config = store_headers({}, {"Authorization": "Bearer secret"})
        self.assertEqual({}, _sanitize_mcp_config(config))
        self.assertEqual({"Authorization": "Bearer secret"}, read_headers(config))

    def test_personal_system_headers_merge_and_remain_private(self):
        self.add_definition(21, 22, "GitLab", "system", "https://system.example.com", 8)
        self.db.commit()
        self.update("definitions", 21, {"Authorization": "Bearer default", "X-Tenant": "shared"}, self.admin)
        revisions_before = self.db.query(McpRevision).count()
        self.update("system", 21, {"authorization": "Bearer user-seven", "X-User": "seven"})
        self.update("system", 21, {"authorization": None, "X-User": "rotated"})
        saved = self.db.query(McpUserHeaders).one()
        self.assertNotIn("user-seven", saved.headers_encrypted)
        self.assertEqual(revisions_before, self.db.query(McpRevision).count())
        runtime = self.runtime()
        self.assertEqual({"Bearer user-seven", "shared", "rotated"}, set(runtime["secret_env"].values()))
        config = json.loads(runtime["mcps"][0].config)
        self.assertEqual("https://system.example.com", config["url"])
        self.assertEqual({"authorization", "X-Tenant", "X-User"}, set(config["headers"]))
        self.assertNotIn("user-seven", json.dumps(runtime["mcp_snapshot"]))
        self.assertEqual({
            "auth_mode": "manual",
            "inherit_system": False,
            "system_auth_mode": "manual",
            "headers": [
                {"name": "authorization", "value": "", "configured": True},
                {"name": "X-User", "value": "", "configured": True},
            ]
        }, get_mcp_headers("system", 21, self.db, self.user))
        self.assertEqual({"auth_mode": "manual", "headers": [], "inherit_system": True, "system_auth_mode": "manual"}, get_mcp_headers("system", 21, self.db, CurrentUser(9)))
        with patch("asset_runtime.validate_mcp_config", return_value={}):
            other = load_runtime_assets(self.db, SimpleNamespace(kind="personal_default"), 9)
        self.assertEqual({"Bearer default", "shared"}, set(other["secret_env"].values()))

        with patch("asset_runtime.validate_mcp_config", return_value={}):
            expert = load_runtime_assets(self.db, SimpleNamespace(kind="expert", id=99), 7)
        self.assertEqual(expert["secret_env"], {})
        self.assertEqual(expert["mcps"], [])

        self.update(
            "system",
            21,
            {"X-User": "rotated"},
            auth_mode="current_user",
        )
        current_user_runtime = self.runtime("Bearer current-user")
        self.assertEqual(
            {"Bearer current-user", "shared", "rotated"},
            set(current_user_runtime["secret_env"].values()),
        )
        self.assertNotIn(
            "current-user",
            json.dumps(current_user_runtime["mcp_snapshot"]),
        )

        self.update("system", 21, {})
        self.assertEqual({"Bearer default", "shared"}, set(self.runtime()["secret_env"].values()))
        self.assertEqual({"auth_mode": "manual", "headers": [], "inherit_system": False, "system_auth_mode": "manual"}, get_mcp_headers("system", 21, self.db, self.user))
        for event in self.db.query(AssetSecurityEvent).all():
            self.assertNotIn("user-seven", event.details_json)

    def test_personal_system_header_endpoint_rejects_other_scopes_and_deleted_definitions(self):
        self.add_definition(21, 22, "System", "system", "https://system.example.com", 8)
        self.add_definition(31, 32, "Private", "user", "https://private.example.com", 8)
        self.db.commit()
        for definition_id in [31, 999]:
            with self.assertRaises(HTTPException) as caught:
                self.update("system", definition_id, {"Authorization": "denied"})
            self.assertEqual(404, caught.exception.status_code)
        self.db.get(McpDefinition, 21).status = "deleted"
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            get_mcp_headers("system", 21, self.db, self.user)
        self.assertEqual(404, caught.exception.status_code)

    def test_system_auth_default_is_inherited_and_uses_each_callers_token(self):
        self.add_definition(21, 22, "Online MCP", "system", "https://mcp.example.com/mcp", 8)
        self.db.commit()
        self.update("definitions", 21, {"X-Tenant": "shared"}, self.admin, auth_mode="current_user")
        definition = self.db.get(McpDefinition, 21)
        revision = self.db.query(McpRevision).filter_by(definition_id=21).order_by(McpRevision.version.desc()).first()
        self.assertEqual("current_user", _definition_payload(definition, revision)["auth_mode"])
        self.assertEqual("current_user", _system_mcp_payload(definition, revision)["auth_mode"])
        response = get_mcp_headers("system", 21, self.db, self.user)
        self.assertEqual({"auth_mode": "current_user", "system_auth_mode": "current_user", "inherit_system": True, "headers": []}, response)
        self.assertEqual("current_user", get_mcp_headers("definitions", 21, self.db, self.admin)["auth_mode"])
        self.assertEqual(0, self.db.query(McpUserHeaders).count())
        for user_id in (7, 9):
            with patch("asset_runtime.validate_mcp_config", return_value={}):
                runtime = load_runtime_assets(self.db, SimpleNamespace(kind="personal_default"), user_id,
                                              request_authorization=f"Bearer caller-{user_id}")
            self.assertEqual({f"Bearer caller-{user_id}", "shared"}, set(runtime["secret_env"].values()))
            self.assertTrue(runtime["uses_current_user_authorization"])
            self.assertNotIn(f"caller-{user_id}", json.dumps(runtime["mcp_snapshot"]))
            self.assertNotIn(f"caller-{user_id}", revision.config_json)
        with self.assertRaisesRegex(RuntimeError, "没有可用的 Bearer Token"):
            self.runtime()

        with self.assertRaisesRegex(RuntimeError, "后台渠道没有可复用的浏览器 Bearer Token"):
            self.runtime(source="weixin_clawbot")

    def test_personal_override_is_isolated_and_can_return_to_live_inheritance(self):
        self.add_definition(21, 22, "Online MCP", "system", "https://mcp.example.com/mcp", 8)
        self.db.commit()
        self.update("definitions", 21, {"X-Tenant": "shared"}, self.admin, auth_mode="current_user")
        self.update("system", 21, {"Authorization": "Bearer personal"})
        self.assertEqual({"Bearer personal", "shared"}, set(self.runtime()["secret_env"].values()))
        self.update("definitions", 21, {"Authorization": "Bearer system", "X-Tenant": "updated"}, self.admin)
        self.assertEqual({"Bearer personal", "updated"}, set(self.runtime()["secret_env"].values()))
        self.update("system", 21, {}, auth_mode="none")
        self.assertEqual({"updated"}, set(self.runtime()["secret_env"].values()))
        with patch("asset_runtime.validate_mcp_config", return_value={}):
            other = load_runtime_assets(self.db, SimpleNamespace(kind="personal_default"), 9)
        self.assertEqual({"Bearer system", "updated"}, set(other["secret_env"].values()))
        # Reading inherited settings never discloses the shared credential to users.
        self.assertEqual([], get_mcp_headers("system", 21, self.db, CurrentUser(9))["headers"])
        response = update_mcp_headers("system", 21, McpHeadersUpdateRequest(headers={}, inherit_system=True), self.db, self.user)
        self.assertTrue(response["inherit_system"])
        self.assertEqual(0, self.db.query(McpUserHeaders).count())
        self.assertEqual({"Bearer system", "updated"}, set(self.runtime()["secret_env"].values()))
        self.update("definitions", 21, {}, self.admin, auth_mode="current_user")
        self.assertEqual("current_user", get_mcp_headers("system", 21, self.db, self.user)["auth_mode"])
        self.assertEqual({"Bearer restored"}, set(self.runtime("Bearer restored")["secret_env"].values()))

    def test_system_auth_mode_requires_admin_and_rejects_non_http_identity_reuse(self):
        self.add_definition(21, 22, "Online MCP", "system", "https://mcp.example.com/mcp", 8)
        self.db.commit()
        with self.assertRaises(HTTPException):
            self.update("definitions", 21, {}, auth_mode="current_user")
        self.assertEqual("manual", self.db.get(McpDefinition, 21).auth_mode)
        self.db.get(McpDefinition, 21).transport_type = "stdio"
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            self.update("definitions", 21, {}, self.admin, auth_mode="current_user")
        self.assertEqual(400, error.exception.status_code)

    @patch("asset_routes._validated_mcp_config", return_value=({"url": "https://public.example.com"}, {}))
    @patch("asset_routes.validate_mcp_config", return_value={})
    @patch("asset_runtime.validate_mcp_config", return_value={})
    def test_expert_can_install_public_service_already_used_as_global_default(self, *_):
        self.db.add(McpService(id=55, user_id=8, name="Public tool", type="http", config='{"url":"https://public.example.com"}', is_public=True))
        self.add_definition(21, 22, "Public tool", "system", "https://system.example.com", 8)
        self.db.flush()
        self.db.get(McpDefinition, 21).source_mcp_service_id = 55
        self.db.commit()
        with patch("asset_routes._agent", return_value=SimpleNamespace(id=99, kind="expert")), patch(
            "asset_routes.bind_agent_workspace", return_value=(SimpleNamespace(id=1), None),
        ):
            definition = import_mcp_definition(McpImportRequest(source_mcp_service_id=55, agent_id=99), db=self.db, current_user=self.user)
            self.assertEqual(definition["scope"], "user")
            connection = create_mcp_connection(McpConnectionCreateRequest(
                definition_id=definition["id"], revision_id=definition["latest_revision"]["id"],
                name="Public tool", agent_id=99,
            ), db=self.db, current_user=self.user)
        result = load_runtime_assets(self.db, SimpleNamespace(kind="expert", id=99), 7)
        self.assertEqual([item.id for item in result["mcps"]], [connection["id"]])
        self.assertEqual(result["mcp_snapshot"][0]["source"], "personal")
        self.assertEqual(result["secret_env"], {})

    def test_current_user_auth_replaces_only_authorization_for_this_run(self):
        self.add_definition(31, 32, "Online MCP", "user", "https://mcp.example.com/mcp", 7)
        self.add_connection(51, 31, 32, "Online MCP")
        self.db.commit()

        self.update(
            "connections",
            51,
            {"Authorization": "Bearer stored", "X-Tenant": "tenant-seven"},
        )
        self.update(
            "connections",
            51,
            {"X-Tenant": "tenant-seven"},
            auth_mode="current_user",
        )

        saved = get_mcp_headers("connections", 51, self.db, self.user)
        self.assertEqual("current_user", saved["auth_mode"])
        self.assertEqual(
            [{"name": "X-Tenant", "value": "", "configured": True}],
            saved["headers"],
        )

        runtime = self.runtime("Bearer current-access-token")
        self.assertEqual(
            {"Bearer current-access-token", "tenant-seven"},
            set(runtime["secret_env"].values()),
        )
        config = json.loads(runtime["mcps"][0].config)
        self.assertEqual({"Authorization", "X-Tenant"}, set(config["headers"]))
        self.assertTrue(runtime["uses_current_user_authorization"])
        self.assertNotIn("current-access-token", json.dumps(runtime["mcp_snapshot"]))
        self.assertNotIn(
            "current-access-token",
            self.db.get(McpConnection, 51).config_overrides_json,
        )

        with self.assertRaisesRegex(RuntimeError, "没有可用的 Bearer Token"):
            self.runtime()


if __name__ == "__main__":
    unittest.main()
