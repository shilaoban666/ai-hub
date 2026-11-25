import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import credit_billing
from agent_execution_lease import AgentExecutionLeaseHandle
from agent_service import _ensure_run_record, _finish_run_record
from agent_run_recovery import recover_stale_web_runs
from auth import CurrentUser, get_current_active_user
from credit_dashboard_routes import personal_router, summary_router
from database import Base, get_db
from models import (
    AgentRun, CreditAccount, CreditLedger, CreditClaimRecord, ModelPricingVersion,
    ModelRunCredential, ModelUsageEvent, WorkspaceExecutionLease,
)


class RunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool,
                                    connect_args={'check_same_thread': False})
        with patch.object(SQLiteTypeCompiler, 'visit_BIGINT', return_value='INTEGER'):
            Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.db = self.factory()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.now = datetime.now(timezone.utc)
        self.db.add_all([
            AgentRun(id='stuck', agent_id=1, session_id=1, user_id=7, workspace_id=5,
                     status='running', source='web', reserved_points=100,
                     settlement_status='reserved', created_at=self.now - timedelta(days=1)),
            CreditAccount(id=1, user_id=7, available_balance=200, reserved_balance=100),
            ModelPricingVersion(id=1, model_id=1, version=1, input_rate=100, rate_scale=100),
            ModelRunCredential(id=1, run_id='stuck', user_id=7, model_id=1,
                               pricing_version_id=1, token_hash='test-hash',
                               max_points=100, consumed_points=3, request_count=1,
                               expires_at=self.now + timedelta(hours=1)),
            ModelUsageEvent(id=1, run_id='stuck', model_id=1, provider_request_id='request-1'),
            WorkspaceExecutionLease(workspace_id=5, run_id='stuck', owner_id='old-worker',
                                    fencing_token=4, heartbeat_at=self.now - timedelta(minutes=5),
                                    lease_until=self.now - timedelta(minutes=4)),
        ])
        self.db.commit()
        app = FastAPI()
        app.include_router(personal_router)
        app.include_router(summary_router)
        self.user = CurrentUser(user_id=7)
        app.dependency_overrides[get_current_active_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def recover(self, scope='personal', force_release=False):
        suffix = '?force_release=true' if force_release else ''
        return self.client.post(f'/api/dashboard/{scope}/credit-usage/runs/stuck/recover{suffix}')

    def test_recovery_settles_actual_cost_releases_lease_and_is_idempotent(self):
        self.assertEqual(self.recover().status_code, 200)
        self.assertEqual(self.recover().json()['settlement_status'], 'settled')
        run = self.db.get(AgentRun, 'stuck')
        self.assertEqual(run.status, 'cancelled')
        self.assertTrue(run.cancel_requested)
        self.assertEqual(run.error_code, 'manual_recovery')
        self.assertIn('7', run.error_message)
        self.assertEqual(run.charged_points, Decimal('3'))
        account = self.db.get(CreditAccount, 1)
        self.assertEqual(account.available_balance, Decimal('297'))
        self.assertEqual(account.reserved_balance, Decimal('0'))
        self.assertEqual(self.db.query(CreditLedger).count(), 1)
        self.assertEqual(self.db.get(ModelRunCredential, 1).status, 'closed')
        lease = self.db.get(WorkspaceExecutionLease, 5)
        self.assertIsNone(lease.run_id)
        self.assertEqual(lease.fencing_token, 5)
        handle = AgentExecutionLeaseHandle(5, 'stuck', 'old-worker', 4, 30, self.factory)
        self.assertFalse(handle._renew())

    def test_live_lease_is_not_reset(self):
        self.db.get(WorkspaceExecutionLease, 5).lease_until = self.now + timedelta(minutes=1)
        self.db.commit()
        self.assertEqual(self.recover().status_code, 409)
        self.assertEqual(self.db.get(AgentRun, 'stuck').status, 'running')
        self.assertEqual(self.db.query(CreditLedger).count(), 0)

    def test_missing_usage_stays_pending_then_late_usage_settles_once(self):
        credential = self.db.get(ModelRunCredential, 1)
        credential.request_count = 2
        credential.request_in_flight = True
        self.db.commit()
        pending = self.recover().json()
        self.assertEqual(pending['settlement_status'], 'pending_reconciliation')
        self.assertIsNotNone(pending['reconciliation_deadline'])
        self.assertEqual(self.db.get(CreditAccount, 1).reserved_balance, Decimal('100'))
        self.assertEqual(self.db.get(ModelRunCredential, 1).status, 'reconciliation')
        with patch.object(credit_billing, 'SessionLocal', self.factory):
            context = {'credential_id': 1, 'request_number': 2}
            credit_billing.finish_gateway_request(context, {'input_tokens': 2}, {})
            credit_billing.finish_gateway_request(context, {'input_tokens': 2}, {})
        self.db.expire_all()
        self.assertEqual(self.db.get(AgentRun, 'stuck').charged_points, Decimal('5'))
        self.assertEqual(self.db.get(CreditAccount, 1).available_balance, Decimal('295'))
        self.assertEqual(self.db.query(CreditLedger).count(), 1)

    def test_old_incomplete_usage_settles_from_recorded_usage_after_grace(self):
        credential = self.db.get(ModelRunCredential, 1)
        credential.request_count = 2
        run = self.db.get(AgentRun, 'stuck')
        run.status = 'failed'
        run.finished_at = self.now - timedelta(days=2)
        self.db.commit()

        result = self.recover()

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['settlement_status'], 'settled')
        self.db.expire_all()
        self.assertEqual(self.db.get(AgentRun, 'stuck').charged_points, Decimal('3'))
        self.assertEqual(self.db.get(CreditAccount, 1).available_balance, Decimal('297'))
        self.assertEqual(self.db.get(CreditAccount, 1).reserved_balance, Decimal('0'))
        metadata = self.db.query(CreditLedger).one().metadata_json
        self.assertIn('"incomplete_usage":true', metadata)

    def test_recovery_does_not_restart_grace_for_an_old_active_run(self):
        credential = self.db.get(ModelRunCredential, 1)
        credential.request_count = 2
        credential.expires_at = self.now - timedelta(days=2)
        self.db.commit()

        result = self.recover()

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['settlement_status'], 'settled')
        self.db.expire_all()
        self.assertEqual(self.db.get(CreditAccount, 1).reserved_balance, Decimal('0'))

    def test_old_run_without_credential_releases_reservation_after_grace(self):
        run = self.db.get(AgentRun, 'stuck')
        run.status = 'failed'
        run.finished_at = self.now - timedelta(days=2)
        self.db.delete(self.db.get(ModelRunCredential, 1))
        self.db.commit()

        result = self.recover()

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['settlement_status'], 'settled')
        self.db.expire_all()
        self.assertEqual(self.db.get(AgentRun, 'stuck').charged_points, Decimal('0'))
        self.assertEqual(self.db.get(CreditAccount, 1).available_balance, Decimal('300'))
        self.assertEqual(self.db.get(CreditAccount, 1).reserved_balance, Decimal('0'))

    def test_force_release_returns_all_reserved_points_without_charging_usage(self):
        credential = self.db.get(ModelRunCredential, 1)
        credential.request_count = 2
        run = self.db.get(AgentRun, 'stuck')
        run.status = 'failed'
        run.finished_at = self.now
        self.db.commit()

        result = self.recover(force_release=True)

        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['force_released'])
        self.assertEqual(result.json()['charged_points'], 0)
        self.db.expire_all()
        self.assertEqual(self.db.get(AgentRun, 'stuck').charged_points, Decimal('0'))
        self.assertEqual(self.db.get(CreditAccount, 1).available_balance, Decimal('300'))
        self.assertEqual(self.db.get(CreditAccount, 1).reserved_balance, Decimal('0'))
        ledger = self.db.query(CreditLedger).one()
        self.assertIn('"force_release":true', ledger.metadata_json)
        self.assertEqual(self.recover(force_release=True).status_code, 200)
        self.assertEqual(self.db.query(CreditLedger).count(), 1)

    def test_missing_credential_does_not_refund_unverified_usage(self):
        self.db.delete(self.db.get(ModelRunCredential, 1))
        self.db.commit()
        self.assertEqual(self.recover().json()['settlement_status'], 'pending_reconciliation')
        self.assertEqual(self.db.get(CreditAccount, 1).reserved_balance, Decimal('100'))

    def test_force_settlement_charges_recorded_usage_before_deadline_once(self):
        self.db.get(AgentRun, 'stuck').status = 'failed'
        self.db.get(AgentRun, 'stuck').finished_at = self.now
        self.db.get(ModelRunCredential, 1).request_count = 2
        self.db.commit()
        url = '/api/dashboard/personal/credit-usage/runs/stuck/recover?force_settle=true'
        self.assertEqual(self.recover().json()['settlement_status'], 'pending_reconciliation')
        result = self.client.post(url)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['charged_points'], 3)
        self.assertIsNone(result.json()['reconciliation_deadline'])
        self.assertEqual(self.db.get(CreditAccount, 1).available_balance, 297)
        self.assertEqual(self.db.get(CreditAccount, 1).reserved_balance, 0)
        self.assertIn('"force_settle":true', self.db.query(CreditLedger).one().metadata_json)
        self.assertIn('"actor_user_id":7', self.db.query(CreditLedger).one().metadata_json)
        self.assertEqual(self.client.post(url).json()['charged_points'], 3)
        self.assertEqual(self.db.query(CreditLedger).count(), 1)

    def test_force_settlement_without_credential_uses_zero_verified_usage(self):
        self.db.get(AgentRun, 'stuck').status = 'failed'
        self.db.delete(self.db.get(ModelRunCredential, 1))
        self.db.commit()
        result = self.client.post('/api/dashboard/personal/credit-usage/runs/stuck/recover?force_settle=true')
        self.assertEqual(result.json()['charged_points'], 0)
        self.assertEqual(self.db.get(CreditAccount, 1).available_balance, 300)

    def test_force_settlement_cannot_end_an_active_run_or_combine_with_refund(self):
        url = '/api/dashboard/personal/credit-usage/runs/stuck/recover?force_settle=true'
        self.assertEqual(self.client.post(url).status_code, 409)
        self.assertEqual(self.client.post(url + '&force_release=true').status_code, 400)
        self.assertEqual(self.db.get(AgentRun, 'stuck').status, 'running')
        self.assertEqual(self.db.query(CreditLedger).count(), 0)

    def test_bulk_settlement_covers_all_history_pages_and_skips_active_and_other_users(self):
        for index in range(20):
            self.db.add(AgentRun(id=f'ended-{index}', agent_id=1, session_id=1, user_id=7,
                                source='channel' if index == 0 else 'web', status='failed',
                                reserved_points=1, settlement_status='pending_reconciliation',
                                created_at=self.now - timedelta(days=500)))
        self.db.get(CreditAccount, 1).reserved_balance += 20
        self.db.add(AgentRun(id='other-user', agent_id=1, session_id=1, user_id=8,
                            status='failed', reserved_points=1, settlement_status='reserved'))
        self.db.commit()
        url = '/api/dashboard/personal/credit-usage/runs/settle-all'
        result = self.client.post(url).json()
        self.assertEqual(result, {'total': 21, 'settled': 20, 'skipped': 1, 'failed': 0, 'errors': []})
        self.assertEqual(self.db.get(CreditAccount, 1).available_balance, 220)
        self.assertEqual(self.db.get(CreditAccount, 1).reserved_balance, 100)
        self.assertEqual(self.db.get(AgentRun, 'stuck').status, 'running')
        self.assertEqual(self.db.get(AgentRun, 'other-user').settlement_status, 'reserved')
        self.assertEqual(self.client.post(url).json()['settled'], 0)
        self.assertEqual(self.db.query(CreditLedger).count(), 20)
        self.assertEqual(self.client.post(url + '?user_id=8').status_code, 403)

    def test_bulk_failure_does_not_rollback_other_settlements(self):
        self.db.get(AgentRun, 'stuck').status = 'failed'
        self.db.add(AgentRun(id='broken', agent_id=1, session_id=1, user_id=8,
                            status='failed', reserved_points=1, settlement_status='reserved'))
        self.db.commit()  # User 8 intentionally has no account.
        url = '/api/dashboard/summary/credit-usage/runs/settle-all'
        self.assertEqual(self.client.post(url).status_code, 403)
        self.user = CurrentUser(user_id=9, is_superuser=True)
        result = self.client.post(url).json()
        self.assertEqual((result['settled'], result['failed']), (1, 1))
        self.assertEqual(result['errors'][0]['run_id'], 'broken')
        self.assertEqual(self.db.get(CreditAccount, 1).available_balance, 297)
        self.assertIn('"actor_user_id":9', self.db.query(CreditLedger).one().metadata_json)
        self.assertEqual(self.client.post(url + '?user_id=7').json()['total'], 0)


    def test_recovered_run_cannot_request_model_or_reserve_again(self):
        self.db.add(CreditClaimRecord(user_id=7, claim_type="initial", claim_date=self.now.date(),
                                     amount=200, policy_version=1, business_key="initial-claim:7"))
        self.db.get(ModelRunCredential, 1).token_hash = credit_billing.token_hash('test-token')
        self.db.commit()
        self.assertEqual(self.recover().status_code, 200)
        with patch.object(credit_billing, 'SessionLocal', self.factory):
            with self.assertRaises(credit_billing.CreditBillingError) as rejected:
                credit_billing.begin_gateway_request('test-token', b'{}')
        self.assertEqual(rejected.exception.code, 'INVALID_RUN_CREDENTIAL')
        with patch.object(credit_billing, '_active_policy', return_value=SimpleNamespace(
            per_run_limit=100, initial_claim_amount=200, daily_claim_amount=0, version=1,
            claim_timezone="Asia/Shanghai",
        )):
            with self.assertRaises(credit_billing.CreditBillingError) as rejected:
                credit_billing.prepare_platform_run(
                    self.db, run=self.db.get(AgentRun, 'stuck'),
                    model=SimpleNamespace(id=1, scope='platform'),
                    timeout_seconds=600, runtime_type='claude_code',
                )
        self.assertEqual(rejected.exception.code, 'RUN_ALREADY_BILLED')
        self.assertEqual(self.db.query(CreditLedger).count(), 1)

    def test_personal_scope_cannot_recover_other_user(self):
        self.user = CurrentUser(user_id=8)
        self.assertEqual(self.recover().status_code, 404)
        self.assertEqual(self.db.get(AgentRun, 'stuck').status, 'running')

    def test_summary_requires_superuser_and_records_operator(self):
        self.user = CurrentUser(user_id=8)
        self.assertEqual(self.recover('summary').status_code, 403)
        self.user = CurrentUser(user_id=8, is_superuser=True)
        self.assertEqual(self.recover('summary').status_code, 200)
        self.assertIn('8', self.db.get(AgentRun, 'stuck').error_message)

    def test_channel_runs_are_not_changed(self):
        self.db.get(AgentRun, 'stuck').source = 'channel'
        self.db.commit()
        self.assertEqual(self.recover().status_code, 409)

    def test_does_not_release_a_newer_run_in_same_workspace(self):
        lease = self.db.get(WorkspaceExecutionLease, 5)
        lease.run_id = 'new-run'
        lease.lease_until = self.now + timedelta(minutes=1)
        self.db.commit()
        self.assertEqual(self.recover().status_code, 200)
        self.assertEqual(self.db.get(WorkspaceExecutionLease, 5).run_id, 'new-run')

    def test_recent_run_without_lease_is_not_reset(self):
        self.db.delete(self.db.get(WorkspaceExecutionLease, 5))
        self.db.get(AgentRun, 'stuck').heartbeat_at = self.now
        self.db.commit()
        self.assertEqual(self.recover().status_code, 409)

    def test_old_queued_run_without_lease_can_be_recovered(self):
        self.db.delete(self.db.get(WorkspaceExecutionLease, 5))
        self.db.get(AgentRun, 'stuck').status = 'queued'
        self.db.commit()
        self.assertEqual(self.recover().json()['status'], 'cancelled')

    def test_terminal_run_retries_settlement_without_changing_result(self):
        self.db.get(AgentRun, 'stuck').status = 'failed'
        self.db.commit()
        self.assertEqual(self.recover().json()['status'], 'failed')

    def test_late_worker_cannot_overwrite_recovery_or_restart(self):
        stale_db = self.factory()
        self.addCleanup(stale_db.close)
        stale_run = stale_db.get(AgentRun, 'stuck')
        stale_db.commit()  # No open read transaction, but retain a stale identity.
        _ = stale_run.status
        self.assertEqual(self.recover().status_code, 200)
        _finish_run_record(stale_db, stale_run, 'succeeded')
        self.db.expire_all()
        self.assertEqual(self.db.get(AgentRun, 'stuck').status, 'cancelled')
        with self.assertRaises(asyncio.CancelledError):
            _ensure_run_record(db=stale_db, run_id='stuck', agent=SimpleNamespace(id=1),
                               session_id=1, user_id=7, source='web', model_id=1,
                               skill_id=None, permission_mode=None, runtime_type='claude_code',
                               workspace=SimpleNamespace(id=5))

    def test_automatic_lease_recovery_fences_late_finish(self):
        self.assertEqual(recover_stale_web_runs(self.db), 1)
        self.db.expire_all()
        stale_db = self.factory()
        self.addCleanup(stale_db.close)
        _finish_run_record(stale_db, stale_db.get(AgentRun, 'stuck'), 'succeeded')
        self.db.expire_all()
        self.assertEqual(self.db.get(AgentRun, 'stuck').status, 'unknown')


if __name__ == '__main__':
    unittest.main()
