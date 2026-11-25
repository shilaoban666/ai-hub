import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agent_execution_lease as leases
from agent_execution_lease import acquire_agent_execution_lease, utcnow
from database import Base
from models import Agent, WorkspaceExecutionLease, AgentRun, AgentSession, UserWorkspace, PlatformAgentSettings


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    db.add(Agent(id=1, user_id=7, name="lease-test", is_deleted=False, is_public=False))
    db.add(AgentSession(id=10, agent_id=1, user_id=7, is_deleted=False))
    db.add(UserWorkspace(id=1, user_id=7, workspace_key="lease-test"))
    db.commit()
    db.close()
    return factory


def test_agent_execution_lease_serializes_waiters():
    async def scenario():
        factory = _session_factory()
        first = await acquire_agent_execution_lease(
            workspace_id=1,
            run_id="a" * 32,
            session_factory=factory,
            lease_seconds=5,
            poll_seconds=0.02,
        )
        async with first:
            assert await first.is_owned()
            waiting = asyncio.create_task(acquire_agent_execution_lease(
                workspace_id=1,
                run_id="b" * 32,
                session_factory=factory,
                lease_seconds=5,
                poll_seconds=0.02,
            ))
            await asyncio.sleep(0.08)
            assert not waiting.done()

        second = await asyncio.wait_for(waiting, timeout=1)
        async with second:
            assert second.fencing_token == first.fencing_token + 1
            assert await second.is_owned()

    asyncio.run(scenario())


def test_expired_lease_takeover_is_fenced_from_old_release():
    async def scenario():
        factory = _session_factory()
        first = await acquire_agent_execution_lease(
            workspace_id=1,
            run_id="c" * 32,
            session_factory=factory,
            lease_seconds=5,
            poll_seconds=0.02,
        )
        db = factory()
        db.add(AgentRun(
            id="c" * 32,
            agent_id=1,
            session_id=10,
            user_id=7,
            source="web",
            status="running",
        ))
        db.commit()
        db.close()
        async with first:
            db = factory()
            row = db.query(WorkspaceExecutionLease).filter_by(workspace_id=1).one()
            row.lease_until = utcnow() - timedelta(seconds=1)
            db.commit()
            db.close()

            second = await acquire_agent_execution_lease(
                workspace_id=1,
                run_id="d" * 32,
                session_factory=factory,
                lease_seconds=5,
                poll_seconds=0.02,
            )
            assert second.fencing_token == first.fencing_token + 1

            db = factory()
            stale_run = db.query(AgentRun).filter_by(id="c" * 32).one()
            assert stale_run.status == "unknown"
            assert stale_run.error_code == "lease_expired"
            assert stale_run.finished_at is not None
            db.close()

        db = factory()
        row = db.query(WorkspaceExecutionLease).filter_by(workspace_id=1).one()
        assert row.run_id == "d" * 32
        assert row.fencing_token == second.fencing_token
        db.close()
        async with second:
            assert await second.is_owned()

    asyncio.run(scenario())


@pytest.mark.parametrize("existing_idle", [False, True])
@pytest.mark.parametrize("waiting_query", ["active", "target"])
def test_acquisition_grants_full_lease_after_lock_wait(existing_idle, waiting_query):
    factory = _session_factory()
    engine = factory.kw["bind"]
    clock = [datetime(2026, 10, 2, tzinfo=timezone.utc)]
    try:
        with factory() as db:
            db.add(UserWorkspace(id=2, user_id=7, agent_id=1, workspace_key="second"))
            db.add(PlatformAgentSettings(
                id=1, version=1, status="published", created_by=7, max_concurrent_runs=2,
            ))
            db.add(WorkspaceExecutionLease(
                workspace_id=1, run_id="existing", owner_id="existing-owner",
                fencing_token=1, lease_until=clock[0] + timedelta(seconds=120),
                heartbeat_at=clock[0],
            ))
            if existing_idle:
                db.add(WorkspaceExecutionLease(
                    workspace_id=2, run_id=None, owner_id=None, fencing_token=4,
                    lease_until=clock[0] - timedelta(seconds=1), heartbeat_at=clock[0],
                ))
            db.commit()

        advanced = []
        def advance_after_lock_read(conn, cursor, statement, parameters, context, executemany):
            if advanced or not statement.startswith("SELECT") or "FROM workspace_execution_leases" not in statement:
                return
            is_active_query = "JOIN user_workspaces" in statement
            if is_active_query == (waiting_query == "active"):
                # Model time spent waiting; SQLite itself does not provide MySQL row locks.
                clock[0] += timedelta(seconds=45)
                advanced.append(True)

        event.listen(engine, "after_cursor_execute", advance_after_lock_read)
        with patch.object(leases, "utcnow", side_effect=lambda: clock[0]):
            token = leases._try_acquire(
                workspace_id=2, run_id="new-run", owner_id="new-owner",
                lease_seconds=30, session_factory=factory,
            )
            assert advanced
            assert token == (5 if existing_idle else 1)
            with factory() as db:
                row = db.get(WorkspaceExecutionLease, 2)
                assert row.heartbeat_at.replace(tzinfo=timezone.utc) == clock[0]
                assert row.lease_until.replace(tzinfo=timezone.utc) == clock[0] + timedelta(seconds=30)
            handle = leases.AgentExecutionLeaseHandle(
                2, "new-run", "new-owner", token, 30, session_factory=factory,
            )
            assert handle._is_owned()
    finally:
        engine.dispose()


if __name__ == "__main__":
    test_agent_execution_lease_serializes_waiters()
    test_expired_lease_takeover_is_fenced_from_old_release()
    print("agent execution lease tests passed")
