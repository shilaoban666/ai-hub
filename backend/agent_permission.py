"""Durable permission decisions shared by every API process."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import CurrentUser, get_current_active_user
from database import SessionLocal, get_db
from models import AgentPermissionRequest, AgentRun
from schemas import PermissionDecideRequest, PermissionRequestInternal


router = APIRouter(prefix="/api/agents", tags=["agents"])
PERMISSION_TIMEOUT_SECONDS = 120
logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _tool_key(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        command = (tool_input or {}).get("command", "").strip()
        first = command.split()[0] if command else ""
        first = first.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return (f"Bash:{first}" if first else "Bash")[:300]
    return tool_name[:300]


def _persist_permission_request(body: PermissionRequestInternal) -> dict:
    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(
            AgentRun.id == body.run_id,
            AgentRun.status == "running",
            AgentRun.cancel_requested == False,
        ).first()
        if run is None:
            return {"ok": False, "detail": "运行不存在或已结束"}

        existing = db.query(AgentPermissionRequest).filter(
            AgentPermissionRequest.req_id == body.req_id
        ).first()
        if existing is not None:
            return {"ok": existing.run_id == body.run_id, "duplicate": True}

        serialized_input = json.dumps(body.tool_input or {}, ensure_ascii=False)
        if len(serialized_input.encode("utf-8")) > 200_000:
            return {"ok": False, "detail": "授权请求参数过大"}
        pending_count = db.query(AgentPermissionRequest.req_id).filter(
            AgentPermissionRequest.run_id == body.run_id,
            AgentPermissionRequest.status == "pending",
        ).count()
        if pending_count >= 20:
            return {"ok": False, "detail": "当前运行待处理授权请求过多"}

        now = utcnow()
        tool_key = _tool_key(body.tool_name, body.tool_input)
        remembered = db.query(AgentPermissionRequest.req_id).filter(
            AgentPermissionRequest.run_id == body.run_id,
            AgentPermissionRequest.tool_key == tool_key,
            AgentPermissionRequest.status == "decided",
            AgentPermissionRequest.decision == "allow",
            AgentPermissionRequest.remember == True,
        ).first() is not None
        request = AgentPermissionRequest(
            req_id=body.req_id,
            run_id=body.run_id,
            tool_key=tool_key,
            tool_name=body.tool_name,
            tool_input=serialized_input,
            status="decided" if remembered else "pending",
            decision="allow" if remembered else None,
            reason="" if remembered else None,
            remember=remembered,
            decided_at=now if remembered else None,
            expires_at=now + timedelta(seconds=PERMISSION_TIMEOUT_SECONDS),
        )
        db.add(request)
        db.commit()
        return {"ok": True, "remembered": remembered}
    except IntegrityError:
        db.rollback()
        existing = db.query(AgentPermissionRequest.req_id).filter(
            AgentPermissionRequest.req_id == body.req_id,
            AgentPermissionRequest.run_id == body.run_id,
        ).first()
        return {"ok": existing is not None, "duplicate": True}
    finally:
        db.close()


@router.post("/internal/permission-request")
async def permission_request(body: PermissionRequestInternal):
    return await asyncio.to_thread(_persist_permission_request, body)


def _read_permission_decision(run_id: str, req_id: str) -> dict | None:
    db = SessionLocal()
    try:
        request = db.query(AgentPermissionRequest).filter(
            AgentPermissionRequest.req_id == req_id,
            AgentPermissionRequest.run_id == run_id,
        ).with_for_update().first()
        if request is None:
            return {"decision": "deny", "reason": "请求不存在或已过期", "remembered": False}
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if run is None or run.status != "running" or run.cancel_requested:
            return {"decision": "deny", "reason": "运行已结束或已取消", "remembered": False}
        if request.status == "decided":
            return {
                "decision": request.decision or "deny",
                "reason": request.reason or "",
                "remembered": bool(request.remember),
            }
        now = utcnow()
        expires_at = _as_utc(request.expires_at)
        if request.status != "pending" or (expires_at is not None and expires_at <= now):
            request.status = "expired"
            request.decision = "deny"
            request.reason = "授权超时，已拒绝"
            request.decided_at = now
            db.commit()
            return {"decision": "deny", "reason": request.reason, "remembered": False}
        db.rollback()
        return None
    finally:
        db.close()


@router.get("/internal/permission-decide")
async def permission_decide(run_id: str, req_id: str):
    deadline = asyncio.get_running_loop().time() + PERMISSION_TIMEOUT_SECONDS
    failure_count = 0
    while True:
        try:
            result = await asyncio.to_thread(_read_permission_decision, run_id, req_id)
            failure_count = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            failure_count += 1
            if failure_count == 1 or failure_count % 20 == 0:
                logger.exception(
                    "Permission decision poll failed; retrying: run_id=%s req_id=%s",
                    run_id,
                    req_id,
                )
            result = None
        if result is not None:
            return result
        if asyncio.get_running_loop().time() >= deadline:
            return {"decision": "deny", "reason": "授权超时，已拒绝", "remembered": False}
        await asyncio.sleep(0.25)


@router.post("/{agent_id}/permission/decide")
async def user_decide(
    agent_id: int,
    body: PermissionDecideRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    request = db.query(AgentPermissionRequest).filter(
        AgentPermissionRequest.req_id == body.req_id,
        AgentPermissionRequest.run_id == body.run_id,
    ).with_for_update().first()
    owned_run = db.query(AgentRun).filter(
        AgentRun.id == body.run_id,
        AgentRun.agent_id == agent_id,
        AgentRun.user_id == current_user.user_id,
    ).first()
    if owned_run is None:
        db.rollback()
        return {"ok": False, "detail": "无权处理此授权请求"}

    if request is None:
        db.rollback()
        return {"ok": False, "code": "not_found", "resolved": True, "detail": "授权请求已失效"}
    if request.status == "expired":
        db.rollback()
        return {"ok": False, "code": "expired", "resolved": True, "detail": "授权超时，已拒绝"}
    if owned_run.status != "running" or owned_run.cancel_requested:
        db.rollback()
        return {"ok": False, "code": "run_ended", "resolved": True, "detail": "运行已结束或已取消，无需再授权"}
    if request.status != "pending":
        same_decision = (
            request.status == "decided"
            and request.decision == body.decision
            and bool(request.remember) == bool(body.remember and body.decision == "allow")
            and (request.reason or "") == (body.reason or "")
        )
        db.rollback()
        if same_decision:
            return {"ok": True, "duplicate": True}
        return {"ok": False, "code": "already_processed", "resolved": True, "detail": "该授权请求已处理"}

    now = utcnow()
    if _as_utc(request.expires_at) <= now:
        request.status = "expired"
        request.decision = "deny"
        request.reason = "授权超时，已拒绝"
        request.decided_at = now
        db.commit()
        return {"ok": False, "code": "expired", "resolved": True, "detail": request.reason}

    request.status = "decided"
    request.decision = body.decision
    request.reason = body.reason or ""
    request.remember = bool(body.remember and body.decision == "allow")
    request.decided_at = utcnow()
    db.commit()
    return {"ok": True}


def claim_pending_permission_events(run_id: str) -> list[dict]:
    db = SessionLocal()
    try:
        now = utcnow()
        requests = db.query(AgentPermissionRequest).filter(
            AgentPermissionRequest.run_id == run_id,
            AgentPermissionRequest.status == "pending",
            AgentPermissionRequest.delivered_at.is_(None),
            AgentPermissionRequest.expires_at > now,
        ).order_by(AgentPermissionRequest.created_at).with_for_update().all()
        events = []
        for request in requests:
            request.delivered_at = now
            try:
                tool_input = json.loads(request.tool_input or "{}")
            except json.JSONDecodeError:
                tool_input = {}
            events.append({
                "type": "permission_request",
                "req_id": request.req_id,
                "run_id": request.run_id,
                "tool_name": request.tool_name,
                "tool_input": tool_input,
                "tool_key": request.tool_key,
                "message": "智能体请求使用该工具，请选择授权方式。",
                "options": [
                    {"key": "deny-once", "label": "本次拒绝", "decision": "deny", "remember": False},
                    {"key": "allow-session", "label": "本轮始终允许", "decision": "allow", "remember": True},
                    {"key": "allow-once", "label": "本次允许", "decision": "allow", "remember": False},
                ],
            })
        db.commit()
        return events
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def cleanup_run(run_id: str):
    db = SessionLocal()
    try:
        now = utcnow()
        db.query(AgentPermissionRequest).filter(
            AgentPermissionRequest.run_id == run_id,
            AgentPermissionRequest.status == "pending",
        ).update({
            AgentPermissionRequest.status: "decided",
            AgentPermissionRequest.decision: "deny",
            AgentPermissionRequest.reason: "会话已结束",
            AgentPermissionRequest.decided_at: now,
        }, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
