"""Configuration CRUD and confirmed runtime changes never import old files."""
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from sqlalchemy.orm import sessionmaker

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agent_routes import create_agent, copy_agent, router, update_agent
from auth import CurrentUser, get_current_active_user
from database import get_db, settings
from enterprise_workspace import utcnow
from agent_execution_lease import AgentExecutionLeaseHandle
from agent_service import _finish_run_record
from exception_handlers import http_exception_handler
from models import (Agent, AgentMessage, AgentRun, AgentSession, PlatformAgentSettings,
                    RuntimeInstance, Skill, UserWorkspace, WorkspaceExecutionLease,
                    SkillRelease, SkillInstallation, ExpertSkillBinding,
                    McpDefinition, McpRevision, McpConnection, ExpertMcpBinding,
                    PromptTemplate, ModelRunCredential, ChannelMessage,
                    CreditAccount, ModelPricingVersion)
from sandbox.container import ContainerSandbox
from runtimes import RUNTIME_REGISTRY
from schemas import AgentCreate, AgentUpdate
from test_agent_routes import _create_db
from test_runtime_migration import migration, seed
from workspace_provider import agent_workspace_snapshot, workspace_snapshot


@pytest.fixture
def db():
    with _create_db() as session, patch('enterprise_workspace.configured_sandbox_type', return_value='container'):
        seed(session)
        policy = session.get(PlatformAgentSettings, 60)
        policy.runtime_type, policy.thinking_level = 'claude_code', 'inherit'
        session.get(UserWorkspace, 10).migration_status = 'pending'
        session.commit()
        yield session


def test_runtime_change_requires_confirmation_before_any_configuration_write(db):
    with pytest.raises(HTTPException) as error:
        update_agent(20, AgentUpdate(name='Changed'), db, CurrentUser(7))
    assert error.value.status_code == 409
    assert '强制终止' in error.value.detail['message']
    assert '其他用户' in error.value.detail['message']
    assert '清空工作区文件' in error.value.detail['message']
    assert error.value.detail['data']['target_runtime'] == 'claude_code'
    # Commit explicitly, proving no pending ORM mutations escaped the check.
    db.commit()
    assert db.get(Agent, 20).name == 'Expert'
    assert db.get(Agent, 20).runtime_type == migration.LEGACY_RUNTIME
    assert db.get(UserWorkspace, 10).workspace_key == 'test'
    assert db.get(AgentSession, 30).runtime_session_id == 'gateway-session'


def test_confirmation_works_with_the_application_error_envelope(db):
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_active_user] = lambda: CurrentUser(7)
    with TestClient(app) as client:
        response = client.put('/api/agents/20', json={'name': 'Changed'})
        assert response.status_code == 409
        assert response.json()['data']['code'] == 'RUNTIME_CHANGE_CONFIRMATION_REQUIRED'
        response = client.put('/api/agents/20', json={
            'name': 'Changed', 'confirm_runtime_change': 'claude_code',
        })
        assert response.status_code == 200
        assert response.json()['runtime_type'] == 'claude_code'


def test_confirmed_switch_uses_empty_files_and_clears_resume_identity(db, tmp_path):
    with patch.object(settings, 'user_workspace_root', str(tmp_path)):
        old = tmp_path / 'test' / 'files'
        old.mkdir(parents=True)
        (old / 'private.txt').write_text('old workspace')
        # An unsupported old symlink must never prevent saving or the new Run.
        (old / 'escape').symlink_to(tmp_path)
        with patch('agent_routes.get_workspace_provider') as provider:
            result = update_agent(20, AgentUpdate(
                name='Changed', confirm_runtime_change='claude_code',
            ), db, CurrentUser(7))
        provider.assert_not_called()
        assert result.runtime_type == 'claude_code' and result.default_model_id == 2
        workspace = db.get(UserWorkspace, 10)
        assert workspace.workspace_key != 'test'
        assert workspace.migration_status == 'not_required'
        session = db.get(AgentSession, 30)
        assert session.runtime_type == 'claude_code'
        assert session.runtime_session_id is session.claude_session_id is session.runtime_instance_id is None
        assert db.get(RuntimeInstance, 40).status == 'retired'
        assert db.get(RuntimeInstance, 40).auth_secret_encrypted is None
        assert db.get(AgentMessage, 31).content == 'previous question'
        assert (old / 'private.txt').read_text() == 'old workspace'
        sandbox = ContainerSandbox()
        # Verify real configuration/view generation without requiring Docker.
        with patch.object(sandbox, '_require_docker'), patch(
            'sandbox.container.legacy_workspace_roots', side_effect=AssertionError('must not read old files'),
        ):
            context = sandbox.prepare_execution(
                agent_workspace_snapshot(db.get(Agent, 20)), None,
                run_id='new-run', workspace=workspace_snapshot(workspace),
            )
        assert list(Path(context.persistent_files_path).iterdir()) == []
        assert not (Path(context.execution_view_path) / 'private.txt').exists()
        assert (Path(context.execution_view_path) / 'CLAUDE.md').exists()
        sandbox.discard_execution(context)
        key = workspace.workspace_key
        update_agent(20, AgentUpdate(description='same runtime'), db, CurrentUser(7))
        assert workspace.workspace_key == key


@pytest.mark.parametrize('status', ['queued', 'running', 'unknown'])
def test_confirmed_switch_stops_unfinished_runs_and_fences_old_writer(db, status):
    run = db.get(AgentRun, 'historic')
    run.status, run.workspace_id = status, 10
    db.add(WorkspaceExecutionLease(
        workspace_id=10, run_id=run.id, owner_id='worker', fencing_token=4,
        lease_until=utcnow() + timedelta(minutes=1), heartbeat_at=utcnow(),
    ))
    db.commit()
    with patch('agent_routes.cancel_web_run') as cancel:
        update_agent(20, AgentUpdate(name='Changed', confirm_runtime_change='claude_code'), db, CurrentUser(7))
    cancel.assert_called_once_with('historic')
    assert run.status == 'cancelled' and run.cancel_requested
    assert run.finished_at is not None and run.worker_id is run.lease_until is None
    assert run.error_code == 'runtime_changed'
    assert db.get(Agent, 20).name == 'Changed'
    assert db.get(Agent, 20).runtime_type == 'claude_code'
    assert db.get(UserWorkspace, 10).workspace_key != 'test'
    lease = db.get(WorkspaceExecutionLease, 10)
    assert lease.fencing_token == 5 and lease.run_id is lease.owner_id is None
    handle = AgentExecutionLeaseHandle(10, 'historic', 'worker', 4, 30, sessionmaker(bind=db.get_bind()))
    assert not handle._renew()
    assert not handle.commit_workspace(lambda: pytest.fail('old writer must be fenced'))
    _finish_run_record(db, run, 'succeeded')
    assert run.status == 'cancelled' and run.error_code == 'runtime_changed'


def test_confirmed_switch_releases_skill_sync_lease_without_run_record(db):
    db.add(WorkspaceExecutionLease(
        workspace_id=10, run_id='skill-sync', owner_id='worker', fencing_token=4,
        lease_until=utcnow() + timedelta(minutes=1), heartbeat_at=utcnow(),
    ))
    db.commit()
    update_agent(20, AgentUpdate(confirm_runtime_change='claude_code'), db, CurrentUser(7))
    lease = db.get(WorkspaceExecutionLease, 10)
    assert lease.fencing_token == 5 and lease.run_id is None


def test_unconfirmed_switch_keeps_tasks_running(db):
    db.get(AgentRun, 'historic').status = 'running'
    db.commit()
    with patch('agent_routes.cancel_web_run') as cancel, pytest.raises(HTTPException):
        update_agent(20, AgentUpdate(name='Changed'), db, CurrentUser(7))
    cancel.assert_not_called()
    db.expire_all()
    assert db.get(AgentRun, 'historic').status == 'running'
    assert not db.get(AgentRun, 'historic').cancel_requested
    assert db.get(UserWorkspace, 10).workspace_key == 'test'


def test_failed_binding_rolls_back_workspace_key_and_session_reset(db):
    db.get(AgentRun, 'historic').status = 'running'
    db.add(WorkspaceExecutionLease(
        workspace_id=10, run_id='historic', owner_id='worker', fencing_token=4,
        lease_until=utcnow() + timedelta(minutes=1), heartbeat_at=utcnow(),
    ))
    db.commit()
    with patch('agent_routes.bind_agent_workspace', side_effect=RuntimeError('database unavailable')), \
            patch('agent_routes.cancel_web_run') as cancel:
        with pytest.raises(HTTPException) as error:
            update_agent(20, AgentUpdate(name='Changed', confirm_runtime_change='claude_code'), db, CurrentUser(7))
    cancel.assert_not_called()
    assert error.value.status_code == 503
    assert db.get(UserWorkspace, 10).workspace_key == 'test'
    assert db.get(AgentSession, 30).runtime_session_id == 'gateway-session'
    assert db.get(Agent, 20).runtime_type == migration.LEGACY_RUNTIME
    assert db.get(AgentRun, 'historic').status == 'running'
    assert not db.get(AgentRun, 'historic').cancel_requested
    assert db.get(WorkspaceExecutionLease, 10).fencing_token == 4
    assert db.get(WorkspaceExecutionLease, 10).run_id == 'historic'


def test_switch_stops_visitors_and_channel_tasks_but_keeps_other_agents(db):
    db.add_all([
        UserWorkspace(id=11, user_id=8, agent_id=20, workspace_key='visitor'),
        UserWorkspace(id=12, user_id=7, agent_id=21, workspace_key='other'),
        Agent(id=21, user_id=7, name='Other'),
        AgentRun(id='visitor', user_id=8, agent_id=20, session_id=30, workspace_id=11, status='running'),
        AgentRun(id='other', user_id=7, agent_id=21, session_id=30, workspace_id=12, status='running'),
        ChannelMessage(id=100, binding_id=1, conversation_id=1, agent_session_id=30,
                       direction='inbound', message_type='text', status='running'),
    ])
    db.get(AgentRun, 'historic').status = 'running'
    db.get(AgentRun, 'historic').source_message_id = 100
    db.commit()
    with patch('agent_routes.cancel_web_run') as cancel:
        update_agent(20, AgentUpdate(confirm_runtime_change='claude_code'), db, CurrentUser(7))
    assert {call.args[0] for call in cancel.call_args_list} == {'historic', 'visitor'}
    assert db.get(AgentRun, 'visitor').status == 'cancelled'
    assert db.get(ChannelMessage, 100).status == 'cancelled'
    assert db.get(AgentRun, 'other').status == 'running'
    assert db.get(UserWorkspace, 11).workspace_key != 'visitor'
    assert db.get(UserWorkspace, 12).workspace_key == 'other'


def test_switch_revokes_model_credential_and_retains_pending_usage(db):
    run = db.get(AgentRun, 'historic')
    run.status, run.reserved_points, run.settlement_status = 'running', 100, 'reserved'
    db.add_all([
        CreditAccount(id=1, user_id=7, available_balance=200, reserved_balance=100),
        ModelPricingVersion(id=1, model_id=2, version=1, input_rate=100, rate_scale=100),
        ModelRunCredential(id=1, run_id=run.id, user_id=7, model_id=2,
                           pricing_version_id=1, token_hash='test-hash', max_points=100,
                           request_count=1, request_in_flight=True,
                           expires_at=utcnow() + timedelta(hours=1)),
    ])
    db.commit()
    with patch('agent_routes.cancel_web_run'):
        update_agent(20, AgentUpdate(confirm_runtime_change='claude_code'), db, CurrentUser(7))
    assert db.get(ModelRunCredential, 1).status == 'reconciliation'
    assert run.settlement_status == 'pending_reconciliation'
    assert db.get(CreditAccount, 1).reserved_balance == 100


def test_same_runtime_save_does_not_stop_tasks(db):
    db.get(Agent, 20).runtime_type = 'claude_code'
    db.get(RuntimeInstance, 40).runtime_type = 'claude_code'
    db.get(AgentRun, 'historic').status = 'running'
    db.commit()
    with patch('agent_routes.cancel_web_run') as cancel:
        update_agent(20, AgentUpdate(name='Changed'), db, CurrentUser(7))
    cancel.assert_not_called()
    assert db.get(AgentRun, 'historic').status == 'running'


def test_runtime_switch_preserves_asset_bindings_and_other_agent_workspace(db):
    agent = db.get(Agent, 20)
    prompt = PromptTemplate(id=108, user_id=7, name='Identity', content='Keep this identity')
    agent.prompt_templates = [prompt]
    db.add_all([
        Skill(id=100, user_id=7, name='Installed skill', version='1'),
        SkillRelease(id=101, skill_id=100, version='1', status='published',
                     file_path='unused.zip', file_url='/releases/unused.zip'),
        SkillInstallation(id=102, user_id=7, scope_agent_id=20, workspace_id=10,
                          skill_id=100, release_id=101, status='active'),
        ExpertSkillBinding(id=103, agent_id=20, installation_id=102),
        McpDefinition(id=104, owner_user_id=7, name='Installed MCP', scope='user',
                      transport_type='http', status='published'),
        McpRevision(id=105, definition_id=104, version='1', status='published',
                    config_json='{}', content_sha256='test', created_by=7),
        McpConnection(id=106, user_id=7, scope_agent_id=20, workspace_id=10,
                      definition_id=104, revision_id=105, name='Connection',
                      config_overrides_json='{"headers":{"X-Test":"kept"}}', status='active'),
        ExpertMcpBinding(id=107, agent_id=20, connection_id=106, status='active'),
        Agent(id=21, user_id=7, name='Other expert', runtime_type='claude_code'),
        UserWorkspace(id=11, user_id=7, agent_id=21, workspace_key='other-expert'),
    ])
    db.commit()
    result = update_agent(20, AgentUpdate(confirm_runtime_change='claude_code'), db, CurrentUser(7))
    assert result.skill_ids == [100]
    assert result.mcp_ids == [104]
    assert result.prompt_template_ids == [108]
    assert db.get(SkillInstallation, 102).workspace_id == 10
    assert db.get(McpConnection, 106).workspace_id == 10
    assert db.get(McpConnection, 106).config_overrides_json == '{"headers":{"X-Test":"kept"}}'
    assert db.get(UserWorkspace, 11).workspace_key == 'other-expert'


def test_no_policy_explicit_runtime_switch_requires_confirmation(db):
    db.delete(db.get(PlatformAgentSettings, 60))
    db.get(Agent, 20).thinking_level = 'inherit'
    db.commit()
    with pytest.raises(HTTPException) as error:
        update_agent(20, AgentUpdate(runtime_type='claude_code'), db, CurrentUser(7))
    assert error.value.status_code == 409
    result = update_agent(20, AgentUpdate(
        runtime_type='claude_code', confirm_runtime_change='claude_code',
    ), db, CurrentUser(7))
    assert result.runtime_type == 'claude_code'
    assert db.get(UserWorkspace, 10).migration_status == 'not_required'


def test_existing_pending_legacy_import_also_requires_confirmation(db):
    db.get(Agent, 20).runtime_type = 'claude_code'
    db.get(RuntimeInstance, 40).status = 'retired'
    db.commit()
    with pytest.raises(HTTPException) as error:
        update_agent(20, AgentUpdate(name='Changed'), db, CurrentUser(7))
    assert error.value.status_code == 409
    update_agent(20, AgentUpdate(confirm_runtime_change='claude_code'), db, CurrentUser(7))
    assert db.get(UserWorkspace, 10).migration_status == 'not_required'


def test_same_runtime_sandbox_migration_keeps_its_files_and_pending_state(db):
    db.get(Agent, 20).runtime_type = 'claude_code'
    db.get(RuntimeInstance, 40).runtime_type = 'claude_code'
    db.commit()
    update_agent(20, AgentUpdate(name='Changed'), db, CurrentUser(7))
    assert db.get(UserWorkspace, 10).workspace_key == 'test'
    assert db.get(UserWorkspace, 10).migration_status == 'pending'


def test_confirmation_cannot_authorize_a_new_policy_target(db):
    with patch.dict(RUNTIME_REGISTRY, future_runtime=RUNTIME_REGISTRY['claude_code']):
        db.get(PlatformAgentSettings, 60).runtime_type = 'future_runtime'
        db.commit()
        with pytest.raises(HTTPException) as error:
            update_agent(20, AgentUpdate(confirm_runtime_change='claude_code'), db, CurrentUser(7))
        assert error.value.status_code == 409
        assert error.value.detail['data']['target_runtime'] == 'future_runtime'
        assert db.get(UserWorkspace, 10).workspace_key == 'test'


def test_create_and_copy_agents_with_resources_do_not_prepare_container(db):
    skill = Skill(id=99, user_id=7, name='Example', version='1', is_public=True)
    db.add(skill)
    db.commit()
    with patch('agent_routes.get_workspace_provider', return_value=ContainerSandbox()) as provider:
        created = create_agent(AgentCreate(name='New', skill_ids=[99]), db, CurrentUser(7))
        db.get(Agent, created.id).is_public = True
        db.commit()
        copied = copy_agent(created.id, db, CurrentUser(8))
    provider.assert_not_called()
    assert created.name == 'New' and copied.name == 'New（副本）'
