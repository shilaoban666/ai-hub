"""Configured credit names must survive every user-visible error path."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from auth import CurrentUser
from credit_accounts import ensure_initial_credits
from credit_billing import prepare_platform_run, begin_gateway_request, token_hash, CreditBillingError
from credit_labels import credit_display_name
from enterprise_routes import get_my_credits, publish_agent_settings
from models import AIModel, AgentRun, AgentSession, CreditAccount, ModelPricingVersion, ModelRunCredential, PlatformAgentSettings
import test_prelaunch_isolation as fixtures


class CreditLabelTests(unittest.TestCase):
    setUp = fixtures.IsolationTests.setUp

    def prepare_run(self):
        model = AIModel(id=1, user_id=0, name='platform', provider='test', scope='platform')
        run = AgentRun(id='credit-label-run', agent_id=99, session_id=1, user_id=7, source='web', status='running')
        self.db.add_all([model, run, AgentSession(id=1, agent_id=99, user_id=7),
                         ModelPricingVersion(id=1, model_id=1, version=1, input_rate=1, output_rate=1)])
        self.policy.initial_claim_amount = 0
        self.db.commit()
        return run, model

    def test_insufficient_balance_follows_published_name_and_ignores_draft(self):
        run, model = self.prepare_run()
        self.db.add(PlatformAgentSettings(version=2, status='draft', created_by=7, credit_display_name='草稿名称'))
        for name in ('趣点', '能量值'):
            self.policy.credit_display_name = name
            self.db.commit()
            with patch('sandbox.get_configured_sandbox_type', return_value='native'):
                with self.assertRaises(CreditBillingError) as error:
                    prepare_platform_run(self.db, run, model, 600, 'claude_code')
            self.assertEqual(error.exception.code, 'CREDITS_EXHAUSTED')
            self.assertEqual(str(error.exception), f'{name}已用尽，请领取或充值后重试')
            self.db.rollback()
            self.assertEqual(get_my_credits(self.db, self.user).display_name, name)

    def test_disabled_account_uses_name_before_and_after_initial_claim(self):
        run, model = self.prepare_run()
        self.policy.credit_display_name = '趣点'
        self.db.add(CreditAccount(user_id=7, status='disabled'))
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            ensure_initial_credits(self.db, 7, self.policy)
        self.assertEqual(error.exception.detail['message'], '趣点账户已停用')
        self.db.rollback()
        for claimed in (False, True):
            if claimed:
                self.db.query(CreditAccount).one().status = 'active'
                self.db.commit()
                ensure_initial_credits(self.db, 7, self.policy)
                self.db.query(CreditAccount).one().status = 'disabled'
                self.db.commit()
            with patch('sandbox.get_configured_sandbox_type', return_value='native'):
                with self.assertRaises(CreditBillingError) as error:
                    prepare_platform_run(self.db, run, model, 600, 'claude_code')
            self.assertEqual(str(error.exception), '趣点账户不可用')
            self.assertEqual(error.exception.code, 'CREDIT_ACCOUNT_UNAVAILABLE')
            self.db.rollback()

    def test_gateway_exhaustion_uses_current_published_name(self):
        self.prepare_run()
        self.db.add(ModelRunCredential(token_hash=token_hash('test-token'), run_id='credit-label-run',
                    user_id=7, model_id=1, pricing_version_id=1, max_points=1, consumed_points=1,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
        for name in ('趣点', '能量值'):
            self.policy.credit_display_name = name
            self.db.commit()
            with patch('credit_billing.SessionLocal', self.factory):
                with self.assertRaises(CreditBillingError) as error:
                    begin_gateway_request('test-token', b'{}')
            self.assertEqual(error.exception.code, 'RUN_BUDGET_EXHAUSTED')
            self.assertEqual(str(error.exception), f'本次运行{name}额度已用尽')

    def test_publish_still_requires_daily_claim_amount(self):
        self.db.add(PlatformAgentSettings(version=2, status='draft', created_by=7,
                    credit_display_name='趣点', default_model_id=1, per_run_limit=0))
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            publish_agent_settings(None, self.db, CurrentUser(user_id=7, is_superuser=True))
        self.assertEqual(error.exception.detail, '每日领取额度必须大于 0')

    def test_missing_name_has_a_neutral_fallback(self):
        for policy in (None, SimpleNamespace(credit_display_name=' ')):
            self.assertEqual(credit_display_name(policy), '积分')
        self.assertEqual(credit_display_name(SimpleNamespace(credit_display_name=' 趣点 ')), '趣点')


if __name__ == '__main__':
    unittest.main()
