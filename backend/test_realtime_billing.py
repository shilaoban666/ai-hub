"""Live billing against a disposable SQLite DB, including concurrent requests."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import credit_billing as billing
import model_gateway as gateway
from database import Base
from models import (Agent, AgentRun, AgentSession, AIModel, CreditAccount, CreditLedger,
                    ModelGatewayRequest, ModelPricingVersion, ModelRunCredential, ModelUsageEvent,
                    PlatformAgentSettings)


class RealtimeBillingTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(temporary.name) / 'credits.sqlite'}",
                                    connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        with patch.object(SQLiteTypeCompiler, 'visit_BIGINT', return_value='INTEGER'):
            Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.factory()
        self.addCleanup(self.db.close)
        self.db.add_all([
            Agent(id=1, user_id=7, name='Assistant'),
            AgentSession(id=1, agent_id=1, user_id=7),
            AIModel(id=1, user_id=0, name='test-model', provider='test', scope='platform',
                    api_protocol='anthropic-messages', api_proxy_url='https://example.test'),
            PlatformAgentSettings(id=1, version=1, created_by=7, status='published',
                                  initial_claim_amount=10, per_run_limit=100),
            ModelPricingVersion(id=1, model_id=1, version=1, input_rate=2,
                                output_rate=5, cache_read_rate=1, cache_creation_rate=3, rate_scale=1000),
        ])
        self.db.commit()
        self.enterContext(patch.object(billing, 'SessionLocal', self.factory))
        self.enterContext(patch('sandbox.get_configured_sandbox_type', return_value='native'))
        self.token = self.prepare('run-1')

    def prepare(self, run_id, user_id=7):
        run = AgentRun(id=run_id, agent_id=1, session_id=1, user_id=user_id,
                       status='running', source='web')
        self.db.add(run)
        self.db.commit()
        token, _ = billing.prepare_platform_run(self.db, run, self.db.get(AIModel, 1), 600, 'claude_code')
        return token

    def begin(self, token=None):
        self.db.rollback()
        return billing.begin_gateway_request(token or self.token, b'{}')

    def refresh(self):
        self.db.rollback()
        self.db.expire_all()

    def balance(self):
        self.refresh()
        return self.db.query(CreditAccount).filter_by(user_id=7).one().available_balance

    def test_prepare_does_not_reserve_even_below_legacy_per_run_limit(self):
        self.assertEqual(self.balance(), Decimal('10'))
        self.assertEqual(self.db.query(CreditAccount).one().reserved_balance, 0)
        self.assertEqual(self.db.get(AgentRun, 'run-1').reserved_points, 0)
        self.assertEqual(self.db.get(AgentRun, 'run-1').settlement_status, 'metering')
        self.assertEqual(self.db.query(CreditLedger).filter_by(entry_type='run_reservation').count(), 0)

    def test_parallel_requests_have_independent_progress_and_idempotent_debits(self):
        first, second = self.begin(), self.begin()
        self.assertNotEqual(first['request_id'], second['request_id'])
        for usage in ({'input_tokens': 500}, {'input_tokens': 500}, {'input_tokens': 100}):
            billing.record_metered_usage(first, usage, {})
        billing.finish_gateway_request(second, {'output_tokens': 200}, {})
        self.assertEqual(self.balance(), 8)
        self.assertEqual(self.db.get(ModelGatewayRequest, first['request_id']).status, 'started')
        billing.finish_gateway_request(first, {'input_tokens': 500, 'output_tokens': 100}, {})
        billing.finish_gateway_request(first, {'input_tokens': 500, 'output_tokens': 100}, {})
        self.assertEqual(self.balance(), Decimal('7.50'))
        self.assertEqual(self.db.query(ModelUsageEvent).count(), 2)
        snapshot = billing.metered_run_snapshot('run-1')
        self.assertEqual(snapshot['usage']['input_tokens'], 500)
        self.assertEqual(snapshot['usage']['output_tokens'], 300)
        self.assertEqual(snapshot['charged_points'], 2.5)

    def test_incremental_rounding_is_based_on_cumulative_request_cost(self):
        context = self.begin()
        for count in range(1, 11):
            billing.record_metered_usage(context, {'input_tokens': count}, {})
        self.assertEqual(self.balance(), Decimal('9.98'))
        billing.abort_gateway_request(context, usage_unknown=True)
        billing.finish_gateway_request(context, {'input_tokens': 10}, {})
        self.assertEqual(self.balance(), Decimal('9.98'))
        self.assertEqual(self.db.get(ModelGatewayRequest, context['request_id']).status, 'completed')

    def test_exhaustion_preserves_full_usage_and_stays_stopped_after_topup(self):
        first, second = self.begin(), self.begin()
        outcome = billing.record_metered_usage(first, {'output_tokens': 2200}, {})
        self.assertEqual(outcome['error_code'], 'CREDITS_EXHAUSTED')
        self.assertEqual(self.balance(), 0)
        run = self.db.get(AgentRun, 'run-1')
        self.assertTrue(run.cancel_requested)
        self.assertEqual(run.error_code, 'credits_exhausted')
        self.assertEqual(billing.metered_run_snapshot('run-1')['error_code'], 'CREDITS_EXHAUSTED')
        billing.finish_gateway_request(first, {'output_tokens': 2200}, {})
        billing.finish_gateway_request(second, {'input_tokens': 500}, {})
        self.refresh()
        raw = json.loads(self.db.query(ModelUsageEvent).filter_by(provider_request_id=first['request_id']).one().raw_usage)
        self.assertEqual(raw['reported_points'], '11.00')
        self.assertEqual(raw['charged_points'], '10.00')
        self.assertEqual(raw['uncovered_points'], '1.00')
        self.assertEqual(billing.metered_run_snapshot('run-1')['usage']['input_tokens'], 500)
        self.db.query(CreditAccount).update({'available_balance': 20})
        self.db.commit()
        with self.assertRaises(billing.CreditBillingError) as error:
            self.begin()
        self.assertEqual(error.exception.code, 'CREDITS_EXHAUSTED')
        # A new Run can use the top-up. Completed callbacks cannot debit it again.
        token = self.prepare('after-topup')
        self.begin(token)
        billing.finish_gateway_request(first, {'output_tokens': 2200}, {})
        self.assertEqual(self.balance(), 20)

    def test_concurrent_runs_share_balance_without_lost_debits(self):
        other_token = self.prepare('run-2')
        contexts = [self.begin(), self.begin(other_token)]
        barrier = Barrier(2)
        def report(context):
            barrier.wait(timeout=5)
            return billing.record_metered_usage(context, {'output_tokens': 1200}, {}, terminal=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(report, contexts))
        self.assertEqual(self.balance(), 0)
        self.assertEqual(sum(row.consumed_points for row in self.db.query(ModelRunCredential)), 10)
        self.assertEqual(sum(row.output_tokens for row in self.db.query(ModelUsageEvent)), 2400)
        for run_id in ('run-1', 'run-2'):
            self.assertEqual(billing.metered_run_snapshot(run_id)['error_code'], 'CREDITS_EXHAUSTED')

    def test_finalization_never_debits_again_and_waits_for_partial_requests(self):
        context = self.begin()
        billing.record_metered_usage(context, {'input_tokens': 500}, {})
        self.refresh()
        run = self.db.get(AgentRun, 'run-1')
        run.status = 'cancelled'
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        billing.settle_platform_run(self.db, run, 'cancelled')
        self.assertEqual(run.settlement_status, 'pending_reconciliation')
        billing.finish_gateway_request(context, {'input_tokens': 500, 'output_tokens': 200}, {})
        self.assertEqual(self.balance(), 8)
        self.assertEqual(self.db.get(AgentRun, 'run-1').settlement_status, 'settled')
        billing.settle_platform_run(self.db, self.db.get(AgentRun, 'run-1'), 'cancelled')
        self.assertEqual(self.balance(), 8)
        self.assertEqual(self.db.query(CreditLedger).filter_by(entry_type='run_settlement').count(), 1)

    def test_force_settlement_keeps_live_debits_and_late_usage_cannot_charge_again(self):
        context = self.begin()
        billing.record_metered_usage(context, {'input_tokens': 500}, {})
        self.refresh()
        run = self.db.get(AgentRun, 'run-1')
        with self.assertRaises(billing.CreditBillingError):
            billing.settle_platform_run(self.db, run, 'running', force_settle=True)
        self.db.rollback()
        run.status = 'failed'
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        billing.settle_platform_run(self.db, run, 'failed')
        self.assertEqual(run.settlement_status, 'pending_reconciliation')
        billing.settle_platform_run(self.db, run, 'failed', force_settle=True, actor_user_id=9)
        self.assertEqual(self.balance(), 9)
        self.assertEqual(self.db.get(AgentRun, 'run-1').charged_points, 1)
        self.assertEqual(self.db.get(AgentRun, 'run-1').settlement_status, 'settled')
        ledger = self.db.query(CreditLedger).filter_by(entry_type='run_settlement').one()
        self.assertEqual(ledger.amount, 0)
        self.assertTrue(json.loads(ledger.metadata_json)['force_settle'])
        billing.finish_gateway_request(context, {'input_tokens': 500, 'output_tokens': 200}, {})
        billing.finish_gateway_request(context, {'input_tokens': 500, 'output_tokens': 200}, {})
        self.assertEqual(self.balance(), 9)
        self.assertEqual(self.db.get(AgentRun, 'run-1').charged_points, 1)
        self.assertEqual(self.db.query(ModelUsageEvent).one().output_tokens, 200)
        billing.settle_platform_run(self.db, self.db.get(AgentRun, 'run-1'), 'failed', force_settle=True)
        self.assertEqual(self.db.query(CreditLedger).filter_by(entry_type='run_settlement').count(), 1)

    def test_empty_account_is_payment_error_before_upstream(self):
        self.db.query(CreditAccount).update({'available_balance': 0})
        self.db.commit()
        async def run():
            request = Request({'type': 'http', 'headers': [(b'x-api-key', self.token.encode())]},
                              AsyncMock(return_value={'type': 'http.request', 'body': b'{}'}))
            with patch.object(gateway.httpx, 'AsyncClient') as upstream:
                response = await gateway.anthropic_messages(request)
                self.assertEqual(response.status_code, 402)
                self.assertIn('已用尽', json.loads(response.body)['error']['message'])
                upstream.assert_not_called()
        asyncio.run(run())

    def test_silent_request_is_interrupted_when_parallel_request_exhausts_account(self):
        context = self.begin()
        async def run():
            stopped = asyncio.Event()
            async def silent_upstream():
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            task = asyncio.create_task(gateway._while_funded(silent_upstream(), context))
            await asyncio.to_thread(billing.record_metered_usage, context, {'output_tokens': 2000}, {})
            with self.assertRaises(billing.CreditBillingError) as error:
                await asyncio.wait_for(task, 2)
            self.assertEqual(error.exception.code, 'CREDITS_EXHAUSTED')
            self.assertTrue(stopped.is_set())
        asyncio.run(run())

    def test_gateway_stream_meters_split_sse_frames_and_stops_on_usage(self):
        async def run():
            async def chunks():
                yield b'data: {"type":"message_start","message":{"usage":{"input_tokens":500}}}\n\n'
                # Input usage must be charged before any body reaches the caller.
                snapshot = await asyncio.to_thread(billing.metered_run_snapshot, 'run-1')
                self.assertEqual(snapshot['charged_points'], 1)
                yield b'data: {"type":"message_delta","usage":{"output_tokens":'
                yield b'2000}}\n\n'
                self.fail('Gateway should close the upstream once credits are depleted')
            upstream = Mock(status_code=200, headers={'content-type': 'text/event-stream'})
            upstream.aiter_bytes = chunks
            upstream.aclose = AsyncMock()
            client = Mock()
            client.send = AsyncMock(return_value=upstream)
            client.aclose = AsyncMock()
            request = Request({'type': 'http', 'headers': [(b'x-api-key', self.token.encode())]},
                AsyncMock(return_value={'type': 'http.request', 'body': b'{"stream":true}'}))
            with patch.object(gateway.httpx, 'AsyncClient', return_value=client), \
                 patch.object(gateway, '_validate_resolved_addresses', AsyncMock()):
                response = await gateway.anthropic_messages(request)
                content = b''.join([part async for part in response.body_iterator])
            self.assertIn(b'credits_exhausted', content)
            upstream.aclose.assert_awaited_once()
            client.aclose.assert_awaited_once()
        asyncio.run(run())
        self.assertEqual(self.balance(), 0)
        event = self.db.query(ModelUsageEvent).one()
        self.assertEqual(event.input_tokens, 500)
        self.assertEqual(event.output_tokens, 2000)

    def test_gateway_preserves_upstream_http_error_and_request_id(self):
        async def run():
            upstream = httpx.Response(503, headers={'request-id': 'req-upstream'},
                json={'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'Provider overloaded'}})
            client = Mock(send=AsyncMock(return_value=upstream), aclose=AsyncMock())
            request = Request({'type': 'http', 'headers': [(b'x-api-key', self.token.encode())]},
                AsyncMock(return_value={'type': 'http.request', 'body': b'{"stream":true}'}))
            with patch.object(gateway.httpx, 'AsyncClient', return_value=client), \
                 patch.object(gateway, '_validate_resolved_addresses', AsyncMock()):
                response = await gateway.anthropic_messages(request)
            self.assertEqual(response.status_code, 503)
            self.assertIn('application/json', response.headers['content-type'])
            error = json.loads(response.body)['error']
            self.assertEqual(error['type'], 'overloaded_error')
            self.assertIn('Provider overloaded', error['message'])
            self.assertIn('HTTP 503; request_id=req-upstream', error['message'])
            client.aclose.assert_awaited_once()
        asyncio.run(run())
        self.assertEqual(self.balance(), 10)

    def test_gateway_read_timeout_returns_sse_error_and_keeps_recorded_debits(self):
        async def run():
            async def chunks():
                yield b'data: {"type":"message_start","message":{"usage":{"input_tokens":500}}}\n\n'
                raise httpx.ReadTimeout('upstream read stalled')
            upstream = Mock(status_code=200, headers={'request-id': 'req-stalled'})
            upstream.aiter_bytes = chunks
            upstream.aclose = AsyncMock()
            client = Mock(send=AsyncMock(return_value=upstream), aclose=AsyncMock())
            request = Request({'type': 'http', 'headers': [(b'x-api-key', self.token.encode())]},
                AsyncMock(return_value={'type': 'http.request', 'body': b'{"stream":true}'}))
            with patch.object(gateway.httpx, 'AsyncClient', return_value=client), \
                 patch.object(gateway, '_validate_resolved_addresses', AsyncMock()):
                response = await gateway.anthropic_messages(request)
                content = b''.join([part async for part in response.body_iterator]).decode()
            self.assertIn('upstream_timeout', content)
            self.assertIn('ReadTimeout: upstream read stalled', content)
            self.assertIn('req-stalled', content)
            self.assertEqual(client.send.await_count, 1)
            upstream.aclose.assert_awaited_once()
            client.aclose.assert_awaited_once()
        asyncio.run(run())
        self.assertEqual(self.balance(), 9)
        self.assertEqual(self.db.query(ModelGatewayRequest).one().status, 'unknown')
        self.refresh()
        run = self.db.get(AgentRun, 'run-1')
        run.status = 'timed_out'
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        billing.settle_platform_run(self.db, run, 'timed_out')
        self.assertEqual(run.settlement_status, 'pending_reconciliation')
        self.assertEqual(billing.recorded_charged_points(run), 1)

    def test_gateway_connect_timeout_is_reported_as_timeout(self):
        async def run():
            client = Mock(send=AsyncMock(side_effect=httpx.ConnectTimeout('connection timed out')), aclose=AsyncMock())
            request = Request({'type': 'http', 'headers': [(b'x-api-key', self.token.encode())]},
                AsyncMock(return_value={'type': 'http.request', 'body': b'{"stream":true}'}))
            with patch.object(gateway.httpx, 'AsyncClient', return_value=client), \
                 patch.object(gateway, '_validate_resolved_addresses', AsyncMock()):
                response = await gateway.anthropic_messages(request)
            self.assertEqual(response.status_code, 504)
            self.assertEqual(json.loads(response.body)['error']['type'], 'upstream_timeout')
            self.assertIn('ConnectTimeout', json.loads(response.body)['error']['message'])
            client.aclose.assert_awaited_once()
        asyncio.run(run())
        self.assertEqual(self.balance(), 10)

    def test_provider_stream_error_keeps_original_message_and_request_id(self):
        async def run():
            async def chunks():
                yield b'data: {"type":"error","error":{"type":"overloaded_error","message":"Provider overloaded"}}\n\n'
            upstream = Mock(status_code=200, headers={'request-id': 'req-provider'})
            upstream.aiter_bytes = chunks
            upstream.aclose = AsyncMock()
            client = Mock(send=AsyncMock(return_value=upstream), aclose=AsyncMock())
            request = Request({'type': 'http', 'headers': [(b'x-api-key', self.token.encode())]},
                AsyncMock(return_value={'type': 'http.request', 'body': b'{"stream":true}'}))
            with patch.object(gateway.httpx, 'AsyncClient', return_value=client), \
                 patch.object(gateway, '_validate_resolved_addresses', AsyncMock()):
                response = await gateway.anthropic_messages(request)
                frames = b''.join([part async for part in response.body_iterator]).decode()
            error = json.loads(next(line[6:] for line in frames.splitlines() if line.startswith('data: ')))['error']
            self.assertEqual(error['type'], 'overloaded_error')
            self.assertIn('Provider overloaded', error['message'])
            self.assertIn('req-provider', error['message'])
            upstream.aclose.assert_awaited_once()
            client.aclose.assert_awaited_once()
        asyncio.run(run())

    def test_error_body_read_timeout_closes_the_response_and_records_uncertain_usage(self):
        async def run():
            upstream = Mock(status_code=503, headers={'request-id': 'req-error-body'},
                            aread=AsyncMock(side_effect=httpx.ReadTimeout('error body stalled')),
                            aclose=AsyncMock())
            client = Mock(send=AsyncMock(return_value=upstream), aclose=AsyncMock())
            request = Request({'type': 'http', 'headers': [(b'x-api-key', self.token.encode())]},
                AsyncMock(return_value={'type': 'http.request', 'body': b'{"stream":true}'}))
            with patch.object(gateway.httpx, 'AsyncClient', return_value=client), \
                 patch.object(gateway, '_validate_resolved_addresses', AsyncMock()):
                response = await gateway.anthropic_messages(request)
            self.assertEqual(response.status_code, 504)
            self.assertIn('req-error-body', json.loads(response.body)['error']['message'])
            upstream.aclose.assert_awaited_once()
            client.aclose.assert_awaited_once()
        asyncio.run(run())
        self.assertEqual(self.balance(), 10)
        self.assertEqual(self.db.query(ModelGatewayRequest).one().status, 'unknown')


if __name__ == '__main__':
    unittest.main()
