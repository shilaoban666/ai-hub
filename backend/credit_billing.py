"""Platform credit metering, live debits and legacy reservation settlement."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
import hashlib
import json
import secrets

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from database import SessionLocal, settings
from credit_labels import credit_display_name
from models import (
    AgentRun,
    AIModel,
    CreditAccount,
    CreditLedger,
    ModelPricingVersion,
    ModelRunCredential,
    ModelUsageEvent,
    ModelGatewayRequest,
    PlatformAgentSettings,
)


class CreditBillingError(RuntimeError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


POINT_QUANTUM = Decimal("0.01")
ZERO_POINTS = Decimal("0.00")


def point_value(value) -> Decimal:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        amount = ZERO_POINTS
    return amount.quantize(POINT_QUANTUM, rounding=ROUND_HALF_UP)


def point_number(value) -> float:
    return float(point_value(value))


def token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def calculate_points(usage: dict, pricing) -> Decimal:
    numerator = (
        int(usage.get("input_tokens") or 0) * int(pricing.input_rate or 0)
        + int(usage.get("output_tokens") or 0) * int(pricing.output_rate or 0)
        + int(usage.get("cache_read_tokens") or 0) * int(pricing.cache_read_rate or 0)
        + int(usage.get("cache_creation_tokens") or 0) * int(pricing.cache_creation_rate or 0)
    )
    scale = max(1, int(pricing.rate_scale or 1))
    if numerator <= 0:
        return ZERO_POINTS
    return (Decimal(numerator) / Decimal(scale)).quantize(
        POINT_QUANTUM,
        rounding=ROUND_CEILING,
    )


def _active_policy(db: Session) -> PlatformAgentSettings | None:
    return db.query(PlatformAgentSettings).filter(
        PlatformAgentSettings.status == "published"
    ).order_by(PlatformAgentSettings.version.desc()).first()


def _active_pricing(db: Session, model_id: int) -> ModelPricingVersion | None:
    return db.query(ModelPricingVersion).filter(
        ModelPricingVersion.model_id == model_id,
        ModelPricingVersion.effective_to.is_(None),
    ).order_by(ModelPricingVersion.version.desc()).first()


def prepare_platform_run(
    db: Session,
    run: AgentRun,
    model: AIModel,
    timeout_seconds: int,
    runtime_type: str,
) -> tuple[str, str]:
    """Authorize live usage against the account without reserving any credits."""
    if getattr(model, "scope", "user") != "platform":
        return "", ""
    # Reject a recovered/unknown Run before checking runtime isolation or
    # account configuration. A terminal Run must never be executable again,
    # and this guard also keeps recovery idempotency independent of sandbox
    # settings in the caller process.
    run = db.query(AgentRun).filter(AgentRun.id == run.id).populate_existing().with_for_update().one()
    if run.error_code in {"manual_recovery", "queue_timeout", "lease_expired"} or run.status == "unknown":
        db.rollback()
        raise CreditBillingError("该 Run 已回收，不能重复执行", "RUN_ALREADY_BILLED")
    if (runtime_type or "claude_code") == "claude_code":
        from sandbox import get_configured_sandbox_type

        if get_configured_sandbox_type() == "directory":
            raise CreditBillingError(
                "企业平台模型禁止使用 directory 沙箱",
                "RUNTIME_ISOLATION_REQUIRED",
            )
    policy = _active_policy(db)
    pricing = _active_pricing(db, model.id)
    if policy is None or pricing is None:
        raise CreditBillingError("平台模型计费配置尚未发布", "CREDIT_POLICY_UNAVAILABLE")
    # Channel/direct-agent entry must receive the same one-time allowance as
    # the workbench. This is deliberately after the custom-model early return.
    from credit_accounts import ensure_initial_credits
    from fastapi import HTTPException
    try:
        ensure_initial_credits(db, run.user_id, policy)
    except HTTPException as exc:
        db.rollback()
        raise CreditBillingError(f"{credit_display_name(policy)}账户不可用", "CREDIT_ACCOUNT_UNAVAILABLE") from exc

    existing = db.query(ModelRunCredential).filter(
        ModelRunCredential.run_id == run.id
    ).with_for_update().first()
    if existing is not None:
        if run.settlement_status not in {"reserved", "metering"} or existing.status != "active":
            raise CreditBillingError("该 Run 已完成计费，不能重复执行", "RUN_ALREADY_BILLED")
        raw_token = "ahr_" + secrets.token_urlsafe(32)
        existing.token_hash = token_hash(raw_token)
        existing.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=max(
                int(settings.model_gateway_credential_ttl_seconds),
                int(timeout_seconds) + 60,
            )
        )
        existing.request_in_flight = False
        db.commit()
        return raw_token, settings.model_gateway_base_url.rstrip("/")

    account = db.query(CreditAccount).filter(
        CreditAccount.user_id == run.user_id
    ).populate_existing().with_for_update().first()
    if account is None or account.status != "active":
        raise CreditBillingError(f"{credit_display_name(policy)}账户不可用", "CREDIT_ACCOUNT_UNAVAILABLE")
    if point_value(account.available_balance) <= 0:
        raise CreditBillingError(f"{credit_display_name(policy)}已用尽，请领取或充值后重试", "CREDITS_EXHAUSTED")

    raw_token = "ahr_" + secrets.token_urlsafe(32)
    run.reserved_points = ZERO_POINTS
    run.charged_points = ZERO_POINTS
    run.settlement_status = "metering"
    snapshot = {
        "billing_mode": "realtime",
        "pricing_version_id": pricing.id,
        "pricing_version": pricing.version,
        "input_rate": pricing.input_rate,
        "output_rate": pricing.output_rate,
        "cache_read_rate": pricing.cache_read_rate,
        "cache_creation_rate": pricing.cache_creation_rate,
        "rate_scale": pricing.rate_scale,
        "policy_version": policy.version,
    }
    run.pricing_snapshot = json.dumps(snapshot, separators=(",", ":"))
    db.add(ModelRunCredential(
        token_hash=token_hash(raw_token),
        run_id=run.id,
        user_id=run.user_id,
        model_id=model.id,
        pricing_version_id=pricing.id,
        max_points=ZERO_POINTS,
        expires_at=datetime.now(timezone.utc) + timedelta(
            seconds=max(
                int(settings.model_gateway_credential_ttl_seconds),
                int(timeout_seconds) + 60,
            )
        ),
    ))
    db.commit()
    return raw_token, settings.model_gateway_base_url.rstrip("/")


def reconciliation_deadline(run: AgentRun, credential: ModelRunCredential | None = None) -> datetime | None:
    """Use immutable execution bounds, never a retry's updated_at timestamp."""
    if run.status in {"queued", "running"}:
        return None
    ended_at = (
        getattr(run, "finished_at", None)
        or getattr(run, "heartbeat_at", None)
        or getattr(run, "started_at", None)
        or getattr(run, "created_at", None)
    )
    if ended_at is None:
        return None
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    if credential is not None:
        expires_at = credential.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        # Recovery can set finished_at to now, long after the gateway could
        # last accept a request. Allow the final accepted request its timeout,
        # but do not restart the grace period for an expired old credential.
        last_request_bound = expires_at + timedelta(
            seconds=max(0, int(settings.model_gateway_request_timeout_seconds)),
        )
        ended_at = min(ended_at, last_request_bound)
    grace = max(0, int(settings.model_gateway_reconciliation_grace_seconds))
    return ended_at + timedelta(seconds=grace)


def _incomplete_reconciliation_expired(run: AgentRun, credential=None) -> bool:
    deadline = reconciliation_deadline(run, credential)
    return deadline is not None and deadline <= datetime.now(timezone.utc)


def settle_platform_run(
    db: Session,
    run: AgentRun,
    final_status: str,
    *,
    force_release: bool = False,
    force_settle: bool = False,
    actor_user_id=None,
) -> None:
    if is_realtime_run(run):
        settle_metered_run(db, run, final_status, force_settle=force_settle,
                           actor_user_id=actor_user_id)
        return
    if point_value(getattr(run, "reserved_points", 0)) <= ZERO_POINTS:
        return
    run = db.query(AgentRun).filter(AgentRun.id == run.id).populate_existing().with_for_update().one()
    if run.settlement_status == "settled":
        return
    if force_settle and run.status not in {"succeeded", "failed", "cancelled", "timed_out"}:
        raise CreditBillingError("请先结束任务再强制结算", "RUN_NOT_TERMINAL")
    credential = db.query(ModelRunCredential).filter(
        ModelRunCredential.run_id == run.id
    ).populate_existing().with_for_update().first()
    if force_release:
        event_count = db.query(func.count(ModelUsageEvent.id)).filter(
            ModelUsageEvent.run_id == run.id
        ).scalar() or 0
        requested_events = credential.request_count if credential is not None else 0
        incomplete_usage = event_count < requested_events
    elif credential is None:
        if not force_settle and not _incomplete_reconciliation_expired(run):
            run.settlement_status = "pending_reconciliation"
            db.commit()
            return
        # A very old run may have lost its credential record as well. There is
        # no verified usage to charge, so release the reservation at the grace
        # deadline and preserve the fact that the usage record was incomplete.
        event_count = 0
        requested_events = 0
        incomplete_usage = True
    else:
        event_count = db.query(func.count(ModelUsageEvent.id)).filter(
            ModelUsageEvent.run_id == run.id
        ).scalar() or 0
        requested_events = credential.request_count
        incomplete_usage = event_count < requested_events
    if not (force_release or force_settle) and incomplete_usage and not _incomplete_reconciliation_expired(run, credential):
        run.settlement_status = "pending_reconciliation"
        if credential is not None:
            credential.status = "reconciliation"
        db.commit()
        return

    actual = ZERO_POINTS if force_release else min(
        point_value(credential.consumed_points) if credential is not None else ZERO_POINTS,
        point_value(run.reserved_points),
    )
    account = db.query(CreditAccount).filter(
        CreditAccount.user_id == run.user_id
    ).populate_existing().with_for_update().one()
    release = point_value(run.reserved_points) - actual
    account.reserved_balance = max(
        ZERO_POINTS,
        point_value(account.reserved_balance) - point_value(run.reserved_points),
    )
    account.available_balance = point_value(account.available_balance) + release
    account.version += 1
    run.charged_points = actual
    run.settlement_status = "settled"
    if credential is not None:
        credential.status = "closed"
        credential.request_in_flight = False
    db.add(CreditLedger(
        user_id=run.user_id,
        entry_type="run_settlement",
        amount=release,
        available_after=account.available_balance,
        reserved_after=account.reserved_balance,
        run_id=run.id,
        business_key=f"run-settle:{run.id}",
        reason=(
            f"Platform model Run force release: {final_status}"
            if force_release else f"Platform model Run settlement: {final_status}"
        ),
        metadata_json=json.dumps(
            {
                "charged_points": point_number(actual),
                "incomplete_usage": incomplete_usage,
                "usage_events": event_count,
                "requested_events": requested_events,
                "force_release": force_release,
                "force_settle": force_settle,
                "actor_user_id": actor_user_id,
            },
            separators=(",", ":"),
        ),
    ))
    db.commit()


def reconcile_pending_platform_runs(
    db: Session,
    *,
    user_id: int | None = None,
    limit: int = 20,
) -> int:
    """Retry unsettled terminal runs, including old reservations left stranded."""
    query = db.query(AgentRun).filter(
        AgentRun.status.notin_(["queued", "running"]),
        or_(
            AgentRun.settlement_status == "pending_reconciliation",
            and_(
                AgentRun.settlement_status.in_(["reserved", "metering"]),
                AgentRun.finished_at.isnot(None),
                AgentRun.status.notin_(["queued", "running"]),
            ),
        ),
    )
    if user_id is not None:
        query = query.filter(AgentRun.user_id == user_id)
    runs = query.order_by(AgentRun.finished_at.asc()).limit(max(1, limit)).all()
    settled = 0
    for run in runs:
        settle_platform_run(db, run, run.status)
        if run.settlement_status == "settled":
            settled += 1
    return settled


def begin_gateway_request(raw_token: str, body: bytes) -> dict:
    db = SessionLocal()
    try:
        credential = db.query(ModelRunCredential).filter(
            ModelRunCredential.token_hash == token_hash(raw_token)
        ).with_for_update().first()
        if credential is None:
            raise CreditBillingError("Run Credential 无效", "INVALID_RUN_CREDENTIAL")
        run = db.query(AgentRun).filter(AgentRun.id == credential.run_id).first()
        if run is not None and is_realtime_run(run):
            db.rollback()
            return begin_metered_request(raw_token)
        if credential.status != "active":
            raise CreditBillingError("Run Credential 无效", "INVALID_RUN_CREDENTIAL")
        expires_at = credential.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            credential.status = "expired"
            db.commit()
            raise CreditBillingError("Run Credential 已过期", "RUN_CREDENTIAL_EXPIRED")
        if credential.request_in_flight:
            raise CreditBillingError("同一 Run 不允许并发模型请求", "CONCURRENT_MODEL_REQUEST")
        remaining = point_value(credential.max_points) - point_value(credential.consumed_points)
        if remaining <= 0:
            raise CreditBillingError(f"本次运行{credit_display_name(_active_policy(db))}额度已用尽", "RUN_BUDGET_EXHAUSTED")
        model = db.query(AIModel).filter(
            AIModel.id == credential.model_id,
            AIModel.scope == "platform",
            AIModel.is_enabled == True,
            AIModel.is_deleted == False,
        ).first()
        pricing = db.query(ModelPricingVersion).filter(
            ModelPricingVersion.id == credential.pricing_version_id
        ).one()
        if model is None:
            raise CreditBillingError("平台模型不可用", "PLATFORM_MODEL_UNAVAILABLE")

        conservative_input_rate = max(
            int(pricing.input_rate or 0),
            int(pricing.cache_read_rate or 0),
            int(pricing.cache_creation_rate or 0),
        )
        input_upper_points = (
            Decimal(len(body) * conservative_input_rate)
            / Decimal(max(1, int(pricing.rate_scale)))
        ).quantize(POINT_QUANTUM, rounding=ROUND_CEILING)
        if input_upper_points >= remaining:
            raise CreditBillingError("请求上下文超过本次运行剩余额度", "RUN_BUDGET_EXHAUSTED")

        credential.request_in_flight = True
        credential.request_count += 1
        request_number = credential.request_count
        db.commit()
        return {
            "credential_hash": credential.token_hash,
            "credential_id": credential.id,
            "request_number": request_number,
            "remaining_points": remaining,
            "input_upper_points": input_upper_points,
            "model_id": model.id,
            "model_name": model.name,
            "api_key": model.api_key,
            "api_base_url": model.api_proxy_url or "https://api.anthropic.com",
            "api_protocol": model.api_protocol,
            "pricing": {
                "input_rate": pricing.input_rate,
                "output_rate": pricing.output_rate,
                "cache_read_rate": pricing.cache_read_rate,
                "cache_creation_rate": pricing.cache_creation_rate,
                "rate_scale": pricing.rate_scale,
            },
        }
    finally:
        db.close()


def finish_gateway_request(context: dict, usage: dict, raw_usage: dict) -> None:
    if context.get("billing_mode") == "realtime":
        record_metered_usage(context, usage, raw_usage, terminal=True)
        return
    db = SessionLocal()
    try:
        credential = db.query(ModelRunCredential).filter(
            ModelRunCredential.id == context["credential_id"]
        ).with_for_update().one()
        # Identify a terminal event by our request number, not a provider retry ID.
        provider_request_id = f"gateway:{credential.id}:{context['request_number']}"
        existing_event = db.query(ModelUsageEvent.id).filter(
            ModelUsageEvent.provider_request_id == provider_request_id,
        ).first()
        if existing_event is not None:
            return
        pricing = db.query(ModelPricingVersion).filter(
            ModelPricingVersion.id == credential.pricing_version_id
        ).one()
        points = calculate_points(usage, pricing)
        consumed_points = point_value(credential.consumed_points)
        max_points = point_value(credential.max_points)
        if consumed_points + points > max_points:
            credential.status = "budget_exhausted"
            credential.request_in_flight = False
            db.commit()
            raise CreditBillingError("模型用量超过 Run 预算", "RUN_BUDGET_EXCEEDED")
        credential.consumed_points = consumed_points + points
        credential.request_in_flight = False
        db.add(ModelUsageEvent(
            run_id=credential.run_id,
            provider_request_id=provider_request_id,
            model_id=credential.model_id,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_read_tokens=int(usage.get("cache_read_tokens") or 0),
            cache_creation_tokens=int(usage.get("cache_creation_tokens") or 0),
            raw_usage=json.dumps(raw_usage, ensure_ascii=False, separators=(",", ":")),
        ))
        db.commit()
        run = db.query(AgentRun).filter(
            AgentRun.id == credential.run_id,
            AgentRun.settlement_status == "pending_reconciliation",
        ).first()
        if run is not None:
            settle_platform_run(db, run, run.status)
    finally:
        db.close()


def abort_gateway_request(context: dict, *, usage_unknown: bool = False) -> None:
    if context.get("billing_mode") == "realtime":
        record_metered_usage(context, {}, {"usage_unknown": usage_unknown},
                             terminal=True, usage_unknown=usage_unknown)
        return
    if not usage_unknown:
        finish_gateway_request(context, {}, {"upstream_connection_failed": True})
        return
    # A read/write failure may follow a billable request. Keep it for reconciliation.
    db = SessionLocal()
    try:
        credential = db.query(ModelRunCredential).filter(
            ModelRunCredential.id == context["credential_id"]
        ).with_for_update().first()
        if credential:
            credential.request_in_flight = False
            db.commit()
    finally:
        db.close()


USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")


def is_realtime_run(run) -> bool:
    try:
        return json.loads(run.pricing_snapshot or "{}").get("billing_mode") == "realtime"
    except (ValueError, TypeError, AttributeError):
        return False


def recorded_charged_points(run) -> float | None:
    """Live debits remain visible while incomplete requests are reconciled."""
    if run is not None and (run.settlement_status == "settled" or is_realtime_run(run)):
        return point_number(run.charged_points)
    return None


def _begin_billing_write(db):
    # MySQL serializes on the Run, credential and account rows. SQLite ignores
    # FOR UPDATE, so acquire its write lock before reading any mutable balance.
    if db.get_bind().dialect.name == "sqlite":
        from sqlalchemy import text
        db.execute(text("BEGIN IMMEDIATE"))


def _usage_totals(db, run_id):
    values = db.query(*[
        func.coalesce(func.sum(getattr(ModelUsageEvent, field)), 0)
        for field in USAGE_FIELDS
    ]).filter(ModelUsageEvent.run_id == run_id).one()
    return dict(zip(USAGE_FIELDS, map(int, values)))


def _account_stop(credential, account, policy, run=None):
    if account is None or account.status != "active":
        return "CREDIT_ACCOUNT_UNAVAILABLE", f"{credit_display_name(policy)}账户不可用，运行已终止"
    if (credential.status == "credits_exhausted"
            or (run is not None and run.error_code == "credits_exhausted")
            or point_value(account.available_balance) <= 0):
        return "CREDITS_EXHAUSTED", f"{credit_display_name(policy)}已用尽，运行已终止，请领取或充值后重试"
    return "", ""


def metered_run_snapshot(run_id: str) -> dict | None:
    """Fresh cross-worker control and progress, also used by channel runtimes."""
    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if run is None or not is_realtime_run(run):
            return None
        credential = db.query(ModelRunCredential).filter_by(run_id=run_id).first()
        if credential is None:
            return None
        account = db.query(CreditAccount).filter_by(user_id=credential.user_id).first()
        code, message = _account_stop(credential, account, _active_policy(db), run)
        return {
            "usage": _usage_totals(db, run_id),
            "charged_points": point_number(credential.consumed_points),
            "available_balance": point_number(account.available_balance) if account else 0,
            "error_code": code,
            "error_message": message,
        }
    finally:
        db.close()


def begin_metered_request(raw_token: str) -> dict:
    db = SessionLocal()
    try:
        _begin_billing_write(db)
        hint = db.query(ModelRunCredential.run_id).filter_by(token_hash=token_hash(raw_token)).first()
        if hint is None:
            raise CreditBillingError("Run Credential 无效", "INVALID_RUN_CREDENTIAL")
        run = db.query(AgentRun).filter_by(id=hint[0]).with_for_update().one()
        credential = db.query(ModelRunCredential).filter_by(
            token_hash=token_hash(raw_token),
        ).with_for_update().one()
        account = db.query(CreditAccount).filter_by(user_id=credential.user_id).with_for_update().first()
        code, message = _account_stop(credential, account, _active_policy(db), run)
        if code:
            raise CreditBillingError(message, code)
        expires_at = credential.expires_at.replace(tzinfo=timezone.utc) if credential.expires_at.tzinfo is None else credential.expires_at
        if credential.status != "active" or expires_at <= datetime.now(timezone.utc):
            raise CreditBillingError("Run Credential 无效或已过期", "INVALID_RUN_CREDENTIAL")
        if run.cancel_requested or run.status not in {"queued", "running"}:
            raise CreditBillingError("运行已终止", "RUN_TERMINATED")
        model = db.query(AIModel).filter_by(
            id=credential.model_id, scope="platform", is_enabled=True, is_deleted=False,
        ).first()
        if model is None:
            raise CreditBillingError("平台模型不可用", "PLATFORM_MODEL_UNAVAILABLE")
        pricing = db.get(ModelPricingVersion, credential.pricing_version_id)
        credential.request_count += 1
        request_id = f"gateway:{credential.id}:{credential.request_count}"
        db.add(ModelGatewayRequest(id=request_id, credential_id=credential.id,
                                   run_id=run.id, status="started"))
        context = {
            "billing_mode": "realtime", "request_id": request_id,
            "credential_id": credential.id, "request_number": credential.request_count,
            "run_id": run.id, "model_id": model.id, "model_name": model.name,
            "api_key": model.api_key,
            "api_base_url": model.api_proxy_url or "https://api.anthropic.com",
            "api_protocol": model.api_protocol,
            "pricing": {key: getattr(pricing, key) for key in (
                "input_rate", "output_rate", "cache_read_rate", "cache_creation_rate", "rate_scale",
            )},
        }
        db.commit()
        return context
    finally:
        db.close()


def record_metered_usage(context: dict, usage: dict, raw_usage: dict, *,
                         terminal=False, usage_unknown=False) -> dict:
    """Apply cumulative per-request usage once; round the total, never each delta.

    Serialize debits on the account across Runs and API workers. Provider usage
    is retained in full even if its last update exceeds the available credits;
    account debits stop at zero and the shortfall remains visible for auditing.
    """
    db = SessionLocal()
    try:
        _begin_billing_write(db)
        run = db.query(AgentRun).filter_by(id=context["run_id"]).with_for_update().one()
        credential = db.query(ModelRunCredential).filter_by(id=context["credential_id"]).with_for_update().one()
        request = db.query(ModelGatewayRequest).filter_by(id=context["request_id"]).with_for_update().one()
        account = db.query(CreditAccount).filter_by(user_id=credential.user_id).with_for_update().one()
        if request.status == "completed":
            # A duplicate completion must not debit a later top-up or alter state.
            code, message = _account_stop(credential, account, _active_policy(db), run)
            return {"error_code": code, "error_message": message}
        event = db.query(ModelUsageEvent).filter_by(provider_request_id=request.id).first()
        if event is None:
            event = ModelUsageEvent(run_id=run.id, provider_request_id=request.id,
                                    model_id=context["model_id"])
            db.add(event)
        for field in USAGE_FIELDS:
            setattr(event, field, max(int(getattr(event, field) or 0), max(0, int(usage.get(field) or 0))))
        pricing = db.get(ModelPricingVersion, credential.pricing_version_id)
        total_points = calculate_points({field: getattr(event, field) for field in USAGE_FIELDS}, pricing)
        delta = max(ZERO_POINTS, total_points - point_value(request.billed_points))
        # Final settlement fixes the charge. Late provider reports remain in
        # usage history, with their additional cost borne by the platform.
        debit = ZERO_POINTS if run.settlement_status == "settled" else min(
            delta, max(ZERO_POINTS, point_value(account.available_balance)),
        )
        request.billed_points = total_points
        request.charged_points = point_value(request.charged_points) + debit
        if debit > 0:
            account.available_balance = point_value(account.available_balance) - debit
            account.version += 1
            credential.consumed_points = point_value(credential.consumed_points) + debit
            run.charged_points = credential.consumed_points
            db.add(CreditLedger(
                user_id=credential.user_id, entry_type="model_usage", amount=-debit,
                available_after=account.available_balance, reserved_after=account.reserved_balance,
                run_id=run.id, business_key=f"usage:{request.id}:{total_points}",
                reason="Platform model reported usage",
                metadata_json=json.dumps({"request_id": request.id, "reported_points": str(total_points)}),
            ))
        previous_raw = json.loads(event.raw_usage or "{}")
        event.raw_usage = json.dumps({**previous_raw, **raw_usage,
            "reported_points": str(total_points), "charged_points": str(request.charged_points),
            "uncovered_points": str(total_points - request.charged_points),
        }, ensure_ascii=False)
        if terminal:
            request.status = "unknown" if usage_unknown else "completed"
        code, message = (None, None) if run.settlement_status == "settled" else _account_stop(
            credential, account, _active_policy(db), run,
        )
        if code:
            # Sticky for this Run, including after a user tops up the account.
            credential.status = "credits_exhausted" if code == "CREDITS_EXHAUSTED" else "disabled"
            run.cancel_requested = True
            run.error_code = code.lower()
            run.error_message = message
        db.flush()
        totals = _usage_totals(db, run.id)
        for field, amount in totals.items():
            setattr(run, field, amount)
        run.total_tokens = sum(totals.values())
        run.usage_detail = json.dumps(totals)
        db.commit()
        if terminal and run.status not in {"queued", "running"}:
            settle_metered_run(db, run, run.status)
        return {"error_code": code, "error_message": message}
    finally:
        db.close()


def settle_metered_run(db, run, final_status, *, force_settle=False, actor_user_id=None):
    """Close live metering without a second debit or a reservation refund."""
    run = db.query(AgentRun).filter_by(id=run.id).populate_existing().with_for_update().one()
    if run.settlement_status == "settled":
        db.rollback()
        return
    if force_settle and run.status not in {"succeeded", "failed", "cancelled", "timed_out"}:
        raise CreditBillingError("请先结束任务再强制结算", "RUN_NOT_TERMINAL")
    credential = db.query(ModelRunCredential).filter_by(run_id=run.id).with_for_update().first()
    incomplete = db.query(ModelGatewayRequest.id).filter(
        ModelGatewayRequest.run_id == run.id, ModelGatewayRequest.status != "completed",
    ).first() is not None
    if incomplete and not force_settle and not _incomplete_reconciliation_expired(run, credential):
        run.settlement_status = "pending_reconciliation"
        if credential is not None and credential.status == "active":
            credential.status = "reconciliation"
        db.commit()
        return
    run.settlement_status = "settled"
    totals = _usage_totals(db, run.id)
    for field, amount in totals.items():
        setattr(run, field, amount)
    run.total_tokens = sum(totals.values())
    run.usage_detail = json.dumps(totals)
    if credential is not None:
        run.charged_points = credential.consumed_points
        if credential.status not in {"credits_exhausted", "disabled"}:
            credential.status = "closed"
    account = db.query(CreditAccount).filter_by(user_id=run.user_id).with_for_update().one()
    db.add(CreditLedger(
        user_id=run.user_id, entry_type="run_settlement", amount=ZERO_POINTS,
        available_after=account.available_balance, reserved_after=account.reserved_balance,
        run_id=run.id, business_key=f"run-settle:{run.id}", reason=f"Live metering complete: {final_status}",
        metadata_json=json.dumps({"billing_mode": "realtime", "incomplete_usage": incomplete,
                                  "force_settle": force_settle, "actor_user_id": actor_user_id,
                                  "charged_points": str(run.charged_points)}),
    ))
    db.commit()
