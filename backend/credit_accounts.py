"""Idempotent account/claim initialization shared by UI and runtime entry points."""
from datetime import datetime, timedelta, timezone
import json
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models import CreditAccount, CreditClaimRecord, CreditLedger, PlatformAgentSettings
from credit_labels import credit_display_name
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

def _local_date(policy: PlatformAgentSettings):
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(policy.claim_timezone)).date()
        except Exception:
            pass
    return datetime.now(timezone(timedelta(hours=8))).date()


def _ensure_account(db: Session, user_id: int) -> CreditAccount:
    account = db.query(CreditAccount).filter(CreditAccount.user_id == user_id).first()
    if account:
        return account
    try:
        account = CreditAccount(user_id=user_id)
        db.add(account)
        db.commit()
        db.refresh(account)
        return account
    except IntegrityError:
        db.rollback()
        account = db.query(CreditAccount).filter(CreditAccount.user_id == user_id).first()
        if account is None:
            raise
        return account


def _claim_key(user_id: int, claim_type: str, claim_date) -> str:
    if claim_type == "initial":
        return f"initial-claim:{user_id}"
    return f"daily-claim:{user_id}:{claim_date.isoformat()}"


def _grant_claim(
    db: Session,
    *,
    user_id: int,
    policy: PlatformAgentSettings,
    claim_type: str,
) -> tuple[CreditAccount, CreditClaimRecord, bool]:
    claim_date = _local_date(policy)
    business_key = _claim_key(user_id, claim_type, claim_date)
    existing = db.query(CreditClaimRecord).filter(
        CreditClaimRecord.business_key == business_key
    ).first()
    if existing:
        return _ensure_account(db, user_id), existing, False

    # Create before taking a locking read: locking a missing account creates a
    # gap lock in MySQL and concurrent first visits can deadlock on insertion.
    _ensure_account(db, user_id)
    account = (
        db.query(CreditAccount)
        .filter(CreditAccount.user_id == user_id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    # Recheck after serialization using a current read, not a transaction's
    # older REPEATABLE READ snapshot. Concurrent claims must never regrant.
    existing = db.query(CreditClaimRecord).filter(
        CreditClaimRecord.business_key == business_key,
    ).with_for_update().first()
    if existing:
        db.commit()
        return account, existing, False
    if account.status != "active":
        raise HTTPException(
            status_code=409,
            detail={"message": f"{credit_display_name(policy)}账户已停用", "data": {"code": "CREDIT_ACCOUNT_DISABLED"}},
        )

    amount = policy.initial_claim_amount if claim_type == "initial" else policy.daily_claim_amount
    account.available_balance += amount
    account.version += 1
    record = CreditClaimRecord(
        user_id=user_id,
        claim_type=claim_type,
        claim_date=claim_date,
        amount=amount,
        policy_version=policy.version,
        business_key=business_key,
    )
    db.add(record)
    db.add(CreditLedger(
        user_id=user_id,
        entry_type=f"{claim_type}_claim",
        amount=amount,
        available_after=account.available_balance,
        reserved_after=account.reserved_balance,
        business_key=business_key,
        reason="Bootstrap credit" if claim_type == "initial" else "Daily credit claim",
        metadata_json=json.dumps({"policy_version": policy.version}, separators=(",", ":")),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(CreditClaimRecord).filter(
            CreditClaimRecord.business_key == business_key
        ).first()
        if existing is None:
            raise
        return _ensure_account(db, user_id), existing, False
    db.refresh(account)
    db.refresh(record)
    return account, record, True


def ensure_initial_credits(db, user_id, policy):
    account, _, _ = _grant_claim(db, user_id=user_id, policy=policy, claim_type="initial")
    return account
