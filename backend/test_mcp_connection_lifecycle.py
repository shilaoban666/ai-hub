import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from asset_routes import (
    create_mcp_connection,
    delete_mcp_connection,
    list_mcp_connections,
    update_mcp_connection_status,
)
from asset_schemas import McpConnectionCreateRequest, McpConnectionStatusRequest
from auth import CurrentUser
from models import (
    ExpertMcpBinding,
    McpConnection,
    McpDefinition,
    McpRevision,
    McpService,
    McpUserHeaders,
    UserWorkspace,
)


class McpConnectionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for table in (
            UserWorkspace.__table__,
            McpDefinition.__table__,
            McpRevision.__table__,
            McpService.__table__,
            McpConnection.__table__,
            McpUserHeaders.__table__,
            ExpertMcpBinding.__table__,
        ):
            table.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = CurrentUser(user_id=7)
        self.db.add(UserWorkspace(id=1, workspace_key="workspace-7", user_id=7))
        self.db.add(McpDefinition(
            id=11,
            owner_user_id=7,
            scope="user",
            name="ERP",
            transport_type="http",
            status="published",
        ))
        self.db.add(McpRevision(
            id=12,
            definition_id=11,
            version=1,
            config_json='{"url":"https://mcp.example.com"}',
            content_sha256="a" * 64,
            status="published",
            security_report_json="{}",
            created_by=7,
        ))
        self.db.add(McpConnection(
            id=13,
            user_id=7,
            workspace_id=1,
            definition_id=11,
            revision_id=12,
            name="ERP",
            status="active",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @patch("asset_routes.audit_asset")
    def test_disable_enable_and_delete_lifecycle(self, _audit):
        disabled = update_mcp_connection_status(
            13,
            McpConnectionStatusRequest(status="disabled"),
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual("disabled", disabled["status"])
        self.assertEqual(1, list_mcp_connections(db=self.db, current_user=self.user)["total"])

        enabled = update_mcp_connection_status(
            13,
            McpConnectionStatusRequest(status="active"),
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual("active", enabled["status"])

        delete_mcp_connection(13, db=self.db, current_user=self.user)
        self.assertEqual(0, list_mcp_connections(db=self.db, current_user=self.user)["total"])

    def test_status_schema_rejects_deleted_state(self):
        with self.assertRaises(ValidationError):
            McpConnectionStatusRequest(status="deleted")

    def test_system_mcp_is_visible_as_read_only_connection(self):
        self.db.add(McpDefinition(
            id=21,
            owner_user_id=8,
            scope="system",
            name="企业知识库",
            transport_type="http",
            status="published",
        ))
        self.db.add(McpRevision(
            id=22,
            definition_id=21,
            version=1,
            config_json='{"url":"https://knowledge.example.com"}',
            content_sha256="b" * 64,
            status="published",
            security_report_json="{}",
            created_by=8,
        ))
        self.db.commit()

        result = list_mcp_connections(db=self.db, current_user=self.user)
        system_item = next(item for item in result["items"] if item["is_system"])

        self.assertEqual("system_default", system_item["source"])
        self.assertEqual("active", system_item["status"])
        self.assertEqual("企业知识库", system_item["name"])

        with self.assertRaises(HTTPException) as context:
            create_mcp_connection(
                McpConnectionCreateRequest(
                    definition_id=21,
                    revision_id=22,
                    name="自定义系统连接",
                ),
                db=self.db,
                current_user=self.user,
            )
        self.assertEqual(409, context.exception.status_code)


if __name__ == "__main__":
    unittest.main()
