"""Optional migration integration test against a dedicated empty MySQL database.

AIHUB_TEST_MYSQL_URL must name a disposable database starting test_aihub_asset_.
The database is never dropped by this test.
"""
import importlib.util
import os
from pathlib import Path
import unittest

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from asset_scopes import migrate_agent_asset_scopes
from models import (
    Base, Agent, CredentialReference, ExpertMcpBinding, ExpertSkillBinding,
    McpConnection, McpDefinition, McpRevision, Skill, SkillInstallation, SkillRelease,
    UserWorkspace,
)


@unittest.skipUnless(os.environ.get("AIHUB_TEST_MYSQL_URL"), "Requires a disposable MySQL database")
class AgentAssetMigrationMySQLTests(unittest.TestCase):
    def test_upgrade_legacy_schema_and_repeat_without_resetting_configuration(self):
        url = make_url(os.environ["AIHUB_TEST_MYSQL_URL"])
        self.assertTrue(url.database.startswith("test_aihub_asset_"))
        engine = create_engine(url, hide_parameters=True)
        self.addCleanup(engine.dispose)
        self.assertEqual(inspect(engine).get_table_names(), [], "Test database must be empty")
        Base.metadata.create_all(engine)
        with Session(engine) as db, db.begin():
            db.add(UserWorkspace(id=1, user_id=7, workspace_key="test-personal"))
            db.add(Skill(id=1, user_id=7, name="Skill", version="1.0"))
            db.flush()
            db.add(SkillRelease(id=1, skill_id=1, version="1.0", file_path="test.zip", file_url="/releases/test.zip", status="published"))
            db.add_all([Agent(id=99, user_id=7, name="A"), Agent(id=100, user_id=7, name="B")])
            db.add(McpDefinition(id=1, owner_user_id=7, name="MCP", transport_type="http", scope="user", status="published"))
            db.add(CredentialReference(id=1, user_id=7, name="test-vault", secret_encrypted="test-ciphertext", fingerprint="a" * 64))
            db.flush()
            db.add(McpRevision(id=1, definition_id=1, version=1, config_json='{"url":"https://example.com"}', content_sha256="a" * 64, status="published", created_by=7))
            db.add(SkillInstallation(id=1, user_id=7, workspace_id=1, skill_id=1, release_id=1))
            db.flush()
            db.add(McpConnection(id=1, user_id=7, workspace_id=1, definition_id=1, revision_id=1, credential_reference_id=1, name="MCP", auth_mode="current_user"))
            db.flush()
            for agent_id in (99, 100):
                db.add(ExpertSkillBinding(agent_id=agent_id, installation_id=1))
                db.add(ExpertMcpBinding(agent_id=agent_id, connection_id=1, status="disabled" if agent_id == 100 else "active"))

        path = Path(__file__).with_name("migrations") / "049_agent_asset_scopes.py"
        spec = importlib.util.spec_from_file_location("migration049", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as connection:
            for table, (key, new_index) in migration.TABLES.items():
                connection.exec_driver_sql(f"ALTER TABLE `{table}` DROP INDEX `{new_index}`, DROP COLUMN scope_agent_id, ADD UNIQUE KEY legacy_user_asset (user_id, `{key}`)")
            migration.apply_schema(connection)
        workspace = migration.migration_workspace
        def fail_second_workspace(db, agent):
            if agent.id == 100:
                raise RuntimeError("simulated migration failure")
            return workspace(db, agent)
        with self.assertRaises(RuntimeError):
            with Session(engine) as db, db.begin():
                migrate_agent_asset_scopes(db, fail_second_workspace)
        with Session(engine) as db:
            self.assertEqual(db.query(SkillInstallation).count(), 1)
            self.assertEqual(db.query(McpConnection).count(), 1)
            self.assertEqual(db.query(UserWorkspace).count(), 1)
            self.assertEqual({b.installation_id for b in db.query(ExpertSkillBinding)}, {1})
        with Session(engine) as db, db.begin():
            self.assertEqual(migrate_agent_asset_scopes(db, workspace), {"skills": 2, "mcps": 2})
            for model in (SkillInstallation, McpConnection, CredentialReference):
                self.assertEqual({r.scope_agent_id for r in db.query(model)}, {0, 99, 100})
            self.assertEqual(db.query(McpConnection).filter_by(scope_agent_id=100).one().status, "disabled")
            db.query(McpConnection).filter_by(scope_agent_id=99).one().auth_mode = "none"
        with engine.begin() as connection:
            migration.apply_schema(connection)
        with Session(engine) as db, db.begin():
            self.assertEqual(migrate_agent_asset_scopes(db, workspace), {"skills": 0, "mcps": 0})
            self.assertEqual(db.query(McpConnection).filter_by(scope_agent_id=99).one().auth_mode, "none")


if __name__ == "__main__":
    unittest.main()
