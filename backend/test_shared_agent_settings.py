"""Independent publications, migration, and shared execution across entry points."""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import Session

import agent_service
import enterprise_routes as routes
from agent_settings import runtime_agent, seed_workbench_settings
from agent_routes import _to_response, create_agent, update_agent
from auth import CurrentUser, get_current_active_user
from database import Base, get_db
from enterprise_schemas import AgentSettingsDraft, PlatformModelUpsert, WorkbenchSettingsDraft
from models import Agent, AIModel, PlatformAgentSettings, WorkbenchSettings
from noun_highlight import DEFAULT_NOUN_EXPLANATION_URL
from schemas import AgentCreate, AgentUpdate
from test_agent_service import (
    _DB, _Query, _Memory, _Runtime, _Sandbox, _agent, _model, _session,
    _execution_dependencies,
)


class SharedSettingsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, autoflush=False)
        self.addCleanup(self.db.close)
        self.admin = CurrentUser(user_id=1, is_superuser=True)
        self.user = CurrentUser(user_id=7)
        self.db.add_all([
            AIModel(id=1, user_id=0, scope="platform", name="claude-sonnet-4-6",
                    provider="Anthropic", api_protocol="anthropic-messages", api_key="test-only"),
            AIModel(id=2, user_id=7, scope="user", name="personal-model",
                    provider="Anthropic", api_protocol="anthropic-messages", api_key="personal-test"),
        ])
        self.db.commit()

    def policy(self, **values):
        return AgentSettingsDraft(initial_claim_amount=10, daily_claim_amount=2, per_run_limit=1, **values)

    def publish_policy(self, **values):
        return routes.publish_agent_settings(self.policy(**values), self.db, self.admin)

    def publish_workbench(self, **values):
        values.setdefault("assistant_name", "Workbench assistant")
        return routes.publish_workbench_settings(WorkbenchSettingsDraft(default_model_id=1, **values), self.db, self.admin)

    def test_pending_workbench_draft_cannot_be_overwritten_or_edited_on_publish(self):
        self.publish_policy()
        self.publish_workbench()
        creator = CurrentUser(user_id=9, is_superuser=True)
        draft = routes.save_workbench_settings_draft(
            WorkbenchSettingsDraft(default_model_id=1, assistant_name="Pending"),
            self.db, creator,
        )
        for operation in (routes.save_workbench_settings_draft, routes.publish_workbench_settings):
            with self.assertRaises(HTTPException) as raised:
                operation(WorkbenchSettingsDraft(default_model_id=1, assistant_name="Overwrite"), self.db, self.admin)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(draft.assistant_name, "Pending")
            self.assertEqual(draft.created_by, creator.user_id)
        published = routes.publish_workbench_settings(None, self.db, self.admin)
        self.assertEqual(published.id, draft.id)
        self.assertEqual(published.assistant_name, "Pending")
        self.assertEqual(published.created_by, creator.user_id)
        self.assertEqual(published.published_by, self.admin.user_id)

    def test_workbench_history_excludes_drafts_and_paginates_publications(self):
        self.publish_policy()
        first = self.publish_workbench(assistant_name="First", system_prompt="# First prompt\nOriginal instructions")
        first_id = first.id
        latest = self.publish_workbench(assistant_name="Latest", system_prompt="# Latest prompt\nUpdated instructions")
        routes.save_workbench_settings_draft(
            WorkbenchSettingsDraft(default_model_id=1, assistant_name="Pending"), self.db, self.admin,
        )
        result = routes.get_workbench_settings_history(0, 1, self.db, self.admin)
        # The legacy published policy is preserved as the initial assistant version.
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["items"][0]["id"], latest.id)
        self.assertEqual(result["items"][0]["status"], "published")
        self.assertEqual(result["items"][0]["changes"]["system_prompt"], {
            "before": "# First prompt\nOriginal instructions",
            "after": "# Latest prompt\nUpdated instructions",
        })
        self.assertEqual(set(result["items"][0]["changes"]), {"assistant_name", "system_prompt"})
        self.assertNotIn("system_prompt", result["items"][0])
        older = routes.get_workbench_settings_history(1, 1, self.db, self.admin)
        self.assertEqual(older["items"][0]["id"], first_id)
        self.assertEqual(older["items"][0]["status"], "superseded")
        self.assertEqual(older["items"][0]["changes"]["assistant_name"]["after"], "First")
        self.assertEqual(older["items"][0]["changes"]["system_prompt"]["after"], "# First prompt\nOriginal instructions")
        with self.assertRaises(HTTPException) as raised:
            routes.get_workbench_settings_history(0, 1, self.db, self.user)
        self.assertEqual(raised.exception.status_code, 403)

    def test_no_change_save_and_publish_use_database_values(self):
        self.publish_policy()
        current = self.publish_workbench()
        payload = WorkbenchSettingsDraft.model_validate(current, from_attributes=True)
        count = self.db.query(WorkbenchSettings).count()
        for operation in (routes.save_workbench_settings_draft, routes.publish_workbench_settings):
            with self.assertRaises(HTTPException) as raised:
                operation(payload, self.db, self.admin)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(self.db.query(WorkbenchSettings).count(), count)
        # Change the database independently of the client's loaded configuration.
        self.db.query(WorkbenchSettings).filter_by(id=current.id).update({"system_prompt": "Backend prompt"})
        self.db.commit()
        draft = routes.save_workbench_settings_draft(payload, self.db, self.admin)
        self.assertIsNone(draft.system_prompt)
        routes.publish_workbench_settings(None, self.db, self.admin)
        history = routes.get_workbench_settings_history(0, 1, self.db, self.admin)
        self.assertEqual(history["items"][0]["changes"], {
            "system_prompt": {"before": "Backend prompt", "after": None},
        })

    def test_blank_text_and_false_are_compared_without_truthiness(self):
        previous = SimpleNamespace(system_prompt=None, noun_highlight_enabled=True)
        current = SimpleNamespace(system_prompt="", noun_highlight_enabled=False)
        changes = routes._workbench_changes(previous, current)
        self.assertEqual(changes, {"noun_highlight_enabled": {"before": True, "after": False}})

    def test_noun_settings_publish_and_sync_without_a_runtime_policy_change(self):
        self.publish_policy()
        self.publish_workbench()
        with patch.object(routes, "ensure_user_workspace", return_value=(SimpleNamespace(id=1), None)), \
             patch.object(routes, "bind_agent_workspace", return_value=(SimpleNamespace(id=1, status="ready"), None)), \
             patch.object(routes, "workspace_payload", return_value={}), \
             patch.object(routes, "_credit_response", return_value=dict(
                 available_balance=10, reserved_balance=0, status="active", version=1,
                 display_name="Credits", display_name_en="Credits", daily_claim_amount=2,
                 today="2026-11-02", claimed_today=False, low_balance_threshold=0)):
            initial = routes.bootstrap_user(self.db, self.user)
            self.assertTrue(initial.assistant.noun_highlight_enabled)
            self.assertEqual(initial.assistant.noun_explanation_url, DEFAULT_NOUN_EXPLANATION_URL)
            draft = routes.save_workbench_settings_draft(WorkbenchSettingsDraft(
                default_model_id=1, noun_highlight_enabled=False,
                noun_explanation_url="https://glossary.example/info?source=chat",
            ), self.db, self.admin)
            self.assertFalse(draft.noun_highlight_enabled)
            self.assertTrue(routes.bootstrap_user(self.db, self.user).assistant.noun_highlight_enabled)
            routes.publish_workbench_settings(None, self.db, self.admin)
            updated = routes.bootstrap_user(self.db, self.user)
            self.assertEqual(updated.assistant.id, initial.assistant.id)
            self.assertFalse(updated.assistant.noun_highlight_enabled)
            self.assertEqual(updated.assistant.noun_explanation_url, "https://glossary.example/info?source=chat")
            self.assertEqual(updated.settings_version, initial.settings_version)
            self.assertFalse(_to_response(self.db.get(Agent, updated.assistant.id), self.db).noun_highlight_enabled)

    def test_expert_noun_configuration_is_independent_and_round_trips_false(self):
        self.publish_policy()
        self.publish_workbench(noun_highlight_enabled=False)
        with patch("agent_routes.bind_agent_workspace"):
            created = create_agent(AgentCreate(name="Expert"), self.db, self.user)
            self.assertTrue(created.noun_highlight_enabled)
            self.assertEqual(created.noun_explanation_url, DEFAULT_NOUN_EXPLANATION_URL)
            changed = update_agent(created.id, AgentUpdate(
                noun_highlight_enabled=False, noun_explanation_url="https://glossary.example/?from=expert",
            ), self.db, self.user)
            self.assertFalse(changed.noun_highlight_enabled)
            self.assertEqual(changed.noun_explanation_url, "https://glossary.example/?from=expert")
            renamed = update_agent(created.id, AgentUpdate(name="Renamed"), self.db, self.user)
            self.assertFalse(renamed.noun_highlight_enabled)
            self.assertEqual(renamed.noun_explanation_url, changed.noun_explanation_url)
        for schema in (WorkbenchSettingsDraft, AgentCreate, AgentUpdate):
            for url in ("javascript:alert(1)", "//example.com", "https://user:pass@example.com", ""):
                with self.subTest(schema=schema, url=url), self.assertRaises(ValidationError):
                    schema(**({"name": "Expert"} if schema is AgentCreate else {}), noun_explanation_url=url)

    def test_runtime_migration_works_before_noun_columns_exist(self):
        self.publish_policy()
        self.publish_workbench()
        self.db.add(Agent(id=9, user_id=7, name="Legacy expert", runtime_type="openclaw", default_model_id=1))
        self.db.commit()
        with self.engine.begin() as connection:
            for table in ("agents", "workbench_settings"):
                for column in ("noun_highlight_enabled", "noun_explanation_url"):
                    connection.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {column}")
        self.db.expunge_all()
        path = Path(__file__).parent / "migrations" / "056_claude_runtime.py"
        spec = importlib.util.spec_from_file_location("pre_noun_runtime_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(migration.backfill(self.db, apply=False)["agents"], 1)
        with patch("enterprise_workspace.reset_runtime_workspace"), \
             patch("enterprise_workspace.bind_agent_workspace", return_value=(SimpleNamespace(), None)):
            self.assertEqual(migration.backfill(self.db)["agents"], 1)
        self.db.commit()

    def test_global_policy_can_publish_without_an_assistant_or_default_model(self):
        result = self.publish_policy(max_turns=70)
        self.assertEqual(result.status, "published")
        self.assertIsNone(result.default_model_id)
        self.assertNotIn("default_model_id", routes.get_agent_settings(self.db, self.admin)["published"].model_dump())
        with self.assertRaises(HTTPException) as error:
            routes.bootstrap_user(self.db, self.user)
        self.assertEqual(error.exception.detail["data"]["code"], "WORKBENCH_SETTINGS_NOT_PUBLISHED")

    def test_publications_and_drafts_are_independent_and_bootstrap_combines_them(self):
        self.publish_policy(thinking_level="high", max_turns=70)
        self.publish_workbench(assistant_name="Team assistant", system_prompt="identity-v1")
        routes.save_agent_settings_draft(self.policy(thinking_level="low", max_turns=20), self.db, self.admin)
        routes.save_workbench_settings_draft(WorkbenchSettingsDraft(default_model_id=1, assistant_name="Draft"), self.db, self.admin)
        policy_version = routes.get_agent_settings(self.db, self.admin)["published"].version
        with patch.object(routes, "ensure_user_workspace", return_value=(SimpleNamespace(id=1), None)), \
             patch.object(routes, "bind_agent_workspace", return_value=(SimpleNamespace(id=1, status="ready"), None)), \
             patch.object(routes, "workspace_payload", return_value={}), \
             patch.object(routes, "_credit_response", return_value=dict(
                 available_balance=10, reserved_balance=0, status="active", version=1,
                 display_name="Credits", display_name_en="Credits", daily_claim_amount=2,
                 today="2026-10-13", claimed_today=False, low_balance_threshold=0)):
            initial = routes.bootstrap_user(self.db, self.user)
            self.assertEqual(initial.assistant_name, "Team assistant")
            self.assertEqual(initial.assistant.thinking_level, "high")
            custom = Agent(user_id=7, name="Expert", system_prompt="expert identity", default_model_id=2,
                           max_turns=3, timeout_seconds=60, thinking_level="max")
            self.db.add(custom)
            self.db.commit()
            routes.publish_workbench_settings(None, self.db, self.admin)
            self.assertEqual(routes.get_agent_settings(self.db, self.admin)["published"].version, policy_version)
            updated = routes.bootstrap_user(self.db, self.user)
            self.assertEqual(updated.assistant.id, initial.assistant.id)
            self.assertEqual(updated.assistant_name, "Draft")
            self.assertEqual(updated.assistant.thinking_level, "high")
            workbench_version = routes.get_workbench_settings(self.db, self.admin)["published"].version
            routes.publish_agent_settings(None, self.db, self.admin)
            self.assertEqual(routes.get_workbench_settings(self.db, self.admin)["published"].version, workbench_version)
            for agent in (self.db.get(Agent, initial.assistant.id), custom):
                response = _to_response(agent, self.db)
                self.assertEqual((response.max_turns, response.thinking_level), (20, "low"))
            self.assertEqual(custom.system_prompt, "expert identity")
            self.assertEqual(custom.default_model_id, 2)
            self.assertEqual(custom.max_turns, 3)  # Reading effective policy never rewrites the expert.

    def test_legacy_identity_and_pending_draft_survive_global_publication(self):
        self.db.add_all([
            PlatformAgentSettings(version=7, status="published", created_by=1, default_model_id=1,
                                  assistant_name="Existing", system_prompt="published identity", assistant_mascot="@sprout"),
            PlatformAgentSettings(version=8, status="draft", created_by=1, default_model_id=1,
                                  assistant_name="Pending", system_prompt="draft identity"),
        ])
        self.db.commit()
        self.publish_policy(max_turns=90)
        state = routes.get_workbench_settings(self.db, self.admin)
        self.assertEqual(state["published"].assistant_name, "Existing")
        self.assertEqual(state["draft"].assistant_name, "Pending")
        self.assertEqual(routes.public_assistant_appearance(self.db), {"mascot": "@sprout"})
        seed_workbench_settings(self.db)
        self.assertEqual(self.db.query(WorkbenchSettings).count(), 2)
        self.publish_policy(max_turns=25)
        self.assertEqual(routes.get_workbench_settings(self.db, self.admin)["published"].system_prompt, "published identity")

    def test_expert_update_cannot_override_published_runtime_policy(self):
        self.publish_policy(max_turns=80, timeout_seconds=300, thinking_level="high")
        agent = Agent(user_id=7, name="Expert", default_model_id=2, max_turns=1)
        self.db.add(agent)
        self.db.commit()
        with patch("agent_routes.bind_agent_workspace"), \
             patch("agent_routes.get_workspace_provider", return_value=SimpleNamespace(prepare=lambda *args: None)):
            result = update_agent(agent.id, AgentUpdate(name="Renamed", runtime_type="claude_code",
                                  thinking_level="off", max_turns=2, timeout_seconds=60), self.db, self.user)
        self.assertEqual((result.runtime_type, result.thinking_level, result.max_turns, result.timeout_seconds),
                         ("claude_code", "high", 80, 300))
        self.assertEqual(result.default_model_id, 2)

    def test_settings_require_admin_and_workbench_validates_its_model(self):
        for getter in (routes.get_agent_settings, routes.get_workbench_settings):
            with self.assertRaises(HTTPException) as error:
                getter(self.db, self.user)
            self.assertEqual(error.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            routes.publish_workbench_settings(WorkbenchSettingsDraft(default_model_id=2), self.db, self.admin)
        self.db.rollback()
        self.publish_policy()
        self.db.get(AIModel, 1).is_enabled = False
        self.db.commit()
        with self.assertRaises(HTTPException):
            self.publish_workbench()

    def test_retired_combined_writes_return_410_without_changing_either_draft(self):
        self.publish_policy(max_turns=80)
        self.publish_workbench(assistant_name="Published assistant")
        routes.save_agent_settings_draft(self.policy(max_turns=60), self.db, self.admin)
        routes.save_workbench_settings_draft(WorkbenchSettingsDraft(default_model_id=1, assistant_name="Pending assistant"), self.db, self.admin)
        before = (
            routes.get_agent_settings(self.db, self.admin),
            routes.get_workbench_settings(self.db, self.admin),
        )
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_active_user] = lambda: self.admin
        payload = {"assistant_name": "Legacy change", "default_model_id": 1,
                   "max_turns": 10, "initial_claim_amount": 10,
                   "daily_claim_amount": 2, "per_run_limit": 1}
        with TestClient(app) as client:
            for method, path, body in (
                ("PUT", "/api/admin/assistant-settings/draft", payload),
                ("POST", "/api/admin/assistant-settings/publish", payload),
                ("POST", "/api/admin/assistant-settings/publish", None),
            ):
                response = client.request(method, path, json=body)
                self.assertEqual(response.status_code, 410)
                self.assertIn("设置已拆分", response.json()["detail"])
        after = (
            routes.get_agent_settings(self.db, self.admin),
            routes.get_workbench_settings(self.db, self.admin),
        )
        self.assertEqual(before, after)

    def test_retired_combined_read_merges_the_current_workbench_identity(self):
        self.publish_policy(max_turns=80)
        self.publish_workbench(assistant_name="Current assistant", system_prompt="identity-v2")
        routes.save_agent_settings_draft(self.policy(max_turns=60), self.db, self.admin)
        routes.save_workbench_settings_draft(
            WorkbenchSettingsDraft(default_model_id=1, assistant_name="Pending assistant"),
            self.db,
            self.admin,
        )
        state = routes.get_assistant_settings(self.db, self.admin)
        self.assertEqual(state["published"].assistant_name, "Current assistant")
        self.assertEqual(state["published"].max_turns, 80)
        self.assertEqual(state["draft"].assistant_name, "Pending assistant")
        self.assertEqual(state["draft"].max_turns, 60)

    def test_default_model_is_protected_until_a_replacement_is_published(self):
        self.publish_policy()
        self.publish_workbench()
        self.db.add(AIModel(id=3, user_id=0, scope="platform", name="replacement",
                            provider="Anthropic", api_protocol="anthropic-messages", api_key="test-only"))
        self.db.commit()
        routes.save_workbench_settings_draft(WorkbenchSettingsDraft(default_model_id=3), self.db, self.admin)
        for values in ({"is_enabled": False}, {"api_protocol": "openai-completions"}):
            with self.subTest(values=values), self.assertRaises(HTTPException) as error:
                routes.update_platform_model(1, PlatformModelUpsert(name="changed", **values), self.db, self.admin)
            self.assertEqual(error.exception.status_code, 400)
            self.assertTrue(self.db.get(AIModel, 1).is_enabled)
            self.assertEqual(self.db.get(AIModel, 1).api_protocol, "anthropic-messages")
        edited = routes.update_platform_model(1, PlatformModelUpsert(name="renamed"), self.db, self.admin)
        self.assertEqual(edited["name"], "renamed")
        self.assertTrue(edited["has_api_key"])
        routes.publish_workbench_settings(None, self.db, self.admin)
        disabled = routes.update_platform_model(1, PlatformModelUpsert(name="renamed", is_enabled=False), self.db, self.admin)
        self.assertFalse(disabled["is_enabled"])

    def test_platform_model_delete_is_soft_and_rejects_referenced_models(self):
        self.publish_policy()
        self.publish_workbench()
        with self.assertRaises(HTTPException) as error:
            routes.delete_platform_model(1, self.db, self.admin)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("工作台默认模型", error.exception.detail)
        self.assertFalse(self.db.get(AIModel, 1).is_deleted)

        agent = Agent(user_id=7, name="Uses platform model", default_model_id=None)
        agent.models = [self.db.get(AIModel, 1)]
        self.db.add(agent)
        self.db.commit()
        workbench = self.db.query(WorkbenchSettings).filter_by(status="published").first()
        workbench.default_model_id = None
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            routes.delete_platform_model(1, self.db, self.admin)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("Uses platform model", error.exception.detail)

        agent.models = []
        self.db.commit()
        result = routes.delete_platform_model(1, self.db, self.admin)
        self.assertEqual(result["message"], "平台模型删除成功")
        self.assertTrue(self.db.get(AIModel, 1).is_deleted)
        self.assertEqual(routes.list_platform_models(self.db, self.admin)["total"], 0)

    def test_platform_model_delete_ignores_superseded_workbench_defaults(self):
        self.publish_policy()
        self.publish_workbench()
        self.db.add(AIModel(id=3, user_id=0, scope="platform", name="replacement",
                            provider="Anthropic", api_protocol="anthropic-messages", api_key="test-only"))
        self.db.commit()
        routes.save_workbench_settings_draft(WorkbenchSettingsDraft(default_model_id=3), self.db, self.admin)
        routes.publish_workbench_settings(None, self.db, self.admin)

        result = routes.delete_platform_model(1, self.db, self.admin)
        self.assertEqual(result["message"], "平台模型删除成功")
        self.assertTrue(self.db.get(AIModel, 1).is_deleted)

    def test_workbench_name_is_normalized_and_blank_names_are_rejected(self):
        value = routes.save_workbench_settings_draft(
            WorkbenchSettingsDraft(assistant_name="  Team assistant  "), self.db, self.admin,
        )
        self.assertEqual(value.assistant_name, "Team assistant")
        for name in ("", "   ", "\t\n"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                WorkbenchSettingsDraft(assistant_name=name)

    def test_standalone_migration_preserves_the_legacy_publication_and_is_repeatable(self):
        self.db.add_all([
            PlatformAgentSettings(version=7, status="published", created_by=1,
                                  assistant_name="Existing", default_model_id=1),
            PlatformAgentSettings(version=8, status="draft", created_by=1,
                                  assistant_name="Pending", default_model_id=1),
        ])
        self.db.commit()
        WorkbenchSettings.__table__.drop(self.engine)
        path = Path(__file__).parent / "migrations" / "052_split_workbench_settings.py"
        spec = importlib.util.spec_from_file_location("split_workbench_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            migration.migrate(self.engine)
            migration.migrate(self.engine)
        self.db.expire_all()
        state = routes.get_workbench_settings(self.db, self.admin)
        self.assertEqual((state["published"].version, state["published"].assistant_name), (7, "Existing"))
        self.assertEqual((state["draft"].version, state["draft"].assistant_name), (8, "Pending"))
        self.assertEqual(self.db.query(WorkbenchSettings).count(), 2)


class SharedExecutionTests(unittest.TestCase):
    def test_workbench_expert_and_channel_execute_the_same_policy_snapshot(self):
        for kind, source in (("personal_default", "web"), ("expert", "web"), ("expert", "weixin")):
            with self.subTest(kind=kind, source=source):
                policy = SimpleNamespace(version=5, runtime_type="claude_code", thinking_level="high",
                                         reasoning_visibility="stream", max_turns=80, timeout_seconds=240)
                agent = _agent()
                agent.kind = kind
                agent.user_id = 7
                model = _model()
                model.name = "claude-sonnet-4-6"
                model.scope = "user"
                db = _DB(_session(), model)
                runtime = _Runtime(thinking="reasoning")
                captured = []

                async def execute(**kwargs):
                    captured.append(kwargs["config"])
                    # A publication during execution must not change this turn.
                    policy.version = 6
                    policy.max_turns = 10
                    policy.thinking_level = "low"
                    await runtime.run(**kwargs)

                with _execution_dependencies(), patch("agent_settings.published_agent_settings", return_value=policy), \
                     patch.object(agent_service, "AgentMemory", _Memory), \
                     patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()), \
                     patch.object(agent_service, "get_runtime", return_value=SimpleNamespace(run=execute)), \
                     patch.object(agent_service, "build_mcp_json", return_value=({}, [])):
                    result = asyncio.run(agent_service.execute_agent_turn(
                        agent=agent, user_input="current", session_id=11, user_id=7, db=db, source=source))
                self.assertEqual(result.status, "succeeded")
                self.assertEqual((captured[0].max_turns, captured[0].timeout_seconds), (80, 240))
                self.assertEqual(captured[0].extra["thinking_level"], "high")
                snapshot = json.loads(db.run.config_snapshot)
                self.assertEqual((snapshot["config_version"], snapshot["max_turns"]), (5, 80))
                self.assertEqual(db.session.config_version, 5)
                self.assertEqual(agent.max_turns, 10)
                self.assertEqual(agent.thinking_level, "inherit")
                thinking = [block for block in result.blocks if block.get("type") == "thinking"]
                self.assertEqual(bool(thinking), source == "web")


if __name__ == "__main__":
    unittest.main()
