"""Published system defaults reach both new/existing assistants and runtime config."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import Session

import enterprise_routes as routes
from agent_service import _build_runtime_config
from auth import CurrentUser
from database import Base
from enterprise_schemas import AgentSettingsDraft, WorkbenchSettingsDraft
from models import Agent, AIModel


class AssistantReasoningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        with patch.object(SQLiteTypeCompiler, 'visit_BIGINT', return_value='INTEGER'):
            Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.admin = CurrentUser(user_id=1, is_superuser=True)
        self.user = CurrentUser(user_id=7)
        self.model = AIModel(
            id=1, user_id=0, name='claude-sonnet-4-6', provider='Anthropic',
            scope='platform', api_protocol='anthropic-messages', api_key='test-only',
            is_enabled=True,
        )
        self.db.add(self.model)
        self.db.commit()
        workspace = SimpleNamespace(id=1, status='ready')
        for name, value in {
            'ensure_user_workspace': (workspace, None), 'bind_agent_workspace': (workspace, None),
            'workspace_payload': {}, '_ensure_account': None, '_grant_claim': None,
            '_credit_response': dict(available_balance=10, reserved_balance=0, status='active', version=1,
                                     display_name='Credits', display_name_en='Credits', daily_claim_amount=0,
                                     today='2026-09-29', claimed_today=True, low_balance_threshold=0),
        }.items():
            replacement = patch.object(routes, name, return_value=value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def settings(self, **changes):
        return AgentSettingsDraft(
            initial_claim_amount=10, daily_claim_amount=10,
            per_run_limit=1, **changes,
        )

    def test_save_publish_bootstrap_and_runtime_keep_reasoning_choices(self):
        routes.save_workbench_settings_draft(WorkbenchSettingsDraft(default_model_id=1), self.db, self.admin)
        config = self.settings(thinking_level='high', reasoning_visibility='stream')
        routes.save_agent_settings_draft(config, self.db, self.admin)
        self.db.expire_all()
        state = routes.get_agent_settings(self.db, self.admin)
        self.assertEqual(state['draft'].thinking_level, 'high')
        self.assertEqual(state['draft'].reasoning_visibility, 'stream')
        self.assertIsNone(state['published'])
        routes.publish_agent_settings(None, self.db, self.admin)
        routes.publish_workbench_settings(None, self.db, self.admin)
        response = routes.bootstrap_user(self.db, self.user)
        agent = self.db.get(Agent, response.assistant_id)
        self.assertEqual((agent.thinking_level, agent.reasoning_visibility), ('high', 'stream'))
        self.assertEqual(response.assistant.thinking_level, 'high')
        self.assertEqual(response.assistant.reasoning_visibility, 'stream')
        runtime = _build_runtime_config(agent, self.model, gateway_token='test', gateway_base_url='http://localhost')
        self.assertEqual(runtime.extra['thinking_level'], 'high')
        self.assertEqual(runtime.extra['reasoning_visibility'], 'stream')

        custom = Agent(user_id=7, name='Custom', thinking_level='max', reasoning_visibility='stream')
        self.db.add(custom)
        self.db.commit()
        update = self.settings(thinking_level='low', reasoning_visibility='off')
        routes.save_agent_settings_draft(update, self.db, self.admin)
        response = routes.bootstrap_user(self.db, self.user)
        self.assertEqual(response.assistant.thinking_level, 'high')  # A draft has no effect.
        routes.publish_agent_settings(None, self.db, self.admin)
        for _ in range(2):
            response = routes.bootstrap_user(self.db, self.user)
            self.assertEqual(response.assistant.id, agent.id)
            self.assertEqual((agent.thinking_level, agent.reasoning_visibility), ('low', 'off'))
            self.assertEqual(response.assistant.reasoning_visibility, 'off')
        self.assertEqual((custom.thinking_level, custom.reasoning_visibility), ('max', 'stream'))

    def test_legacy_defaults_and_invalid_settings(self):
        config = self.settings()
        self.assertEqual((config.thinking_level, config.reasoning_visibility), ('inherit', 'off'))
        for values in ({'thinking_level': 'minimal'}, {'thinking_level': 'invalid'}, {'reasoning_visibility': 'invalid'}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self.settings(**values)


if __name__ == '__main__':
    unittest.main()
