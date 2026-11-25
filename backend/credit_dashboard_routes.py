"""Personal and global credit reporting, based on settled runs rather than refunds."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, cast, func
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.orm import Session

from auth import CurrentUser, get_current_active_user
from agent_run_recovery import recover_web_run, settle_all_runs
from database import get_db
from dashboard_routes import LOCAL_TZ, _resolve_period
from models import (
    AIModel, AgentRun, AgentSession, CreditAccount, CreditLedger, ModelRunCredential,
)


def _period(period, start_date, end_date):
    try:
        start, end, _, _ = _resolve_period(period, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式无效") from exc
    if end - start > timedelta(days=366):
        raise HTTPException(status_code=400, detail="统计范围不能超过 366 天")
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def _iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def _scoped(query, column, user_id):
    return query.filter(column == user_id) if user_id is not None else query


def _runs(db, user_id):
    run_id = AgentRun.id
    if db.bind.dialect.name in {"mysql", "mariadb"}:
        # Legacy IDs may use ASCII; COLLATE alone cannot change their character set.
        run_id = cast(run_id, CHAR(32, charset="utf8mb4")).collate("utf8mb4_unicode_ci")
    # One settlement per run; group defensively so ledger joins cannot multiply charges.
    settlements = _scoped(db.query(
        CreditLedger.run_id,
        CreditLedger.user_id,
        func.min(CreditLedger.created_at).label("settled_at"),
    ).filter(CreditLedger.entry_type == "run_settlement"), CreditLedger.user_id, user_id)
    settlements = settlements.group_by(CreditLedger.run_id, CreditLedger.user_id).subquery()
    query = db.query(
        AgentRun.id.label("run_id"), AgentRun.user_id, AgentRun.session_id,
        AgentRun.created_at, settlements.c.settled_at,
        func.coalesce(settlements.c.settled_at, AgentRun.created_at).label("recorded_at"),
        AgentRun.status, AgentRun.source, AgentRun.settlement_status, AgentRun.reserved_points,
        AgentRun.pricing_snapshot,
        AgentRun.charged_points.label("charged_points"),
        ModelRunCredential.model_id,
        func.coalesce(AIModel.name, "未知模型").label("model_name"),
        func.coalesce(AgentSession.title, "未命名会话").label("session_title"),
    ).outerjoin(settlements, and_(
        settlements.c.run_id == run_id, settlements.c.user_id == AgentRun.user_id,
    )).outerjoin(ModelRunCredential, and_(
        ModelRunCredential.run_id == run_id, ModelRunCredential.user_id == AgentRun.user_id,
    )).outerjoin(AIModel, AIModel.id == ModelRunCredential.model_id).outerjoin(AgentSession, and_(
        AgentSession.id == AgentRun.session_id, AgentSession.user_id == AgentRun.user_id,
    )).filter(AgentRun.settlement_status != "not_required")
    return _scoped(query, AgentRun.user_id, user_id).subquery()


def _settled(db, runs, start, end):
    return db.query(runs).filter(
        runs.c.settlement_status == "settled",
        runs.c.settled_at >= start, runs.c.settled_at < end,
    )


def _ledger(db, user_id, start, end):
    return _scoped(db.query(CreditLedger).filter(
        CreditLedger.created_at >= start, CreditLedger.created_at < end,
    ), CreditLedger.user_id, user_id)


def _bucket(db, column, granularity):
    formats = {"hour": "%Y-%m-%d %H:00:00", "day": "%Y-%m-%d 00:00:00"}
    if db.bind.dialect.name == "sqlite":
        local = func.datetime(column, "+8 hours")
        if granularity == "week":
            return func.datetime(func.date(local, "-6 days", "weekday 1"))
        return func.strftime(formats[granularity], local)
    local = func.convert_tz(column, "+00:00", "+08:00")
    if granularity == "week":
        return func.date_format(func.subdate(func.date(local), func.weekday(local)), formats["day"])
    return func.date_format(local, formats[granularity])


def _trend(db, settled, ledger, start, end, granularity):
    bucket = _bucket(db, settled.c.settled_at, granularity)
    consumed = dict(db.query(bucket, func.sum(settled.c.charged_points)).group_by(bucket).all())
    bucket = _bucket(db, CreditLedger.created_at, granularity)
    received = dict(ledger.filter(CreditLedger.entry_type.in_(["initial_claim", "daily_claim"]))
                    .with_entities(bucket, func.sum(CreditLedger.amount)).group_by(bucket).all())
    cursor = start.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).replace(minute=0, second=0, microsecond=0)
    if granularity != "hour":
        cursor = cursor.replace(hour=0)
    if granularity == "week":
        cursor -= timedelta(days=cursor.weekday())
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=7 if granularity == "week" else 1)
    rows = []
    while cursor < end.replace(tzinfo=timezone.utc):
        key = cursor.strftime("%Y-%m-%d %H:%M:%S")
        rows.append({"bucket": cursor.isoformat(), "consumed_points": consumed.get(key, Decimal("0.00")),
                     "claimed_points": received.get(key, Decimal("0.00"))})
        cursor += step
    return rows


def build_usage(db, user_id, start, end, granularity):
    runs = _runs(db, user_id)
    settled = _settled(db, runs, start, end).subquery()
    totals = db.query(
        func.coalesce(func.sum(settled.c.charged_points), 0).label("consumed_points"),
        func.count().label("run_count"),
        func.count(func.distinct(case((settled.c.charged_points > 0, settled.c.user_id)))).label("active_users"),
    ).select_from(settled).one()
    balances = _scoped(db.query(
        func.coalesce(func.sum(CreditAccount.available_balance), 0).label("available_balance"),
        func.coalesce(func.sum(CreditAccount.reserved_balance), 0).label("reserved_balance"),
    ), CreditAccount.user_id, user_id).one()
    ledger = _ledger(db, user_id, start, end)
    movements = dict(ledger.with_entities(CreditLedger.entry_type, func.sum(CreditLedger.amount))
                     .group_by(CreditLedger.entry_type).all())
    adjustments = ledger.filter(CreditLedger.entry_type == "admin_adjustment").with_entities(
        func.coalesce(func.sum(case((CreditLedger.amount > 0, CreditLedger.amount), else_=0)), 0),
        func.coalesce(func.sum(case((CreditLedger.amount < 0, -CreditLedger.amount), else_=0)), 0),
    ).one()
    pending = dict(db.query(runs.c.settlement_status, func.count()).filter(
        runs.c.settlement_status.in_(["reserved", "metering", "pending_reconciliation"]),
    ).group_by(runs.c.settlement_status).all())
    models = db.query(
        settled.c.model_id, settled.c.model_name,
        func.sum(settled.c.charged_points).label("consumed_points"),
        func.count().label("run_count"),
    ).group_by(settled.c.model_id, settled.c.model_name).order_by(
        func.sum(settled.c.charged_points).desc(), settled.c.model_id,
    ).limit(10).all()
    initial = movements.get("initial_claim", Decimal("0.00"))
    daily = movements.get("daily_claim", Decimal("0.00"))
    return {
        "period": {"start_at": _iso(start), "end_at": _iso(end), "granularity": granularity},
        "summary": {
            **dict(totals._mapping), **dict(balances._mapping),
            "initial_claim_points": initial, "daily_claim_points": daily,
            "claimed_points": initial + daily,
            "adjustment_added": adjustments[0], "adjustment_deducted": adjustments[1],
            "reserved_runs": pending.get("reserved", 0) + pending.get("metering", 0),
            "pending_runs": pending.get("pending_reconciliation", 0),
        },
        "trend": _trend(db, settled, ledger, start, end, granularity),
        "models": [dict(row._mapping) for row in models],
    }


def build_runs(db, user_id, start, end, skip, limit, status="all"):
    runs = _runs(db, user_id)
    query = db.query(runs).filter(runs.c.recorded_at >= start, runs.c.recorded_at < end)
    if status == "reserved":
        query = query.filter(runs.c.settlement_status == "reserved")
    elif status == "metering":
        query = query.filter(runs.c.settlement_status == "metering")
    elif status != "all":
        query = query.filter(runs.c.settlement_status == status)
    total = query.count()
    rows = query.order_by(runs.c.recorded_at.desc(), runs.c.run_id.desc()).offset(skip).limit(limit).all()
    items = []
    for row in rows:
        item = dict(row._mapping)
        for key in ("created_at", "settled_at", "recorded_at"):
            item[key] = _iso(item[key])
        import json
        realtime = json.loads(item.pop("pricing_snapshot") or "{}").get("billing_mode") == "realtime"
        item["billing_mode"] = "realtime" if realtime else "reservation"
        if item["settlement_status"] != "settled" and not realtime:
            item["charged_points"] = None
        items.append(item)
    return {"total": total, "items": items}


def build_ledger(db, user_id, start, end, skip, limit, entry_type="all"):
    query = _ledger(db, user_id, start, end)
    if entry_type != "all":
        query = query.filter(CreditLedger.entry_type == entry_type)
    total = query.count()
    return {"total": total, "items": [{
        "id": row.id, "user_id": row.user_id, "entry_type": row.entry_type,
        "amount": row.amount, "available_after": row.available_after,
        "reserved_after": row.reserved_after, "run_id": row.run_id,
        "reason": row.reason, "created_at": _iso(row.created_at),
    } for row in query.order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc()).offset(skip).limit(limit).all()]}


def build_users(db, user_id, start, end, skip, limit):
    settled = _settled(db, _runs(db, user_id), start, end).subquery()
    query = db.query(
        settled.c.user_id, func.sum(settled.c.charged_points).label("consumed_points"),
        func.count().label("run_count"),
    ).group_by(settled.c.user_id)
    total = query.count()
    rows = query.order_by(func.sum(settled.c.charged_points).desc(), settled.c.user_id).offset(skip).limit(limit).all()
    return {"total": total, "items": [dict(row._mapping) for row in rows]}


def create_router(summary=False):
    scope = "summary" if summary else "personal"
    router = APIRouter(prefix=f"/api/dashboard/{scope}/credit-usage", tags=["dashboard"])

    def scoped_user(
        user_id: Optional[int] = Query(None, ge=1),
        current_user: CurrentUser = Depends(get_current_active_user),
    ):
        if summary:
            if not current_user.is_superuser:
                raise HTTPException(status_code=403, detail="仅超级管理员可查看全局用量看板")
            return user_id
        if user_id is not None and user_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="无权查看其他用户的积分用量")
        return current_user.user_id

    def date_range(
        period: str = Query("7d", pattern="^(today|7d|month|custom)$"),
        start_date: Optional[str] = Query(None), end_date: Optional[str] = Query(None),
    ):
        return _period(period, start_date, end_date)

    @router.get("")
    def usage(
        granularity: str = Query("day", pattern="^(hour|day|week)$"),
        user_id=Depends(scoped_user), dates=Depends(date_range), db: Session = Depends(get_db),
    ):
        return build_usage(db, user_id, *dates, granularity)

    @router.get("/runs")
    def runs(
        skip: int = Query(0, ge=0), limit: int = Query(16, ge=1, le=100),
        status: str = Query("all", pattern="^(all|settled|reserved|metering|pending_reconciliation)$"),
        user_id=Depends(scoped_user), dates=Depends(date_range), db: Session = Depends(get_db),
    ):
        return build_runs(db, user_id, *dates, skip, limit, status)

    @router.post("/runs/settle-all")
    def settle_runs(
        user_id=Depends(scoped_user),
        current_user: CurrentUser = Depends(get_current_active_user),
        db: Session = Depends(get_db),
    ):
        return settle_all_runs(db, user_id=user_id, actor_user_id=current_user.user_id)

    @router.post("/runs/{run_id}/recover")
    def recover_run(
        run_id: str, user_id=Depends(scoped_user),
        current_user: CurrentUser = Depends(get_current_active_user),
        force_release: bool = Query(False),
        force_settle: bool = Query(False),
        db: Session = Depends(get_db),
    ):
        return recover_web_run(
            db, run_id, user_id=user_id, actor_user_id=current_user.user_id,
            force_release=force_release, force_settle=force_settle,
        )

    @router.get("/ledger")
    def ledger(
        skip: int = Query(0, ge=0), limit: int = Query(16, ge=1, le=100),
        entry_type: str = Query("all", pattern="^(all|initial_claim|daily_claim|admin_adjustment|model_usage|run_reservation|run_settlement)$"),
        user_id=Depends(scoped_user), dates=Depends(date_range), db: Session = Depends(get_db),
    ):
        return build_ledger(db, user_id, *dates, skip, limit, entry_type)

    if summary:
        @router.get("/users")
        def users(
            skip: int = Query(0, ge=0), limit: int = Query(16, ge=1, le=100),
            user_id=Depends(scoped_user), dates=Depends(date_range), db: Session = Depends(get_db),
        ):
            return build_users(db, user_id, *dates, skip, limit)

    return router


personal_router = create_router()
summary_router = create_router(summary=True)
