"""Credential-scoped HTTP runs on the shared Agent execution service."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import lazyload

from agent_settings import runtime_agent
from asset_runtime import scoped_skill_query
from auth import CurrentUser, get_current_active_user
from database import SessionLocal, get_db, settings
from enterprise_workspace import utcnow
from model_compat import model_supports_runtime
from message_content import unpack_user_content
from models import (
    Agent, AgentMessage, AgentOpenCall, AgentOpenRequest, AgentRun, AgentSession,
    AIModel, Skill,
)

logger = logging.getLogger(__name__)
SOURCE = "api"
OPEN_PREFIX = "/api/open/agents/"
ADMIN_PREFIX = "/api/agents"
ACTIVE = ("queued", "running")
PROMPT_LIMIT = 16000
SYNC_WAIT_SECONDS = 8
QUEUE_TIMEOUT_SECONDS = 900
MAX_PENDING_PER_AGENT = 4
MAX_RUNS_PER_MINUTE = 20

router = APIRouter(
    prefix=ADMIN_PREFIX, tags=["agent-open-calls"],
    dependencies=[Depends(HTTPBearer(scheme_name="GatewayAuth", auto_error=False))],
)
open_router = APIRouter(prefix=OPEN_PREFIX.rstrip("/"), tags=["agent-open-calls"])


class OpenCallConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class OpenCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str | None = Field(None, max_length=100)
    prompt: str | None = Field(None, max_length=PROMPT_LIMIT)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lock_write(db):
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


def _agent(db, agent_id, *, locked=False):
    query = db.query(Agent).options(lazyload("*")).filter(
        Agent.id == agent_id, Agent.kind == "expert", Agent.is_deleted.is_(False),
    )
    return (query.with_for_update() if locked else query).first()


def _owned_agent(db, agent_id, user, *, locked=False):
    agent = _agent(db, agent_id, locked=locked)
    if agent is None or agent.user_id != user.user_id:
        raise HTTPException(404, "智能体不存在")
    return agent


def _model_id(db, agent):
    from sandbox.open_call import check_open_call_sandbox
    try:
        check_open_call_sandbox()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    resolved = runtime_agent(db, agent)
    if resolved.runtime_type != "claude_code":
        raise HTTPException(409, "开放调用需要 Claude Code Runtime")
    model = db.get(AIModel, agent.default_model_id) if agent.default_model_id else None
    if (model is None or model.is_deleted or not model.is_enabled
            or model.scope != "platform" or not model_supports_runtime(model, resolved.runtime_type)):
        raise HTTPException(409, "请先保存支持 Claude Code 的平台默认模型")
    return model.id


def _config_response(agent, config, *, key=None):
    return {
        "enabled": bool(config and config.key_digest),
        "query_enabled": settings.agent_open_call_allow_query,
        "path": _public_run_path(agent.id),
        **({"session_key": key} if key else {}),
    }


def _rotate_key(config):
    key = secrets.token_urlsafe(32)
    config.key_digest = _digest(key)
    config.generation = uuid4().hex
    return key


@router.get("/{agent_id}/open-call")
def read_open_call(agent_id: int, response: Response, db=Depends(get_db),
                   user: CurrentUser = Depends(get_current_active_user)):
    response.headers["Cache-Control"] = "no-store"
    agent = _owned_agent(db, agent_id, user)
    return _config_response(agent, db.get(AgentOpenCall, agent.id))


@router.put("/{agent_id}/open-call")
def save_open_call(agent_id: int, data: OpenCallConfig, response: Response, db=Depends(get_db),
                   user: CurrentUser = Depends(get_current_active_user)):
    response.headers["Cache-Control"] = "no-store"
    _lock_write(db)
    agent = _owned_agent(db, agent_id, user, locked=True)
    config = db.get(AgentOpenCall, agent.id)
    if config is None:
        config = AgentOpenCall(agent_id=agent.id, generation=uuid4().hex)
        db.add(config)

    if data.enabled:
        _model_id(db, agent)

    key = None
    if data.enabled and not config.key_digest:
        key = _rotate_key(config)
    elif not data.enabled and config.key_digest:
        config.key_digest = None
        config.generation = uuid4().hex
    db.commit()
    return _config_response(agent, config, key=key)


@router.post("/{agent_id}/open-call/rotate")
def rotate_open_call(agent_id: int, response: Response, db=Depends(get_db),
                     user: CurrentUser = Depends(get_current_active_user)):
    response.headers["Cache-Control"] = "no-store"
    _lock_write(db)
    agent = _owned_agent(db, agent_id, user, locked=True)
    config = db.get(AgentOpenCall, agent.id)
    if not config or not config.key_digest:
        raise HTTPException(409, "请先开启开放调用")
    key = _rotate_key(config)
    db.commit()
    return _config_response(agent, config, key=key)


def _owner_runs(db, agent):
    return db.query(AgentRun).filter_by(agent_id=agent.id, user_id=agent.user_id, source=SOURCE)


def _record(db, run, *, detail=False, user_message=None, queued=None):
    snapshot = json.loads(run.config_snapshot or "{}")
    submitted = snapshot.get("open_call_input") or {}
    if detail:
        queued = db.get(AgentOpenRequest, run.id)
        user_message = db.query(AgentMessage.content).filter_by(
            session_id=run.session_id, role="user",
        ).order_by(AgentMessage.id).first()
    user_content = unpack_user_content(user_message[0]) if user_message else {}
    prompt = submitted.get("prompt") if "prompt" in submitted else (
        user_content.get("content") or (queued.prompt if queued else None)
    )
    skill = submitted.get("skill") or (user_content.get("skill") or {}).get("name")
    if not skill and queued and queued.skill_id:
        skill = f"id:{queued.skill_id}"
    result = {
        "run_id": run.id, "status": run.status, "created_at": run.created_at,
        "started_at": run.started_at, "finished_at": run.finished_at,
        "duration_ms": run.duration_ms, "total_tokens": run.total_tokens,
        "charged_points": run.charged_points,
        "prompt": prompt if detail else (prompt[:200] if prompt else None),
        "skill": skill,
    }
    if detail:
        content = db.query(AgentMessage.content).filter_by(
            id=run.assistant_message_id, session_id=run.session_id, role="assistant",
        ).scalar() if run.assistant_message_id else None
        result.update(result=_final_text(content), error_code=run.error_code, error_message=run.error_message)
    return result


@router.get("/{agent_id}/open-call/runs")
def list_open_runs(agent_id: int, response: Response,
                   skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
                   run_id: str | None = Query(None, max_length=32),
                   db=Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    response.headers["Cache-Control"] = "no-store"
    agent = _owned_agent(db, agent_id, user)
    query = _owner_runs(db, agent)
    if run_id:
        query = query.filter(AgentRun.id == run_id)
    total = query.count()
    runs = query.order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).offset(skip).limit(limit).all()
    # Fetch prompts together, without loading tool outputs or assistant histories.
    messages = db.query(AgentMessage.session_id, AgentMessage.content).filter(
        AgentMessage.session_id.in_([run.session_id for run in runs]), AgentMessage.role == "user",
    ).order_by(AgentMessage.id).all() if runs else []
    prompts = {}
    for session_id, content in messages:
        prompts.setdefault(session_id, (content,))
    requests = {item.run_id: item for item in db.query(AgentOpenRequest).filter(
        AgentOpenRequest.run_id.in_([run.id for run in runs]),
    ).all()} if runs else {}
    return {"total": total, "items": [
        _record(db, run, user_message=prompts.get(run.session_id), queued=requests.get(run.id))
        for run in runs
    ]}


@router.get("/{agent_id}/open-call/runs/{run_id}")
def read_open_run(agent_id: int, run_id: str, response: Response, db=Depends(get_db),
                  user: CurrentUser = Depends(get_current_active_user)):
    response.headers["Cache-Control"] = "no-store"
    agent = _owned_agent(db, agent_id, user)
    run = _owner_runs(db, agent).filter(AgentRun.id == run_id).first()
    if run is None:
        raise HTTPException(404, "调用记录不存在")
    return _record(db, run, detail=True)


def _final_text(content):
    if not content:
        return None
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return content
    if not isinstance(payload, dict) or not isinstance(payload.get("blocks"), list):
        return content
    return "".join(
        block.get("content", "") for block in payload["blocks"]
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("content"), str)
    ).strip() or None


def _one(values):
    if len(values) > 1:
        raise HTTPException(422, "同一个参数只能传入一次")
    return values[0] if values else None


def _request_key(request):
    header = _one(request.headers.getlist("X-Agent-Key"))
    from_query = request.query_params.getlist("session_key")
    if from_query:
        if not settings.agent_open_call_allow_query:
            raise HTTPException(400, "请在 X-Agent-Key 请求头传入密钥")
        if header is not None:
            raise HTTPException(422, "密钥只能通过一种方式传入")
        header = _one(from_query)
    if not header or not re.fullmatch(r"[A-Za-z0-9_-]{43}", header):
        raise HTTPException(401, "密钥无效或开放调用已关闭")
    return header


def _authorized(db, agent_id, key, *, locked=False):
    agent = _agent(db, agent_id, locked=locked)
    config = db.get(AgentOpenCall, agent.id) if agent else None
    if not config or not config.key_digest or not hmac.compare_digest(config.key_digest, _digest(key)):
        raise HTTPException(401, "密钥无效或开放调用已关闭")
    return agent, config


async def _request_input(request):
    if set(request.query_params) - {"session_key", "skill", "prompt"}:
        raise HTTPException(422, "请求包含不支持的查询参数")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 250000:
            raise HTTPException(413, "请求体过大")
        body.extend(chunk)
    values = {}
    for name in ("skill", "prompt"):
        value = _one(request.query_params.getlist(name))
        if value is not None:
            if not settings.agent_open_call_allow_query:
                raise HTTPException(400, "请在 JSON 请求体传入 skill 和 prompt")
            values[name] = value
    try:
        if body:
            payload = json.loads(body)
            if not isinstance(payload, dict) or values.keys() & payload.keys():
                raise ValueError
            values.update(payload)
        data = OpenCallInput.model_validate(values)
    except (ValueError, ValidationError):
        raise HTTPException(422, "skill 或 prompt 的格式不正确，且不能通过两种方式重复传入") from None
    if any("\x00" in value or any(0xd800 <= ord(c) <= 0xdfff for c in value)
           for value in (data.prompt, data.skill) if value):
        raise HTTPException(422, "skill 或 prompt 含无效字符")
    return data


def _public_run_path(agent_id, run_id=None):
    base = f"/aihub{OPEN_PREFIX}{agent_id}/runs"
    return f"{base}/{run_id}" if run_id else base


def _queue(db, agent_id, key, data, idempotency):
    _lock_write(db)
    agent, config = _authorized(db, agent_id, key, locked=True)
    skill = (data.skill or "").strip()
    provided_prompt = (data.prompt or "").strip()
    fingerprint = _digest(json.dumps([skill, provided_prompt], ensure_ascii=False))
    namespace = None
    if idempotency:
        namespace = "api:" + _digest(f"{agent_id}:{config.generation}:{idempotency}")
        previous = db.query(AgentRun.id, AgentRun.idempotency_fingerprint).filter_by(
            user_id=agent.user_id, source=SOURCE, idempotency_key=namespace,
        ).first()
        if previous:
            if previous.idempotency_fingerprint != fingerprint:
                raise HTTPException(409, "Idempotency-Key 已用于内容不同的请求")
            return previous.id

    skill_id = None
    if skill:
        candidates = scoped_skill_query(db, agent, agent.user_id).with_entities(
            Skill.id, Skill.name,
        ).distinct().all()
        matches = [row.id for row in candidates if skill == f"id:{row.id}"]
        if not matches:
            matches = [row.id for row in candidates if skill == row.name]
        if len(matches) != 1:
            raise HTTPException(422, "技能不存在、未授权或名称重复，请检查技能标识")
        skill_id = matches[0]

    runs = db.query(AgentRun.id).filter_by(agent_id=agent_id, source=SOURCE)
    now = utcnow()
    if (runs.filter(AgentRun.status.in_(ACTIVE)).count() >= MAX_PENDING_PER_AGENT
            or runs.filter(AgentRun.created_at >= now - timedelta(minutes=1)).count() >= MAX_RUNS_PER_MINUTE):
        raise HTTPException(429, "开放调用过于频繁，请稍后再试", headers={"Retry-After": "5"})

    model_id = _model_id(db, agent)
    session = AgentSession(
        agent_id=agent.id, user_id=agent.user_id, source=SOURCE,
        title="开放调用", model_id=model_id, runtime_type="claude_code",
    )
    db.add(session)
    db.flush()
    run_id = uuid4().hex
    db.add(AgentRun(
        id=run_id, agent_id=agent.id, user_id=agent.user_id, session_id=session.id,
        source=SOURCE, status="queued", idempotency_key=namespace,
        idempotency_fingerprint=fingerprint if namespace else None,
        config_snapshot=json.dumps({"open_call_input": {"prompt": provided_prompt or None, "skill": skill or None}}, ensure_ascii=False),
        deadline_at=now + timedelta(seconds=QUEUE_TIMEOUT_SECONDS),
    ))
    db.flush()
    db.add(AgentOpenRequest(run_id=run_id, generation=config.generation, prompt=provided_prompt or None, skill_id=skill_id))
    db.commit()
    return run_id


def _result(db, agent_id, run_id, key):
    agent, config = _authorized(db, agent_id, key)
    run = db.query(AgentRun).join(AgentOpenRequest, AgentOpenRequest.run_id == AgentRun.id).filter(
        AgentRun.id == run_id, AgentRun.agent_id == agent.id, AgentRun.user_id == agent.user_id,
        AgentRun.source == SOURCE, AgentOpenRequest.generation == config.generation,
    ).first()
    if run is None:
        raise HTTPException(404, "运行不存在")
    payload = {"run_id": run.id, "status": run.status}
    if run.status == "succeeded":
        content = db.query(AgentMessage.content).filter_by(
            id=run.assistant_message_id, session_id=run.session_id, role="assistant",
        ).scalar() if run.assistant_message_id else None
        payload["result"] = _final_text(content) or ""
    elif run.status not in ACTIVE:
        error_code = run.error_code or "execution_failed"
        messages = {
            "queue_timeout": "任务在排队期间超时",
            "asset_resolution_failed": "智能体的技能或连接器加载失败，请检查智能体配置",
            "run_timeout": "智能体执行超时",
            "credits_exhausted": "智能体积分不足",
            "credit_account_unavailable": "智能体积分账户不可用",
            "open_call_config_changed": "智能体的开放调用配置已变更",
        }
        payload["error"] = {"code": error_code, "message": messages.get(error_code, "智能体执行未完成")}
    return payload


def _queue_request(agent_id, key, data, idempotency):
    with SessionLocal() as db:
        return _queue(db, agent_id, key, data, idempotency)


def _read_result(agent_id, run_id, key):
    with SessionLocal() as db:
        return _result(db, agent_id, run_id, key)


@open_router.post("/{agent_id}/runs", openapi_extra={"security": [], "requestBody": {
    "content": {"application/json": {"schema": OpenCallInput.model_json_schema()}},
}, "parameters": [
    {"name": "X-Agent-Key", "in": "header", "schema": {"type": "string"}},
    {"name": "Idempotency-Key", "in": "header", "schema": {"type": "string", "maxLength": 100}},
]})
async def submit_open_run(agent_id: int, request: Request):
    key = _request_key(request)
    data = await _request_input(request)
    idempotency = (_one(request.headers.getlist("Idempotency-Key")) or "").strip()
    if len(idempotency) > 100:
        raise HTTPException(422, "Idempotency-Key 长度不能超过 100 个字符")
    run_id = await asyncio.to_thread(_queue_request, agent_id, key, data, idempotency)
    deadline = time.monotonic() + SYNC_WAIT_SECONDS
    while True:
        payload = await asyncio.to_thread(_read_result, agent_id, run_id, key)
        if payload["status"] not in ACTIVE:
            return JSONResponse(payload)
        if time.monotonic() >= deadline:
            location = _public_run_path(agent_id, run_id)
            payload["status_url"] = location
            return JSONResponse(payload, status_code=202, headers={"Location": location, "Retry-After": "2"})
        await asyncio.sleep(0.4)


@open_router.get("/{agent_id}/runs/{run_id}", openapi_extra={"security": [], "parameters": [
    {"name": "X-Agent-Key", "in": "header", "schema": {"type": "string"}},
]})
def get_open_run(agent_id: int, run_id: str, request: Request, db=Depends(get_db)):
    key = _request_key(request)
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise HTTPException(404, "运行不存在")
    return _result(db, agent_id, run_id, key)


class _OpenCallAccessFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn access records carry the raw path plus query as argument #3.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            path = record.args[2]
            if isinstance(path, str) and OPEN_PREFIX in path.split("?", 1)[0]:
                args = list(record.args)
                args[2] = path.split("?", 1)[0]
                record.args = tuple(args)
        return True


def install_open_call_log_filter():
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _OpenCallAccessFilter) for item in access.filters):
        access.addFilter(_OpenCallAccessFilter())
