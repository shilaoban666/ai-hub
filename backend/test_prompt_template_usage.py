"""Prompt templates are user-message shortcuts for every agent and runtime."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import agent_service
from agent_workspace import build_claude_md
from runtimes.base import RuntimeEvent
import test_agent_service as fixtures


class PromptTemplateUsageTests(unittest.TestCase):
    def test_bound_templates_never_enter_system_instructions_or_duplicate_user_input(self):
        raw_template = 'Summarize {{topic}}'
        filled_template = 'Summarize inventory'
        identity = 'You are the inventory assistant.'

        for kind in ('personal_default', 'expert'):
            for runtime_type in ('claude_code',):
                for source in ('web', 'dingtalk'):
                    for user_input in ('Hello', filled_template):
                        with self.subTest(kind=kind, runtime=runtime_type, source=source, input=user_input):
                            captured = {}

                            class Workspace(fixtures._Sandbox):
                                def prepare_execution(self, agent, model, **kwargs):
                                    captured['system'] = build_claude_md(agent)
                                    return super().prepare_execution(agent, model, **kwargs)

                            class Runtime:
                                async def run(self, config, ctx, user_input, history, on_event, run_context=None):
                                    captured['input'] = user_input
                                    await on_event(RuntimeEvent(type='text', content='ok'))
                                    await on_event(RuntimeEvent(type='done'))

                            agent = fixtures._agent()
                            agent.kind = kind
                            agent.runtime_type = runtime_type
                            agent.name = 'Inventory assistant'
                            agent.description = ''
                            agent.system_prompt = identity
                            agent.prompt_templates = [SimpleNamespace(id=1, name='Summary', content=raw_template)]
                            # A reused object must not retain the old combined instructions.
                            agent.effective_system_prompt = identity + '\n' + raw_template
                            session = fixtures._session()
                            session.runtime_type = runtime_type
                            with (
                                fixtures._execution_dependencies(),
                                patch.object(agent_service, 'AgentMemory', fixtures._Memory),
                                patch.object(agent_service, 'get_workspace_provider', return_value=Workspace()),
                                patch.object(agent_service, 'get_runtime', return_value=Runtime()),
                            ):
                                # This DB rejects prompt queries: execution must never load templates.
                                result = asyncio.run(agent_service.execute_agent_turn(
                                    agent=agent, user_input=user_input, session_id=11, user_id=7,
                                    source=source, db=fixtures._DB(session, fixtures._model()),
                                ))
                            self.assertEqual(result.status, 'succeeded')
                            self.assertEqual(agent.effective_system_prompt, identity)
                            self.assertIn(identity, captured['system'])
                            self.assertNotIn(raw_template, captured['system'])
                            self.assertNotIn(filled_template, captured['system'])
                            self.assertEqual(captured['input'], user_input)
                            self.assertEqual((captured['system'] + captured['input']).count(filled_template),
                                             int(user_input == filled_template))


if __name__ == '__main__':
    unittest.main()
