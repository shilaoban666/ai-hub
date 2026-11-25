"""Local HTTP/queue/runtime checks; no production DB, model or business calls."""
import asyncio
import json
import logging
import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

import agent_open_calls as calls
import agent_open_worker as worker
import agent_service
from auth import CurrentUser, get_current_active_user
from database import Base, get_db, settings
from enterprise_workspace import utcnow
from exception_handlers import http_exception_handler, validation_exception_handler
from fastapi.exceptions import RequestValidationError
from middleware import ResponseWrapperMiddleware
from models import (
    Agent, AgentMessage, AgentOpenCall, AgentOpenRequest, AgentRun, AgentSession, AIModel,
    Skill, SkillInstallation, SkillRelease, ExpertSkillBinding,
    McpConnection, McpDefinition, McpRevision, ExpertMcpBinding,
)
from runtimes.base import RuntimeEvent, RuntimeRunContext, RuntimeConfig
from sandbox.base import WorkspaceContext


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "test.sqlite"), connect_args={"check_same_thread": False})
    with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
        Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        db.add_all([
            Agent(id=1, user_id=7, name="one", kind="expert", default_model_id=11),
            Agent(id=2, user_id=7, name="two", kind="expert", default_model_id=11),
            AIModel(id=11, user_id=1, name="platform", provider="anthropic", scope="platform",
                    api_protocol="anthropic-messages", is_enabled=True),
        ])
        db.commit()
    app = FastAPI()
    app.add_middleware(ResponseWrapperMiddleware)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(calls.router)
    app.include_router(calls.open_router)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_active_user] = lambda: CurrentUser(7)
    monkeypatch.setattr(calls, "SessionLocal", factory)
    monkeypatch.setattr(calls, "SYNC_WAIT_SECONDS", 0)
    monkeypatch.setattr(settings, "claude_code_sandbox_type", "container")
    monkeypatch.setattr(settings, "agent_open_call_allow_query", False)
    monkeypatch.setattr(settings, "user_workspace_root", str(tmp_path / "workspaces"))
    client = TestClient(app)
    yield SimpleNamespace(factory=factory, client=client, app=app, tmp=tmp_path)
    client.close()
    engine.dispose()


def configure(env, agent_id=1, **kwargs):
    response = env.client.put(f"/api/agents/{agent_id}/open-call", json={"enabled": True, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def submit(env, key, agent_id=1, payload=None, headers=None):
    return env.client.post(
        f"/api/open/agents/{agent_id}/runs", json=payload or {"prompt": "hello"},
        headers={"X-Agent-Key": key, **(headers or {})},
    )


def result(env, key, run_id, agent_id=1):
    return env.client.get(
        f"/api/open/agents/{agent_id}/runs/{run_id}", headers={"X-Agent-Key": key},
    )


def add_skill(env, skill_id=21, *, agent_id=1, name="test-skill", status="published", owner=7, public=False):
    with env.factory() as db:
        db.add_all([
            Skill(id=skill_id, user_id=owner, name=name, version="1", is_public=public),
            SkillRelease(id=skill_id, skill_id=skill_id, version="1", status=status,
                         file_path="unused.zip", file_url="/releases/unused.zip"),
            SkillInstallation(id=skill_id, skill_id=skill_id, release_id=skill_id,
                              user_id=7, scope_agent_id=agent_id, workspace_id=1),
            ExpertSkillBinding(id=skill_id, agent_id=agent_id, installation_id=skill_id),
        ])
        db.commit()


def add_mcp(env, *, policy=None, auth="none", url="https://example.com/mcp", override=None):
    with env.factory() as db:
        db.add_all([
            McpDefinition(id=31, owner_user_id=7, name="knowledge", transport_type="http", status="published"),
            McpRevision(id=31, definition_id=31, version=1, status="published", content_sha256="a" * 64, created_by=7,
                        config_json=json.dumps({"url": url, "headers": {"secret": "publisher-secret"}, "env": {"SECRET": "secret"}})),
            McpConnection(id=31, user_id=7, name="knowledge", scope_agent_id=1,
                          workspace_id=1, definition_id=31, revision_id=31, auth_mode=auth,
                          config_overrides_json=json.dumps(override or {}),
                          tool_policy_json=json.dumps(policy or {"risk_level": "read", "allowed_tools": ["lookup"]})),
            ExpertMcpBinding(id=31, agent_id=1, connection_id=31),
        ])
        db.commit()


def test_owner_only_one_time_key_and_no_secret_storage(env):
    config = configure(env)
    key = config["session_key"]
    assert len(key) == 43
    assert config["enabled"]
    response = env.client.get("/api/agents/1/open-call")
    assert response.headers["cache-control"] == "no-store"
    assert "session_key" not in response.json()["data"]
    with env.factory() as db:
        assert db.get(AgentOpenCall, 1).key_digest == calls._digest(key)
        assert key not in db.get(AgentOpenCall, 1).key_digest
    env.app.dependency_overrides[get_current_active_user] = lambda: CurrentUser(8)
    assert env.client.get("/api/agents/1/open-call").status_code == 404
    assert env.client.post("/api/agents/1/open-call/rotate").status_code == 404
    assert env.client.put("/api/agents/1/open-call", json={"enabled": False}).status_code == 404


@pytest.mark.parametrize("key", ["", "wrong", "x" * 43])
def test_invalid_key_never_creates_session(env, key):
    configure(env)
    response = submit(env, key)
    assert response.status_code == 401
    assert "data" not in response.json()
    assert "no-store" in response.headers["cache-control"]
    with env.factory() as db:
        assert db.query(AgentSession).count() == 0


def test_private_agent_does_not_require_login_and_new_calls_get_independent_sessions(env):
    key = configure(env)["session_key"]
    first = submit(env, key)
    second = submit(env, key)
    assert first.status_code == second.status_code == 202
    assert first.json()["status_url"].startswith("/aihub/api/open/agents/1/runs/")
    with env.factory() as db:
        sessions = db.query(AgentSession).all()
        assert len(sessions) == 2 and all(s.source == "api" for s in sessions)
        assert sessions[0].id != sessions[1].id
        assert all(s.runtime_session_id is None for s in sessions)
        assert all(s.user_id == 7 for s in sessions)
    env.app.dependency_overrides[get_current_active_user] = lambda: (_ for _ in ()).throw(AssertionError("login called"))
    assert result(env, key, first.json()["run_id"]).status_code == 200


def test_defaults_and_invalid_parameters(env):
    with env.factory() as db:
        db.get(Agent, 1).system_prompt = "use this"
        db.commit()
    key = configure(env)["session_key"]
    response = env.client.post("/api/open/agents/1/runs", json={}, headers={"X-Agent-Key": key})
    assert response.status_code == 202
    with env.factory() as db:
        assert db.get(AgentOpenRequest, response.json()["run_id"]).prompt is None
    for payload in ({"prompt": 3}, {"prompt": "x" * 16001}, {"session_id": 9}, {"prompt": "bad\x00"}):
        assert submit(env, key, payload=payload).status_code == 422
    assert env.client.get("/api/open/agents/1/runs", headers={"X-Agent-Key": key}).status_code == 405


def test_no_prompt_or_skill_uses_agent_configuration(env):
    key = configure(env)["session_key"]
    with env.factory() as db:
        config = db.get(AgentOpenCall, 1)
        # Old rows must not retain behavior from the removed external settings.
        config.default_prompt = "obsolete"
        config.skill_ids = [999]
        config.mcp_ids = [999]
        db.commit()
    response = env.client.post("/api/open/agents/1/runs", json={}, headers={"X-Agent-Key": key})
    assert response.status_code == 202
    with env.factory() as db:
        request = db.get(AgentOpenRequest, response.json()["run_id"])
        assert request.prompt is None and request.skill_id is None


@pytest.mark.parametrize("field,value", [
    ("default_prompt", "old"), ("skill_ids", [21]), ("mcp_ids", [31]),
])
def test_removed_settings_are_not_an_independent_configuration(env, field, value):
    assert env.client.put("/api/agents/1/open-call", json={"enabled": True, field: value}).status_code == 422
    config = configure(env)
    assert not {"default_prompt", "skill_ids", "mcp_ids", "skills", "mcps"}.intersection(config)



def test_query_mode_is_explicit_and_body_query_conflicts_rejected(env, monkeypatch):
    key = configure(env)["session_key"]
    path = "/api/open/agents/1/runs"
    assert env.client.post(path, params={"session_key": key, "prompt": "你好"}).status_code == 400
    monkeypatch.setattr(settings, "agent_open_call_allow_query", True)
    response = env.client.post(path, params={"session_key": key, "prompt": "你好 & x=y"})
    assert response.status_code == 202
    with env.factory() as db:
        assert db.get(AgentOpenRequest, response.json()["run_id"]).prompt == "你好 & x=y"
    assert env.client.post(path, params={"session_key": key}, headers={"X-Agent-Key": key}).status_code == 422
    assert env.client.post(path, params={"session_key": key, "prompt": "a"}, json={"prompt": "b"}).status_code == 422
    assert env.client.post(path + "?session_key=" + key + "&prompt=a&prompt=b").status_code == 422
    assert env.client.post(path + "?session_key=" + key + "&session_key=" + key).status_code == 422


def test_idempotent_retry_conflict_and_other_agent_namespace(env):
    key = configure(env)["session_key"]
    headers = {"Idempotency-Key": "order-123"}
    first = submit(env, key, headers=headers)
    second = submit(env, key, headers=headers)
    assert first.json()["run_id"] == second.json()["run_id"]
    assert submit(env, key, payload={"prompt": "different"}, headers=headers).status_code == 409
    key2 = configure(env, 2)["session_key"]
    other = submit(env, key2, agent_id=2, headers=headers)
    assert other.status_code == 202 and other.json()["run_id"] != first.json()["run_id"]
    with env.factory() as db:
        assert db.query(AgentSession).count() == 2


def test_rotation_and_disable_revoke_execution_and_results(env):
    key = configure(env)["session_key"]
    run_id = submit(env, key).json()["run_id"]
    new_key = env.client.post("/api/agents/1/open-call/rotate").json()["data"]["session_key"]
    assert submit(env, key).status_code == 401
    assert result(env, key, run_id).status_code == 401
    assert result(env, new_key, run_id).status_code == 404
    assert worker.claim_run(env.factory, "worker") == run_id
    assert worker.check_run(env.factory, run_id, "worker") == "open_call_config_changed"
    assert env.client.put("/api/agents/1/open-call", json={"enabled": False}).status_code == 200
    assert submit(env, new_key).status_code == 401


def test_cannot_read_other_agent_or_web_run(env):
    key = configure(env)["session_key"]
    key2 = configure(env, 2)["session_key"]
    run_id = submit(env, key).json()["run_id"]
    assert result(env, key2, run_id, agent_id=2).status_code == 404
    assert result(env, key, "not-a-run").status_code == 404
    with env.factory() as db:
        db.get(AgentRun, run_id).source = "web"
        db.commit()
    assert result(env, key, run_id).status_code == 404


def test_current_skill_bindings_and_exact_resolution(env):
    add_skill(env)
    add_skill(env, 22, name="secret", agent_id=2)
    key = configure(env)["session_key"]
    assert submit(env, key, payload={"prompt": "test", "skill": "secret"}).status_code == 422
    assert submit(env, key, payload={"prompt": "test", "skill": "missing"}).status_code == 422
    for selector in ("test-skill", "id:21"):
        response = submit(env, key, payload={"prompt": "test", "skill": selector})
        assert response.status_code == 202
        with env.factory() as db:
            assert db.get(AgentOpenRequest, response.json()["run_id"]).skill_id == 21
    with env.factory() as db:
        db.get(SkillInstallation, 21).status = "removed"
        db.commit()
    assert submit(env, key, payload={"prompt": "test", "skill": "test-skill"}).status_code == 422


def test_draft_and_newly_bound_skills_are_available_without_resaving_open_call(env):
    add_skill(env, status="workspace")
    key = configure(env)["session_key"]
    assert submit(env, key, payload={"skill": "test-skill"}).status_code == 202
    add_skill(env, 22, name="added-later")
    assert submit(env, key, payload={"skill": "added-later"}).status_code == 202
    add_skill(env, 23, agent_id=2, name="other-agent")
    assert submit(env, key, payload={"skill": "other-agent"}).status_code == 422


@pytest.mark.parametrize("updates", [
    {"scope": "user"}, {"is_enabled": False}, {"is_deleted": True}, {"api_protocol": "openai-completions"},
])
def test_only_compatible_platform_model_can_be_opened(env, updates):
    with env.factory() as db:
        for name, value in updates.items():
            setattr(db.get(AIModel, 11), name, value)
        db.commit()
    assert env.client.put("/api/agents/1/open-call", json={"enabled": True}).status_code == 409


def test_all_agent_connectors_inherit_current_config_and_manual_credentials(env):
    import asset_runtime
    add_mcp(env, auth="manual", override={
        "url": "https://current.example.com/mcp",
        "headers": {"Authorization": "agent-secret"},
    }, policy={"risk_level": "read", "allowed_tools": ["*"]})
    configure(env)
    with env.factory() as db, patch.object(asset_runtime, "validate_mcp_config", return_value={}):
        assets = asset_runtime.load_runtime_assets(db, db.get(Agent, 1), 7, source="api")
        assert [m.id for m in assets["mcps"]] == [31]
        config = json.loads(assets["mcps"][0].config)
        assert config["url"] == "https://current.example.com/mcp"
        assert config["headers"] == {"Authorization": "agent-secret"}
        assert assets["mcps"][0].allowed_tools == ["*"]
        assert not assets["requires_confirmation"]
        # A later edit is used by the next run without saving open-call settings.
        connection = db.get(McpConnection, 31)
        connection.config_overrides_json = json.dumps({"headers": {"Authorization": "updated-secret"}})
        db.commit()
        updated = asset_runtime.load_runtime_assets(db, db.get(Agent, 1), 7, source="api")
        assert json.loads(updated["mcps"][0].config)["headers"]["Authorization"] == "updated-secret"


@pytest.mark.parametrize("auth,policy,message", [
    ("current_user", None, "没有可复用的浏览器 Bearer Token"),
    ("manual", {"risk_level": "write", "allowed_tools": ["update"]}, "interactive web run"),
])
def test_existing_noninteractive_connector_requirements_are_preserved(env, auth, policy, message):
    import asset_runtime
    add_mcp(env, auth=auth, policy=policy)
    configure(env)
    with env.factory() as db, patch.object(asset_runtime, "validate_mcp_config", return_value={}):
        with pytest.raises(RuntimeError, match=message):
            asset_runtime.load_runtime_assets(db, db.get(Agent, 1), 7, source="api")


def test_result_returns_only_final_text_and_sanitized_error(env):
    key = configure(env)["session_key"]
    run_id = submit(env, key).json()["run_id"]
    with env.factory() as db:
        run = db.get(AgentRun, run_id)
        message = AgentMessage(session_id=run.session_id, role="assistant", content=json.dumps({"blocks": [
            {"type": "thinking", "content": "private"}, {"type": "text", "content": "你好"},
            {"type": "tool_result", "content": "secret"},
        ]}))
        db.add(message)
        db.flush()
        run.status, run.assistant_message_id = "succeeded", message.id
        db.commit()
    response = result(env, key, run_id)
    assert response.json() == {"run_id": run_id, "status": "succeeded", "result": "你好"}
    with env.factory() as db:
        run = db.get(AgentRun, run_id)
        run.status, run.error_message, run.error_code = "failed", "secret token abc", "private_failure"
        db.commit()
    assert "secret" not in result(env, key, run_id).text


def test_queue_limit_and_timeout_recovery_never_replay(env):
    key = configure(env)["session_key"]
    ids = [submit(env, key).json()["run_id"] for _ in range(4)]
    assert submit(env, key).status_code == 429
    with env.factory() as db:
        db.get(AgentRun, ids[0]).deadline_at = utcnow() - timedelta(seconds=1)
        db.commit()
    worker.recover_runs(env.factory)
    with env.factory() as db:
        assert db.get(AgentRun, ids[0]).status == "failed"
        assert db.get(AgentOpenRequest, ids[0]).prompt is None
    run_id = worker.claim_run(env.factory, "worker")
    assert worker.claim_run(env.factory, "other") != run_id
    with env.factory() as db:
        db.get(AgentRun, run_id).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    with patch.object(worker, "get_open_call_sandbox") as sandbox:
        worker.recover_runs(env.factory)
        assert sandbox.return_value._remove_root.called
    with env.factory() as db:
        assert db.get(AgentRun, run_id).status == "unknown"
        assert db.get(AgentOpenRequest, run_id).prompt is None


def test_api_access_log_filter_removes_all_query_values():
    record = logging.LogRecord("uvicorn.access", 20, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("remote", "POST", "/api/open/agents/1/runs?session_key=secret&prompt=private", "1.1", 202), None)
    assert calls._OpenCallAccessFilter().filter(record)
    assert "secret" not in record.getMessage() and "private" not in record.getMessage()


def test_disposable_workspace_has_no_owner_files_or_history(env, monkeypatch):
    from sandbox.open_call import OpenContainerSandbox
    from sandbox.container import ContainerSandbox
    class Underlying:
        pass
    provider = OpenContainerSandbox()
    owner = SimpleNamespace(id=9, user_id=7, workspace_key="private", migration_status="pending", legacy_agent_ids=[1])
    captured = {}
    def prepare(_self, agent, model, *, run_id, workspace, filter_skills):
        captured.update(vars(workspace))
        path = env.tmp / "workspaces" / workspace.workspace_key
        path.mkdir(parents=True)
        (path / "test").write_text("temporary")
        return WorkspaceContext("container", "/workspace", str(path), [],
                                run_id=run_id, handle={"user_root": str(path)})
    with patch.object(ContainerSandbox, "prepare_execution", prepare):
        ctx = provider.prepare_execution(SimpleNamespace(id=1), None, run_id="a" * 32, workspace=owner)
    assert captured["workspace_key"] == "open-" + "a" * 32
    assert captured["legacy_agent_ids"] == []
    assert owner.workspace_key == "private"
    with patch("sandbox.open_call.subprocess.run") as docker:
        provider.cleanup(ctx)
        assert docker.call_args.args[0][-1] == "aihub-run-" + "a" * 20
    assert not (env.tmp / "workspaces" / captured["workspace_key"]).exists()


def test_worker_executes_through_shared_engine_and_records_result(env):
    key = configure(env)["session_key"]
    run_id = env.client.post("/api/open/agents/1/runs", json={}, headers={"X-Agent-Key": key}).json()["run_id"]
    with env.factory() as db:
        db.get(Agent, 1).system_prompt = "updated agent instructions"
        db.commit()
    assert worker.claim_run(env.factory, "worker") == run_id
    captured = {}

    class Sandbox:
        def prepare_execution(self, agent, model, *, run_id, workspace, filter_skills):
            captured["agent"] = agent
            return WorkspaceContext("container", "/workspace", "/workspace", [], run_id=run_id, handle={})
        def cleanup(self, ctx):
            captured["cleanup"] = True
        def discard_execution(self, ctx):
            pass

    class Runtime:
        async def run(self, **kwargs):
            captured["runtime"] = kwargs
            await kwargs["on_event"](RuntimeEvent(type="text", content="real execution result"))
            await kwargs["on_event"](RuntimeEvent(type="done"))

    empty_assets = {
        "skills": [], "skill_snapshot": [], "mcps": [], "mcp_snapshot": [], "secret_env": {},
        "effective_capabilities": [], "requires_confirmation": False,
    }
    with patch.object(agent_service, "load_runtime_assets", return_value=empty_assets) as load, \
            patch.object(agent_service, "get_workspace_provider", return_value=Sandbox()), \
            patch.object(agent_service, "get_runtime", return_value=Runtime()), \
            patch.object(agent_service, "prepare_platform_run", return_value=("test-token", "http://gateway")), \
            patch.object(agent_service, "settle_platform_run"), \
            patch.object(agent_service, "load_global_runtime_environment", side_effect=AssertionError("private environment loaded")), \
            patch.object(agent_service, "generate_session_title", side_effect=AssertionError("extra model call")):
        asyncio.run(worker.run_one(env.factory, run_id, "worker"))
    assert captured["cleanup"]
    assert captured["runtime"]["run_context"].source == "api"
    assert captured["runtime"]["history"] == []
    assert captured["agent"].runtime_secret_env == {}
    assert captured["agent"].effective_system_prompt == "updated agent instructions"
    assert captured["runtime"]["user_input"] == "请按照你的职责和配置开始执行。"
    assert load.call_args.kwargs["source"] == "api"
    assert not load.call_args.kwargs["interactive_permissions"]
    assert "skills_only" not in load.call_args.kwargs
    assert result(env, key, run_id).json()["result"] == "real execution result"
    with env.factory() as db:
        assert db.get(AgentOpenRequest, run_id).prompt is None
        assert db.get(AgentRun, run_id).status == "succeeded"
        assert "open_call_input" in json.loads(db.get(AgentRun, run_id).config_snapshot)


def test_api_runtime_inherits_tools_and_denies_interactive_permission(env):
    from runtimes.claude_code import ClaudeCodeRuntime
    from runtimes.sdk_permissions import request_tool_permission

    async def scenario():
        source = """
import json, sys, pathlib
pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))
sys.stdin.readline()
print(json.dumps({"type":"result","subtype":"success","result":"ok"}), flush=True)
"""
        args_path = str(env.tmp / "args.json")
        ctx = WorkspaceContext("directory", str(env.tmp), str(env.tmp),
                               [sys.executable, "-c", source, args_path], claude_bin="claude-test",
                               run_cwd=str(env.tmp))
        events = []
        async def emit(event):
            events.append(event)
        await ClaudeCodeRuntime().run(
            RuntimeConfig(timeout_seconds=5, extra={"allowed_mcp_tools": ["mcp__knowledge__lookup"]}),
            ctx, "hello", [], emit, RuntimeRunContext("r", 1, source="api"),
        )
        args = json.loads((env.tmp / "args.json").read_text())
        assert "--tools" not in args
        assert "--disable-slash-commands" not in args
        assert args[args.index("--mcp-config") + 1] == ".mcp.json"
        assert "--strict-mcp-config" in args
        denied = await request_tool_permission(RuntimeRunContext("r", 1, source="api"), "Write", {}, None)
        assert denied.behavior == "deny"
    asyncio.run(scenario())


def test_save_does_not_rotate_existing_key_and_disable_reenable_issues_new_key(env):
    key = configure(env)["session_key"]
    updated = configure(env)
    assert "session_key" not in updated
    assert submit(env, key).status_code == 202
    env.client.put("/api/agents/1/open-call", json={"enabled": False})
    new_key = configure(env)["session_key"]
    assert key != new_key
    assert submit(env, key).status_code == 401


def test_poll_success_can_be_returned_synchronously(env, monkeypatch):
    key = configure(env)["session_key"]
    real_read = calls._read_result
    def complete(agent_id, run_id, credential):
        with env.factory() as db:
            run = db.get(AgentRun, run_id)
            message = AgentMessage(session_id=run.session_id, role="assistant",
                                   content=json.dumps({"blocks": [{"type": "text", "content": "done"}]}))
            db.add(message)
            db.flush()
            run.status, run.assistant_message_id = "succeeded", message.id
            db.commit()
        return real_read(agent_id, run_id, credential)
    monkeypatch.setattr(calls, "_read_result", complete)
    response = submit(env, key)
    assert response.status_code == 200 and response.json()["result"] == "done"


def test_queued_run_is_cancelled_before_runtime_after_key_rotation(env):
    key = configure(env)["session_key"]
    run_id = submit(env, key).json()["run_id"]
    worker.claim_run(env.factory, "worker")
    env.client.post("/api/agents/1/open-call/rotate")
    with patch.object(worker, "execute_agent_turn", side_effect=AssertionError("Runtime must not start")):
        asyncio.run(worker.run_one(env.factory, run_id, "worker"))
    with env.factory() as db:
        assert db.get(AgentRun, run_id).status == "cancelled"
        assert db.get(AgentOpenRequest, run_id).prompt is None


def test_skill_loader_inherits_all_bound_versions_and_excludes_other_agents(env):
    import asset_runtime
    add_skill(env, 21, name="published")
    add_skill(env, 22, name="latest", status="workspace")
    add_skill(env, 23, name="other-agent", agent_id=2)
    archive = env.tmp / "release.zip"
    archive.write_bytes(b"archive-fixture")
    cached = SimpleNamespace(
        files_json=json.dumps([{"type": "file", "path": "SKILL.md", "content": "# rules"}]),
        content_sha256="c" * 64, directory=str(env.tmp),
    )
    with env.factory() as db, \
            patch.object(asset_runtime, "resolve_release_file_path", return_value=str(archive)), \
            patch.object(asset_runtime, "get_cached_release", return_value=cached), \
            patch.object(asset_runtime, "get_development_snapshot", return_value=cached):
        assets = asset_runtime.load_runtime_assets(db, db.get(Agent, 1), 7, source="api")
        assert {(skill.id, skill.version) for skill in assets["skills"]} == {(21, "1"), (22, "latest")}
        assert assets["mcps"] == []
        db.get(SkillInstallation, 21).status = "removed"
        db.commit()
        updated = asset_runtime.load_runtime_assets(db, db.get(Agent, 1), 7, source="api")
        assert [skill.id for skill in updated["skills"]] == [22]


def test_rotating_key_cancels_a_running_runtime(env):
    key = configure(env)["session_key"]
    run_id = submit(env, key).json()["run_id"]
    worker.claim_run(env.factory, "worker")
    started = asyncio.Event()
    stopped = []

    async def blocked(**kwargs):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            stopped.append(True)
            raise

    async def scenario():
        with patch.object(worker, "execute_agent_turn", side_effect=blocked):
            task = asyncio.create_task(worker.run_one(env.factory, run_id, "worker"))
            await asyncio.wait_for(started.wait(), 5)
            with env.factory() as db:
                calls._rotate_key(db.get(AgentOpenCall, 1))
                db.commit()
            await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    assert stopped
    with env.factory() as db:
        assert db.get(AgentRun, run_id).status == "cancelled"
        assert db.get(AgentRun, run_id).error_code == "open_call_config_changed"


def test_gateway_discovers_only_execution_routes_as_no_login(env):
    paths = env.app.openapi()["paths"]
    assert paths["/api/open/agents/{agent_id}/runs"]["post"]["security"] == []
    assert paths["/api/open/agents/{agent_id}/runs/{run_id}"]["get"]["security"] == []
    for method in ("get", "put"):
        assert paths["/api/agents/{agent_id}/open-call"][method]["security"]
    assert paths["/api/agents/{agent_id}/open-call/rotate"]["post"]["security"]
    assert paths["/api/agents/{agent_id}/open-call/runs"]["get"]["security"]
    assert paths["/api/agents/{agent_id}/open-call/runs/{run_id}"]["get"]["security"]


def test_owner_records_include_old_generations_and_exclude_other_sources_users_agents(env):
    key = configure(env)["session_key"]
    run_id = submit(env, key, payload={"prompt": "recorded request"}).json()["run_id"]
    key2 = configure(env, 2)["session_key"]
    other_id = submit(env, key2, agent_id=2).json()["run_id"]
    with env.factory() as db:
        original = db.get(AgentRun, run_id)
        for ident, source, user_id in [("web", "web", 7), ("other-user", "api", 8)]:
            db.add(AgentRun(id=ident, agent_id=1, session_id=original.session_id, user_id=user_id, source=source))
        db.commit()
    env.client.post("/api/agents/1/open-call/rotate")
    env.client.put("/api/agents/1/open-call", json={"enabled": False})
    records = env.client.get("/api/agents/1/open-call/runs")
    assert records.status_code == 200
    assert records.headers["cache-control"] == "no-store"
    data = records.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["run_id"] == run_id
    assert data["items"][0]["prompt"] == "recorded request"
    assert key not in records.text
    assert "generation" not in records.text and "config_snapshot" not in records.text
    assert env.client.get(f"/api/agents/1/open-call/runs/{run_id}").status_code == 200
    assert env.client.get(f"/api/agents/1/open-call/runs/{other_id}").status_code == 404
    assert env.client.get("/api/agents/1/open-call/runs/web").status_code == 404
    assert env.client.get("/api/agents/1/open-call/runs/other-user").status_code == 404
    env.app.dependency_overrides[get_current_active_user] = lambda: CurrentUser(8)
    assert env.client.get("/api/agents/1/open-call/runs").status_code == 404
    assert env.client.get(f"/api/agents/1/open-call/runs/{run_id}").status_code == 404


def test_owner_records_pagination_run_lookup_and_full_prompt(env):
    key = configure(env)["session_key"]
    prompt = "long request " * 100
    first = submit(env, key, payload={"prompt": prompt}).json()["run_id"]
    second = submit(env, key).json()["run_id"]
    assert env.client.get("/api/agents/1/open-call/runs", params={"limit": 1}).json()["data"]["total"] == 2
    pages = [env.client.get("/api/agents/1/open-call/runs", params={"skip": skip, "limit": 1}).json()["data"]["items"][0]["run_id"] for skip in (0, 1)]
    assert set(pages) == {first, second}
    response = env.client.get("/api/agents/1/open-call/runs", params={"run_id": first}).json()["data"]
    assert response["total"] == 1 and len(response["items"][0]["prompt"]) == 200
    assert env.client.get(f"/api/agents/1/open-call/runs/{first}").json()["data"]["prompt"] == prompt.strip()
    for params in ({"skip": -1}, {"limit": 0}, {"limit": 101}):
        assert env.client.get("/api/agents/1/open-call/runs", params=params).status_code == 422


def test_owner_records_show_results_errors_and_legacy_user_messages(env):
    from message_content import pack_user_content
    key = configure(env)["session_key"]
    run_id = submit(env, key).json()["run_id"]
    with env.factory() as db:
        run = db.get(AgentRun, run_id)
        # Existing requests predate the input snapshot and their queue input was cleared.
        run.config_snapshot = None
        db.get(AgentOpenRequest, run_id).prompt = None
        db.add(AgentMessage(session_id=run.session_id, role="user",
                            content=pack_user_content("legacy question", skill={"id": 21, "name": "legacy-skill"})))
        answer = AgentMessage(session_id=run.session_id, role="assistant", content=json.dumps({"blocks": [
            {"type": "thinking", "content": "private reasoning"},
            {"type": "text", "content": "final answer"},
            {"type": "tool_result", "content": "private tool data"},
        ]}))
        db.add(answer)
        db.flush()
        run.assistant_message_id = answer.id
        run.status = "succeeded"
        run.duration_ms = 0
        run.total_tokens = 0
        db.commit()
    detail = env.client.get(f"/api/agents/1/open-call/runs/{run_id}").json()["data"]
    assert detail["prompt"] == "legacy question" and detail["skill"] == "legacy-skill"
    assert detail["result"] == "final answer"
    assert detail["duration_ms"] == detail["total_tokens"] == 0
    assert "private reasoning" not in str(detail) and "private tool data" not in str(detail)
    with env.factory() as db:
        run = db.get(AgentRun, run_id)
        run.status, run.error_code, run.error_message = "failed", "asset_resolution_failed", "specific connector error"
        db.commit()
    failed = env.client.get(f"/api/agents/1/open-call/runs/{run_id}").json()["data"]
    assert failed["error_message"] == "specific connector error"


def test_request_audit_survives_failure_before_message_and_queue_input_cleanup(env):
    key = configure(env)["session_key"]
    run_id = submit(env, key, payload={"prompt": "failed before execution"}).json()["run_id"]
    with env.factory() as db:
        worker._finish(db, db.get(AgentRun, run_id), "failed", "queue_timeout", "queue expired")
    detail = env.client.get(f"/api/agents/1/open-call/runs/{run_id}").json()["data"]
    assert detail["prompt"] == "failed before execution"
    assert detail["result"] is None and detail["error_code"] == "queue_timeout"
