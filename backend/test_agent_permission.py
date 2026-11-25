import asyncio
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agent_permission
from agent_permission import (
    claim_pending_permission_events,
    permission_decide,
    permission_request,
    user_decide,
)
from auth import CurrentUser
from database import Base
from models import Agent, AgentPermissionRequest, AgentRun, AgentSession
from schemas import PermissionDecideRequest, PermissionRequestInternal


def _factory(db_path=None):
    engine = create_engine(
        f"sqlite:///{db_path}" if db_path else "sqlite://",
        connect_args={"check_same_thread": False},
        **({} if db_path else {"poolclass": StaticPool}),
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    db.add(Agent(id=1, user_id=7, name="agent", is_deleted=False, is_public=False))
    db.add(AgentSession(id=2, agent_id=1, user_id=7, is_deleted=False))
    db.add(AgentRun(
        id="run-1",
        agent_id=1,
        session_id=2,
        user_id=7,
        source="web",
        status="running",
        cancel_requested=False,
    ))
    db.commit()
    db.close()
    return factory


def test_permission_decision_survives_different_sessions():
    async def scenario():
        factory = _factory()
        with patch.object(agent_permission, "SessionLocal", factory):
            created = await permission_request(PermissionRequestInternal(
                run_id="run-1",
                req_id="req-1",
                tool_name="Bash",
                tool_input={"command": "echo ok"},
            ))
            assert created["ok"] is True

            events = claim_pending_permission_events("run-1")
            assert [event["req_id"] for event in events] == ["req-1"]
            assert claim_pending_permission_events("run-1") == []

            request_db = factory()
            decided = await user_decide(
                1,
                PermissionDecideRequest(
                    run_id="run-1",
                    req_id="req-1",
                    decision="allow",
                    remember=True,
                ),
                request_db,
                CurrentUser(7),
            )
            request_db.close()
            assert decided["ok"] is True

            result = await permission_decide("run-1", "req-1")
            assert result == {"decision": "allow", "reason": "", "remembered": True}

            remembered = await permission_request(PermissionRequestInternal(
                run_id="run-1",
                req_id="req-2",
                tool_name="Bash",
                tool_input={"command": "echo again"},
            ))
            assert remembered == {"ok": True, "remembered": True}
            assert await permission_decide("run-1", "req-2") == {
                "decision": "allow",
                "reason": "",
                "remembered": True,
            }

    asyncio.run(scenario())


def test_permission_decision_requires_run_owner():
    async def scenario():
        factory = _factory()
        with patch.object(agent_permission, "SessionLocal", factory):
            await permission_request(PermissionRequestInternal(
                run_id="run-1",
                req_id="req-owner",
                tool_name="Read",
                tool_input={"file_path": "a.txt"},
            ))
            db = factory()
            body = PermissionDecideRequest(
                run_id="run-1",
                req_id="req-owner",
                decision="allow",
            )
            denied = await user_decide(1, body, db, CurrentUser(8))
            assert denied["ok"] is False
            request = db.query(AgentPermissionRequest).filter_by(req_id="req-owner").one()
            assert request.status == "pending"
            db.close()

    asyncio.run(scenario())


def test_permission_decide_retries_transient_database_error():
    expected = {"decision": "allow", "reason": "", "remembered": False}
    with patch(
        "agent_permission._read_permission_decision",
        side_effect=[RuntimeError("db unavailable"), expected],
    ):
        result = asyncio.run(permission_decide("r" * 32, "req-retry"))
    assert result == expected


def test_expired_request_cannot_be_approved():
    async def scenario():
        factory = _factory()
        with patch.object(agent_permission, "SessionLocal", factory):
            await permission_request(PermissionRequestInternal(
                run_id="run-1", req_id="expired", tool_name="Write",
            ))
            db = factory()
            request = db.query(AgentPermissionRequest).filter_by(req_id="expired").one()
            request.expires_at = agent_permission.utcnow() - timedelta(seconds=1)
            db.commit()
            result = await user_decide(1, PermissionDecideRequest(
                run_id="run-1", req_id="expired", decision="allow",
            ), db, CurrentUser(7))
            assert not result["ok"]
            assert request.decision == "deny"
            db.close()
            assert (await permission_decide("run-1", "expired"))["decision"] == "deny"
    asyncio.run(scenario())


def test_cancellation_overrides_an_existing_allow():
    async def scenario():
        factory = _factory()
        with patch.object(agent_permission, "SessionLocal", factory):
            await permission_request(PermissionRequestInternal(
                run_id="run-1", req_id="cancelled", tool_name="Write",
            ))
            db = factory()
            result = await user_decide(1, PermissionDecideRequest(
                run_id="run-1", req_id="cancelled", decision="allow",
            ), db, CurrentUser(7))
            assert result["ok"]
            db.query(AgentRun).filter_by(id="run-1").one().cancel_requested = True
            db.commit()
            db.close()
            assert (await permission_decide("run-1", "cancelled"))["decision"] == "deny"
    asyncio.run(scenario())


def test_repeated_decision_is_idempotent_and_conflicting_decision_is_rejected():
    async def scenario():
        factory = _factory()
        with patch.object(agent_permission, "SessionLocal", factory):
            await permission_request(PermissionRequestInternal(
                run_id="run-1", req_id="repeated", tool_name="Write",
            ))
            body = PermissionDecideRequest(
                run_id="run-1", req_id="repeated", decision="allow", remember=True,
            )
            with factory() as db:
                assert (await user_decide(1, body, db, CurrentUser(7)))["ok"]
            with factory() as db:
                assert await user_decide(1, body, db, CurrentUser(7)) == {"ok": True, "duplicate": True}
            with factory() as db:
                conflicting = await user_decide(1, body.model_copy(update={"decision": "deny"}), db, CurrentUser(7))
                assert conflicting["code"] == "already_processed"
                assert conflicting["resolved"] and not conflicting["ok"]
                request = db.query(AgentPermissionRequest).filter_by(req_id="repeated").one()
                assert request.decision == "allow" and request.remember
            with factory() as db:
                # Terminal responses must not reveal another user's decisions.
                denied = await user_decide(1, body, db, CurrentUser(8))
                assert not denied["ok"] and "resolved" not in denied
    asyncio.run(scenario())


def test_expired_cancelled_and_missing_requests_report_terminal_status():
    async def scenario():
        factory = _factory()
        with patch.object(agent_permission, "SessionLocal", factory):
            await permission_request(PermissionRequestInternal(
                run_id="run-1", req_id="terminal", tool_name="Write",
            ))
            body = PermissionDecideRequest(run_id="run-1", req_id="terminal", decision="allow")
            with factory() as db:
                request = db.query(AgentPermissionRequest).filter_by(req_id="terminal").one()
                request.expires_at = agent_permission.utcnow() - timedelta(seconds=1)
                db.commit()
                for _ in range(2):
                    result = await user_decide(1, body, db, CurrentUser(7))
                    assert result["code"] == "expired" and result["resolved"] and not result["ok"]
                assert request.decision == "deny"
                result = await user_decide(1, body.model_copy(update={"req_id": "missing"}), db, CurrentUser(7))
                assert result["code"] == "not_found" and result["resolved"]
            await permission_request(PermissionRequestInternal(
                run_id="run-1", req_id="cancelled-pending", tool_name="Write",
            ))
            with factory() as db:
                db.query(AgentRun).filter_by(id="run-1").one().cancel_requested = True
                db.commit()
                result = await user_decide(1, body.model_copy(update={"req_id": "cancelled-pending"}), db, CurrentUser(7))
                assert result["code"] == "run_ended" and result["resolved"] and not result["ok"]
                assert db.query(AgentPermissionRequest).filter_by(req_id="cancelled-pending").one().decision is None
    asyncio.run(scenario())


if __name__ == "__main__":
    test_permission_decision_survives_different_sessions()
    test_permission_decision_requires_run_owner()
    test_permission_decide_retries_transient_database_error()
    print("agent permission tests passed")
