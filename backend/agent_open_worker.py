"""Database queue consumer started with each API process; never replays started runs."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_

from agent_access import PublicRuntimeAgent
from agent_execution_lease import acquire_agent_execution_lease
from agent_open_calls import SOURCE, _agent, _lock_write
from agent_service import _finish_run_record, execute_agent_turn
from agent_settings import runtime_agent
from database import SessionLocal
from enterprise_workspace import bind_agent_workspace, utcnow
from models import Agent, AgentOpenCall, AgentOpenRequest, AgentRun
from sandbox.open_call import get_open_call_sandbox

logger = logging.getLogger(__name__)
WORKER_LEASE_SECONDS = 90


def _utc(value):
    return value.replace(tzinfo=utcnow().tzinfo) if value and value.tzinfo is None else value


def _finish(db, run, status, code, message):
    _finish_run_record(db, run, status, message, error_code=code)
    item = db.get(AgentOpenRequest, run.id)
    if item:
        item.prompt = None
        db.commit()


def claim_run(factory, worker_id):
    with factory() as db:
        _lock_write(db)
        run = db.query(AgentRun).filter(
            AgentRun.source == SOURCE, AgentRun.status == "queued",
        ).order_by(AgentRun.created_at, AgentRun.id).with_for_update(skip_locked=True).first()
        if run is None:
            return None
        now = utcnow()
        if _utc(run.deadline_at) <= now:
            _finish(db, run, "failed", "queue_timeout", "开放调用排队超时")
            return None
        run.status = "running"
        run.worker_id = worker_id
        run.heartbeat_at = now
        run.lease_until = now + timedelta(seconds=WORKER_LEASE_SECONDS)
        # This also bounds workspace-lease waiting and finalization.
        resolved = runtime_agent(db, db.get(Agent, run.agent_id))
        run.deadline_at = now + timedelta(seconds=max(1, resolved.timeout_seconds) + 30)
        db.commit()
        return run.id


def check_run(factory, run_id, worker_id):
    with factory() as db:
        run = db.query(AgentRun).filter_by(
            id=run_id, source=SOURCE, status="running", worker_id=worker_id,
        ).first()
        if run is None:
            return "lease_expired"
        config = db.get(AgentOpenCall, run.agent_id)
        item = db.get(AgentOpenRequest, run.id)
        agent = _agent(db, run.agent_id)
        if (not agent or not config or not config.key_digest or not item
                or config.generation != item.generation or run.cancel_requested):
            return "open_call_config_changed"
        if _utc(run.deadline_at) <= utcnow():
            return "run_timeout"
        run.heartbeat_at = utcnow()
        run.lease_until = run.heartbeat_at + timedelta(seconds=WORKER_LEASE_SECONDS)
        db.commit()
        return None


async def run_one(factory, run_id, worker_id):
    owner = asyncio.current_task()
    stop_code = None

    async def guard():
        return await asyncio.to_thread(check_run, factory, run_id, worker_id) is None

    async def controls():
        nonlocal stop_code
        while True:
            await asyncio.sleep(1)
            try:
                stop_code = await asyncio.to_thread(check_run, factory, run_id, worker_id)
            except Exception:
                logger.exception("Open Agent control check failed: run_id=%s", run_id)
                stop_code = "control_unavailable"
            if stop_code:
                owner.cancel()
                return

    controller = asyncio.create_task(controls())
    try:
        with factory() as db:
            run = db.get(AgentRun, run_id)
            if await asyncio.to_thread(check_run, factory, run_id, worker_id):
                _finish(db, run, "cancelled", "open_call_config_changed", "开放调用配置已变更")
                return
            item = db.get(AgentOpenRequest, run_id)
            agent = PublicRuntimeAgent(runtime_agent(db, _agent(db, run.agent_id)), {
                "open_call_run_id": run_id,
                # Current connector settings are resolved from scoped bindings.
                # Do not also apply the legacy agent-level plaintext overrides.
                "mcp_overrides": [],
            })
            prompt = item.prompt or "请按照你的职责和配置开始执行。"
            skill_id = item.skill_id
            workspace, _ = bind_agent_workspace(db, agent)
            run.workspace_id = workspace.id
            db.commit()
            lease = await acquire_agent_execution_lease(
                workspace_id=workspace.id, run_id=run_id, wait_guard=guard, session_factory=factory,
            )

            async def combined_guard():
                return await guard() and await lease.is_owned()

            async with lease:
                await execute_agent_turn(
                    agent=agent, user_input=prompt, session_id=run.session_id,
                    user_id=run.user_id, db=db, run_id=run_id, source=SOURCE,
                    skill_id_override=skill_id, permission_mode="default",
                    interactive_permissions=False, run_guard=combined_guard,
                    workspace_commit=lease.commit_workspace,
                )
    except asyncio.CancelledError:
        # Cancel the runtime before making the durable terminal transition.
        with factory() as db:
            run = db.get(AgentRun, run_id)
            if run and run.worker_id == worker_id and run.status in {"queued", "running"}:
                _finish(db, run, "cancelled", stop_code or "worker_stopped", "开放调用执行已停止")
        if stop_code is None:
            raise
    except Exception:
        logger.exception("Open Agent execution failed: run_id=%s", run_id)
        with factory() as db:
            run = db.get(AgentRun, run_id)
            if run and run.worker_id == worker_id and run.status in {"queued", "running"}:
                _finish(db, run, "failed", "execution_failed", "开放调用执行失败")
    finally:
        controller.cancel()
        await asyncio.gather(controller, return_exceptions=True)
        with factory() as db:
            run = db.get(AgentRun, run_id)
            if run and run.status not in {"queued", "running"}:
                item = db.get(AgentOpenRequest, run_id)
                if item:
                    item.prompt = None
                    db.commit()
            if run and run.status in {"queued", "running"} and run.worker_id == worker_id:
                _finish(db, run, "failed", "execution_failed", "开放调用未完成")


def recover_runs(factory):
    cleanup = []
    with factory() as db:
        now = utcnow()
        ids = [row.id for row in db.query(AgentRun.id).filter(
            AgentRun.source == SOURCE,
            or_(
                (AgentRun.status == "running") & (AgentRun.lease_until < now),
                (AgentRun.status == "queued") & (AgentRun.deadline_at < now),
            ),
        ).limit(30)]
        db.rollback()
        for run_id in ids:
            _lock_write(db)
            run = db.query(AgentRun).filter_by(id=run_id).with_for_update(skip_locked=True).first()
            if not run:
                db.rollback()
                continue
            if run.status == "queued" and _utc(run.deadline_at) < now:
                _finish(db, run, "failed", "queue_timeout", "开放调用排队超时")
            elif run.status == "running" and _utc(run.lease_until) < now:
                # Unknown executions are reconciled, never automatically retried.
                _finish(db, run, "unknown", "lease_expired", "开放调用执行进程失联")
                cleanup.append(run_id)
            else:
                db.rollback()
    # Expired runs are fenced by status/lease; remove disposable runtime state.
    for run_id in cleanup:
        try:
            sandbox = get_open_call_sandbox()
            from database import settings
            import os
            sandbox._remove_root(os.path.join(settings.user_workspace_root, "open-" + run_id), run_id)
        except Exception:
            logger.warning("Open Agent workspace cleanup deferred: run_id=%s", run_id, exc_info=True)


async def open_call_worker_loop(factory=SessionLocal):
    worker_id = "api-" + uuid4().hex
    running = set()
    last_recovery = 0
    try:
        while True:
            try:
                for task in list(running):
                    if task.done():
                        running.remove(task)
                        if not task.cancelled() and task.exception():
                            logger.error("Open Agent worker failed", exc_info=task.exception())
                now = asyncio.get_running_loop().time()
                if now - last_recovery >= 30:
                    await asyncio.to_thread(recover_runs, factory)
                    last_recovery = now
                if len(running) < 2:
                    run_id = await asyncio.to_thread(claim_run, factory, worker_id)
                    if run_id:
                        running.add(asyncio.create_task(run_one(factory, run_id, worker_id)))
                        continue
            except Exception:
                logger.exception("Open Agent queue temporarily unavailable")
                await asyncio.sleep(2)
            await asyncio.sleep(0.4)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Keep the consumer available through temporary database outages.
        logger.exception("Open Agent queue consumer failed")
        raise
    finally:
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
