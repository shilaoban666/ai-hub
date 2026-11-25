"""Retired-runtime cutover keeps history/assets and starts with empty files."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from models import (Agent, AgentMessage, AgentRun, AgentSession, AIModel,
                    PlatformAgentSettings, RuntimeCell, RuntimeInstance, UserWorkspace,
                    WorkbenchSettings)
from test_agent_routes import _create_db
from runtimes import (RUNTIME_INFO, RUNTIME_REGISTRY, get_runtime, get_runtime_info,
                      register_runtime)
from model_compat import RUNTIME_MODEL_PROTOCOLS, model_supports_runtime
from schemas import AgentCreate
from sandbox.legacy_workspace import merge_workspace

spec = importlib.util.spec_from_file_location(
    "claude_migration", Path(__file__).parent / "migrations/056_claude_runtime.py",
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def seed(db):
    db.add_all([
        AIModel(id=1, user_id=7, name="old", provider="custom", api_protocol="openai-completions"),
        AIModel(id=2, user_id=7, name="claude", provider="custom", api_protocol="anthropic-messages"),
        AIModel(id=3, user_id=8, name="other user", provider="custom", api_protocol="anthropic-messages"),
        UserWorkspace(id=10, user_id=7, agent_id=20, workspace_key="test", migration_status="completed"),
        Agent(id=20, user_id=7, name="Expert", runtime_type=migration.LEGACY_RUNTIME,
              default_model_id=1, thinking_level="adaptive", workspace_id=10),
        AgentSession(id=30, user_id=7, agent_id=20, runtime_type=migration.LEGACY_RUNTIME,
                     source="dingtalk_clawbot", runtime_session_id="gateway-session", model_id=1,
                     runtime_instance_id=40, claude_session_id="stale"),
        AgentMessage(id=31, session_id=30, role="user", content="previous question"),
        RuntimeInstance(id=40, user_id=7, agent_id=20, runtime_type=migration.LEGACY_RUNTIME,
                        deployment_mode="remote", external_agent_id="agent-20", endpoint="http://old",
                        auth_secret_encrypted="old-secret", status="ready"),
        RuntimeCell(id=50, workspace_id=10, user_id=7, agent_id=20,
                    runtime_type=migration.LEGACY_RUNTIME, status="ready"),
        PlatformAgentSettings(id=60, created_by=7, version=1, status="published",
                              runtime_type=migration.LEGACY_RUNTIME, thinking_level="minimal"),
        AgentRun(id="historic", agent_id=20, session_id=30, user_id=7, source="web",
                 status="succeeded", runtime_instance_id=40,
                 config_snapshot='{"runtime_type":"openclaw"}'),
    ])
    db.commit()


def test_migration_preserves_messages_and_audit_and_is_idempotent():
    with _create_db() as db:
        seed(db)
        preview = migration.backfill(db, apply=False)
        assert preview["agents"] == 1
        assert db.get(Agent, 20).runtime_type == migration.LEGACY_RUNTIME
        migration.backfill(db)
        db.commit()
        assert (db.get(Agent, 20).runtime_type, db.get(Agent, 20).default_model_id,
                db.get(Agent, 20).thinking_level) == ("claude_code", 2, "inherit")
        session = db.get(AgentSession, 30)
        assert session.runtime_type == "claude_code" and session.model_id == 2
        assert session.source == "dingtalk_clawbot"
        assert session.runtime_session_id is session.runtime_instance_id is session.claude_session_id is None
        assert db.get(AgentMessage, 31).content == "previous question"
        assert db.get(AgentRun, "historic").runtime_instance_id == 40
        assert db.get(AgentRun, "historic").config_snapshot == '{"runtime_type":"openclaw"}'
        assert db.get(RuntimeInstance, 40).status == "retired"
        assert db.get(RuntimeInstance, 40).auth_secret_encrypted is None
        assert db.get(RuntimeCell, 50).runtime_type == "claude_code"
        assert db.get(UserWorkspace, 10).migration_status == "not_required"
        assert db.get(UserWorkspace, 10).workspace_key != "test"
        assert db.get(PlatformAgentSettings, 60).thinking_level == "inherit"
        assert not any(migration.backfill(db).values())


def test_migration_refuses_missing_user_model_and_unfinished_runs():
    with _create_db() as db:
        seed(db)
        db.get(AIModel, 2).is_enabled = False
        db.commit()
        with pytest.raises(RuntimeError, match="Anthropic Messages"):
            migration.backfill(db)
        assert db.get(Agent, 20).runtime_type == migration.LEGACY_RUNTIME
        db.get(AIModel, 2).is_enabled = True
        db.get(AgentRun, "historic").status = "unknown"
        db.commit()
        with pytest.raises(RuntimeError, match="unresolved"):
            migration.backfill(db)
        assert db.get(AgentSession, 30).runtime_session_id == "gateway-session"


def test_migration_creates_missing_workspace_and_repairs_published_workbench_model():
    with _create_db() as db:
        seed(db)
        agent = db.get(Agent, 20)
        agent.workspace_id = None
        db.add_all([
            AIModel(id=4, user_id=0, scope="platform", name="shared claude",
                    provider="Anthropic", api_protocol="anthropic-messages"),
            WorkbenchSettings(id=70, created_by=7, version=1, status="published", default_model_id=1),
        ])
        db.commit()
        migration.backfill(db)
        db.commit()
        assert db.get(UserWorkspace, agent.workspace_id).migration_status == "not_required"
        assert db.get(WorkbenchSettings, 70).default_model_id == 4


def test_rerunning_migration_disables_earlier_legacy_file_import_without_touching_claude_migrations():
    from migrations.upgrade_checks import DATA_CHECKS
    pending_sql = DATA_CHECKS['056: legacy file import pending']
    with _create_db() as db:
        seed(db)
        migration.backfill(db)
        db.commit()
        workspace = db.get(UserWorkspace, 10)
        workspace.migration_status = 'pending'  # Earlier version of 056.
        previous_key = workspace.workspace_key
        db.add_all([
            Agent(id=21, user_id=7, name='Claude', runtime_type='claude_code'),
            UserWorkspace(id=11, user_id=7, agent_id=21, workspace_key='claude-files',
                          migration_status='pending'),
        ])
        db.commit()
        assert db.connection().exec_driver_sql(pending_sql).scalar() == 1
        assert migration.backfill(db, apply=False)['pending_workspaces'] == 1
        assert workspace.workspace_key == previous_key
        migration.backfill(db)
        db.commit()
        assert workspace.migration_status == 'not_required'
        assert workspace.workspace_key != previous_key
        assert db.connection().exec_driver_sql(pending_sql).scalar() == 0
        assert db.get(UserWorkspace, 11).migration_status == 'pending'
        assert db.get(UserWorkspace, 11).workspace_key == 'claude-files'
        assert not any(migration.backfill(db).values())


def test_only_claude_is_registered_and_extensions_remain_usable():
    assert set(get_runtime_info()) == {"claude_code"}
    with pytest.raises(ValidationError):
        AgentCreate(name="old", runtime_type=migration.LEGACY_RUNTIME)
    implementation = RUNTIME_REGISTRY["claude_code"]
    try:
        register_runtime("test_engine", implementation, info={
            "label": "Test", "model_protocols": ["openai-completions"], "available": True,
        })
        assert isinstance(get_runtime("test_engine"), implementation)
        assert AgentCreate(name="new", runtime_type="test_engine").runtime_type == "test_engine"
        assert model_supports_runtime(SimpleNamespace(api_protocol="openai-completions"), "test_engine")
    finally:
        for registry in (RUNTIME_REGISTRY, RUNTIME_INFO, RUNTIME_MODEL_PROTOCOLS):
            registry.pop("test_engine", None)


def test_workspace_merge_keeps_both_versions_and_handles_type_conflicts(tmp_path):
    source, destination = tmp_path / "20", tmp_path / "files"
    source.mkdir()
    destination.mkdir()
    (source / "report.txt").write_text("old")
    (destination / "report.txt").write_text("current")
    (source / "folder").mkdir()
    (source / "folder/note.txt").write_text("note")
    (destination / "folder").write_text("current file")
    (source / "empty.txt").touch()
    (source / "binary.bin").write_bytes(b"\x00\xff")
    (source / ".venv").mkdir()
    (source / ".venv/python").symlink_to("/usr/bin/python3")
    merge_workspace(source, destination)
    assert (destination / "report.txt").read_text() == "current"
    assert (destination / "folder").read_text() == "current file"
    assert (destination / "legacy-agent-20/report.txt").read_text() == "old"
    assert (destination / "legacy-agent-20/folder/note.txt").read_text() == "note"
    assert (destination / "binary.bin").read_bytes() == b"\x00\xff"
    assert (destination / "empty.txt").stat().st_size == 0
    assert not (destination / ".venv").exists()
    merge_workspace(source, destination)
    assert not (destination / "legacy-agent-20.1").exists()


def test_workspace_merge_rejects_symlink_escape(tmp_path):
    source, destination = tmp_path / "20", tmp_path / "files"
    source.mkdir()
    (source / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="unsupported"):
        merge_workspace(source, destination)
    assert not destination.exists()
