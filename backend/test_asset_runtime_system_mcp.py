import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from asset_runtime import load_runtime_assets
from models import (
    CredentialReference, ExpertMcpBinding, ExpertSkillBinding,
    McpConnection,
    McpUserHeaders,
    McpDefinition,
    McpRevision,
    Skill,
    SkillInstallation,
    SkillRelease,
    SystemSkillInstallation,
    UserWorkspace,
)


class SystemMcpRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for table in (
            ExpertMcpBinding.__table__,
            ExpertSkillBinding.__table__,
            UserWorkspace.__table__,
            Skill.__table__,
            SkillRelease.__table__,
            SkillInstallation.__table__,
            SystemSkillInstallation.__table__,
            CredentialReference.__table__,
            McpDefinition.__table__,
            McpRevision.__table__,
            McpConnection.__table__,
            McpUserHeaders.__table__,
        ):
            table.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(UserWorkspace(id=1, workspace_key="workspace-7", user_id=7))

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_definition(self, definition_id, revision_id, name, scope, url, owner_user_id):
        self.db.add(McpDefinition(
            id=definition_id,
            owner_user_id=owner_user_id,
            scope=scope,
            name=name,
            transport_type="http",
            status="published",
        ))
        self.db.add(McpRevision(
            id=revision_id,
            definition_id=definition_id,
            version=1,
            config_json=json.dumps({"url": url}),
            content_sha256=str(definition_id) * 32,
            status="published",
            security_report_json="{}",
            created_by=owner_user_id,
        ))

    def add_connection(self, connection_id, definition_id, revision_id, name, overrides=None):
        self.db.add(McpConnection(
            id=connection_id,
            user_id=7,
            workspace_id=1,
            definition_id=definition_id,
            revision_id=revision_id,
            name=name,
            config_overrides_json=json.dumps(overrides or {}),
            tool_policy_json='{"risk_level":"read","allowed_tools":[]}',
            status="active",
        ))

    @patch("asset_runtime.validate_mcp_config", return_value={"status": "passed"})
    def test_system_mcp_is_always_loaded_and_cannot_be_overridden(self, _validate):
        self.add_definition(21, 22, "企业知识库", "system", "https://system.example.com", 8)
        self.add_definition(31, 32, "个人知识库", "user", "https://personal.example.com", 7)
        self.add_definition(41, 42, "研发工具", "user", "https://dev.example.com", 7)
        self.add_connection(
            51,
            21,
            22,
            "改名后的系统连接",
            {"url": "https://override.example.com"},
        )
        self.add_connection(52, 31, 32, "企业知识库")
        self.add_connection(53, 41, 42, "研发工具")
        self.db.commit()

        result = load_runtime_assets(
            self.db,
            SimpleNamespace(kind="personal_default"),
            7,
        )

        self.assertEqual(["企业知识库", "研发工具"], [item.name for item in result["mcps"]])
        system_config = json.loads(result["mcps"][0].config)
        self.assertEqual("https://system.example.com", system_config["url"])
        self.assertEqual(
            ["system_default", "personal"],
            [item["source"] for item in result["mcp_snapshot"]],
        )

    @patch("asset_runtime.validate_mcp_config", return_value={})
    def test_expert_uses_only_bound_connections_even_with_same_named_default(self, _validate):
        self.add_definition(21, 22, "Tools", "system", "https://system.example.com", 8)
        self.add_definition(31, 32, "Tools", "user", "https://personal.example.com", 7)
        self.add_connection(51, 31, 32, "Tools")
        self.db.get(McpConnection, 51).scope_agent_id = 99
        self.db.add(ExpertMcpBinding(id=1, agent_id=99, connection_id=51))
        self.db.commit()
        for source in ("web", "weixin_clawbot", "dingtalk_clawbot"):
            result = load_runtime_assets(self.db, SimpleNamespace(kind="expert", id=99), 7, source=source)
            self.assertEqual([item.id for item in result["mcps"]], [51])
            self.assertEqual(json.loads(result["mcps"][0].config)["url"], "https://personal.example.com")
            self.assertEqual(result["mcp_snapshot"][0]["source"], "personal")
        self.assertEqual(load_runtime_assets(self.db, SimpleNamespace(kind="expert", id=100), 7)["mcps"], [])
        self.assertEqual(load_runtime_assets(self.db, SimpleNamespace(kind="expert", id=99), 8)["mcps"], [])
        self.db.get(ExpertMcpBinding, 1).status = "disabled"
        self.db.commit()
        self.assertEqual(load_runtime_assets(self.db, SimpleNamespace(kind="expert", id=99), 7)["mcps"], [])


if __name__ == "__main__":
    unittest.main()
