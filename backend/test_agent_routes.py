from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import json
import asyncio
import pytest

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from agent_routes import (
    _agent_publication_errors,
    _to_response,
    _get_mcps_or_400,
    _get_skills_or_400,
    _migrate_web_session_runtime,
    _normalize_mcp_overrides,
    cancel_agent_run,
    create_conversation_share,
    delete_workspace_file,
    get_public_conversation_share,
    get_agent_runtime_status,
    get_agent_statistics,
    get_messages,
    preview_workspace_file,
    revoke_conversation_share,
    router,
    update_agent,
)
from agent_service import _agent_default_model_id
from auth import CurrentUser
from database import Base, settings
from models import Agent, AgentConversationShare, AgentMessage, AgentRun, AgentSession, AIModel, McpService, PlatformAgentSettings, RuntimeInstance, Skill, SkillRelease, SkillInstallation, ExpertSkillBinding, McpConnection, McpDefinition, McpRevision, ExpertMcpBinding
from schemas import AgentSessionMessagesResponse, AgentUpdate, PublicConversationShareResponse
from schemas import AgentMcpOverride


def _create_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
        Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_expert_response_does_not_restore_unbound_legacy_skill():
    db = _create_db()
    try:
        skill = Skill(id=1, user_id=7, name="Legacy skill", version="1", is_public=True)
        agent = Agent(id=9, user_id=7, name="Expert", kind="expert")
        agent.skills = [skill]
        agent.mcps = [McpService(id=2, user_id=7, name="Legacy MCP", type="http")]
        db.add_all([
            agent,
            SkillRelease(id=11, skill_id=1, version="1", status="published",
                         file_path="unused.zip", file_url="/releases/unused.zip"),
            SkillInstallation(id=21, user_id=7, scope_agent_id=9, workspace_id=9,
                              skill_id=1, release_id=11, status="active"),
            ExpertSkillBinding(id=31, agent_id=9, installation_id=21),
        ])
        db.commit()
        assert _to_response(agent, db).skill_ids == [1]
        db.query(ExpertSkillBinding).filter_by(agent_id=9).delete()
        db.commit()
        response = _to_response(agent, db)
        assert response.skill_ids == []
        assert response.skills == []
        assert response.mcp_ids == []
    finally:
        db.close()


def test_expert_response_includes_workspace_skills_only_for_author():
    db = _create_db()
    try:
        agent = Agent(id=9, user_id=7, name="Expert", kind="expert")
        db.add_all([
            agent,
            Skill(id=1, user_id=7, name="Unreleased skill", version="1", is_public=False),
            SkillRelease(id=11, skill_id=1, version="latest", status="workspace",
                         file_path="unused.zip", file_url="/releases/unused.zip"),
            SkillInstallation(id=21, user_id=7, scope_agent_id=9, workspace_id=9,
                              skill_id=1, release_id=11, status="active"),
            ExpertSkillBinding(id=31, agent_id=9, installation_id=21),
        ])
        db.commit()
        for viewer_id in (None, 7):
            response = _to_response(agent, db, viewer_id=viewer_id)
            assert response.skill_ids == [1]
            assert response.skill_installation_ids == [21]
            assert response.skills == [{"id": 1, "name": "Unreleased skill", "conversation_examples": []}]
        # Even a public skill's workspace files remain private to its author.
        db.get(Skill, 1).is_public = True
        db.commit()
        assert _to_response(agent, db, viewer_id=8).skills == []
        db.get(SkillRelease, 11).status = "revoked"
        db.commit()
        assert _to_response(agent, db, viewer_id=7).skills == []
    finally:
        db.close()


def test_inactive_mcp_binding_does_not_block_publication():
    db = _create_db()
    try:
        agent = Agent(id=9, user_id=7, name="Expert", kind="expert")
        db.add_all([
            agent,
            McpDefinition(id=11, owner_user_id=7, name="Private MCP", scope="user",
                          transport_type="http", status="published"),
            McpRevision(id=12, definition_id=11, version="1", status="published",
                        config_json="{}", content_sha256="test-revision", created_by=7),
            McpConnection(id=13, user_id=7, scope_agent_id=9, workspace_id=9,
                          definition_id=11, revision_id=12, name="Private MCP", status="active"),
            ExpertMcpBinding(id=14, agent_id=9, connection_id=13, status="disabled"),
        ])
        db.commit()
        assert _agent_publication_errors(db, agent) == []
        db.get(ExpertMcpBinding, 14).status = "active"
        db.commit()
        assert _agent_publication_errors(db, agent) == ["MCP 未公开: Private MCP"]
    finally:
        db.close()


@pytest.mark.parametrize('settlement_status,pricing_snapshot,charge,expected', [
    ('settled', None, '1.23', Decimal('1.23')),
    ('pending_reconciliation', '{"billing_mode":"realtime"}', '1.23', Decimal('1.23')),
    ('pending_reconciliation', '{"billing_mode":"realtime"}', '0', Decimal('0')),
    ('pending_reconciliation', None, '1.23', None),
    ('none', None, '0', None),
])
def test_get_messages_includes_session_metadata_and_preserves_items(
    settlement_status, pricing_snapshot, charge, expected,
):
    db = _create_db()
    try:
        db.add(Agent(
            id=9,
            user_id=7,
            name="Channel agent",
            is_deleted=False,
            is_public=False,
        ))
        db.add(AgentSession(
            id=101,
            agent_id=9,
            user_id=7,
            title="DingTalk ClawBot",
            source="dingtalk_clawbot",
            source_binding_id=55,
            message_count=2,
            is_deleted=False,
        ))
        db.add_all([
            AgentMessage(id=201, session_id=101, role="user", content="hello"),
            AgentMessage(id=202, session_id=101, role="assistant", content="world"),
            AgentRun(
                id="run-with-charge",
                agent_id=9,
                session_id=101,
                user_id=7,
                source="web",
                status="succeeded",
                assistant_message_id=202,
                charged_points=Decimal(charge),
                settlement_status=settlement_status,
                pricing_snapshot=pricing_snapshot,
            ),
        ])
        db.commit()

        result = get_messages(
            agent_id=9,
            session_id=101,
            before_id=None,
            limit=100,
            db=db,
            current_user=CurrentUser(7),
        )
        payload = AgentSessionMessagesResponse.model_validate(result).model_dump()

        assert payload["session"]["id"] == 101
        assert payload["session"]["source"] == "dingtalk_clawbot"
        assert payload["session"]["source_binding_id"] == 55
        assert [
            (item["id"], item["role"], item["content"])
            for item in payload["items"]
        ] == [
            (201, "user", "hello"),
            (202, "assistant", "world"),
        ]
        assert payload["items"][0]["charged_points"] is None
        assert payload["items"][1]["charged_points"] == expected
        assert payload["items"][1]["run_id"] == "run-with-charge"
    finally:
        db.close()


def test_migrate_web_session_runtime_clears_previous_runtime_identity():
    session = AgentSession(
        source="web",
        runtime_type="previous_runtime",
        runtime_session_id="previous-session",
        claude_session_id="legacy-session",
        runtime_instance_id=42,
        runtime_state="active",
    )

    changed = _migrate_web_session_runtime(session, "claude_code")

    assert changed is True
    assert session.runtime_type == "claude_code"
    assert session.runtime_session_id is None
    assert session.claude_session_id is None
    assert session.runtime_instance_id is None
    assert session.runtime_state == "active"


def test_migrate_web_session_runtime_does_not_change_channel_session():
    session = AgentSession(
        source="dingtalk_clawbot",
        runtime_type="previous_runtime",
        runtime_session_id="channel-session",
        runtime_instance_id=42,
    )

    changed = _migrate_web_session_runtime(session, "claude_code")

    assert changed is False
    assert session.runtime_type == "previous_runtime"
    assert session.runtime_session_id == "channel-session"
    assert session.runtime_instance_id == 42


def test_get_messages_pages_backward_without_reordering_items():
    db = _create_db()
    try:
        db.add(Agent(id=10, user_id=7, name="Paged agent", is_deleted=False, is_public=False))
        db.add(AgentSession(id=102, agent_id=10, user_id=7, is_deleted=False))
        db.add_all([
            AgentMessage(id=message_id, session_id=102, role="user", content=str(message_id))
            for message_id in range(301, 306)
        ])
        db.commit()

        latest = get_messages(10, 102, None, 2, db, CurrentUser(7))
        middle = get_messages(10, 102, 304, 2, db, CurrentUser(7))
        oldest = get_messages(10, 102, 302, 2, db, CurrentUser(7))

        assert [item["id"] for item in latest["items"]] == [304, 305]
        assert latest["has_more"] is True
        assert [item["id"] for item in middle["items"]] == [302, 303]
        assert middle["has_more"] is True
        assert [item["id"] for item in oldest["items"]] == [301]
        assert oldest["has_more"] is False
    finally:
        db.close()


def test_get_messages_route_declares_metadata_response_model():
    route = next(
        route
        for route in router.routes
        if route.path == "/api/agents/{agent_id}/sessions/{session_id}/messages"
        and "GET" in route.methods
    )

    assert route.response_model is AgentSessionMessagesResponse


def test_agent_statistics_uses_existing_run_metrics_and_owner_scope():
    db = _create_db()
    try:
        now = datetime.now(timezone.utc)
        db.add_all([
            Agent(id=21, user_id=7, name="Stats agent", is_deleted=False, is_public=False),
            AgentSession(id=211, agent_id=21, user_id=7, is_deleted=False),
            PlatformAgentSettings(version=1, status="published", created_by=7, credit_display_name="趣点"),
            AgentRun(
                id="run-success",
                agent_id=21,
                session_id=211,
                user_id=7,
                source="web",
                status="succeeded",
                duration_ms=1000,
                input_tokens=20,
                output_tokens=10,
                cache_read_tokens=5,
                cache_creation_tokens=2,
                total_tokens=30,
                charged_points=Decimal("1.23"),
                created_at=now,
            ),
            AgentRun(
                id="run-failed",
                agent_id=21,
                session_id=211,
                user_id=7,
                source="weixin_clawbot",
                status="failed",
                duration_ms=3000,
                input_tokens=8,
                output_tokens=2,
                cache_read_tokens=1,
                total_tokens=10,
                error_code="runtime_error",
                error_message="runtime unavailable",
                created_at=now,
            ),
            AgentRun(
                id="run-cancelled",
                agent_id=21,
                session_id=211,
                user_id=7,
                source="web",
                status="cancelled",
                duration_ms=500,
                created_at=now,
            ),
        ])
        db.commit()

        result = get_agent_statistics(21, 7, db, CurrentUser(7))

        assert result["credit_display_name"] == "趣点"
        assert result["summary"] == {
            "total_runs": 3,
            "succeeded_runs": 1,
            "failed_runs": 1,
            "cancelled_runs": 1,
            "active_runs": 0,
            "abnormal_runs": 0,
            "success_rate": 50.0,
            "failure_rate": 50.0,
            "median_duration_ms": 2000,
            "p95_duration_ms": 3000,
            "input_tokens": 28,
            "output_tokens": 12,
            "cache_read_tokens": 6,
            "cache_creation_tokens": 2,
            "total_tokens": 40,
            "average_tokens_per_run": 13,
            "charged_points": Decimal("1.23"),
        }
        assert result["errors"][0]["error_code"] == "runtime_error"
        assert result["recent_failures"][0]["run_id"] == "run-failed"
        assert {item["source"] for item in result["sources"]} == {"web", "weixin_clawbot"}
        assert sum(item["total_runs"] for item in result["trend"]) == 3
        assert sum(item["total_tokens"] for item in result["trend"]) == 40
        assert sum(item["charged_points"] for item in result["trend"]) == Decimal("1.23")
        assert {item["source"]: item["charged_points"] for item in result["sources"]} == {
            "web": Decimal("1.23"), "weixin_clawbot": Decimal("0.00"),
        }
        assert sum(item["charged_points"] == 0 for item in result["trend"]) == 6
        from schemas import AgentStatisticsResponse
        validated = AgentStatisticsResponse.model_validate(result)
        assert sum(item.charged_points for item in validated.trend) == Decimal("1.23")
        assert sum(item.charged_points for item in validated.sources) == Decimal("1.23")

        today_result = get_agent_statistics(21, 1, db, CurrentUser(7))
        assert len(today_result["trend"]) == 1
        assert today_result["trend"][0]["charged_points"] == Decimal("1.23")
        assert today_result["summary"]["total_runs"] == 3
    finally:
        db.close()


def test_agent_default_model_falls_back_to_runtime_compatible_catalog_entry():
    db = _create_db()
    try:
        db.add_all([
            AIModel(
                id=501,
                user_id=7,
                name="OpenAI first",
                provider="openai",
                scope="platform",
                api_protocol="openai-completions",
                is_enabled=True,
                is_deleted=False,
            ),
            AIModel(
                id=502,
                user_id=7,
                name="Claude fallback",
                provider="anthropic",
                scope="platform",
                api_protocol="anthropic-messages",
                is_enabled=True,
                is_deleted=False,
            ),
        ])
        agent = Agent(
            id=50,
            user_id=7,
            name="Expert",
            runtime_type="claude_code",
            default_model_id=501,
            is_deleted=False,
        )
        db.add(agent)
        db.commit()

        assert _agent_default_model_id(db, agent, 7) == 502
    finally:
        db.close()


def test_agent_statistics_rejects_cross_user_access():
    db = _create_db()
    try:
        db.add(Agent(id=22, user_id=7, name="Private stats", is_deleted=False, is_public=False))
        db.commit()

        try:
            get_agent_statistics(22, 7, db, CurrentUser(8))
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 403
        else:
            raise AssertionError("cross-user statistics must be rejected")
    finally:
        db.close()


def test_conversation_share_is_public_until_owner_revokes_it():
    db = _create_db()
    try:
        db.add(Agent(id=41, user_id=7, name="Shared agent", is_deleted=False, is_public=False))
        db.add(AgentSession(
            id=42,
            agent_id=41,
            user_id=7,
            title="Shared conversation",
            is_deleted=False,
        ))
        db.add_all([
            AgentMessage(id=401, session_id=42, role="user", content="input"),
            AgentMessage(
                id=402,
                session_id=42,
                role="assistant",
                content='{"blocks":[{"type":"thinking","content":"reason"},'
                        '{"type":"tool_use","name":"Lookup","input":{"id":1}},'
                        '{"type":"tool_result","content":"output"}],'
                        '"usage":{"input_tokens":21,"output_tokens":13,"total_tokens":34}}',
            ),
        ])
        db.commit()

        share = create_conversation_share(41, 42, db, CurrentUser(7))
        public_result = get_public_conversation_share(share.token, None, 100, db)
        payload = PublicConversationShareResponse.model_validate(public_result).model_dump()

        assert payload["title"] == "Shared conversation"
        assert payload["agent_name"] == "Shared agent"
        assert [(item["role"], item["content"]) for item in payload["items"]] == [
            ("user", "input"),
            ("assistant", db.query(AgentMessage).filter(AgentMessage.id == 402).one().content),
        ]
        assistant_payload = json.loads(payload["items"][1]["content"])
        assert assistant_payload["usage"]["total_tokens"] == 34

        revoke_conversation_share(41, 42, db, CurrentUser(7))
        assert db.query(AgentConversationShare).filter_by(token=share.token).one().is_active is False
        try:
            get_public_conversation_share(share.token, None, 100, db)
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 404
        else:
            raise AssertionError("revoked share must no longer be public")
    finally:
        db.close()


def test_conversation_share_cannot_be_created_for_another_users_session():
    db = _create_db()
    try:
        db.add(Agent(id=51, user_id=7, name="Owner agent", is_deleted=False, is_public=False))
        db.add(AgentSession(id=52, agent_id=51, user_id=7, is_deleted=False))
        db.commit()

        try:
            create_conversation_share(51, 52, db, CurrentUser(8))
        except Exception as exc:
            assert getattr(exc, "status_code", None) in {403, 404}
        else:
            raise AssertionError("cross-user conversation share must be rejected")
    finally:
        db.close()


def test_claude_runtime_status_does_not_wait_for_retired_instance():
    db = _create_db()
    try:
        db.add(Agent(
            id=31,
            user_id=7,
            name="Claude agent",
            runtime_type="claude_code",
            is_deleted=False,
            is_public=False,
        ))
        db.add(RuntimeInstance(
            id=32,
            agent_id=31,
            user_id=7,
            runtime_type="previous_runtime",
            deployment_mode="managed",
            external_agent_id="aihub-31",
            status="updating",
        ))
        db.commit()

        result = get_agent_runtime_status(31, db, CurrentUser(7))
        payload = result.model_dump()
        assert payload["status"] == "not_applicable"
        assert payload["readiness_message"] is None
    finally:
        db.close()


def test_agent_bindings_allow_owned_and_public_resources_only():
    db = _create_db()
    try:
        db.add_all([
            Skill(id=1, user_id=7, name="owned", version="1.0.0", is_public=False),
            Skill(id=2, user_id=8, name="public", version="1.0.0", is_public=True),
            Skill(id=3, user_id=8, name="private", version="1.0.0", is_public=False),
            McpService(id=11, user_id=7, name="owned", type="http", is_public=False),
            McpService(id=12, user_id=8, name="public", type="http", is_public=True),
            McpService(id=13, user_id=8, name="private", type="http", is_public=False),
        ])
        db.commit()

        assert {item.id for item in _get_skills_or_400(db, [1, 2], CurrentUser(7))} == {1, 2}
        assert {item.id for item in _get_mcps_or_400(db, [11, 12], CurrentUser(7))} == {11, 12}

        for resolver, resource_id in (
            (_get_skills_or_400, 3),
            (_get_mcps_or_400, 13),
        ):
            try:
                resolver(db, [resource_id], CurrentUser(7))
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 404
            else:
                raise AssertionError("private cross-user resource must be rejected")
    finally:
        db.close()


def test_cancel_agent_run_marks_persisted_run_and_requests_local_cancel():
    db = _create_db()
    try:
        db.add(Agent(id=21, user_id=7, name="agent", is_deleted=False, is_public=False))
        db.add(AgentSession(id=22, agent_id=21, user_id=7, is_deleted=False))
        db.add(AgentRun(
            id="run-cancel",
            agent_id=21,
            session_id=22,
            user_id=7,
            source="web",
            status="running",
        ))
        db.commit()

        with patch("agent_routes.cancel_web_run", return_value=True):
            result = cancel_agent_run(21, "run-cancel", db, CurrentUser(7))

        run = db.query(AgentRun).filter(AgentRun.id == "run-cancel").first()
        assert run.cancel_requested is True
        assert result["cancel_requested"] is True
        assert result["cancelled_in_process"] is True
    finally:
        db.close()


def test_update_agent_with_resources_defers_container_preparation():
    db = _create_db()
    try:
        model = AIModel(
            id=71,
            user_id=7,
            name="claude-test",
            provider="Anthropic",
            api_protocol="anthropic-messages",
            is_deleted=False,
        )
        agent = Agent(
            id=72,
            user_id=7,
            name="before",
            default_model_id=71,
            runtime_type="claude_code",
            is_deleted=False,
            is_public=False,
        )
        agent.models = [model]
        agent.skills = [Skill(id=73, user_id=7, name="Existing skill", version="1", is_deleted=False)]
        db.add(agent)
        db.add(agent.skills[0])
        db.commit()

        # The real container provider rejects prepare() without a Run. Saving
        # an agent with existing skills must never enter that lifecycle.
        from sandbox.container import ContainerSandbox
        with patch("agent_routes.get_workspace_provider", return_value=ContainerSandbox()) as factory:
            result = update_agent(72, AgentUpdate(name="after"), db, CurrentUser(7))

        factory.assert_not_called()
        assert result.name == "after"
        db.expire_all()
        assert db.query(Agent).filter(Agent.id == 72).one().name == "after"
    finally:
        db.close()


def test_update_agent_skips_workspace_sync_without_resources():
    db = _create_db()
    try:
        agent = Agent(
            id=72,
            user_id=7,
            name="before",
            is_deleted=False,
            is_public=False,
        )
        db.add(agent)
        db.commit()

        with patch("agent_routes.get_workspace_provider") as get_provider:
            result = update_agent(72, AgentUpdate(name="after"), db, CurrentUser(7))

        assert result.name == "after"
        get_provider.assert_not_called()
    finally:
        db.close()




def test_mcp_overrides_are_limited_to_bound_transport_fields():
    stdio = McpService(id=11, user_id=7, name="stdio", type="stdio")
    http = McpService(id=12, user_id=7, name="http", type="streamable_http")
    result = _normalize_mcp_overrides([
        AgentMcpOverride(mcp_id=11, env={"TOKEN": "secret"}),
        AgentMcpOverride(mcp_id=12, headers={"Authorization": "Bearer secret"}),
    ], [stdio, http], "claude_code")
    assert result == [
        {"mcp_id": 11, "env": {"TOKEN": "secret"}, "headers": {}},
        {"mcp_id": 12, "env": {}, "headers": {"Authorization": "Bearer secret"}},
    ]

    try:
        _normalize_mcp_overrides(
            [AgentMcpOverride(mcp_id=12, env={"TOKEN": "bad"})],
            [http],
            "claude_code",
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("HTTP MCP must reject env overrides")


@patch("agent_routes.bind_agent_workspace", return_value=(SimpleNamespace(id=73), None))
def test_workspace_text_preview_enforces_size_and_line_limits(_bind_workspace):
    db = _create_db()
    try:
        db.add(Agent(id=73, user_id=7, name="Preview agent", is_deleted=False, is_public=False))
        db.commit()

        class PreviewProvider:
            def __init__(self, content):
                self.content = content

            def read_file(self, agent_id, path):
                return self.content, path.rsplit("/", 1)[-1]

            def read_file_limited(self, agent_id, path, max_bytes):
                return self.content[:max_bytes + 1], path.rsplit("/", 1)[-1]

        with patch("agent_routes.get_workspace_provider", return_value=PreviewProvider(b"one\ntwo\n")):
            result = preview_workspace_file(73, "notes.md", db, CurrentUser(7))
        assert result["content"] == "one\ntwo\n"
        assert result["line_count"] == 2

        oversized = b"x" * (1024 * 1024 + 1)
        with patch("agent_routes.get_workspace_provider", return_value=PreviewProvider(oversized)):
            try:
                preview_workspace_file(73, "large.txt", db, CurrentUser(7))
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 413
            else:
                raise AssertionError("oversized text preview must be rejected")

        too_many_lines = ("line\n" * 1001).encode()
        with patch("agent_routes.get_workspace_provider", return_value=PreviewProvider(too_many_lines)):
            try:
                preview_workspace_file(73, "long.log", db, CurrentUser(7))
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 413
            else:
                raise AssertionError("text preview over 1000 lines must be rejected")

        html_content = ("<html>\n" + "<p>generated</p>\n" * 1200 + "</html>").encode()
        with patch("agent_routes.get_workspace_provider", return_value=PreviewProvider(html_content)):
            result = preview_workspace_file(73, "output/generated.html", db, CurrentUser(7))
        assert result["content"] == html_content.decode()
        assert result["line_count"] == 1202

        large_html_content = b"<html>\n" + b"<p>generated</p>\n" * 70000 + b"</html>"
        assert len(large_html_content) > 1024 * 1024
        for path in ("output/large.html", "output/large.htm", "output/large.HTML", "output/large.HTM"):
            with patch("agent_routes.get_workspace_provider", return_value=PreviewProvider(large_html_content)):
                result = preview_workspace_file(73, path, db, CurrentUser(7))
            assert result["content"] == large_html_content.decode()
            assert result["size"] == len(large_html_content)
            assert result["line_count"] == 70002
    finally:
        db.close()


@patch("agent_routes.bind_agent_workspace", return_value=(SimpleNamespace(id=74), None))
def test_workspace_delete_protects_managed_directories_and_deletes_user_directories(_bind_workspace):
    db = _create_db()
    try:
        db.add(Agent(
            id=74,
            user_id=7,
            name="Delete agent",
            runtime_type="claude_code",
            is_deleted=False,
            is_public=False,
        ))
        db.commit()

        class DeleteProvider:
            def __init__(self):
                self.deleted = []

            def delete_path(self, workspace, path):
                self.deleted.append((workspace.id, path))

        provider = DeleteProvider()
        with patch("agent_routes.get_workspace_provider", return_value=provider):
            for protected_path in (".claude/archive", "reports/../.claude/skills/weather"):
                try:
                    asyncio.run(delete_workspace_file(74, protected_path, db, CurrentUser(7)))
                except Exception as exc:
                    assert getattr(exc, "status_code", None) == 403
                else:
                    raise AssertionError("managed Claude directories must be protected")

            try:
                asyncio.run(delete_workspace_file(74, "/memory", db, CurrentUser(7)))
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 400
            else:
                raise AssertionError("absolute workspace paths must be rejected")

            from agent_execution_lease import acquire_agent_execution_lease
            factory = sessionmaker(bind=db.get_bind())
            from models import UserWorkspace
            db.add(UserWorkspace(id=74, user_id=7, workspace_key="delete-test"))
            db.commit()
            async def acquire(**kwargs):
                return await acquire_agent_execution_lease(**kwargs, session_factory=factory)
            with patch("agent_routes.acquire_agent_execution_lease", acquire):
                result = asyncio.run(delete_workspace_file(74, "reports/archive", db, CurrentUser(7)))

        assert provider.deleted == [(74, "reports/archive")]
        assert result["message"] == "工作区内容已删除"
    finally:
        db.close()


if __name__ == "__main__":
    test_expert_response_does_not_restore_unbound_legacy_skill()
    test_inactive_mcp_binding_does_not_block_publication()
    test_get_messages_includes_session_metadata_and_preserves_items('settled', None, '1.23', Decimal('1.23'))
    test_get_messages_pages_backward_without_reordering_items()
    test_get_messages_route_declares_metadata_response_model()
    test_agent_statistics_uses_existing_run_metrics_and_owner_scope()
    test_agent_statistics_rejects_cross_user_access()
    test_conversation_share_is_public_until_owner_revokes_it()
    test_conversation_share_cannot_be_created_for_another_users_session()
    test_claude_runtime_status_does_not_wait_for_retired_instance()
    test_agent_bindings_allow_owned_and_public_resources_only()
    test_cancel_agent_run_marks_persisted_run_and_requests_local_cancel()
    test_update_agent_rolls_back_when_workspace_sync_fails()
    test_mcp_overrides_are_limited_to_bound_transport_fields()
    test_workspace_text_preview_enforces_size_and_line_limits()
    test_workspace_delete_protects_managed_directories_and_deletes_user_directories()
    print("agent route tests passed")
