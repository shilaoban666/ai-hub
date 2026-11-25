import asyncio
from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

from database import Base
from auth import CurrentUser
from models import (Agent, PromptTemplate, agent_prompt_templates, UserWorkspace,
                    WorkspaceExecutionLease, PlatformAgentSettings, CreditAccount,
                    CreditClaimRecord, CreditLedger, AIModel, AgentRun, AgentSession,
                    ModelPricingVersion)
from asset_routes import import_prompt_snapshot, unbind_prompt_template, list_workspace_prompts
from asset_schemas import PromptImportRequest
from agent_prompts import load_agent_prompts, set_agent_prompts, copy_agent_prompts
from agent_prompt_snapshots import freeze_agent_prompts
from agent_execution_lease import _try_acquire, AgentExecutionLeaseHandle, utcnow, acquire_agent_execution_lease
from credit_accounts import ensure_initial_credits, _grant_claim
from credit_billing import prepare_platform_run, CreditBillingError
import enterprise_routes


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        with patch.object(SQLiteTypeCompiler, 'visit_BIGINT', return_value='INTEGER'):
            Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.db = self.factory()
        self.addCleanup(self.db.close)
        self.user = CurrentUser(user_id=7)
        self.policy = PlatformAgentSettings(version=1, status='published', created_by=7,
                                           max_concurrent_runs=1, initial_claim_amount=10,
                                           daily_claim_amount=2, per_run_limit=1)
        self.db.add_all([
            self.policy, Agent(id=99, user_id=7, name='A'), Agent(id=100, user_id=7, name='B'),
            PromptTemplate(id=1, user_id=8, name='Public', content='v1', is_public=True),
            PromptTemplate(id=2, user_id=7, name='Own', content='own-v1'),
            UserWorkspace(id=1, user_id=7, workspace_key='personal'),
            UserWorkspace(id=2, user_id=7, agent_id=99, workspace_key='agent99'),
            UserWorkspace(id=3, user_id=8, workspace_key='other-user'),
        ])
        self.db.commit()

    def install(self, agent_id, source=1):
        return import_prompt_snapshot(PromptImportRequest(source_template_id=source, agent_id=agent_id), self.db, self.user)

    def test_prompt_references_are_scoped_to_agent_and_follow_source_changes(self):
        for agent_id in (99, 100):
            self.install(agent_id)
            self.install(agent_id, 2)
        self.assertEqual(self.db.query(PromptTemplate).count(), 2)
        self.assertEqual([x['id'] for x in list_workspace_prompts(db=self.db, current_user=self.user)['items']], [2])
        self.db.get(PromptTemplate, 1).content = 'v2'
        self.db.get(PromptTemplate, 2).is_deleted = True
        self.db.commit()
        for agent_id in (99, 100):
            self.assertEqual([p.content for p in load_agent_prompts(self.db, agent_id)], ['v2'])
        unbind_prompt_template(1, 99, self.db, self.user)
        self.install(99)
        self.assertEqual({p.id: p.content for p in load_agent_prompts(self.db, 99)}[1], 'v2')
        self.assertEqual(load_agent_prompts(self.db, 100)[0].content, 'v2')

    def test_repeated_install_keeps_one_live_reference_and_rejects_foreign_agent(self):
        self.install(99)
        self.db.get(PromptTemplate, 1).content = 'v2'
        self.db.commit()
        self.assertEqual(self.install(99)['content'], 'v2')
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            import_prompt_snapshot(PromptImportRequest(source_template_id=1, agent_id=99), self.db, CurrentUser(8))
        self.assertEqual(len(load_agent_prompts(self.db, 99)), 1)

    def test_system_prompts_require_explicit_agent_reference_and_follow_source(self):
        template = self.db.get(PromptTemplate, 1)
        template.is_system = True
        self.db.commit()
        self.assertIn(1, [row['id'] for row in list_workspace_prompts(db=self.db, current_user=self.user)['items']])
        for agent_id in (99, 100):
            self.assertEqual(load_agent_prompts(self.db, agent_id), [])
        self.install(99)
        template.content = 'updated-default-prompt'
        self.db.commit()
        self.assertEqual([p.content for p in load_agent_prompts(self.db, 99)], ['updated-default-prompt'])
        template.is_deleted = True
        self.db.commit()
        self.assertEqual(load_agent_prompts(self.db, 99), [])
        self.assertEqual(load_agent_prompts(self.db, 100), [])
        self.assertNotIn(1, [row['id'] for row in list_workspace_prompts(db=self.db, current_user=self.user)['items']])

    def test_legacy_snapshots_are_ignored_and_reference_copy_preserves_order(self):
        self.db.execute(agent_prompt_templates.insert().values(agent_id=99, prompt_template_id=1, position=5))
        self.db.execute(agent_prompt_templates.insert().values(agent_id=99, prompt_template_id=2, position=1))
        self.db.commit()
        freeze_agent_prompts(self.db, 99)
        self.db.rollback()
        self.assertTrue(all(r.snapshot_json is None for r in self.db.execute(agent_prompt_templates.select())))
        freeze_agent_prompts(self.db, 99)
        self.db.commit()
        self.db.get(PromptTemplate, 1).content = 'changed'
        freeze_agent_prompts(self.db, 99)
        self.db.commit()
        self.assertEqual([p.content for p in load_agent_prompts(self.db, 99)], ['own-v1', 'changed'])
        self.db.execute(agent_prompt_templates.insert().values(agent_id=100, prompt_template_id=1))
        copy_agent_prompts(self.db, 99, 100)
        self.assertEqual([p.content for p in load_agent_prompts(self.db, 100)], ['own-v1', 'changed'])
        self.assertTrue(all(row.snapshot_json is None for row in self.db.execute(
            agent_prompt_templates.select().where(agent_prompt_templates.c.agent_id == 100))))

    def test_reference_order_changes_transactionally_and_new_import_appends(self):
        set_agent_prompts(self.db, 99, [self.db.get(PromptTemplate, 2), self.db.get(PromptTemplate, 1)])
        self.db.commit()
        self.assertEqual([p.id for p in load_agent_prompts(self.db, 99)], [2, 1])
        set_agent_prompts(self.db, 99, [self.db.get(PromptTemplate, 1)])
        self.db.rollback()
        self.assertEqual([p.id for p in load_agent_prompts(self.db, 99)], [2, 1])
        unbind_prompt_template(2, 99, self.db, self.user)
        self.install(99, 2)
        self.assertEqual([p.id for p in load_agent_prompts(self.db, 99)], [1, 2])

    def test_withdrawn_source_is_unavailable_without_granting_private_access(self):
        from agent_routes import _get_prompt_templates_or_400
        from fastapi import HTTPException
        self.install(99)
        source = self.db.get(PromptTemplate, 1)
        source.is_public = False
        self.db.commit()
        self.assertEqual(load_agent_prompts(self.db, 99), [])
        with self.assertRaises(HTTPException) as error:
            _get_prompt_templates_or_400(self.db, [1], self.user, agent_id=99)
        self.assertEqual(error.exception.status_code, 404)
        source.is_public = True
        self.db.commit()
        self.assertEqual([p.id for p in load_agent_prompts(self.db, 99)], [1])
        unbind_prompt_template(1, 99, self.db, self.user)
        self.assertFalse(source.is_deleted)
        self.assertEqual(source.content, 'v1')
        self.assertEqual(self.db.query(PromptTemplate).count(), 2)

    def test_failed_workspace_binding_rolls_back_prompt_bindings_and_profile(self):
        from agent_routes import update_agent
        from schemas import AgentUpdate
        from fastapi import HTTPException
        self.install(99)
        with (patch('agent_routes.bind_agent_workspace', side_effect=RuntimeError('simulated binding failure')),
              patch('enterprise_workspace.configured_sandbox_type', return_value='native')):
            with self.assertRaises(HTTPException) as context:
                update_agent(99, AgentUpdate(name='changed', prompt_template_ids=[1, 2]), self.db, self.user)
        self.assertEqual(context.exception.status_code, 503)
        self.db.expire_all()
        self.assertEqual(self.db.get(Agent, 99).name, 'A')
        self.assertEqual([p.id for p in load_agent_prompts(self.db, 99)], [1])

    def acquire(self, workspace, run):
        return _try_acquire(workspace_id=workspace, run_id=run, owner_id='test', lease_seconds=30, session_factory=self.factory)

    def test_live_reference_used_in_detail_and_settings_without_system_injection(self):
        from agent_routes import _to_response, _get_prompt_templates_or_400
        import agent_service
        import test_agent_service as fixtures
        self.install(99)
        self.db.get(PromptTemplate, 1).content = 'new-source'
        self.db.commit()
        response = _to_response(self.db.get(Agent, 99), self.db)
        self.assertEqual(response.prompt_templates[0]['content'], 'new-source')
        retained = _get_prompt_templates_or_400(self.db, [1], self.user, agent_id=99)
        self.assertEqual([p.id for p in retained], [1])
        agent = fixtures._agent()
        agent.system_prompt = '身份与职责'
        with (fixtures._execution_dependencies(),
              patch.object(agent_service, 'AgentMemory', fixtures._Memory),
              patch.object(agent_service, 'get_workspace_provider', return_value=fixtures._Sandbox()),
              patch.object(agent_service, 'build_mcp_json', return_value=({}, [])),
              patch.object(agent_service, 'get_runtime', return_value=fixtures._Runtime())):
            result = asyncio.run(agent_service.execute_agent_turn(
                agent=agent, user_input='test', session_id=11, user_id=7,
                db=fixtures._DB(fixtures._session(), fixtures._model())))
        self.assertEqual(result.status, 'succeeded')
        self.assertEqual(agent.effective_system_prompt, '身份与职责')
        self.assertNotIn('new-source', agent.effective_system_prompt)
        self.assertNotIn('v1', agent.effective_system_prompt)
        self.db.get(PromptTemplate, 1).is_deleted = True
        self.db.commit()
        self.assertEqual(_to_response(self.db.get(Agent, 99), self.db).prompt_templates, [])

    def test_publication_and_agent_copy_follow_live_source_visibility_and_content(self):
        from agent_routes import _agent_publication_errors, copy_agent
        self.install(99, 2)
        template = self.db.get(PromptTemplate, 2)
        template.is_public = True
        template.content = 'public-version'
        self.db.commit()
        self.assertEqual(_agent_publication_errors(self.db, self.db.get(Agent, 99)), [])
        source = self.db.get(Agent, 99)
        source.is_public = True
        template.content = 'source-after-install'
        self.db.commit()
        with (patch('agent_routes.bind_agent_workspace', return_value=(SimpleNamespace(id=3), None)),
              patch('agent_routes.get_workspace_provider')):
            copied = copy_agent(99, self.db, CurrentUser(8))
        self.assertEqual(copied.prompt_templates[0]['content'], 'source-after-install')
        template.content = 'updated-after-agent-copy'
        self.db.commit()
        for agent_id in (99, copied.id):
            self.assertEqual(load_agent_prompts(self.db, agent_id)[0].content, 'updated-after-agent-copy')
        self.assertEqual(self.db.query(PromptTemplate).count(), 2)

    def handle(self, workspace, run, token):
        return AgentExecutionLeaseHandle(workspace, run, 'test', token, 30, self.factory)

    def test_user_limit_applies_across_workbench_agents_and_channel_runs(self):
        token = self.acquire(1, 'web-run')
        self.assertEqual(token, 1)
        self.assertIsNone(self.acquire(2, 'channel-run'))
        self.assertEqual(self.acquire(3, 'other-user-run'), 1)
        self.handle(1, 'web-run', token)._release()
        self.assertEqual(self.acquire(2, 'channel-run'), 1)

    def test_limit_changes_expiry_and_old_release_fencing(self):
        first = self.acquire(1, 'one')
        self.policy.max_concurrent_runs = 2
        self.db.commit()
        self.assertEqual(self.acquire(2, 'two'), 1)
        self.assertIsNone(self.acquire(1, 'same-workspace'))
        self.db.query(WorkspaceExecutionLease).filter_by(workspace_id=1).update({'lease_until': utcnow()-timedelta(seconds=1)})
        self.db.commit()
        second = self.acquire(1, 'replacement')
        self.assertEqual(second, first + 1)
        self.handle(1, 'one', first)._release()
        self.assertTrue(self.handle(1, 'replacement', second)._is_owned())

    def test_guard_cancel_does_not_take_a_slot(self):
        async def guard():
            return False
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(acquire_agent_execution_lease(workspace_id=1, run_id='cancelled', wait_guard=guard, session_factory=self.factory))
        self.assertEqual(self.db.query(WorkspaceExecutionLease).count(), 0)

    def test_credits_initialize_from_admin_before_workbench_only_once(self):
        first = enterprise_routes.get_my_credits(self.db, self.user)
        self.assertEqual(first.available_balance, 10)
        self.policy.initial_claim_amount = 20
        self.policy.version = 2
        self.db.commit()
        second = enterprise_routes.get_my_credits(self.db, self.user)
        self.assertEqual(second.available_balance, 10)
        self.assertEqual(self.db.query(CreditClaimRecord).count(), 1)
        self.assertEqual(self.db.query(CreditLedger).count(), 1)
        daily = enterprise_routes.claim_daily_credits(self.db, CurrentUser(8))
        self.assertEqual(daily.available_balance, 22)

    def test_platform_direct_entry_initializes_without_reservation_but_custom_never_bills(self):
        model = AIModel(id=1, user_id=0, name='platform', provider='test', scope='platform')
        self.db.add(model)
        self.db.add(AgentSession(id=1, agent_id=99, user_id=7))
        run = AgentRun(id='platform-run', agent_id=99, session_id=1, user_id=7, source='weixin_clawbot', status='running')
        self.db.add(run)
        self.db.add(ModelPricingVersion(model_id=1, version=1, input_rate=1, output_rate=1))
        self.db.commit()
        with patch('sandbox.get_configured_sandbox_type', return_value='native'):
            credential, _ = prepare_platform_run(self.db, run, model, 600, 'claude_code')
        self.assertTrue(credential)
        self.assertEqual(self.db.query(CreditAccount).one().available_balance, 10)
        self.assertEqual(self.db.query(CreditAccount).one().reserved_balance, 0)
        self.assertEqual(self.db.query(CreditClaimRecord).count(), 1)
        with patch('credit_accounts.ensure_initial_credits', side_effect=AssertionError('Custom model touched billing')):
            self.assertEqual(prepare_platform_run(self.db, SimpleNamespace(user_id=8), SimpleNamespace(scope='user'), 600, 'claude_code'), ('',''))
        self.assertIsNone(self.db.query(CreditAccount).filter_by(user_id=8).first())

    def test_disabled_account_and_insufficient_platform_credits_do_not_affect_custom_model(self):
        model = AIModel(id=1, user_id=0, name='platform', provider='test', scope='platform')
        self.db.add_all([model, ModelPricingVersion(model_id=1, version=1, input_rate=1, output_rate=1),
                         AgentSession(id=1, agent_id=99, user_id=7),
                         CreditAccount(user_id=7, available_balance=0, status='disabled')])
        run = AgentRun(id='blocked-platform', agent_id=99, session_id=1, user_id=7, source='web', status='running')
        self.db.add(run)
        self.db.commit()
        with patch('sandbox.get_configured_sandbox_type', return_value='native'):
            with self.assertRaises(CreditBillingError) as context:
                prepare_platform_run(self.db, run, model, 600, 'claude_code')
            self.assertEqual(context.exception.code, 'CREDIT_ACCOUNT_UNAVAILABLE')
            self.assertEqual(self.db.query(CreditClaimRecord).count(), 0)
            self.db.query(CreditAccount).one().status = 'active'
            self.policy.initial_claim_amount = 0
            self.db.commit()
            with self.assertRaises(CreditBillingError) as context:
                prepare_platform_run(self.db, run, model, 600, 'claude_code')
            self.assertEqual(context.exception.code, 'CREDITS_EXHAUSTED')
            self.db.rollback()
        before = self.db.query(CreditLedger).count()
        with patch('credit_accounts.ensure_initial_credits', side_effect=AssertionError('Must skip')):
            self.assertEqual(prepare_platform_run(self.db, run, SimpleNamespace(scope='user'), 600, 'claude_code'), ('', ''))
        self.assertEqual(self.db.query(CreditLedger).count(), before)


if __name__ == '__main__':
    unittest.main()
