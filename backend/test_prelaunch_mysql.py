"""Run only against an empty disposable test_aihub_prelaunch_* MySQL database."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from agent_execution_lease import _try_acquire, AgentExecutionLeaseHandle, utcnow
from agent_prompts import load_agent_prompts
from credit_accounts import ensure_initial_credits, _grant_claim
from models import (Base, Agent, PromptTemplate, agent_prompt_templates, UserWorkspace,
                    UserExecutionGate, WorkspaceExecutionLease, PlatformAgentSettings,
                    CreditAccount, CreditClaimRecord, CreditLedger, AgentSession, AIModel,
                    AgentRun, ModelPricingVersion, ModelRunCredential, ModelUsageEvent)
import agent_routes
from agent_service import _finish_run_record
from agent_run_recovery import recover_web_run
from auth import CurrentUser
from schemas import AgentUpdate
from agent_routes import update_agent
from fastapi import HTTPException


@unittest.skipUnless(os.environ.get('AIHUB_TEST_MYSQL_URL'), 'Requires disposable MySQL')
class PrelaunchMySQLTests(unittest.TestCase):
    def test_migration_concurrency_and_first_credit_claims(self):
        url = make_url(os.environ['AIHUB_TEST_MYSQL_URL'])
        self.assertTrue(url.database.startswith('test_aihub_prelaunch_'))
        engine = create_engine(url, hide_parameters=True, pool_size=12, max_overflow=0)
        self.addCleanup(engine.dispose)
        self.assertEqual(inspect(engine).get_table_names(), [], 'Database must be empty')
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db, db.begin():
            db.add_all([Agent(id=n, user_id=7, name=f'Agent {n}') for n in range(1, 10)])
            db.add(PlatformAgentSettings(version=1, status='published', created_by=7,
                                        max_concurrent_runs=1, initial_claim_amount=10,
                                        daily_claim_amount=2, per_run_limit=1))
            db.add(PromptTemplate(id=1, user_id=7, name='Template', content='frozen-v1'))
            db.add(PromptTemplate(id=2, user_id=7, name='Deleted', content='inactive', is_deleted=True))
            db.flush()
            for n in range(1, 9):
                db.add(UserWorkspace(id=n, user_id=7, agent_id=n if n > 1 else None, workspace_key=f'w{n}'))
            db.add(UserWorkspace(id=9, user_id=8, workspace_key='other-user'))
            for agent_id in (1, 2):
                for template_id in (1, 2):
                    db.execute(agent_prompt_templates.insert().values(
                        agent_id=agent_id, prompt_template_id=template_id, position=template_id))

        path = Path(__file__).with_name('migrations') / '051_agent_prompt_snapshots.py'
        spec = importlib.util.spec_from_file_location('migration051', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as connection:
            connection.exec_driver_sql('ALTER TABLE agent_prompt_templates DROP COLUMN snapshot_json')
            UserExecutionGate.__table__.drop(connection)
            migration.apply_schema(connection)
        with self.assertRaises(RuntimeError):
            with factory() as db, db.begin():
                migration.backfill(db)
                raise RuntimeError('simulated rollback')
        with factory() as db:
            self.assertEqual(len(db.execute(agent_prompt_templates.select()).all()), 4)
            self.assertTrue(all(r.snapshot_json is None for r in db.execute(agent_prompt_templates.select())))
        with factory() as db, db.begin():
            self.assertEqual(migration.backfill(db), 2)
            db.get(PromptTemplate, 1).content = 'edited-after-migration'
        with engine.begin() as connection:
            migration.apply_schema(connection)
        with factory() as db, db.begin():
            self.assertEqual(migration.backfill(db), 0)
            for agent_id in (1, 2):
                self.assertEqual([p.content for p in load_agent_prompts(db, agent_id)], ['edited-after-migration'])

        # A failed metadata binding must not commit a profile/prompt change.
        with factory() as db:
            with (patch('agent_routes.bind_agent_workspace', side_effect=RuntimeError('simulated binding failure')),
                  patch('enterprise_workspace.configured_sandbox_type', return_value='native')):
                with self.assertRaises(HTTPException) as failure:
                    update_agent(1, AgentUpdate(name='not-saved', prompt_template_ids=[]), db, CurrentUser(7))
            self.assertEqual(failure.exception.status_code, 503)
            db.expire_all()
            self.assertEqual(db.get(Agent, 1).name, 'Agent 1')
            self.assertEqual([p.content for p in load_agent_prompts(db, 1)], ['edited-after-migration'])

        def acquire(workspace, run):
            return _try_acquire(workspace_id=workspace, run_id=run, owner_id='test',
                                lease_seconds=30, session_factory=factory)

        def handle(workspace, run, token):
            return AgentExecutionLeaseHandle(workspace, run, 'test', token, 30, factory)

        # First-ever gate creation and acquisition happen concurrently. Repeat
        # with limits 1 and 2 and check that queued attempts create no lease.
        for limit in (1, 2):
            with factory() as db, db.begin():
                db.query(PlatformAgentSettings).one().max_concurrent_runs = limit
            barrier = Barrier(8)
            def contender(n):
                barrier.wait(timeout=10)
                return n, acquire(n, f'limit-{limit}-run-{n}')
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(contender, range(1, 9)))
            acquired = [(n, token) for n, token in results if token is not None]
            self.assertEqual(len(acquired), limit)
            other = acquire(9, f'other-{limit}')
            self.assertIsNotNone(other)
            handle(9, f'other-{limit}', other)._release()
            for n, token in acquired:
                lease = handle(n, f'limit-{limit}-run-{n}', token)
                self.assertTrue(lease._renew())
                self.assertTrue(lease._is_owned())
                lease._release()

        old = acquire(1, 'expired')
        with factory() as db, db.begin():
            db.query(WorkspaceExecutionLease).filter_by(workspace_id=1).update({
                'lease_until': utcnow() - timedelta(seconds=1),
            })
        new = acquire(1, 'replacement')
        self.assertEqual(new, old + 1)
        self.assertFalse(handle(1, 'expired', old)._renew())
        handle(1, 'expired', old)._release()
        self.assertTrue(handle(1, 'replacement', new)._is_owned())
        handle(1, 'replacement', new)._release()

        self._verify_fenced_workspace_writes(factory, engine)
        self._verify_agent_pagination(factory, engine)

        # Race initial claims against daily claims and against an account
        # instance loaded before a concurrent credit update.
        barrier = Barrier(8)
        def claim(n):
            with factory() as db:
                policy = db.query(PlatformAgentSettings).one()
                barrier.wait(timeout=10)
                ensure_initial_credits(db, 7, policy)
                if n % 2:
                    _grant_claim(db, user_id=7, policy=policy, claim_type='daily')
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(claim, range(8)))
        with factory() as db:
            account = db.query(CreditAccount).filter_by(user_id=7).one()
            self.assertEqual(account.available_balance, 12)
            self.assertEqual(db.query(CreditClaimRecord).count(), 2)
            self.assertEqual(db.query(CreditLedger).count(), 2)
            ensure_initial_credits(db, 8, db.query(PlatformAgentSettings).one())
        with factory() as stale:
            account = stale.query(CreditAccount).filter_by(user_id=8).one()
            with factory() as db, db.begin():
                db.query(CreditAccount).filter_by(user_id=8).update({'available_balance': 50})
            policy = stale.query(PlatformAgentSettings).one()
            _grant_claim(stale, user_id=8, policy=policy, claim_type='daily')
            self.assertEqual(account.available_balance, 52)
        self._verify_database_disconnect(factory, engine)
        print('MySQL verified: migration/rollback/rerun, 8 contenders at limits 1/2, '
              'expiry/fencing, workspace commit locks, full lease after waits, '
              'personal/public pagination, 8 concurrent claims, actual connection loss/recovery')

    def _verify_fenced_workspace_writes(self, factory, engine):
        with factory() as db, db.begin():
            db.query(PlatformAgentSettings).one().max_concurrent_runs = 2
            db.add_all([Agent(id=n, user_id=7, name=f'Agent {n}') for n in (10, 11)])
            db.flush()
            db.add_all([UserWorkspace(id=n, user_id=7, agent_id=n, workspace_key=f'w{n}')
                        for n in (10, 11)])
            db.flush()
            db.add(WorkspaceExecutionLease(
                workspace_id=11, run_id=None, owner_id=None, fencing_token=4,
                lease_until=utcnow() - timedelta(seconds=1), heartbeat_at=utcnow(),
            ))

        def acquire(workspace, run):
            return _try_acquire(workspace_id=workspace, run_id=run, owner_id='test',
                                lease_seconds=30, session_factory=factory)

        for target in (10, 11):
            with TemporaryDirectory(prefix='aihub-mysql-fencing-') as root:
                output = Path(root) / 'saved.txt'
                old_run = f'writer-{target}'
                old_token = acquire(1, old_run)
                self.assertIsNotNone(old_token)
                old = AgentExecutionLeaseHandle(1, old_run, 'test', old_token, 30, factory)
                expiry = utcnow() + timedelta(seconds=2)
                with factory() as db, db.begin():
                    db.get(WorkspaceExecutionLease, 1).lease_until = expiry
                started, finish, waiting = Event(), Event(), Event()

                def write():
                    started.set()
                    if not finish.wait(10):
                        raise RuntimeError('workspace writer timed out')
                    output.write_text(old_run)

                def mark_waiting(conn, cursor, sql, parameters, context, executemany):
                    if ('FROM workspace_execution_leases' in sql
                            and 'JOIN user_workspaces' in sql and 'FOR UPDATE' in sql):
                        waiting.set()

                event.listen(engine, 'before_cursor_execute', mark_waiting)
                try:
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        writer = pool.submit(old.commit_workspace, write)
                        try:
                            self.assertTrue(started.wait(5))
                            grant = pool.submit(acquire, target, f'waiting-{target}')
                            self.assertTrue(waiting.wait(5))
                            takeover = pool.submit(acquire, 1, f'takeover-{target}')
                            time.sleep(2.2)
                            self.assertGreater(utcnow(), expiry)
                            self.assertFalse(grant.done())
                            self.assertFalse(takeover.done())
                            released_at = utcnow()
                            finish.set()
                            self.assertTrue(writer.result(timeout=5))
                            new_token = grant.result(timeout=5)
                            self.assertIsNotNone(new_token)
                            self.assertIsNone(takeover.result(timeout=5))
                        finally:
                            finish.set()
                    self.assertEqual(output.read_text(), old_run)
                    self.assertTrue(old._is_owned())
                    with factory() as db:
                        row = db.get(WorkspaceExecutionLease, target)
                        heartbeat = row.heartbeat_at.replace(tzinfo=released_at.tzinfo)
                        self.assertGreaterEqual(heartbeat, released_at.replace(microsecond=0))
                        self.assertEqual(row.lease_until - row.heartbeat_at, timedelta(seconds=30))
                    granted = AgentExecutionLeaseHandle(target, f'waiting-{target}', 'test', new_token, 30, factory)
                    self.assertTrue(granted._is_owned())
                    granted._release()
                    with factory() as db, db.begin():
                        db.get(WorkspaceExecutionLease, 1).lease_until = utcnow() - timedelta(seconds=1)
                    self.assertFalse(old.commit_workspace(lambda: output.write_text('expired')))
                    replacement_token = acquire(1, f'replacement-{target}')
                    self.assertIsNotNone(replacement_token)
                    replacement = AgentExecutionLeaseHandle(
                        1, f'replacement-{target}', 'test', replacement_token, 30, factory,
                    )
                    self.assertFalse(old.commit_workspace(lambda: output.write_text('stale')))
                    old._release()
                    self.assertTrue(replacement._is_owned())
                    self.assertTrue(replacement.commit_workspace(lambda: output.write_text('replacement')))
                    self.assertEqual(output.read_text(), 'replacement')
                    replacement._release()
                finally:
                    finish.set()
                    event.remove(engine, 'before_cursor_execute', mark_waiting)

    def _verify_agent_pagination(self, factory, engine):
        with factory() as db, db.begin():
            db.add_all([Agent(id=n, user_id=20, kind='expert', name=f'mysql-personal-{n}')
                        for n in range(100, 110)])
            db.add(AIModel(id=100, user_id=20, name='model', provider='anthropic'))
            db.flush()
            db.add_all([AgentSession(id=n, agent_id=100, user_id=20) for n in range(100, 200)])
            updated = utcnow()
            db.add_all([Agent(id=n, user_id=21, kind='expert', name=f'mysql-public-{n}',
                              is_public=True, updated_at=updated) for n in range(200, 212)])
            db.flush()
            cases = (
                (200, {'is_public': False}, True, False, False),
                (201, {'is_public': True}, False, False, False),
                (202, {'is_public': True}, True, False, True),
                (203, {'is_public': True}, False, True, False),
                (204, {'is_system': True}, False, True, False),
                (205, None, True, False, False),
                (206, {}, True, False, False),
                (207, {'is_public': 1}, True, False, False),
            )
            for agent_id, snapshot, public, system, deleted in cases:
                db.add(PromptTemplate(id=agent_id, user_id=21, name=f'Prompt {agent_id}',
                                      content='prompt', is_public=public, is_system=system,
                                      is_deleted=deleted))
                db.flush()
                db.execute(agent_prompt_templates.insert().values(
                    agent_id=agent_id, prompt_template_id=agent_id,
                    snapshot_json=json.dumps(snapshot) if snapshot is not None else None,
                ))

        statements = []
        def collect_selects(conn, cursor, sql, parameters, context, executemany):
            if sql.lstrip().upper().startswith('SELECT'):
                statements.append(sql)
        event.listen(engine, 'before_cursor_execute', collect_selects)
        try:
            counts = []
            for limit in (1, 10):
                with factory() as db:
                    statements.clear()
                    result = agent_routes.list_agents(0, limit, None, db, CurrentUser(20))
                    self.assertEqual(result.total, 10)
                    self.assertEqual(len(result.items), limit)
                    self.assertFalse(any('FROM agent_sessions' in sql and 'count(' not in sql.lower()
                                         for sql in statements))
                    counts.append(len(statements))
                    if limit == 10:
                        self.assertEqual(sum(item.session_count for item in result.items), 100)
            self.assertEqual(counts[0], counts[1])
            self.assertLessEqual(counts[1], 8)
            with factory() as db:
                statements.clear()
                result = agent_routes.list_public_agents('mysql-public-', 3, 4, db)
                self.assertEqual(result['total'], 10)
                self.assertEqual([item['id'] for item in result['items']], [208, 207, 206, 205])
                self.assertEqual(len(statements), 5)
                self.assertTrue(all('agent_sessions' not in sql for sql in statements))
                empty = agent_routes.list_public_agents('mysql-no-match', 0, 10, db)
                self.assertEqual(empty, {'total': 0, 'items': []})
        finally:
            event.remove(engine, 'before_cursor_execute', collect_selects)

    def _verify_database_disconnect(self, factory, engine):
        run_id = 'mysql-disconnect'
        with factory() as db, db.begin():
            db.add(Agent(id=12, user_id=30, kind='expert', name='disconnect-test'))
            db.add(AIModel(id=101, user_id=30, name='disconnect-model', provider='anthropic'))
            db.flush()
            db.add(UserWorkspace(id=12, user_id=30, agent_id=12, workspace_key='disconnect'))
            db.add(AgentSession(id=300, agent_id=12, user_id=30))
            db.add(ModelPricingVersion(id=101, model_id=101, version=1, input_rate=1, rate_scale=1))
            db.add(CreditAccount(user_id=30, available_balance=95, reserved_balance=5))
            db.flush()
            db.add(AgentRun(id=run_id, user_id=30, agent_id=12, session_id=300, workspace_id=12,
                            source='web', status='running', reserved_points=5, settlement_status='reserved'))
            db.flush()
            db.add(ModelRunCredential(
                run_id=run_id, user_id=30, model_id=101, pricing_version_id=101,
                token_hash='disconnect-test-hash', max_points=5, consumed_points=2,
                request_count=1, expires_at=utcnow() + timedelta(hours=1),
            ))
            db.add(ModelUsageEvent(run_id=run_id, model_id=101, provider_request_id='disconnect-usage'))

        token = _try_acquire(workspace_id=12, run_id=run_id, owner_id='disconnect-owner',
                             lease_seconds=5, session_factory=factory)
        self.assertIsNotNone(token)
        lease = AgentExecutionLeaseHandle(12, run_id, 'disconnect-owner', token, 5, factory)
        control_engine = create_engine(engine.url, hide_parameters=True, pool_size=1, max_overflow=0)
        self.addCleanup(control_engine.dispose)
        killed = []
        def disconnect_lease_query(conn, cursor, sql, parameters, context, executemany):
            if 'workspace_execution_leases' not in sql:
                return
            connection_id = int(conn.connection.driver_connection.thread_id())
            with control_engine.connect().execution_options(isolation_level='AUTOCOMMIT') as control:
                control.exec_driver_sql(f'KILL CONNECTION {connection_id}')
            killed.append(connection_id)

        with TemporaryDirectory(prefix='aihub-mysql-disconnect-') as root:
            output = Path(root) / 'saved.txt'
            output.write_text('before-disconnect')
            event.listen(engine, 'before_cursor_execute', disconnect_lease_query)
            try:
                with patch('agent_execution_lease.logger') as logger:
                    self.assertFalse(lease._is_owned())
                    with self.assertRaises(DBAPIError) as failed_write:
                        lease.commit_workspace(lambda: output.write_text('must-not-write'))
                    self.assertTrue(failed_write.exception.connection_invalidated)
                    self.assertEqual(output.read_text(), 'before-disconnect')

                    async def owner():
                        async with lease:
                            await asyncio.sleep(10)

                    async def scenario():
                        task = asyncio.create_task(owner())
                        with self.assertRaises(asyncio.CancelledError):
                            await asyncio.wait_for(task, timeout=8)
                        self.assertTrue(lease._lost.is_set())
                        self.assertFalse(await lease.is_owned())
                    asyncio.run(scenario())
                    messages = [call.args[0] for call in logger.exception.call_args_list]
                    self.assertTrue(any('heartbeat failed' in message for message in messages))
                    self.assertTrue(any('release failed' in message for message in messages))
                self.assertGreaterEqual(len(killed), 5)
            finally:
                event.remove(engine, 'before_cursor_execute', disconnect_lease_query)

            # MySQL DATETIME has second precision; wait for its stored expiry.
            time.sleep(0.75)
            with factory() as db:
                run = db.get(AgentRun, run_id)
                _finish_run_record(db, run, 'unknown', '运行租约已失效', error_code='lease_lost')
                db.refresh(run)
                self.assertEqual((run.status, run.error_code), ('unknown', 'lease_lost'))
                self.assertEqual(run.charged_points, 2)
                first = recover_web_run(db, run_id, user_id=30, actor_user_id=30)
                second = recover_web_run(db, run_id, user_id=30, actor_user_id=30)
                self.assertEqual(first, second)
                self.assertEqual(first['settlement_status'], 'settled')
                self.assertEqual(first['charged_points'], 2)
                _finish_run_record(db, run, 'succeeded')
                db.expire_all()
                self.assertEqual(db.get(AgentRun, run_id).error_code, 'manual_recovery')
                self.assertEqual(db.query(CreditLedger).filter_by(run_id=run_id).count(), 1)
                account = db.query(CreditAccount).filter_by(user_id=30).one()
                self.assertEqual((account.available_balance, account.reserved_balance), (98, 0))

            replacement_token = _try_acquire(
                workspace_id=12, run_id='disconnect-replacement', owner_id='replacement-owner',
                lease_seconds=30, session_factory=factory,
            )
            self.assertIsNotNone(replacement_token)
            replacement = AgentExecutionLeaseHandle(
                12, 'disconnect-replacement', 'replacement-owner', replacement_token, 30, factory,
            )
            self.assertFalse(lease.commit_workspace(lambda: output.write_text('stale')))
            lease._release()
            self.assertTrue(replacement._is_owned())
            self.assertTrue(replacement.commit_workspace(lambda: output.write_text('recovered')))
            self.assertEqual(output.read_text(), 'recovered')
            replacement._release()


if __name__ == '__main__':
    unittest.main()
