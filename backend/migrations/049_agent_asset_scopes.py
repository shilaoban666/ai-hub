"""Run after 048 with backend/channel workers stopped:

    python migrations/049_agent_asset_scopes.py --apply

Schema changes are idempotent (MySQL DDL auto-commits). Data copies and binding
rewrites commit together; retrying never overwrites an already isolated record.
Uses the backend's configured database. Does not decrypt or print credentials.
"""
import argparse
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from asset_scopes import migrate_agent_asset_scopes
from database import engine, settings
from models import UserWorkspace


TABLES = {
    "skill_installations": ("skill_id", "uq_skill_installations_user_scope_skill"),
    "mcp_connections": ("name", "uq_mcp_connections_user_scope_name"),
    "credential_references": ("name", "uq_credential_references_user_scope_name"),
}


def migration_workspace(db, agent):
    # ensure_user_workspace commits internally; migration must own its transaction.
    workspace = db.query(UserWorkspace).filter_by(user_id=agent.user_id, agent_id=agent.id).one_or_none()
    if workspace is None:
        workspace = UserWorkspace(
            workspace_key=uuid.uuid4().hex, user_id=agent.user_id, agent_id=agent.id,
            quota_bytes=max(0, int(settings.user_workspace_quota_bytes)),
        )
        db.add(workspace)
        db.flush()
    agent.workspace_id = workspace.id
    return workspace


def apply_schema(connection):
    if connection.dialect.name != "mysql":
        raise RuntimeError("This schema migration requires MySQL")
    inspector = inspect(connection)
    if "status" not in {c["name"] for c in inspector.get_columns("expert_mcp_bindings")}:
        raise RuntimeError("Run 048_agent_mcp_binding_status.sql first")
    for table, (key, new_index) in TABLES.items():
        inspector = inspect(connection)
        if "scope_agent_id" not in {c["name"] for c in inspector.get_columns(table)}:
            connection.exec_driver_sql(f"ALTER TABLE `{table}` ADD COLUMN scope_agent_id INT NOT NULL DEFAULT 0 AFTER user_id")
        indexes = inspect(connection).get_indexes(table)
        # Add the replacement first; never leave this table without uniqueness.
        if not any(i["name"] == new_index for i in indexes):
            connection.exec_driver_sql(f"ALTER TABLE `{table}` ADD UNIQUE KEY `{new_index}` (user_id, scope_agent_id, `{key}`)")
        for index in indexes:
            if index.get("unique") and index["column_names"] == ["user_id", key]:
                name = index["name"].replace("`", "``")
                connection.exec_driver_sql(f"ALTER TABLE `{table}` DROP INDEX `{name}`")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply schema and isolate existing bindings")
    args = parser.parse_args()
    if not args.apply:
        parser.print_help()
        return
    with engine.begin() as connection:
        apply_schema(connection)
    with Session(engine) as db, db.begin():
        counts = migrate_agent_asset_scopes(
            db, migration_workspace,
        )
    print(f"Asset isolation complete: {counts['skills']} skill bindings, {counts['mcps']} MCP bindings")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # SQLAlchemy tracebacks may include legacy config/credential parameters.
        print(f"Asset isolation failed ({type(exc).__name__}). Keep writers stopped; data transaction rolled back. Fix the cause and rerun.", file=sys.stderr)
        raise SystemExit(1) from None
