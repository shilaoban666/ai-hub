import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import agent_service
from agent_service import (
    AgentRunResult,
    _cancel_queued_web_run,
    _finalize_unresolved_web_run,
    _monitor_web_run_controls,
    _queue_web_run,
    _queued_web_run_is_active,
    _web_run_cancel_requested,
    run_agent_chat,
)
from database import Base
from models import Agent, AgentRun


def _factory(path=None):
    engine = create_engine(
        f"sqlite:///{path}" if path else "sqlite://",
        connect_args={"check_same_thread": False},
        **({} if path else {"poolclass": StaticPool}),
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    db.add(Agent(
        id=1,
        user_id=7,
        name="agent",
        runtime_type="claude_code",
        timeout_seconds=60,
        is_deleted=False,
        is_public=False,
    ))
    db.commit()
    db.close()
    return factory


def test_queued_web_run_can_be_cancelled_from_another_session():
    factory = _factory()
    with (
        patch.object(agent_service, "SessionLocal", factory),
        patch.object(
            agent_service,
            "bind_agent_workspace",
            return_value=(SimpleNamespace(id=5), SimpleNamespace()),
        ),
    ):
        session_id = _queue_web_run(
            1,
            "hello",
            None,
            7,
            "claude_code",
            None,
            "q" * 32,
        )
        assert session_id > 0
        assert _queued_web_run_is_active("q" * 32) is True

        remote_db = factory()
        run = remote_db.query(AgentRun).filter_by(id="q" * 32).one()
        run.cancel_requested = True
        remote_db.commit()
        remote_db.close()

        assert _web_run_cancel_requested("q" * 32) is True
        assert _queued_web_run_is_active("q" * 32) is False
        _cancel_queued_web_run("q" * 32)

        verify_db = factory()
        run = verify_db.query(AgentRun).filter_by(id="q" * 32).one()
        assert run.status == "cancelled"
        assert run.finished_at is not None
        verify_db.close()


def test_unresolved_web_run_is_finalized_without_overwriting_terminal_state():
    factory = _factory()
    with (
        patch.object(agent_service, "SessionLocal", factory),
        patch.object(
            agent_service,
            "bind_agent_workspace",
            return_value=(SimpleNamespace(id=5), SimpleNamespace()),
        ),
    ):
        _queue_web_run(1, "hello", None, 7, "claude_code", None, "f" * 32)
        _finalize_unresolved_web_run(
            "f" * 32,
            "failed",
            "startup failed",
            "execution_error",
        )
        _finalize_unresolved_web_run("f" * 32, "cancelled", "late cancel")

        db = factory()
        run = db.query(AgentRun).filter_by(id="f" * 32).one()
        assert run.status == "failed"
        assert run.error_code == "execution_error"
        assert run.error_message == "startup failed"
        assert run.finished_at is not None
        db.close()


def test_unresolved_web_run_settles_platform_reservation_after_finalizing():
    factory = _factory()
    with (
        patch.object(agent_service, "SessionLocal", factory),
        patch.object(
            agent_service,
            "bind_agent_workspace",
            return_value=(SimpleNamespace(id=5), SimpleNamespace()),
        ),
        patch.object(agent_service, "settle_platform_run") as settle,
    ):
        _queue_web_run(1, "hello", None, 7, "claude_code", None, "s" * 32)
        _finalize_unresolved_web_run("s" * 32, "failed", "stream ended")

    settled_run = settle.call_args.args[1]
    assert settled_run.id == "s" * 32
    assert settled_run.status == "failed"
    assert settle.call_args.args[2] == "failed"


def test_control_monitor_retries_transient_failures_and_cancels_owner():
    async def scenario():
        owner = asyncio.create_task(asyncio.Event().wait())
        queue = asyncio.Queue()
        cancel_checks = iter([RuntimeError("db unavailable"), False, True])
        permission_checks = iter([RuntimeError("db unavailable"), []])

        def cancel_requested(_run_id):
            value = next(cancel_checks)
            if isinstance(value, Exception):
                raise value
            return value

        def permission_events(_run_id):
            value = next(permission_checks)
            if isinstance(value, Exception):
                raise value
            return value

        with (
            patch.object(agent_service, "_web_run_cancel_requested", cancel_requested),
            patch.object(agent_service, "claim_pending_permission_events", permission_events),
        ):
            await asyncio.wait_for(
                _monitor_web_run_controls("r" * 32, owner, queue, interval=0.01),
                timeout=1,
            )
        await asyncio.gather(owner, return_exceptions=True)
        assert owner.cancelled()

    asyncio.run(scenario())


def test_web_stream_emits_cancelable_run_id_before_execution_starts():
    class Lease:
        def commit_workspace(self, operation):
            operation()
            return True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def is_owned(self):
            return True

    async def acquire_lease(**_kwargs):
        return Lease()

    async def execute_turn(**kwargs):
        await kwargs["on_started"](kwargs["run_id"], kwargs["session_id"])
        return AgentRunResult(
            run_id=kwargs["run_id"],
            session_id=kwargs["session_id"],
            blocks=[],
            final_text="",
            usage=None,
            runtime_session_id=None,
            status="succeeded",
        )

    async def scenario(path):
        # Streaming now reads and writes concurrently. A StaticPool shares one
        # SQLite connection across transactions and can roll back another task's
        # writes; use independent connections as the production DB does.
        factory = _factory(path)
        events = []
        from fakeredis.aioredis import FakeRedis
        from agent_stream_redis import RedisRunStore
        import agent_stream
        store = RedisRunStore(FakeRedis(decode_responses=True), 'test:control:')
        with (
            patch.object(agent_service, "get_store", return_value=store),
            patch.object(agent_stream, "get_store", return_value=store),
            patch.object(agent_service, "SessionLocal", factory),
            patch.object(
                agent_service,
                "bind_agent_workspace",
                return_value=(SimpleNamespace(id=5), SimpleNamespace()),
            ),
            patch.object(agent_service, "acquire_agent_execution_lease", acquire_lease),
            patch.object(agent_service, "execute_agent_turn", execute_turn),
        ):
            async for chunk in run_agent_chat(
                agent_id=1,
                user_input="hello",
                session_id=None,
                user_id=7,
            ):
                for line in chunk.splitlines():
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        if event["type"] == "run_snapshot":
                            events = event["events"]
                        elif event["type"] == "run_delta":
                            events.extend(event["events"])
                        else:
                            events.append(event)

        assert [event["type"] for event in events[:2]] == ["run_queued", "run_start"]
        assert events[0]["run_id"] == events[1]["run_id"]

        db = factory()
        run = db.query(AgentRun).filter_by(id=events[0]["run_id"]).one()
        assert run.status == "succeeded"
        db.close()
        factory.kw["bind"].dispose()

    with TemporaryDirectory() as directory:
        asyncio.run(scenario(Path(directory) / "stream.db"))


if __name__ == "__main__":
    test_queued_web_run_can_be_cancelled_from_another_session()
    test_unresolved_web_run_is_finalized_without_overwriting_terminal_state()
    test_control_monitor_retries_transient_failures_and_cancels_owner()
    test_web_stream_emits_cancelable_run_id_before_execution_starts()
    print("agent run control tests passed")
