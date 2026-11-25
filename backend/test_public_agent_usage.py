"""Public configuration stays with its owner; execution belongs to its caller."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from fastapi import HTTPException
from agent_access import get_usable_agent
from agent_routes import (get_agent, list_agents, list_public_agents, create_session,
                          list_sessions, get_messages, update_agent, publish_agent,
                          unpublish_agent, delete_agent, list_workspace_files,
                          get_agent_statistics, cancel_agent_run, copy_agent)
from agent_service import _queue_web_run, execute_agent_turn
from asset_runtime import load_runtime_assets
from asset_routes import (list_skill_catalog, list_mcp_connections, install_skill, uninstall_skill, create_mcp_connection,
                          delete_mcp_connection, import_prompt_snapshot, unbind_prompt_template, import_mcp_definition,
                          inspect_mcp_connection, router as asset_router)
from asset_schemas import SkillInstallRequest, McpConnectionCreateRequest, PromptImportRequest, McpImportRequest
from auth import CurrentUser
from enterprise_workspace import bind_agent_workspace
from models import (Agent, AgentSession, AgentRun, AIModel, UserWorkspace, PromptTemplate,
                    Skill, SkillRelease, SkillInstallation, ExpertSkillBinding,
                    McpDefinition, McpRevision, McpConnection, ExpertMcpBinding,
                    CredentialReference, McpService)
from schemas import AgentSessionCreate, AgentUpdate
from test_agent_routes import _create_db
from agent_prompt_snapshots import freeze_agent_prompts
from runtimes.base import RuntimeEvent
from test_agent_service import _Sandbox
from mcp_headers import ENCRYPTED_HEADERS, ENCRYPTED_ENV


class PublicAgentUsageTests(unittest.TestCase):
    def setUp(self):
        self.db = _create_db()
        self.addCleanup(self.db.close)
        self.owner, self.visitor, self.other = CurrentUser(7), CurrentUser(8), CurrentUser(9)
        self.agent = Agent(id=99, user_id=7, name='公开专家', kind='expert', is_public=True,
                           system_prompt='专家身份', workspace_id=70)
        self.db.add_all([
            self.agent,
            UserWorkspace(id=70, user_id=7, agent_id=99, workspace_key='owner-private'),
            AIModel(id=71, user_id=7, name='owner-model', provider='anthropic',
                    api_protocol='anthropic-messages', scope='user'),
            AIModel(id=81, user_id=8, name='caller-model', provider='anthropic',
                    api_protocol='anthropic-messages', scope='user'),
            AgentSession(id=701, agent_id=99, user_id=7, workspace_id=70, title='owner-history'),
        ])
        self.agent.default_model_id = 71
        self.db.commit()
        sandbox = patch('enterprise_workspace.configured_sandbox_type', return_value='container')
        sandbox.start()
        self.addCleanup(sandbox.stop)

    def test_public_discovery_detail_uses_callers_models_and_session_count(self):
        catalog = list_public_agents(q='', skip=0, limit=100, db=self.db)
        self.assertEqual([x['id'] for x in catalog['items']], [99])
        self.assertEqual(list_agents(skip=0, limit=100, db=self.db, current_user=self.visitor).total, 0)
        result = get_agent(99, self.db, self.visitor)
        self.assertFalse(result.can_edit)
        self.assertEqual(result.model_ids, [81])
        self.assertEqual(result.default_model_id, 81)
        self.assertEqual(result.session_count, 0)
        self.assertEqual(result.mcp_overrides, [])
        self.assertTrue(get_agent(99, self.db, self.owner).can_edit)
        self.assertEqual(self.db.query(Agent).count(), 1, 'Direct use must not create an editable copy')

    def test_private_unpublished_deleted_and_private_resource_agents_rejected(self):
        for field in ('is_public', 'is_deleted'):
            with self.subTest(field=field):
                setattr(self.agent, field, field == 'is_deleted')
                self.db.commit()
                with self.assertRaises(HTTPException):
                    get_usable_agent(self.db, 99, 8)
                setattr(self.agent, field, field == 'is_public')
                self.db.commit()
        template = PromptTemplate(id=1, user_id=7, name='Private', content='private')
        self.db.add(template)
        self.db.flush()
        self.agent.prompt_templates = [template]
        freeze_agent_prompts(self.db, self.agent.id)
        self.db.commit()
        with self.assertRaises(HTTPException):
            get_agent(99, self.db, self.visitor)
        self.assertEqual(list_public_agents(q='', skip=0, limit=100, db=self.db)['total'], 0)

    def test_configuration_mutations_are_owner_only(self):
        # Use real public resource IDs so denial is about the agent, not a
        # missing source. Archive parsing is unrelated to this permission test.
        skill = Skill(id=1, user_id=7, name='Public skill', version='1', is_public=True)
        release = SkillRelease(id=1, skill_id=1, version='1', status='published',
                               file_path='unused.zip', file_url='/releases/unused.zip')
        self.db.add_all([
            skill, release,
            McpDefinition(id=1, owner_user_id=7, name='Public MCP', scope='public', transport_type='http', status='published'),
            McpRevision(id=1, definition_id=1, version='1', status='published', created_by=7,
                        content_sha256='a'*64, config_json='{}'),
            PromptTemplate(id=1, user_id=7, name='Public prompt', content='Public content', is_public=True),
        ])
        self.db.commit()
        source = patch('asset_routes._skill_release', return_value=(release, skill, None, {}))
        source.start()
        self.addCleanup(source.stop)
        actions = [
            lambda: update_agent(99, AgentUpdate(name='tampered'), self.db, self.visitor),
            lambda: publish_agent(99, self.db, self.visitor),
            lambda: unpublish_agent(99, self.db, self.visitor),
            lambda: delete_agent(99, self.db, self.visitor),
            lambda: install_skill(SkillInstallRequest(release_id=1, agent_id=99), self.db, self.visitor),
            lambda: create_mcp_connection(McpConnectionCreateRequest(definition_id=1, revision_id=1, name='bad', agent_id=99), self.db, self.visitor),
            lambda: import_prompt_snapshot(PromptImportRequest(source_template_id=1, agent_id=99), self.db, self.visitor),
            lambda: unbind_prompt_template(1, 99, self.db, self.visitor),
        ]
        for action in actions:
            with self.subTest(action=action):
                with self.assertRaises(HTTPException) as error:
                    action()
                self.assertIn(error.exception.status_code, (403, 404))
        self.assertEqual(self.db.get(Agent, 99).name, '公开专家')

    def test_publication_requires_saved_available_platform_default_model(self):
        self.agent.is_public = False
        model = self.db.get(AIModel, 71)
        for model_id, scope, enabled, deleted in (
            (None, 'platform', True, False), (999, 'platform', True, False),
            (71, 'user', True, False), (71, 'platform', False, False),
            (71, 'platform', True, True),
        ):
            with self.subTest(model_id=model_id, scope=scope, enabled=enabled, deleted=deleted):
                self.agent.default_model_id = model_id
                model.scope, model.is_enabled, model.is_deleted = scope, enabled, deleted
                self.db.commit()
                with self.assertRaises(HTTPException) as error:
                    publish_agent(99, self.db, self.owner)
                self.assertEqual(error.exception.status_code, 409)
                self.assertIn('平台模型', error.exception.detail)
                self.assertFalse(self.agent.is_public)
        self.agent.default_model_id = 71
        model.scope, model.is_enabled, model.is_deleted = 'platform', True, False
        self.db.commit()
        self.assertTrue(publish_agent(99, self.db, self.owner).is_public)
        self.assertEqual(get_agent(99, self.db, self.visitor).default_model_id, 71)

    def test_published_default_cannot_be_changed_to_custom_model(self):
        self.db.get(AIModel, 71).scope = 'platform'
        self.db.add(AIModel(id=72, user_id=7, name='Custom model', provider='anthropic',
                            api_protocol='anthropic-messages', scope='user'))
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            update_agent(99, AgentUpdate(default_model_id=72), self.db, self.owner)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.agent.default_model_id, 71)
        unpublish_agent(99, self.db, self.owner)
        with patch('agent_routes.get_workspace_provider', return_value=_Sandbox()):
            result = update_agent(99, AgentUpdate(default_model_id=72), self.db, self.owner)
        self.assertEqual(result.default_model_id, 72)
        self.assertFalse(result.is_public)

    def test_publication_error_preserves_named_resources_in_http_response(self):
        from exception_handlers import http_exception_handler
        self.db.get(AIModel, 71).scope = 'platform'
        self.agent.is_public = False
        template = PromptTemplate(id=1, user_id=7, name='合规提示词', content='private', is_public=False)
        self.db.add_all([
            template,
            Skill(id=1, user_id=7, name='商品合规技能', version='1', is_public=False),
            SkillRelease(id=2, skill_id=1, version='1', status='published', file_path='unused.zip', file_url='/releases/unused.zip'),
            SkillInstallation(id=3, user_id=7, scope_agent_id=99, workspace_id=70, skill_id=1, release_id=2, status='active'),
            ExpertSkillBinding(agent_id=99, installation_id=3),
            McpDefinition(id=11, owner_user_id=7, name='合规 MCP', scope='user', transport_type='http', status='published'),
            McpRevision(id=12, definition_id=11, version='1', status='published', created_by=7, content_sha256='a'*64, config_json='{}'),
            McpConnection(id=14, user_id=7, scope_agent_id=99, workspace_id=70, definition_id=11, revision_id=12, name='合规 MCP', status='active'),
            ExpertMcpBinding(agent_id=99, connection_id=14, status='active'),
        ])
        self.agent.prompt_templates = [template]
        freeze_agent_prompts(self.db, 99)
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            publish_agent(99, self.db, self.owner)
        response = asyncio.run(http_exception_handler(None, error.exception))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.body)['data']['items'], [
            '技能未公开: 商品合规技能', 'MCP 未公开: 合规 MCP', '提示词未公开: 合规提示词',
        ])
        self.assertFalse(self.agent.is_public)

    def test_conversations_files_and_workspace_pointers_are_isolated(self):
        sessions = [create_session(99, AgentSessionCreate(agent_id=99), self.db, user) for user in (self.visitor, self.other)]
        self.assertNotEqual(sessions[0].workspace_id, sessions[1].workspace_id)
        self.assertNotIn(70, [s.workspace_id for s in sessions])
        self.assertEqual(self.agent.workspace_id, 70)
        for user, session in zip((self.visitor, self.other), sessions):
            result = list_sessions(99, skip=0, limit=100, db=self.db, current_user=user)
            self.assertEqual([s.id for s in result.items], [session.id])
        for forbidden in (701, sessions[1].id):
            with self.assertRaises(HTTPException):
                get_messages(99, forbidden, limit=50, before_id=None, db=self.db, current_user=self.visitor)
        seen = []
        provider = SimpleNamespace(list_dir=lambda workspace, path: seen.append(workspace.user_id) or {'type': 'dir', 'items': []})
        with patch('agent_routes.get_workspace_provider', return_value=provider):
            list_workspace_files(99, '', self.db, self.visitor)
            list_workspace_files(99, '', self.db, self.other)
        self.assertEqual(seen, [8, 9])
        shared = get_usable_agent(self.db, 99, 8)
        workspace, _ = bind_agent_workspace(self.db, shared)
        self.assertEqual(workspace.legacy_agent_ids, [])
        self.assertEqual(self.agent.workspace_id, 70)

    def test_queue_records_caller_and_rechecks_publication(self):
        # _queue_web_run closes its own Session; use a separate session on the in-memory engine.
        from sqlalchemy.orm import sessionmaker
        factory = sessionmaker(bind=self.db.get_bind())
        with patch('agent_service.SessionLocal', factory):
            session_id = _queue_web_run(99, 'question', None, 8, None, 81, 'visitor-run')
        run = self.db.get(AgentRun, 'visitor-run')
        self.assertEqual(run.user_id, 8)
        self.assertEqual(run.session_id, session_id)
        self.assertEqual(self.db.get(UserWorkspace, run.workspace_id).user_id, 8)
        self.agent.is_public = False
        self.db.commit()
        with patch('agent_service.SessionLocal', factory), self.assertRaises(HTTPException):
            _queue_web_run(99, 'question', None, 9, None, None, 'rejected-run')
        # Revocation must not prevent stopping one's own already-running request.
        with patch('agent_routes.cancel_web_run', return_value=False):
            self.assertTrue(cancel_agent_run(99, run.id, self.db, self.visitor)['cancel_requested'])

    def test_public_mcp_never_uses_publisher_overrides_or_vault(self):
        self.db.add_all([
            McpDefinition(id=11, owner_user_id=7, name='Public MCP', scope='public', transport_type='http', status='published'),
            McpRevision(id=12, definition_id=11, version='1', status='published', created_by=7,
                        content_sha256='a'*64, config_json=json.dumps({'url': 'https://mcp.example.com', 'headers': {'X-Private': 'definition-secret'}})),
            CredentialReference(id=13, user_id=7, name='vault', secret_encrypted='owner-ciphertext', fingerprint='b'*64),
            McpConnection(id=14, user_id=7, scope_agent_id=99, workspace_id=70, definition_id=11,
                          revision_id=12, name='Public MCP', status='active', auth_mode='current_user',
                          credential_reference_id=13, config_overrides_json=json.dumps({'url': 'https://private.example.com', 'headers': {'X-Private': 'owner-secret'}})),
            ExpertMcpBinding(agent_id=99, connection_id=14, status='active'),
        ])
        self.db.commit()
        with patch('asset_runtime.validate_mcp_config', return_value={}), patch('asset_runtime.decrypt_agent_credential') as decrypt:
            assets = load_runtime_assets(self.db, get_usable_agent(self.db, 99, 8), 8,
                                         request_authorization='Bearer caller-token')
        decrypt.assert_not_called()
        self.assertEqual(list(assets['secret_env'].values()), ['Bearer caller-token'])
        self.assertEqual(json.loads(assets['mcps'][0].config)['url'], 'https://mcp.example.com')
        self.assertIsNone(assets['mcp_snapshot'][0]['credential_reference_id'])
        with self.assertRaises(HTTPException):
            delete_mcp_connection(14, self.db, self.visitor, agent_id=99)

    def _inspection_mcp(self):
        self.enterContext(patch('asset_security.socket.getaddrinfo', return_value=[
            (2, 1, 6, '', ('93.184.216.34', 443)),
        ]))
        self.db.add_all([
            McpDefinition(id=11, owner_user_id=7, name='Public MCP', scope='public', transport_type='http', status='published'),
            McpRevision(id=12, definition_id=11, version='1', status='published', created_by=7,
                        content_sha256='a'*64, config_json=json.dumps({
                            'url': 'https://mcp.example.com',
                            'headers': {'X-Private': 'definition-secret'},
                            ENCRYPTED_HEADERS: 'must-not-decrypt',
                            'env': {'PRIVATE': 'definition-secret'},
                            ENCRYPTED_ENV: 'must-not-decrypt',
                        })),
            CredentialReference(id=13, user_id=7, name='vault', secret_encrypted='owner-ciphertext', fingerprint='b'*64),
            McpConnection(id=14, user_id=7, scope_agent_id=99, workspace_id=70, definition_id=11,
                          revision_id=12, name='Public MCP', status='active', auth_mode='current_user',
                          credential_reference_id=13, config_overrides_json=json.dumps({
                              'url': 'https://private.example.com', 'headers': {'Authorization': 'owner-secret'},
                          })),
            ExpertMcpBinding(agent_id=99, connection_id=14, status='active'),
        ])
        self.db.commit()

    def test_public_mcp_inspection_uses_caller_token_without_owner_secrets(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from auth import get_current_active_user
        from database import get_db
        self._inspection_mcp()
        app = FastAPI()
        app.include_router(asset_router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_active_user] = lambda: self.visitor
        resources = {'tools': [{'name': 'search'}], 'resources': [{'uri': 'mcp://catalog'}], 'prompts': []}
        with patch('asset_routes.inspect_mcp_server', new_callable=AsyncMock, return_value=resources) as inspect, \
                patch('asset_routes.decrypt_agent_credential') as decrypt, TestClient(app) as client:
            response = client.get('/api/assets/mcp/connections/14/inspect?agent_id=99',
                                  headers={'Authorization': 'Bearer visitor-token'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['resources'], resources['resources'])
        inspect.assert_awaited_once_with('http', {
            'url': 'https://mcp.example.com', 'headers': {'Authorization': 'Bearer visitor-token'},
        })
        decrypt.assert_not_called()

    def test_public_imported_mcp_inspection_checks_source_visibility(self):
        self._inspection_mcp()
        definition = self.db.get(McpDefinition, 11)
        definition.scope, definition.source_mcp_service_id = 'user', 15
        self.db.add(McpService(id=15, user_id=7, name='Source', type='http', is_public=True))
        self.db.commit()
        with patch('asset_routes.inspect_mcp_server', new_callable=AsyncMock, return_value={}) as inspect:
            asyncio.run(inspect_mcp_connection(14, self.db, self.visitor, 99, 'Bearer visitor-token'))
            inspect.assert_awaited_once()
            self.db.get(McpService, 15).is_public = False
            self.db.commit()
            with self.assertRaises(HTTPException):
                asyncio.run(inspect_mcp_connection(14, self.db, self.visitor, 99, 'Bearer visitor-token'))
            self.assertEqual(inspect.await_count, 1)

    def test_public_mcp_inspection_denies_unrelated_scopes_and_private_agents(self):
        self._inspection_mcp()
        connection = self.db.get(McpConnection, 14)
        binding = self.db.query(ExpertMcpBinding).filter_by(agent_id=99).one()
        cases = [
            (connection, 'scope_agent_id', 0, 99),
            (connection, 'user_id', 9, 99),
            (binding, 'status', 'disabled', 99),
            (connection, 'status', 'deleted', 99),
            (self.agent, 'is_public', False, 99),
            (self.agent, 'is_deleted', True, 99),
        ]
        with patch('asset_routes.inspect_mcp_server', new_callable=AsyncMock) as inspect:
            for row, field, value, agent_id in cases:
                original = getattr(row, field)
                with self.subTest(field=field, value=value, agent_id=agent_id):
                    setattr(row, field, value)
                    self.db.commit()
                    with self.assertRaises(HTTPException):
                        asyncio.run(inspect_mcp_connection(14, self.db, self.visitor, agent_id, 'Bearer visitor-token'))
                    setattr(row, field, original)
                    self.db.commit()
            with self.assertRaises(HTTPException):
                asyncio.run(inspect_mcp_connection(14, self.db, self.visitor, None, 'Bearer visitor-token'))
            inspect.assert_not_awaited()

    def test_public_mcp_inspection_requires_caller_authorization_only_when_configured(self):
        self._inspection_mcp()
        with patch('asset_routes.inspect_mcp_server', new_callable=AsyncMock, return_value={}) as inspect:
            with self.assertRaises(HTTPException) as error:
                asyncio.run(inspect_mcp_connection(14, self.db, self.visitor, 99, None))
            self.assertEqual(error.exception.status_code, 409)
            inspect.assert_not_awaited()
            for auth_mode in ('manual', 'none'):
                self.db.get(McpConnection, 14).auth_mode = auth_mode
                self.db.commit()
                asyncio.run(inspect_mcp_connection(14, self.db, self.visitor, 99, 'Bearer visitor-token'))
                self.assertEqual(inspect.await_args.args[1], {'url': 'https://mcp.example.com', 'headers': {}})

    def test_owner_mcp_inspection_keeps_owner_configuration(self):
        self._inspection_mcp()
        connection = self.db.get(McpConnection, 14)
        connection.credential_reference_id, connection.auth_mode = None, 'manual'
        self.db.commit()
        with patch('asset_routes.inspect_mcp_server', new_callable=AsyncMock, return_value={}) as inspect:
            asyncio.run(inspect_mcp_connection(14, self.db, self.owner, 99, None))
        self.assertEqual(inspect.await_args.args[1]['url'], 'https://private.example.com')
        self.assertEqual(inspect.await_args.args[1]['headers'], {'Authorization': 'owner-secret'})

    def test_public_resource_pages_share_metadata_but_not_credentials(self):
        self.db.add_all([
            Skill(id=1, user_id=7, name='Public skill', description='Full description', author='Publisher', version='1', is_public=True),
            Skill(id=4, user_id=7, name='Unrelated private skill', version='1', is_public=False),
            SkillRelease(id=2, skill_id=1, version='1', status='published', file_path='unused.zip', file_url='/releases/unused.zip'),
            SkillInstallation(id=3, user_id=7, scope_agent_id=99, workspace_id=70, skill_id=1, release_id=2, status='active'),
            ExpertSkillBinding(agent_id=99, installation_id=3),
            McpDefinition(id=11, owner_user_id=7, name='Public MCP', scope='public', transport_type='http', status='published'),
            McpRevision(id=12, definition_id=11, version='1', status='published', created_by=7,
                        content_sha256='a'*64, config_json='{"headers":{"Authorization":"secret"}}',
                        security_report_json='{"private":"diagnostic"}'),
            CredentialReference(id=13, user_id=7, name='vault', secret_encrypted='owner-ciphertext', fingerprint='b'*64),
            McpConnection(id=14, user_id=7, scope_agent_id=99, workspace_id=70, definition_id=11,
                          revision_id=12, name='Public MCP', status='active', auth_mode='current_user', credential_reference_id=13),
            ExpertMcpBinding(agent_id=99, connection_id=14, status='disabled'),
            McpDefinition(id=21, owner_user_id=7, name='Private disabled MCP', scope='user', transport_type='http', status='published'),
            McpRevision(id=22, definition_id=21, version='1', status='published', created_by=7, content_sha256='b'*64, config_json='{}'),
            McpConnection(id=24, user_id=7, scope_agent_id=99, workspace_id=70, definition_id=21,
                          revision_id=22, name='Private disabled MCP', status='active'),
            ExpertMcpBinding(agent_id=99, connection_id=24, status='disabled'),
            McpConnection(id=25, user_id=7, scope_agent_id=0, workspace_id=70, definition_id=11,
                          revision_id=12, name='Unrelated installation', status='active'),
        ])
        self.db.commit()
        owner_catalog = list_skill_catalog(db=self.db, current_user=self.owner, agent_id=99)['items']
        visitor_catalog = list_skill_catalog(db=self.db, current_user=self.visitor, agent_id=99)['items']
        self.assertEqual([row['skill_id'] for row in visitor_catalog], [1])
        for key in ('name', 'description', 'author', 'releases', 'effective_release_id', 'user_installation'):
            self.assertEqual(visitor_catalog[0][key], owner_catalog[0][key], key)
        owner_mcp = list_mcp_connections(self.db, self.owner, agent_id=99)['items']
        visitor_mcp = list_mcp_connections(self.db, self.visitor, agent_id=99)['items']
        self.assertEqual([row['id'] for row in visitor_mcp], [14])
        owner_row = next(row for row in owner_mcp if row['id'] == 14)
        for key in ('name', 'description', 'transport_type', 'auth_mode', 'status', 'revision_version'):
            self.assertEqual(visitor_mcp[0][key], owner_row[key], key)
        self.assertEqual(visitor_mcp[0]['status'], 'disabled')
        self.assertIsNone(visitor_mcp[0]['credential_reference_id'])
        self.assertEqual(visitor_mcp[0]['security_report'], {})
        self.assertNotIn('secret', json.dumps(visitor_mcp))
        self.assertEqual(list_mcp_connections(self.db, self.visitor)['total'], 0)
        # Revocation closes both read endpoints; mutation endpoints remain owner-only.
        self.agent.is_public = False
        self.db.commit()
        for read in (list_skill_catalog, list_mcp_connections):
            with self.assertRaises(HTTPException):
                read(db=self.db, current_user=self.visitor, agent_id=99)

    def test_imported_mcp_follows_source_visibility_for_publish_catalog_use_and_copy(self):
        self.db.get(AIModel, 71).scope = 'platform'
        source = McpService(id=55, user_id=7, name='online-mcp', type='http',
                            config='{"url":"https://mcp.example.com"}', is_public=False)
        self.db.add(source)
        self.db.commit()
        with patch('asset_routes.validate_mcp_config', return_value={}):
            imported = import_mcp_definition(McpImportRequest(source_mcp_service_id=55, agent_id=99), self.db, self.owner)
            create_mcp_connection(McpConnectionCreateRequest(
                definition_id=imported['id'], revision_id=imported['latest_revision']['id'],
                name='online-mcp', agent_id=99, auth_mode='current_user',
            ), self.db, self.owner)
        definition = self.db.get(McpDefinition, imported['id'])
        self.assertEqual(definition.scope, 'user')
        with self.assertRaises(HTTPException):
            publish_agent(99, self.db, self.owner)
        # Publishing after import must take effect without reinstalling or
        # rewriting a user's independent definition/credentials.
        source.is_public = True
        self.db.commit()
        self.assertTrue(publish_agent(99, self.db, self.owner).is_public)
        self.assertEqual(definition.scope, 'user')
        self.assertEqual(list_public_agents(q='', skip=0, limit=1, db=self.db)['total'], 1)
        self.assertEqual(get_agent(99, self.db, self.visitor).mcp_connections[0]['name'], 'online-mcp')
        with patch('asset_runtime.validate_mcp_config', return_value={}):
            runtime = load_runtime_assets(self.db, get_usable_agent(self.db, 99, 8), 8,
                                          request_authorization='Bearer consumer-token')
        self.assertEqual([m.name for m in runtime['mcps']], ['online-mcp'])
        with patch('agent_routes.get_workspace_provider', return_value=SimpleNamespace(prepare=lambda *args, **kwargs: None)):
            copied = copy_agent(99, self.db, self.visitor)
        self.assertEqual(len(copied.mcp_connections), 1, 'Copy must not silently drop an imported public MCP')
        for visibility, deleted in ((False, False), (True, True)):
            with self.subTest(visibility=visibility, deleted=deleted):
                source.is_public, source.is_deleted = visibility, deleted
                self.db.commit()
                with self.assertRaises(HTTPException):
                    get_usable_agent(self.db, 99, 8)
                with self.assertRaises(HTTPException):
                    publish_agent(99, self.db, self.owner)
                self.assertEqual(list_public_agents(q='', skip=0, limit=1, db=self.db)['total'], 0)

    def test_shared_skill_version_and_live_prompt_reference_are_reused_without_copy(self):
        self.db.add_all([
            Skill(id=1, user_id=7, name='Public skill', version='1', is_public=True),
            SkillRelease(id=2, skill_id=1, version='1', status='published', file_path='unused.zip', file_url='/releases/unused.zip'),
            SkillInstallation(id=3, user_id=7, scope_agent_id=99, workspace_id=70, skill_id=1, release_id=2, status='active', granted_capabilities='[]'),
            ExpertSkillBinding(agent_id=99, installation_id=3),
        ])
        template = PromptTemplate(id=1, user_id=7, name='Public prompt', content='snapshot v1', is_public=True)
        self.db.add(template)
        self.db.flush()
        self.agent.prompt_templates = [template]
        freeze_agent_prompts(self.db, self.agent.id)
        self.db.commit()
        template.content = 'source v2'
        self.db.commit()
        cached = SimpleNamespace(content_sha256='hash', files_json='[]', directory='cache')
        with patch('asset_runtime.os.path.isfile', return_value=True), patch('asset_runtime.get_cached_release', return_value=cached):
            assets = load_runtime_assets(self.db, get_usable_agent(self.db, 99, 8), 8, skills_only=True)
        self.assertEqual([s['release_id'] for s in assets['skill_snapshot']], [2])
        self.assertEqual(get_agent(99, self.db, self.visitor).prompt_templates[0]['content'], 'source v2')
        card = list_public_agents(q='', skip=0, limit=100, db=self.db)['items'][0]
        self.assertEqual(card['user_id'], 7)
        self.assertEqual(card['skills'], [{'id': 1, 'name': 'Public skill'}])
        self.assertEqual(card['skill_count'], 1)
        self.assertEqual(self.db.query(SkillInstallation).count(), 1)
        with self.assertRaises(HTTPException):
            uninstall_skill(3, self.db, self.visitor, agent_id=99)

    def test_execution_and_billing_use_caller_identity(self):
        self.db.get(AIModel, 81).scope = 'platform'
        self.db.commit()
        captured = []
        class Runtime:
            async def run(inner, config, ctx, user_input, history, on_event, run_context=None):
                await on_event(RuntimeEvent(type='text', content='public answer'))
                await on_event(RuntimeEvent(type='done'))
        def prepare(db, run, model, *args):
            captured.append((run.user_id, model.id, run.workspace_id))
            return 'test-gateway-token', 'https://example.com'
        with (patch('agent_service.get_workspace_provider', return_value=_Sandbox()),
              patch('agent_service.get_runtime', return_value=Runtime()),
              patch('agent_service.record_run_view'), patch('agent_service.finish_run_view'),
              patch('agent_service.generate_session_title', new=AsyncMock(return_value='Caller question')),
              patch('agent_service.prepare_platform_run', side_effect=prepare),
              patch('agent_service.settle_platform_run')):
            result = asyncio.run(execute_agent_turn(agent=self.agent, user_input='question',
                session_id=None, user_id=8, db=self.db, model_id_override=81, run_id='execution-run'))
        self.assertEqual(result.status, 'succeeded', result.error)
        self.assertEqual(result.final_text, 'public answer')
        self.assertEqual(captured[0][:2], (8, 81))
        self.assertEqual(self.db.get(UserWorkspace, captured[0][2]).user_id, 8)
        self.assertEqual(self.agent.workspace_id, 70)
        self.assertEqual(get_agent_statistics(99, days=7, db=self.db, current_user=self.owner)['summary']['total_runs'], 0)
        self.assertEqual(get_agent_statistics(99, days=7, db=self.db, current_user=self.visitor)['summary']['total_runs'], 1)


if __name__ == '__main__':
    unittest.main()
