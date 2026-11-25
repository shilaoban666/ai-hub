import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from asset_routes import (
    change_skill_release, rollback_skill, uninstall_skill, install_skill,
    get_mcp_headers, update_mcp_headers, create_mcp_connection, delete_mcp_connection,
    list_mcp_connections, list_skill_installations, rotate_credential,
    delete_credential,
    _encrypt_secret,
)
from asset_runtime import load_runtime_assets
from asset_scopes import connection_config, migrate_agent_asset_scopes, scoped_credential
from asset_schemas import (
    SkillInstallRequest, SkillChangeReleaseRequest, McpHeadersUpdateRequest,
    McpConnectionCreateRequest, CredentialRotateRequest,
)
from auth import CurrentUser
from models import (
    Agent, CredentialReference, ExpertMcpBinding, ExpertSkillBinding, McpConnection,
    McpDefinition, McpRevision, SkillInstallation,
)
from mcp_headers import read_headers, store_headers
import test_global_skill_installation as skill_fixtures


class AssetScopeIsolationTests(unittest.TestCase):
    def setUp(self):
        skill_fixtures.GlobalSkillInstallationTests.setUp(self)
        self.db.autoflush = True
        Agent.__table__.create(self.engine)
        for agent_id in (7, 99, 100):
            self.db.add(Agent(id=agent_id, user_id=7, name=f"Agent {agent_id}", kind="expert"))
        self.db.commit()
        key = patch("credential_crypto.settings.agent_credential_encryption_key", "a" * 32)
        key.start()
        self.addCleanup(key.stop)
        validate = patch("asset_runtime.validate_mcp_config", return_value={})
        validate.start()
        self.addCleanup(validate.stop)

    def workspace(self, db, agent):
        return SimpleNamespace(id=agent.id)

    def assert_connection_headers(self, connection_id, expected, agent_id=None):
        # The API masks secrets; check the stored effective config for isolation.
        self.assertEqual(
            get_mcp_headers("connections", connection_id, self.db, self.user, agent_id=agent_id)["headers"],
            [{"name": name, "value": "", "configured": True} for name in expected],
        )
        connection = self.db.get(McpConnection, connection_id)
        revision = self.db.get(McpRevision, connection.revision_id)
        self.assertEqual(read_headers(connection_config(connection, revision)), expected)

    def migrate(self):
        result = migrate_agent_asset_scopes(self.db, self.workspace)
        self.db.commit()
        return result

    def install(self, agent_id):
        with patch("asset_routes.bind_agent_workspace", return_value=(SimpleNamespace(id=agent_id), None)):
            return install_skill(SkillInstallRequest(release_id=11, agent_id=agent_id), self.db, self.user)

    def test_skill_versions_rollback_and_uninstall_are_independent(self):
        a, b = self.install(99), self.install(100)
        self.assertEqual(len({1, a["id"], b["id"]}), 3)
        change_skill_release(a["id"], SkillChangeReleaseRequest(release_id=12, agent_id=99), self.db, self.user)
        self.assertEqual(self.db.get(SkillInstallation, 1).release_id, 11)
        self.assertEqual(self.db.get(SkillInstallation, b["id"]).release_id, 11)
        with self.assertRaises(HTTPException):
            change_skill_release(1, SkillChangeReleaseRequest(release_id=12, agent_id=99), self.db, self.user)
        runtime = load_runtime_assets(self.db, SimpleNamespace(id=99, kind="expert"), 7)
        self.assertEqual([row["release_id"] for row in runtime["skill_snapshot"]], [12])
        rollback_skill(a["id"], self.db, self.user, agent_id=99)
        self.assertEqual(self.db.get(SkillInstallation, a["id"]).release_id, 11)
        uninstall_skill(1, self.db, self.user)
        self.assertEqual(self.db.get(SkillInstallation, a["id"]).status, "active")
        self.assertEqual(self.db.get(SkillInstallation, b["id"]).status, "active")
        self.assertNotIn(a["id"], [r["id"] for r in list_skill_installations(self.db, self.user)["items"]])
        with self.assertRaises(HTTPException):
            change_skill_release(a["id"], SkillChangeReleaseRequest(release_id=12, agent_id=99), self.db, CurrentUser(8))

    def prepare_shared_mcp(self):
        config = store_headers({"url": "https://mcp.example.com", "env": {"REGION": "old"}}, {"X-Token": "original-test-value"})
        self.db.add(McpDefinition(id=11, owner_user_id=7, name="Shared", scope="user", transport_type="http", status="published"))
        self.db.add(McpRevision(id=12, definition_id=11, version=1, config_json=json.dumps(config), content_sha256="a" * 64, status="published", created_by=7))
        self.db.add(CredentialReference(id=21, user_id=7, name="vault", secret_encrypted=_encrypt_secret(7, "vault", "original-vault"), fingerprint="a" * 64))
        self.db.add(McpConnection(id=31, user_id=7, workspace_id=7, definition_id=11, revision_id=12, credential_reference_id=21, name="Shared", config_overrides_json='{"env":{"EXTRA":"kept"}}', auth_mode="manual", tool_policy_json='{"risk_level":"read"}'))
        self.db.add_all([
            ExpertMcpBinding(id=41, agent_id=99, connection_id=31),
            ExpertMcpBinding(id=42, agent_id=100, connection_id=31, status="disabled"),
            ExpertSkillBinding(id=43, agent_id=99, installation_id=1),
            ExpertSkillBinding(id=44, agent_id=100, installation_id=1),
        ])
        self.db.commit()

    def test_migration_preserves_snapshots_and_is_repeatable(self):
        self.prepare_shared_mcp()
        self.assertEqual(self.migrate(), {"skills": 3, "mcps": 2})
        a = self.db.query(McpConnection).filter_by(scope_agent_id=99).one()
        b = self.db.query(McpConnection).filter_by(scope_agent_id=100).one()
        self.assertEqual(len({31, a.id, b.id}), 3)
        self.assertEqual(len({21, a.credential_reference_id, b.credential_reference_id}), 3)
        self.assertEqual(json.loads(a.config_overrides_json)["env"], {"REGION": "old", "EXTRA": "kept"})
        self.assert_connection_headers(a.id, {"X-Token": "original-test-value"}, agent_id=99)
        update_mcp_headers("connections", a.id, McpHeadersUpdateRequest(headers={"X-Token": "agent-a"}, agent_id=99), self.db, self.user)
        update_mcp_headers("connections", 31, McpHeadersUpdateRequest(headers={"X-Token": "workbench"}), self.db, self.user)
        rotate_credential(21, CredentialRotateRequest(secret="rotated-personal"), self.db, self.user)
        self.assert_connection_headers(b.id, {"X-Token": "original-test-value"}, agent_id=100)
        with self.assertRaises(HTTPException):
            get_mcp_headers("connections", b.id, self.db, self.user, agent_id=99)
        with self.assertRaises(HTTPException):
            update_mcp_headers("connections", 31, McpHeadersUpdateRequest(headers={}, agent_id=99), self.db, self.user)
        self.assertEqual(self.migrate(), {"skills": 0, "mcps": 0})
        self.assert_connection_headers(a.id, {"X-Token": "agent-a"}, agent_id=99)
        runtime = load_runtime_assets(self.db, SimpleNamespace(id=99, kind="expert"), 7)
        self.assertIn("original-vault", runtime["secret_env"].values())
        self.assertIn("agent-a", runtime["secret_env"].values())
        self.assertNotIn("rotated-personal", runtime["secret_env"].values())
        self.assertNotIn("agent-a", json.dumps(runtime["mcp_snapshot"]))
        self.assertEqual(load_runtime_assets(self.db, SimpleNamespace(id=100, kind="expert"), 7)["mcps"], [])
        delete_mcp_connection(31, self.db, self.user)
        self.assertEqual([r["id"] for r in list_mcp_connections(self.db, self.user, 99)["items"]], [a.id])
        self.assertEqual(get_mcp_headers("connections", b.id, self.db, self.user, agent_id=100)["auth_mode"], "manual")

    @patch("asset_routes.validate_mcp_config", return_value={})
    def test_new_expert_connection_never_inherits_personal_headers(self, _validate):
        self.prepare_shared_mcp()
        # Fresh import starts with its own blank auth even when using a definition
        # also referenced by the workbench. A selected Vault value is snapshotted.
        with patch("asset_routes.bind_agent_workspace", return_value=(SimpleNamespace(id=99), None)):
            result = create_mcp_connection(McpConnectionCreateRequest(
                definition_id=11, revision_id=12, name="Shared", agent_id=99,
                credential_reference_id=21,
            ), self.db, self.user)
        self.assertNotEqual(result["id"], 31)
        self.assertEqual(get_mcp_headers("connections", result["id"], self.db, self.user, agent_id=99)["headers"], [])
        self.assert_connection_headers(31, {"X-Token": "original-test-value"})
        self.assertNotEqual(self.db.get(McpConnection, result["id"]).credential_reference_id, 21)

    def test_reselecting_personal_credential_refreshes_only_the_target_agent(self):
        self.prepare_shared_mcp()
        first = scoped_credential(self.db, 7, 21, 99)
        other = scoped_credential(self.db, 7, 21, 100)
        self.db.commit()
        original = self.db.get(CredentialReference, first).fingerprint

        rotate_credential(21, CredentialRotateRequest(secret="new-personal-secret"), self.db, self.user)
        self.assertEqual(self.db.get(CredentialReference, first).fingerprint, original)
        self.assertEqual(self.db.get(CredentialReference, other).fingerprint, original)

        self.assertEqual(scoped_credential(self.db, 7, 21, 99), first)
        self.db.commit()
        self.assertEqual(
            self.db.get(CredentialReference, first).fingerprint,
            self.db.get(CredentialReference, 21).fingerprint,
        )
        self.assertEqual(self.db.get(CredentialReference, other).fingerprint, original)
        with self.assertRaises(HTTPException):
            scoped_credential(self.db, 7, first, 100)
        with self.assertRaises(HTTPException):
            rotate_credential(first, CredentialRotateRequest(secret="forbidden"), self.db, self.user)
        with self.assertRaises(HTTPException):
            delete_credential(first, self.db, self.user)


if __name__ == "__main__":
    unittest.main()
