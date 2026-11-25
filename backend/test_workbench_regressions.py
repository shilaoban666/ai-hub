"""Regression coverage for public MCPs, failed billing and model continuity."""

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import agent_routes
import credit_billing
import enterprise_routes
with patch("sqlalchemy.schema.MetaData.create_all"):
    import main
import model_gateway
from auth import CurrentUser
from database import Base
from models import (
    Agent, AgentRun, AgentSession, AIModel, CreditAccount, CreditLedger,
    McpService, ModelPricingVersion, ModelRunCredential, ModelUsageEvent,
    PlatformAgentSettings, PromptTemplate, Skill,
)
from schemas import AgentMessageRequest


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        # SQLite only auto-increments the exact INTEGER primary-key type.
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.db = self.factory()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)

    def add_model(self, model_id, **overrides):
        values = dict(id=model_id, user_id=7, name=f"model-{model_id}",
                      provider="anthropic", scope="platform",
                      api_protocol="anthropic-messages")
        values.update(overrides)
        model = AIModel(**values)
        self.db.add(model)
        return model


class ResourceListOrderingTests(DatabaseTestCase):
    def test_creation_order_is_stable_across_pages_search_and_updates(self):
        user = CurrentUser(user_id=7)
        oldest = datetime(2026, 9, 1)
        newest = datetime(2026, 9, 20)
        for model_type, endpoint, extra, params in [
            (Skill, main.get_skills, {"version": "1.0"}, {}),
            (McpService, main.get_mcps, {"type": "json"}, {}),
            (AIModel, main.get_models, {"scope": "user", "provider": "test"}, {"scope": "user"}),
            (PromptTemplate, main.get_prompt_templates, {"content": "test"}, {}),
        ]:
            with self.subTest(resource=model_type.__name__):
                for item_id, created_at in [(1, oldest), (2, newest), (3, newest), (4, datetime(2026, 9, 10))]:
                    self.db.add(model_type(
                        id=item_id, user_id=7,
                        name="other" if item_id == 4 else f"match-{item_id}",
                        created_at=created_at,
                        # Updating an old resource must not move it to the top.
                        updated_at=datetime(2026, 9, 23) if item_id == 1 else created_at,
                        **extra,
                    ))
                self.db.add_all([
                    model_type(id=5, user_id=8, name="match-foreign", created_at=newest, **extra),
                    model_type(id=6, user_id=7, name="match-deleted", created_at=newest, is_deleted=True, **extra),
                ])
                self.db.commit()
                first = endpoint(skip=0, limit=2, db=self.db, current_user=user, **params)
                second = endpoint(skip=2, limit=2, db=self.db, current_user=user, **params)
                self.assertEqual(first["total"], 4)
                self.assertEqual(second["total"], 4)
                item_id = (lambda item: item["id"]) if model_type is AIModel else (lambda item: item.id)
                self.assertEqual([item_id(item) for item in first["items"] + second["items"]], [3, 2, 4, 1])
                search = endpoint(search="match", db=self.db, current_user=user, **params)
                self.assertEqual(search["total"], 3)
                self.assertEqual([item_id(item) for item in search["items"]], [3, 2, 1])


class PersonalModelManagementTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = CurrentUser(user_id=7)
        self.add_model(1, scope="user", name="custom-one")
        self.add_model(2, scope="user", name="custom-two", is_enabled=False)
        self.add_model(3, scope="user", user_id=8, name="custom-foreign")
        self.add_model(4, scope="user", is_deleted=True, name="custom-deleted")
        # A platform model may have the same creator as the current user.
        self.add_model(5, user_id=7, api_key="platform-test-secret")
        self.add_model(6, user_id=8)
        self.db.commit()

    def test_personal_list_filters_scope_before_search_count_and_pagination(self):
        response = main.get_models(scope="user", db=self.db, current_user=self.user)
        self.assertEqual(response["total"], 2)
        self.assertEqual({model["id"] for model in response["items"]}, {1, 2})
        page = main.get_models(scope="user", skip=1, limit=1, db=self.db, current_user=self.user)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 1)
        self.assertIn(page["items"][0]["id"], {1, 2})
        search = main.get_models(scope="user", search="two", db=self.db, current_user=self.user)
        self.assertEqual(search["total"], 1)
        self.assertEqual(search["items"][0]["id"], 2)

    def test_selection_catalog_still_returns_platform_models_without_secrets(self):
        response = main.get_models(db=self.db, current_user=self.user)
        self.assertEqual(response["total"], 4)
        platform = [item for item in response["items"] if item["scope"] == "platform"]
        self.assertEqual({item["id"] for item in platform}, {5, 6})
        self.assertTrue(all(item["api_key"] == "" for item in response["items"]))

    def test_personal_api_cannot_modify_platform_or_foreign_models(self):
        for model_id in (3, 5, 6):
            for operation in ("update", "delete"):
                with self.subTest(model_id=model_id, operation=operation):
                    with self.assertRaises(HTTPException) as raised:
                        if operation == "update":
                            main.update_model(model_id, main.schemas.ModelUpdate(remarks="changed"),
                                              db=self.db, current_user=self.user)
                        else:
                            main.delete_model(model_id, db=self.db, current_user=self.user)
                    self.assertEqual(raised.exception.status_code, 404)
                    model = self.db.get(AIModel, model_id)
                    self.assertFalse(model.is_deleted)
                    self.assertIsNone(model.remarks)

    def test_own_custom_model_can_be_edited_and_soft_deleted(self):
        main.update_model(1, main.schemas.ModelUpdate(remarks="updated"), db=self.db, current_user=self.user)
        self.assertEqual(self.db.get(AIModel, 1).remarks, "updated")
        main.delete_model(1, db=self.db, current_user=self.user)
        self.assertTrue(self.db.get(AIModel, 1).is_deleted)
        response = main.get_models(scope="user", db=self.db, current_user=self.user)
        self.assertEqual(response["total"], 1)
        self.assertEqual(response["items"][0]["id"], 2)

    def test_custom_model_api_key_blank_update_preserves_and_nonblank_replaces(self):
        model = self.db.get(AIModel, 1)
        model.api_key = "original-key"
        self.db.commit()

        main.update_model(
            1,
            main.schemas.ModelUpdate(api_key=""),
            db=self.db,
            current_user=self.user,
        )
        self.db.expire_all()
        self.assertEqual(self.db.get(AIModel, 1).api_key, "original-key")

        main.update_model(
            1,
            main.schemas.ModelUpdate(api_key="replacement-key"),
            db=self.db,
            current_user=self.user,
        )
        self.db.expire_all()
        self.assertEqual(self.db.get(AIModel, 1).api_key, "replacement-key")


class PublicMcpTests(DatabaseTestCase):
    def test_public_list_and_detail_redact_credentials_without_changing_storage(self):
        config = json.dumps({"mcpServers": {"example": {
            "type": "http",
            "url": "https://alice:password-secret@example.com:8443/mcp?token=query-secret#fragment-secret",
            "headers": {"Authorization": "header-secret"},
            "env": {"API_KEY": "env-secret"},
            "command": "npx",
            "args": ["--token=arg-secret", "positional-secret"],
            "options": {"accessToken": "nested-secret"},
        }}})
        self.db.add_all([
            McpService(id=1, user_id=7, name="public", type="json", config=config, is_public=True),
            McpService(id=2, user_id=7, name="private", type="json", config=config, is_public=False),
        ])
        self.db.commit()
        listing = main.get_public_mcps(db=self.db)
        detail = main.get_public_mcp(1, db=self.db)
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["config"], detail["config"])
        self.assertNotIn("secret", detail["config"])
        redacted = json.loads(detail["config"])["mcpServers"]["example"]
        self.assertEqual(redacted["command"], "npx")
        self.assertEqual(redacted["type"], "http")
        url = urlsplit(redacted["url"])
        self.assertIsNone(url.username)
        self.assertEqual(url.netloc, "example.com:8443")
        self.assertEqual(url.path, "/mcp")
        self.assertNotEqual(parse_qs(url.query)["token"], ["query-secret"])
        self.assertEqual(url.fragment, "")
        self.assertEqual(self.db.get(McpService, 1).config, config)
        with self.assertRaises(HTTPException) as raised:
            main.get_public_mcp(2, db=self.db)
        self.assertEqual(raised.exception.status_code, 404)

    def test_custom_paths_inline_commands_and_invalid_urls_fail_closed(self):
        for url in ["https://example.com/path-secret", "https://[::1]:bad/mcp",
                    "file:///path-secret", {"token": "nested-secret"}, 123, None]:
            with self.subTest(url=url):
                result = main._redact_public_mcp_config(json.dumps({
                    "url": url, "command": "sh -c 'echo command-secret'",
                    "nested": [{"password": "value-secret"}],
                }))
                self.assertNotIn("secret", result)
        self.assertIsNone(main._redact_public_mcp_config("invalid json secret"))


class FailedBillingTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.add_model(1)
        self.db.add_all([
            Agent(id=1, user_id=7, name="assistant"),
            AgentSession(id=1, agent_id=1, user_id=7, model_id=1),
            AgentRun(id="run-1", agent_id=1, session_id=1, user_id=7,
                     status="failed", reserved_points=10, settlement_status="reserved"),
            CreditAccount(id=1, user_id=7, available_balance=90, reserved_balance=10),
            ModelPricingVersion(id=1, model_id=1, version=1, input_rate=2,
                                output_rate=5, rate_scale=1000),
            ModelRunCredential(id=1, token_hash=credit_billing.token_hash("ahr_test-token"),
                               run_id="run-1", user_id=7, model_id=1, pricing_version_id=1,
                               max_points=10, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)),
        ])
        self.db.commit()
        replacement = patch.object(credit_billing, "SessionLocal", self.factory)
        replacement.start()
        self.addCleanup(replacement.stop)

    def begin(self):
        return credit_billing.begin_gateway_request("ahr_test-token", b"{}")

    def settle(self):
        self.db.expire_all()
        credit_billing.settle_platform_run(self.db, self.db.get(AgentRun, "run-1"), "failed")

    def assert_balances(self, available, reserved):
        self.db.expire_all()
        account = self.db.get(CreditAccount, 1)
        self.assertEqual(account.available_balance, Decimal(available))
        self.assertEqual(account.reserved_balance, Decimal(reserved))

    def test_connection_failure_releases_reservation_once_even_after_pending_settlement(self):
        context = self.begin()
        self.settle()
        self.assertEqual(self.db.get(AgentRun, "run-1").settlement_status, "pending_reconciliation")
        credit_billing.abort_gateway_request(context)
        credit_billing.abort_gateway_request(context)
        self.settle()
        self.assert_balances("100", "0")
        self.assertEqual(self.db.query(ModelUsageEvent).count(), 1)
        self.assertEqual(self.db.query(CreditLedger).count(), 1)
        self.assertEqual(self.db.get(AgentRun, "run-1").settlement_status, "settled")

    def test_failure_after_success_refunds_only_unused_points(self):
        context = self.begin()
        credit_billing.finish_gateway_request(context, {"input_tokens": 1000}, {})
        credit_billing.abort_gateway_request(self.begin())
        self.settle()
        self.assert_balances("98", "0")
        self.assertEqual(self.db.get(AgentRun, "run-1").charged_points, Decimal("2"))
        self.assertEqual(self.db.query(ModelUsageEvent).count(), 2)

    def test_duplicate_completion_does_not_clear_a_later_in_flight_request(self):
        first = self.begin()
        credit_billing.abort_gateway_request(first)
        second = self.begin()
        credit_billing.abort_gateway_request(first)
        self.db.expire_all()
        self.assertTrue(self.db.get(ModelRunCredential, 1).request_in_flight)
        credit_billing.abort_gateway_request(second)
        self.settle()
        self.assert_balances("100", "0")

    def test_unknown_usage_remains_pending_until_usage_arrives(self):
        context = self.begin()
        credit_billing.abort_gateway_request(context, usage_unknown=True)
        self.settle()
        self.assert_balances("90", "10")
        self.assertEqual(self.db.get(AgentRun, "run-1").settlement_status, "pending_reconciliation")
        credit_billing.finish_gateway_request(context, {"input_tokens": 500}, {})
        self.assert_balances("99", "0")

    def test_reconciliation_releases_stale_terminal_reservation(self):
        run = self.db.get(AgentRun, "run-1")
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()

        settled = credit_billing.reconcile_pending_platform_runs(self.db, user_id=7)

        self.assertEqual(settled, 1)
        self.assert_balances("100", "0")
        self.assertEqual(self.db.get(AgentRun, "run-1").settlement_status, "settled")

    def test_provider_id_reuse_does_not_merge_distinct_requests(self):
        for _ in range(2):
            credit_billing.finish_gateway_request(
                self.begin(), {"input_tokens": 500}, {"provider_request_id": "same-upstream-id"},
            )
        self.settle()
        self.assert_balances("98", "0")
        self.assertEqual(self.db.query(ModelUsageEvent).count(), 2)

    def test_gateway_classifies_connection_and_response_failures(self):
        for error_type, unknown in [(httpx.ConnectError, False), (httpx.ConnectTimeout, False),
                                    (httpx.PoolTimeout, False), (httpx.ReadTimeout, True),
                                    (httpx.WriteError, True), (httpx.RemoteProtocolError, True)]:
            with self.subTest(error_type=error_type):
                context = self.begin()
                client = Mock()
                client.send = AsyncMock(side_effect=error_type("test failure"))
                client.aclose = AsyncMock()
                receive = AsyncMock(return_value={"type": "http.request", "body": b"{}"})
                request = Request({"type": "http", "headers": [(b"x-api-key", b"ahr_test-token")]}, receive)
                with patch.object(model_gateway, "begin_gateway_request", return_value=context), \
                     patch.object(model_gateway, "_validate_resolved_addresses", new=AsyncMock()), \
                     patch.object(model_gateway.httpx, "AsyncClient", return_value=client), \
                     patch.object(model_gateway, "abort_gateway_request") as abort:
                    response = asyncio.run(model_gateway.anthropic_messages(request))
                self.assertEqual(response.status_code, 502)
                abort.assert_called_once_with(context, usage_unknown=unknown)
                client.aclose.assert_awaited_once()
                credit_billing.abort_gateway_request(context)


class HistoricalModelTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(agent_routes, "check_stream_store", new=AsyncMock()))
        self.user = CurrentUser(user_id=7)
        new = self.add_model(1)
        old = self.add_model(2)
        self.add_model(3, is_enabled=False)
        self.add_model(4, is_deleted=True)
        self.add_model(5, scope="user", user_id=8)
        self.add_model(6)
        self.add_model(7)
        self.add_model(8, scope="user")
        self.agent = Agent(id=1, user_id=7, name="assistant", icon="H",
                           kind="personal_default", default_agent_user_id=7,
                           default_model_id=2, settings_version=1, models=[old])
        self.db.add(self.agent)
        self.db.add(PlatformAgentSettings(id=1, version=2, status="published", created_by=7,
                                         assistant_name="assistant", default_model_id=new.id))
        for model_id in range(2, 9):
            self.db.add(AgentSession(id=model_id, agent_id=1, user_id=8 if model_id == 7 else 7,
                                     model_id=model_id, is_deleted=model_id == 6))
        self.db.commit()
        workspace = SimpleNamespace(id=1, status="ready")
        for name, value in {
            "ensure_user_workspace": (workspace, None), "bind_agent_workspace": (workspace, None),
            "workspace_payload": {}, "_ensure_account": None, "_grant_claim": None,
            "_credit_response": dict(available_balance=10, reserved_balance=0, status="active", version=1,
                                     display_name="Credits", display_name_en="Credits", daily_claim_amount=0,
                                     today="2026-09-07", claimed_today=True, low_balance_threshold=0),
        }.items():
            replacement = patch.object(enterprise_routes, name, return_value=value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_new_default_preserves_accessible_models_and_can_resume(self):
        response = enterprise_routes.bootstrap_user(db=self.db, current_user=self.user)
        self.assertEqual(response.default_model_id, 1)
        self.assertEqual({model.id for model in self.agent.models}, {1, 2, 6, 7, 8})
        result = asyncio.run(agent_routes.send_message(
            1, AgentMessageRequest(session_id=2, model_id=2, content="continue"),
            db=self.db, current_user=self.user,
        ))
        self.assertEqual(result.media_type, "text/event-stream")

    def test_bootstrap_repairs_bindings_even_when_policy_version_already_matches(self):
        self.agent.settings_version = 2
        self.agent.default_model_id = 1
        self.agent.models = [self.db.get(AIModel, 1)]
        self.db.commit()
        for _ in range(2):
            enterprise_routes.bootstrap_user(db=self.db, current_user=self.user)
            self.assertEqual({model.id for model in self.agent.models}, {1, 2, 6, 7, 8})

    def test_new_enabled_models_are_available_without_republishing_settings(self):
        enterprise_routes.bootstrap_user(db=self.db, current_user=self.user)
        self.add_model(9)
        self.add_model(10, scope="user")
        self.db.commit()
        response = enterprise_routes.bootstrap_user(db=self.db, current_user=self.user)
        self.assertEqual(response.default_model_id, 1)
        self.assertEqual([item["id"] for item in response.assistant.models], [1, 2, 6, 7, 8, 9, 10])
        result = asyncio.run(agent_routes.send_message(
            1, AgentMessageRequest(model_id=9, content="hello"),
            db=self.db, current_user=self.user,
        ))
        self.assertEqual(result.media_type, "text/event-stream")
        self.db.get(AIModel, 9).is_enabled = False
        self.db.commit()
        response = enterprise_routes.bootstrap_user(db=self.db, current_user=self.user)
        self.assertNotIn(9, [item["id"] for item in response.assistant.models])

    def test_refresh_includes_new_own_models_without_bootstrap_and_excludes_secrets(self):
        self.add_model(10, scope="user", api_key="private-test-key", api_proxy_url="https://private.example/v1")
        self.add_model(11, scope="user", is_enabled=False)
        self.add_model(12, scope="user", is_deleted=True)
        self.add_model(13, scope="user", user_id=8)
        self.db.commit()
        response = agent_routes.list_agent_models(1, db=self.db, current_user=self.user)
        self.assertEqual([item["id"] for item in response["items"]], [1, 2, 6, 7, 8, 10])
        own = next(item for item in response["items"] if item["id"] == 10)
        self.assertEqual(own["scope"], "user")
        self.assertEqual(set(own), {"id", "name", "provider", "remarks", "scope", "api_protocol", "compatible_runtimes"})
        with self.assertRaises(HTTPException) as raised:
            agent_routes.list_agent_models(1, db=self.db, current_user=CurrentUser(user_id=8))
        self.assertEqual(raised.exception.status_code, 403)

    def test_workbench_and_expert_accept_unbound_own_model(self):
        self.add_model(10, scope="user")
        self.db.commit()
        self.assertNotIn(10, [model.id for model in self.agent.models])
        result = asyncio.run(agent_routes.send_message(
            1, AgentMessageRequest(model_id=10, content="hello"),
            db=self.db, current_user=self.user,
        ))
        self.assertEqual(result.media_type, "text/event-stream")
        agent = self.db.get(Agent, 1)
        agent.kind = "expert"
        self.db.commit()
        self.assertEqual([item["id"] for item in agent_routes.list_agent_models(
            1, db=self.db, current_user=self.user,
        )["items"]], [1, 2, 6, 7, 8, 10])
        result = asyncio.run(agent_routes.send_message(
            1, AgentMessageRequest(model_id=10, content="hello"),
            db=self.db, current_user=self.user,
        ))
        self.assertEqual(result.media_type, "text/event-stream")

    def test_workbench_rejects_disabled_deleted_foreign_and_incompatible_custom_models(self):
        self.add_model(10, scope="user", is_enabled=False)
        self.add_model(11, scope="user", is_deleted=True)
        self.add_model(12, scope="user", api_protocol="openai-completions")
        self.db.commit()
        for model_id, status in [(10, 400), (11, 404), (5, 404), (12, 400)]:
            with self.subTest(model_id=model_id), self.assertRaises(HTTPException) as raised:
                asyncio.run(agent_routes.send_message(
                    1, AgentMessageRequest(model_id=model_id, content="hello"),
                    db=self.db, current_user=self.user,
                ))
            self.assertEqual(raised.exception.status_code, status)

    def test_history_cannot_switch_model_or_open_another_users_session(self):
        enterprise_routes.bootstrap_user(db=self.db, current_user=self.user)
        for session_id, model_id, status in [(2, 1, 409), (7, 7, 404), (3, 3, 400), (5, 5, 404)]:
            with self.subTest(session_id=session_id):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(agent_routes.send_message(
                        1, AgentMessageRequest(session_id=session_id, model_id=model_id, content="continue"),
                        db=self.db, current_user=self.user,
                    ))
                self.assertEqual(raised.exception.status_code, status)


if __name__ == "__main__":
    unittest.main()
