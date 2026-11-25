"""Database-backed, renewable execution lease shared by all Agent entry points."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database import SessionLocal, settings
from models import AgentRun, WorkspaceExecutionLease, UserWorkspace, UserExecutionGate, PlatformAgentSettings


logger = logging.getLogger(__name__)
WaitGuard = Callable[[], Awaitable[bool]]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _default_owner_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:12]}"[:100]


async def drain_worker(task):
    """Wait for an uncancellable worker through repeated caller cancellation."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    return task.result()


async def _run_sync_atomic(func, *args, **kwargs):
    """Keep a database mutation ordered even if its caller is cancelled."""
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await drain_worker(task)
        except Exception:
            logger.exception("Synchronous lease operation failed during cancellation")
        raise


@dataclass
class AgentExecutionLeaseHandle:
    workspace_id: int
    run_id: str
    owner_id: str
    fencing_token: int
    lease_seconds: int
    session_factory: object = SessionLocal
    _heartbeat_task: asyncio.Task | None = field(default=None, init=False)
    _owner_task: asyncio.Task | None = field(default=None, init=False)
    _lost: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    async def __aenter__(self):
        self._owner_task = asyncio.current_task()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name=f"agent-lease-heartbeat-{self.run_id}",
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        cancelled = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            stopping = asyncio.gather(self._heartbeat_task, return_exceptions=True)
            try:
                await asyncio.shield(stopping)
            except asyncio.CancelledError:
                cancelled = True
                await drain_worker(stopping)
        await _run_sync_atomic(self._release)
        if cancelled:
            raise asyncio.CancelledError

    async def is_owned(self) -> bool:
        if self._lost.is_set():
            return False
        return await asyncio.to_thread(self._is_owned)

    def _is_owned(self) -> bool:
        db = self.session_factory()
        try:
            now = utcnow()
            row = db.query(WorkspaceExecutionLease.workspace_id).filter(
                WorkspaceExecutionLease.workspace_id == self.workspace_id,
                WorkspaceExecutionLease.run_id == self.run_id,
                WorkspaceExecutionLease.owner_id == self.owner_id,
                WorkspaceExecutionLease.fencing_token == self.fencing_token,
                WorkspaceExecutionLease.lease_until > now,
            ).first()
            return row is not None
        except Exception:
            logger.exception(
                "Agent execution lease ownership check failed: run_id=%s",
                self.run_id,
            )
            return False
        finally:
            db.close()

    def commit_workspace(self, operation) -> bool:
        """Fence a filesystem mutation against lease expiry and takeover."""
        db = self.session_factory()
        try:
            # SQLite ignores FOR UPDATE; its write transaction provides the
            # same serialization for local tests and supported SQLite usage.
            if db.get_bind().dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            row = db.query(WorkspaceExecutionLease).filter_by(
                workspace_id=self.workspace_id,
            ).with_for_update().first()
            if (row is None or row.run_id != self.run_id
                    or row.owner_id != self.owner_id
                    or row.fencing_token != self.fencing_token
                    or row.lease_until is None
                    or _as_utc(row.lease_until) <= utcnow()):
                db.rollback()
                return False
            operation()
            now = utcnow()
            row.heartbeat_at = now
            row.lease_until = now + timedelta(seconds=self.lease_seconds)
            db.commit()
            return True
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    async def _heartbeat_loop(self) -> None:
        interval = max(1.0, min(10.0, self.lease_seconds / 3))
        loop = asyncio.get_running_loop()
        last_success = loop.time()
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await _run_sync_atomic(self._renew)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Agent execution lease heartbeat failed: run_id=%s",
                    self.run_id,
                )
                if loop.time() - last_success < self.lease_seconds * 0.75:
                    continue
                renewed = False
            if renewed:
                last_success = loop.time()
                continue
            self._lost.set()
            if self._owner_task is not None and not self._owner_task.done():
                self._owner_task.cancel()
            return

    def _renew(self) -> bool:
        db = self.session_factory()
        try:
            if db.get_bind().dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            row = db.query(WorkspaceExecutionLease).filter(
                WorkspaceExecutionLease.workspace_id == self.workspace_id,
                WorkspaceExecutionLease.run_id == self.run_id,
                WorkspaceExecutionLease.owner_id == self.owner_id,
                WorkspaceExecutionLease.fencing_token == self.fencing_token,
            ).with_for_update().first()
            # A workspace copy can hold this row longer than a heartbeat.
            # Renew using the time after the locking read, never an old time.
            now = utcnow()
            if row is None or _as_utc(row.lease_until) <= now:
                db.rollback()
                return False
            row.heartbeat_at = now
            row.lease_until = now + timedelta(seconds=self.lease_seconds)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _release(self) -> None:
        db = self.session_factory()
        try:
            now = utcnow()
            db.query(WorkspaceExecutionLease).filter(
                WorkspaceExecutionLease.workspace_id == self.workspace_id,
                WorkspaceExecutionLease.run_id == self.run_id,
                WorkspaceExecutionLease.owner_id == self.owner_id,
                WorkspaceExecutionLease.fencing_token == self.fencing_token,
            ).update(
                {
                    WorkspaceExecutionLease.run_id: None,
                    WorkspaceExecutionLease.owner_id: None,
                    WorkspaceExecutionLease.lease_until: now,
                    WorkspaceExecutionLease.heartbeat_at: now,
                },
                synchronize_session=False,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Agent execution lease release failed: run_id=%s", self.run_id)
        finally:
            db.close()


def _try_acquire(
    *,
    workspace_id: int,
    run_id: str,
    owner_id: str,
    lease_seconds: int,
    session_factory,
) -> int | None:
    db = session_factory()
    try:
        now = utcnow()
        user_id = db.query(UserWorkspace.user_id).filter(
            UserWorkspace.id == workspace_id, UserWorkspace.is_deleted == False,
        ).scalar()
        if user_id is None:
            raise RuntimeError('执行工作区不存在')
        dialect = db.get_bind().dialect.name
        if dialect == 'mysql':
            from sqlalchemy.dialects.mysql import insert
            db.execute(insert(UserExecutionGate).values(user_id=user_id).on_duplicate_key_update(user_id=user_id))
        elif dialect == 'sqlite':
            from sqlalchemy.dialects.sqlite import insert
            db.execute(insert(UserExecutionGate).values(user_id=user_id).on_conflict_do_nothing())
        else:
            raise RuntimeError('Unsupported execution lease database')
        db.query(UserExecutionGate).filter_by(user_id=user_id).with_for_update().one()
        now = utcnow()
        limit = db.query(PlatformAgentSettings.max_concurrent_runs).filter(
            PlatformAgentSettings.status == 'published',
        ).order_by(PlatformAgentSettings.version.desc()).limit(1).scalar() or 1
        # A locking read sees the latest commits even under MySQL REPEATABLE
        # READ. Plain COUNT may reuse a snapshot taken before acquiring gate.
        active = db.query(WorkspaceExecutionLease.workspace_id).join(
            UserWorkspace, UserWorkspace.id == WorkspaceExecutionLease.workspace_id,
        ).filter(
            UserWorkspace.user_id == user_id,
            WorkspaceExecutionLease.run_id.isnot(None),
            WorkspaceExecutionLease.lease_until > now,
        ).with_for_update().all()
        if len(active) >= max(1, int(limit)):
            db.rollback()
            return None
        row = db.query(WorkspaceExecutionLease).filter(
            WorkspaceExecutionLease.workspace_id == workspace_id
        ).with_for_update().first()
        # Lock waits must not consume the lease that is about to be granted.
        now = utcnow()
        if row is None:
            row = WorkspaceExecutionLease(
                workspace_id=workspace_id,
                run_id=run_id,
                owner_id=owner_id,
                fencing_token=1,
                lease_until=now + timedelta(seconds=lease_seconds),
                heartbeat_at=now,
            )
            db.add(row)
            db.commit()
            return 1

        lease_until = _as_utc(row.lease_until)
        # MySQL DATETIME may round the release timestamp to the next second.
        # An explicitly released row is free regardless of that timestamp.
        if row.run_id is not None and lease_until is not None and lease_until > now:
            db.rollback()
            return None

        previous_run_id = row.run_id
        if previous_run_id and previous_run_id != run_id:
            db.query(AgentRun).filter(
                AgentRun.id == previous_run_id,
                AgentRun.status.in_(["queued", "running"]),
            ).update(
                {
                    AgentRun.status: "unknown",
                    AgentRun.heartbeat_at: now,
                    AgentRun.finished_at: now,
                    AgentRun.lease_until: None,
                    AgentRun.error_code: "lease_expired",
                    AgentRun.error_message: (
                        "执行进程失联且租约已过期，运行结果未写入会话"
                    ),
                },
                synchronize_session=False,
            )

        row.run_id = run_id
        row.owner_id = owner_id
        row.fencing_token = (row.fencing_token or 0) + 1
        row.lease_until = now + timedelta(seconds=lease_seconds)
        row.heartbeat_at = now
        fencing_token = row.fencing_token
        db.commit()
        return fencing_token
    except IntegrityError:
        db.rollback()
        existing = db.query(WorkspaceExecutionLease.workspace_id).filter(
            WorkspaceExecutionLease.workspace_id == workspace_id
        ).first()
        if existing is not None:
            return None
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def acquire_agent_execution_lease(
    *,
    workspace_id: int,
    run_id: str,
    wait_guard: WaitGuard | None = None,
    session_factory=SessionLocal,
    lease_seconds: int | None = None,
    poll_seconds: float | None = None,
    wait: bool = True,
) -> AgentExecutionLeaseHandle | None:
    lease_seconds = max(
        5,
        int(lease_seconds or settings.agent_execution_lease_seconds),
    )
    poll_seconds = max(
        0.05,
        float(poll_seconds or settings.agent_execution_lease_poll_seconds),
    )
    owner_id = _default_owner_id()
    while True:
        if wait_guard is not None and not await wait_guard():
            raise asyncio.CancelledError
        acquire_task = asyncio.create_task(asyncio.to_thread(
            _try_acquire,
            workspace_id=workspace_id,
            run_id=run_id,
            owner_id=owner_id,
            lease_seconds=lease_seconds,
            session_factory=session_factory,
        ))
        try:
            fencing_token = await asyncio.shield(acquire_task)
        except asyncio.CancelledError:
            try:
                fencing_token = await drain_worker(acquire_task)
            except Exception:
                logger.exception(
                    "Agent execution lease acquisition failed during cancellation: run_id=%s",
                    run_id,
                )
                fencing_token = None
            if fencing_token is not None:
                abandoned = AgentExecutionLeaseHandle(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    owner_id=owner_id,
                    fencing_token=fencing_token,
                    lease_seconds=lease_seconds,
                    session_factory=session_factory,
                )
                await _run_sync_atomic(abandoned._release)
            raise
        if fencing_token is not None:
            return AgentExecutionLeaseHandle(
                workspace_id=workspace_id,
                run_id=run_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                lease_seconds=lease_seconds,
                session_factory=session_factory,
            )
        if not wait:
            return None
        await asyncio.sleep(poll_seconds)
