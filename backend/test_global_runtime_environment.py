"""Global environment CRUD and real script reads across users/runtime launch paths."""
import asyncio
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import agent_service
import enterprise_routes as routes
from auth import CurrentUser, get_current_active_user
from database import get_db
from enterprise_schemas import GlobalRuntimeEnvironment
from models import PlatformGlobalSettings
from runtime_environment import load_global_runtime_environment
from runtimes.base import RuntimeConfig, RuntimeEvent
from runtimes.claude_code import _build_runtime_env, _encode_tunneled_env
from sandbox.base import WorkspaceContext
from sandbox.native import RUNNER_SCRIPT
from test_agent_service import (
    _DB, _Memory, _Runtime, _Sandbox, _agent, _execution_dependencies, _model, _session,
)


@pytest.fixture
def settings_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    PlatformGlobalSettings.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_admin_crud_keeps_runtime_variables_out_of_brand_response(settings_db):
    app = FastAPI()
    app.include_router(routes.router)
    user = CurrentUser(1, is_superuser=True)
    app.dependency_overrides[get_db] = lambda: settings_db
    app.dependency_overrides[get_current_active_user] = lambda: user
    endpoint = "/api/admin/global-settings/runtime-environment"
    with TestClient(app) as client:
        assert client.get(endpoint).json() == {"variables": {}}
        variables = {"X_MCP_TOKEN": "test-only-token", "X_MCP_USER": "toolbox", "EMPTY_VALUE": ""}
        result = client.put(endpoint, json={"variables": variables})
        assert result.status_code == 200
        assert result.json()["variables"] == variables
        assert client.get(endpoint).json()["variables"] == variables
        # Updating branding must preserve the separately saved environment.
        assert client.put("/api/admin/global-settings", json={"brand_name": "Test platform"}).status_code == 200
        assert load_global_runtime_environment(settings_db) == variables
        assert "runtime_environment" not in client.get("/api/global-settings").json()
        user = CurrentUser(8)
        assert client.get(endpoint).status_code == 403
        assert client.put(endpoint, json={"variables": {}}).status_code == 403
        assert "test-only-token" not in client.get("/api/global-settings").text
        user = CurrentUser(1, is_superuser=True)
        assert client.put(endpoint, json={"variables": {}}).json() == {"variables": {}}
        assert load_global_runtime_environment(settings_db) == {}


def test_updates_and_deletion_refresh_even_with_preloaded_settings(settings_db):
    settings_db.add(PlatformGlobalSettings(id=1, runtime_environment={"X_MCP_TOKEN": "old"}))
    settings_db.commit()
    with Session(settings_db.bind) as worker_db:
        cached = worker_db.get(PlatformGlobalSettings, 1)
        assert load_global_runtime_environment(worker_db) == {"X_MCP_TOKEN": "old"}
        for variables in ({"X_MCP_TOKEN": "new"}, {}):
            routes.update_global_runtime_environment(GlobalRuntimeEnvironment(variables=variables), settings_db, CurrentUser(1, is_superuser=True))
            assert cached.runtime_environment == {"X_MCP_TOKEN": "old"}
            assert load_global_runtime_environment(worker_db) == variables


@pytest.mark.parametrize("variables", [
    {"X-MCP-Token": "test"}, {"1TOKEN": "test"}, {"PATH": "/outside"},
    {"HOME": "/outside"}, {"AIHUB_AGENT_WORKSPACE": "/outside"},
    {"CLAUDE_CONFIG_DIR": "/outside"}, {"ANTHROPIC_API_KEY": "test"},
    {"TOKEN": "nul\0byte"}, {"TOKEN": "x" * (64 * 1024)},
])
def test_invalid_environment_is_rejected(variables):
    with pytest.raises(ValidationError):
        GlobalRuntimeEnvironment(variables=variables)


@pytest.mark.parametrize("sandbox_type", ["native", "container", "directory"])
def test_all_users_and_channels_receive_updated_environment_in_real_scripts(settings_db, tmp_path, sandbox_type):
    workspace = tmp_path / sandbox_type
    workspace.mkdir()
    # Mimic an installed Skill script without storing any credential in its source.
    script = workspace / "skill.py"
    script.write_text('import json, os; print(json.dumps({k: os.environ.get(k) for k in ("X_MCP_TOKEN", "X_MCP_USER")}))')
    expected = {}

    class Sandbox(_Sandbox):
        def prepare_execution(self, agent, model, **kwargs):
            self.env = dict(agent.runtime_secret_env)
            return WorkspaceContext(
                sandbox_type, str(workspace), str(workspace), [],
                env={"AIHUB_AGENT_WORKSPACE": str(workspace), **self.env},
                tunnel_env_via_stdin=sandbox_type != "directory",
                is_isolated=sandbox_type != "directory",
            )

    class ScriptRuntime(_Runtime):
        async def run(self, config, ctx, user_input, history, on_event, run_context=None):
            env = _build_runtime_env(RuntimeConfig(), ctx)
            # The native/container wrapper must forward custom variables, too.
            if ctx.tunnel_env_via_stdin:
                command = [sys.executable, "-c", RUNNER_SCRIPT, "test-runner", sys.executable, str(script)]
                input_data = _encode_tunneled_env(ctx, env)
                launch_env = {"PATH": os.defpath}
            else:
                command, input_data, launch_env = [sys.executable, str(script)], None, env
            result = subprocess.run(command, input=input_data, env=launch_env, capture_output=True, check=True)
            assert json.loads(result.stdout) == expected
            await on_event(RuntimeEvent(type="done", content="script passed"))

    sandbox = Sandbox()
    with (
        _execution_dependencies(),
        patch.object(agent_service, "load_global_runtime_environment", side_effect=lambda _: load_global_runtime_environment(settings_db)),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(agent_service, "get_workspace_provider", return_value=sandbox),
        patch.object(agent_service, "get_runtime", return_value=ScriptRuntime()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
    ):
        for variables in ({"X_MCP_TOKEN": "test-only-token", "X_MCP_USER": "toolbox"}, {"X_MCP_TOKEN": "updated"}, {}):
            routes.update_global_runtime_environment(GlobalRuntimeEnvironment(variables=variables), settings_db, CurrentUser(1, is_superuser=True))
            expected = {key: variables.get(key) for key in ("X_MCP_TOKEN", "X_MCP_USER")}
            for user_id, source in ((7, "web"), (8, "dingtalk_clawbot"), (9, "weixin_clawbot")):
                agent, session, model = _agent(), _session(), _model()
                agent.user_id = session.user_id = model.user_id = user_id
                session.source = source
                db = _DB(session, model)
                result = asyncio.run(agent_service.execute_agent_turn(
                    agent=agent, user_input="run skill", session_id=11,
                    user_id=user_id, source=source, db=db,
                ))
                assert result.status == "succeeded", result.error
                assert sandbox.env == variables
                assert "test-only-token" not in (db.run.config_snapshot or "")
