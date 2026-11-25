"""Explicit and automatic recovery of orphaned Web runs."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_

from credit_billing import reconciliation_deadline, reconcile_pending_platform_runs, settle_platform_run
from database import SessionLocal
from models import AgentRun, ModelRunCredential, WorkspaceExecutionLease


ACTIVE_STATUSES = {"queued", "running", "unknown"}
logger = logging.getLogger(__name__)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def recover_stale_web_runs(db, *, limit=100):
    """Close Web runs that lost their queue deadline or execution lease.

    Candidate selection is intentionally cheap. Each candidate is then locked
    in the same workspace-lease-then-run order used by execution takeover, so
    multiple API workers cannot recover the same run or fence a newer run.
    """
    now = datetime.now(timezone.utc)
    batch_size = max(1, int(limit))
    queued_ids = [row[0] for row in db.query(AgentRun.id).filter(
        AgentRun.source == "web",
        AgentRun.status == "queued",
        AgentRun.deadline_at.isnot(None),
        AgentRun.deadline_at <= now,
    ).order_by(AgentRun.created_at.asc()).limit(batch_size).all()]
    running_ids = [row[0] for row in db.query(AgentRun.id).outerjoin(
        WorkspaceExecutionLease,
        and_(
            WorkspaceExecutionLease.workspace_id == AgentRun.workspace_id,
            WorkspaceExecutionLease.run_id == AgentRun.id,
        ),
    ).filter(
        AgentRun.source == "web",
        AgentRun.status == "running",
        or_(
            WorkspaceExecutionLease.workspace_id.is_(None),
            WorkspaceExecutionLease.lease_until <= now,
        ),
    ).order_by(AgentRun.created_at.asc()).limit(batch_size).all()]

    recovered = 0
    for run_id in dict.fromkeys(queued_ids + running_ids):
        db.rollback()
        hint = db.query(AgentRun.workspace_id).filter(
            AgentRun.id == run_id,
            AgentRun.source == "web",
        ).first()
        if hint is None:
            continue
        workspace_id = hint[0]
        lease = None
        if workspace_id is not None:
            lease = db.query(WorkspaceExecutionLease).filter(
                WorkspaceExecutionLease.workspace_id == workspace_id,
            ).populate_existing().with_for_update(skip_locked=True).first()
            if lease is None:
                # A skipped row may be locked by the active worker. Distinguish
                # that from a genuinely missing legacy lease before proceeding.
                lease_exists = db.query(WorkspaceExecutionLease.workspace_id).filter(
                    WorkspaceExecutionLease.workspace_id == workspace_id,
                ).first()
                if lease_exists is not None:
                    db.rollback()
                    continue

        run = db.query(AgentRun).filter(
            AgentRun.id == run_id,
            AgentRun.source == "web",
        ).populate_existing().with_for_update(skip_locked=True).first()
        if run is None:
            db.rollback()
            continue

        changed = False
        if run.status == "queued":
            deadline = _utc(run.deadline_at)
            if deadline is not None and deadline <= now:
                run.status = "failed"
                run.finished_at = now
                run.heartbeat_at = now
                run.lease_until = None
                run.error_code = "queue_timeout"
                run.error_message = "运行在排队等待期间超时，未启动 Runtime"
                changed = True
        elif run.status == "running":
            owns_lease = lease is not None and lease.run_id == run.id
            lease_live = owns_lease and _utc(lease.lease_until) > now
            if not lease_live:
                if owns_lease:
                    lease.fencing_token = (lease.fencing_token or 0) + 1
                    lease.run_id = None
                    lease.owner_id = None
                    lease.lease_until = now
                    lease.heartbeat_at = now
                run.status = "unknown"
                run.finished_at = now
                run.heartbeat_at = now
                run.worker_id = None
                run.lease_until = None
                run.error_code = "lease_expired"
                run.error_message = "执行进程失联且租约已过期，运行结果未写入会话"
                changed = True

        if not changed:
            db.rollback()
            continue
        db.commit()
        recovered += 1
        try:
            settle_platform_run(db, run, run.status)
        except Exception:
            db.rollback()
            logger.exception("Automatic Web run settlement failed: run_id=%s", run.id)

    return recovered


def _recover_with_factory(session_factory, limit):
    db = session_factory()
    try:
        recovered = recover_stale_web_runs(db, limit=limit)
        reconcile_pending_platform_runs(db, limit=limit)
        return recovered
    finally:
        db.close()


async def web_run_recovery_loop(session_factory=SessionLocal, *, interval_seconds=30, limit=100):
    """Periodically recover orphaned Web runs on every API worker."""
    interval = max(5.0, float(interval_seconds))
    while True:
        try:
            await asyncio.to_thread(_recover_with_factory, session_factory, limit)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic Web run recovery failed")
        await asyncio.sleep(interval)


def settle_all_runs(db, *, user_id, actor_user_id):
    """Settle a snapshot of all ended, unsettled runs, independently per run."""
    terminal = {"succeeded", "failed", "cancelled", "timed_out"}
    pending = {"reserved", "metering", "pending_reconciliation"}
    query = db.query(AgentRun.id).filter(AgentRun.settlement_status.in_(pending))
    if user_id is not None:
        query = query.filter(AgentRun.user_id == user_id)
    skipped = query.filter(~AgentRun.status.in_(terminal)).count()
    run_ids = [row[0] for row in query.filter(AgentRun.status.in_(terminal)).order_by(AgentRun.id).all()]
    db.rollback()
    settled = failed = 0
    errors = []
    for run_id in run_ids:
        try:
            scoped = db.query(AgentRun).filter(AgentRun.id == run_id)
            if user_id is not None:
                scoped = scoped.filter(AgentRun.user_id == user_id)
            run = scoped.populate_existing().with_for_update().first()
            if run is None or run.status not in terminal or run.settlement_status not in pending:
                skipped += 1
                db.rollback()
                continue
            settle_platform_run(db, run, run.status, force_settle=True, actor_user_id=actor_user_id)
            db.refresh(run)
            if run.settlement_status == "settled":
                settled += 1
            else:
                skipped += 1
            db.rollback()
        except Exception:
            db.rollback()
            failed += 1
            logger.exception("Bulk credit settlement failed: run_id=%s actor=%s", run_id, actor_user_id)
            if len(errors) < 20:
                errors.append({"run_id": run_id, "message": "结算失败，请稍后重试"})
    return {"total": settled + skipped + failed,
            "settled": settled, "skipped": skipped, "failed": failed, "errors": errors}


def recover_web_run(db, run_id, *, user_id, actor_user_id, force_release=False, force_settle=False):
    if force_release and force_settle:
        raise HTTPException(400, "强制结算与强制返还不能同时执行")
    query = db.query(AgentRun).filter(AgentRun.id == run_id)
    if user_id is not None:
        query = query.filter(AgentRun.user_id == user_id)
    existing = query.first()
    if existing is None:
        raise HTTPException(404, "运行记录不存在")
    if existing.source != "web":
        raise HTTPException(409, "渠道任务请在渠道管理中处理")

    # Keep lock order consistent with lease acquisition: workspace, then run.
    lease = db.query(WorkspaceExecutionLease).filter(
        WorkspaceExecutionLease.workspace_id == existing.workspace_id,
    ).populate_existing().with_for_update().first() if existing.workspace_id else None
    run = query.populate_existing().with_for_update().one()
    if force_settle and run.status in ACTIVE_STATUSES:
        db.rollback()
        raise HTTPException(409, "请先结束或恢复对话，再强制结算")
    now = datetime.now(timezone.utc)
    if run.status in ACTIVE_STATUSES:
        owns_lease = lease is not None and lease.run_id == run.id
        if owns_lease and _utc(lease.lease_until) > now:
            db.rollback()
            raise HTTPException(409, "该对话仍在执行，请先在对话中停止；执行进程失联后可恢复")
        # Older runs may have no workspace lease. Do not race a newly queued run.
        last_activity = _utc(run.heartbeat_at or run.started_at or run.created_at)
        if not owns_lease and last_activity and last_activity > now - timedelta(minutes=2):
            db.rollback()
            raise HTTPException(409, "该对话刚刚有活动，请稍后刷新再恢复")
        if owns_lease:
            lease.fencing_token += 1
            lease.run_id = None
            lease.owner_id = None
            lease.lease_until = now
            lease.heartbeat_at = now
        run.status = "cancelled"
        run.cancel_requested = True
        run.finished_at = run.finished_at or now
        run.heartbeat_at = now
        run.worker_id = None
        run.lease_until = None
        run.error_code = "manual_recovery"
        run.error_message = f"用户 {actor_user_id} 手工恢复了失联对话；已保留会话历史，未重新执行任务"

    # Stop future requests before releasing any reservation. In-flight requests
    # can still report usage and complete reconciliation through the gateway.
    credential = db.query(ModelRunCredential).filter(
        ModelRunCredential.run_id == run.id,
    ).populate_existing().with_for_update().first()
    if credential is not None and credential.status == "active":
        credential.status = "reconciliation"
    db.commit()
    settle_platform_run(db, run, run.status, force_release=force_release,
                        force_settle=force_settle, actor_user_id=actor_user_id)
    db.refresh(run)
    deadline = reconciliation_deadline(run, credential) if run.settlement_status == "pending_reconciliation" else None
    return {
        "run_id": run.id, "status": run.status,
        "settlement_status": run.settlement_status,
        "charged_points": run.charged_points if run.settlement_status == "settled" else None,
        "reconciliation_deadline": deadline.isoformat() if deadline else None,
        "force_released": bool(force_release and run.settlement_status == "settled"),
    }
