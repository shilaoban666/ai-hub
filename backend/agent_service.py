"""Agent execution orchestration shared by Web and external channels."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Awaitable, Callable

from sqlalchemy.orm import Session, lazyload
from sqlalchemy.exc import IntegrityError

from agent_execution_lease import acquire_agent_execution_lease, drain_worker, _run_sync_atomic
from agent_stream import StreamSnapshot, read_events, replay_events
from agent_stream_redis import get_store, MAX_BATCHES, MAX_DELTA_BYTES
from agent_memory import AgentMemory
from workspace_artifacts import changed_artifacts
from agent_permission import claim_pending_permission_events, cleanup_run
from agent_workspace import build_mcp_json, get_mcp_server_names, get_mcp_tool_permissions
from asset_runtime import load_runtime_assets
from conversation_title import fallback_session_title, generate_session_title
from database import SessionLocal, settings
from agent_access import agent_for_user, get_usable_agent
from agent_settings import runtime_agent, runtime_snapshot
from runtime_environment import load_global_runtime_environment
from credit_billing import (
    CreditBillingError,
    recorded_charged_points,
    prepare_platform_run,
    metered_run_snapshot,
    is_realtime_run,
    settle_platform_run,
)
from runtime_errors import safe_error_detail
from enterprise_workspace import (
    bind_agent_workspace,
    finish_run_view,
    record_run_view,
)
from model_compat import (
    configured_model_protocol,
    normalize_thinking_level,
    model_identity,
    model_supports_runtime,
    protocol_label,
)
from model_catalog import workbench_models
from models import Agent, AgentRun, AgentSession, AIModel, UserWorkspace, UserExecutionGate
from runtimes import get_runtime
from runtimes.attachments import build_runtime_attachments
from message_content import pack_user_content
from runtimes.base import (
    RuntimeConfig,
    RuntimeEvent,
    RuntimeRunContext,
)
from sandbox.base import WorkspaceContext, WorkspacePreparationError
from workspace_provider import (get_workspace_provider, agent_workspace_snapshot,
                                workspace_snapshot, workspace_model_snapshot)


logger = logging.getLogger(__name__)

_ACTIVE_WEB_RUNS: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task]] = {}
_WEB_STREAM_TASKS: set[asyncio.Task] = set()


def _agent_available_models(db: Session, agent: Agent, user_id: int) -> list[AIModel]:
    """Resolve models the same way as the personal AI workbench.

    Expert agent copies deliberately do not carry model bindings or API keys.
    """
    return workbench_models(db, user_id)


def _agent_default_model_id(db: Session, agent: Agent, user_id: int, *, models=None) -> int | None:
    if models is None:
        models = _agent_available_models(db, agent, user_id)
    runtime_type = getattr(agent, "runtime_type", None) or "claude_code"
    compatible = [model for model in models if model_supports_runtime(model, runtime_type)]
    available = {model.id for model in compatible}
    if agent.default_model_id in available:
        return agent.default_model_id
    return compatible[0].id if compatible else None


def cancel_web_run(run_id: str) -> bool:
    """Request cancellation for an in-process Web run."""
    entry = _ACTIVE_WEB_RUNS.get(run_id)
    if entry is None:
        return False
    loop, task = entry
    if task.done():
        return False
    loop.call_soon_threadsafe(task.cancel)
    return True


def _cleanup_deleted_agent_workspace_if_idle(db: Session, agent_id: int) -> None:
    deleted_agent = (
        db.query(Agent)
        .populate_existing()
        .filter(Agent.id == agent_id, Agent.is_deleted == True)
        .first()
    )
    if deleted_agent is None:
        return
    active_runs = db.query(AgentRun).filter(
        AgentRun.agent_id == agent_id,
        AgentRun.status.in_(["queued", "running"]),
    ).count()
    if active_runs:
        return
    # Agent deletion must never remove the user's shared persistent workspace.
    return

EventCallback = Callable[[RuntimeEvent], Awaitable[None]]
StartedCallback = Callable[[str, int], Awaitable[None]]
RunGuardCallback = Callable[[], Awaitable[bool]]
PersistStartedCallback = Callable[[], Awaitable[bool]]


async def _complete_turn_finalization(awaitable):
    """Finish cleanup/storage even when stop controls cancel the caller again.

    The child retains the run's lease checks; shielding does not authorize a
    stale execution to write. Its exceptions still propagate to the caller.
    """
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        return await drain_worker(task)


@dataclass
class AgentRunResult:
    run_id: str
    session_id: int
    blocks: list[dict]
    final_text: str
    usage: dict | None
    runtime_session_id: str | None
    status: str
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    error: str | None = None
    duration_ms: int | None = None
    charged_points: float | None = None


_RUNTIME_ERROR_PRESENTATIONS = (
    (
        ("insufficient account balance", "insufficient balance"),
        "model_balance_insufficient",
        "模型服务余额不足，请联系管理员充值或切换其他模型后重试。",
        100,
    ),
    (
        ("failed to authenticate", "authentication_error", "invalid api key", "invalid_api_key"),
        "model_authentication_failed",
        "模型服务认证失败，请联系管理员检查模型密钥配置。",
        90,
    ),
    (
        ("workspace has not been trusted",),
        "workspace_not_trusted",
        "工作区尚未完成信任初始化，请联系管理员重新初始化运行环境。",
        80,
    ),
    (
        ("model_not_found", "model not found", "unknown model", "invalid model",
         "model does not exist", "unrecognized model"),
        "model_not_supported",
        "当前模型不受运行环境支持，请联系管理员检查模型名称或切换其他模型。",
        60,
    ),
    (
        ("rate limit", "rate_limit"),
        "model_rate_limited",
        "模型服务当前请求过多，请稍后重试。",
        50,
    ),
    (
        ("upstream_timeout", "timed out", "timeout", "超时"),
        "model_request_timeout",
        "模型请求超时，请稍后重试，已生成的内容和已记录的用量已保留。",
        55,
    ),
    (
        ("upstream_connection_failed", "connection error", "connection reset",
         "connection refused", "econnreset", "econnrefused", "socket hang up"),
        "model_connection_failed",
        "模型服务连接中断，请稍后重试，已生成的内容和已记录的用量已保留。",
        55,
    ),
)


def _normalize_runtime_error_event(evt: RuntimeEvent) -> tuple[RuntimeEvent, int]:
    """Convert provider/CLI diagnostics into one actionable user-facing error."""
    code = str(evt.error_code or "").strip()
    raw = safe_error_detail(str(evt.content or ""))
    metadata = dict(evt.metadata or {})
    metadata["error_detail"] = safe_error_detail(str(metadata.get("error_detail") or raw))
    if code == "runtime_timeout":
        metadata["error_origin"] = "runtime"
    elif "[AIHub 模型网关]" in raw:
        metadata["error_origin"] = "aihub"
    elif not metadata.get("error_origin"):
        if "api error:" in raw.casefold():
            metadata["error_origin"] = "upstream"
        else:
            metadata["error_origin"] = "unknown"
    evt.metadata = metadata
    if code and code != "runtime_error":
        evt.content = raw or "智能体运行失败，请稍后重试。"
        priority = 100 if code == "model_balance_insufficient" else 70
        return evt, priority

    lowered = raw.casefold()
    for needles, normalized_code, message, priority in _RUNTIME_ERROR_PRESENTATIONS:
        if any(needle in lowered for needle in needles):
            evt.content = message
            evt.error_code = normalized_code
            if normalized_code in {"model_connection_failed", "model_request_timeout"}:
                metadata["error_origin"] = "model_connection"
            elif normalized_code == "workspace_not_trusted":
                metadata["error_origin"] = "runtime"
            elif metadata["error_origin"] == "unknown":
                metadata["error_origin"] = "upstream"
            return evt, priority

    evt.content = raw or "智能体运行失败，请稍后重试。"
    evt.error_code = code or "runtime_error"
    return evt, 10 if raw and raw != "未知错误" else 0


def _merge_usage(total: dict | None, current: dict | None) -> dict | None:
    """Accumulate incremental runtime usage events for the complete turn."""
    if not current:
        return total
    merged = dict(total or {})
    for key, value in current.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            merged[key] = merged.get(key, 0) + value
        elif key not in merged:
            merged[key] = value
    return merged


def _usage_metrics(usage: dict | None) -> dict:
    """Normalize provider usage keys into queryable AgentRun columns."""
    if not usage:
        return {}

    def number(*keys: str) -> int | None:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return max(0, int(value))
        return None

    input_tokens = number("input_tokens", "prompt_tokens")
    output_tokens = number("output_tokens", "completion_tokens")
    cache_read_tokens = number("cache_read_input_tokens", "cache_read_tokens")
    cache_creation_tokens = number(
        "cache_creation_input_tokens", "cache_creation_tokens"
    )
    total_tokens = number("total_tokens")
    if total_tokens is None:
        parts = (
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
        )
        if any(value is not None for value in parts):
            total_tokens = sum(value or 0 for value in parts)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "total_tokens": total_tokens,
        "usage_detail": json.dumps(usage, ensure_ascii=False),
    }


def apply_run_metrics(
    run: AgentRun | None,
    usage: dict | None,
    duration_ms: int | None,
) -> None:
    if run is None:
        return
    run.duration_ms = duration_ms
    for field, value in _usage_metrics(usage).items():
        setattr(run, field, value)


def _build_runtime_config(
    agent: Agent,
    model: AIModel,
    run_id: str = "",
    permission_mode: str = "",
    gateway_token: str = "",
    gateway_base_url: str = "",
) -> RuntimeConfig:
    """Build a runtime config from the persisted Agent and model."""
    is_platform_model = getattr(model, "scope", "user") == "platform"
    if is_platform_model and (not gateway_token or not gateway_base_url):
        raise RuntimeError("平台模型 Run Credential 尚未签发")
    extra = {}
    if run_id:
        extra["run_id"] = run_id
    if permission_mode:
        extra["permission_mode"] = permission_mode
    extra["mcp_server_names"] = get_mcp_server_names(
        getattr(agent, "runtime_mcps", None) or [],
    )
    mcp_permissions = get_mcp_tool_permissions(getattr(agent, "runtime_mcps", None) or [])
    extra["allowed_mcp_tools"] = mcp_permissions["allow"] + mcp_permissions["ask"]
    extra["thinking_level"] = normalize_thinking_level(
        model, getattr(agent, "thinking_level", "inherit")
    )
    extra["reasoning_visibility"] = (
        getattr(agent, "reasoning_visibility", "off") or "off"
    )

    return RuntimeConfig(
        runtime_type=agent.runtime_type or "claude_code",
        api_key=gateway_token if is_platform_model else (model.api_key or ""),
        api_base_url=gateway_base_url if is_platform_model else model.api_proxy_url,
        model=model.name or "",
        max_turns=agent.max_turns or 50,
        timeout_seconds=agent.timeout_seconds or 600,
        extra=extra,
    )


def _resolve_session(
    *,
    agent: Agent,
    user_input: str,
    session_id: int | None,
    user_id: int,
    db: Session,
    source: str,
    source_binding_id: int | None,
    runtime_type: str,
    model_id: int | None,
    workspace_id: int,
) -> AgentSession | None:
    if session_id:
        session = db.query(AgentSession).filter(
            AgentSession.id == session_id,
            AgentSession.agent_id == agent.id,
            AgentSession.user_id == user_id,
            AgentSession.is_deleted == False,
        ).first()
        if session is not None and session.model_id is None:
            session.model_id = model_id
            session.config_version = getattr(agent, "settings_version", None)
        if session is not None and session.workspace_id is None:
            session.workspace_id = workspace_id
        return session

    now = datetime.now(timezone.utc)
    session = AgentSession(
        agent_id=agent.id,
        user_id=user_id,
        workspace_id=workspace_id,
        source=source,
        source_binding_id=source_binding_id,
        runtime_type=runtime_type,
        model_id=model_id,
        config_version=getattr(agent, "settings_version", None),
        updated_at=now,
        title=user_input[:50] + ("..." if len(user_input) > 50 else ""),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


class _BlockTimingState:
    """Track block durations in memory until the assistant message is saved."""

    def __init__(self) -> None:
        self.thinking_started_at: float | None = None
        self.thinking_block_index: int | None = None
        self.tool_started_at: dict[int, float] = {}

    @staticmethod
    def _duration_ms(started_at: float, finished_at: float) -> int:
        return max(0, round((finished_at - started_at) * 1000))

    def needs_timestamp(self, evt: RuntimeEvent) -> bool:
        """Return whether this event starts or finishes a tracked interval."""
        if evt.type == "thinking":
            return self.thinking_started_at is None or bool(self.tool_started_at)
        if evt.type == "tool_use":
            return True
        if self.thinking_started_at is not None:
            return True
        if evt.type == "tool_result":
            return bool(self.tool_started_at)
        if evt.type in {"text", "done", "error"}:
            return bool(self.tool_started_at)
        return False

    def _finish_thinking(self, blocks: list[dict], now: float) -> None:
        index = self.thinking_block_index
        started_at = self.thinking_started_at
        if index is not None and started_at is not None and index < len(blocks):
            blocks[index]["duration_ms"] = self._duration_ms(started_at, now)
        self.thinking_started_at = None
        self.thinking_block_index = None

    def _finish_tool(self, blocks: list[dict], index: int, now: float) -> None:
        started_at = self.tool_started_at.pop(index, None)
        if started_at is not None and index < len(blocks):
            blocks[index]["duration_ms"] = self._duration_ms(started_at, now)

    def before_event(self, blocks: list[dict], evt: RuntimeEvent, now: float) -> None:
        if evt.type != "thinking":
            self._finish_thinking(blocks, now)

        if evt.type == "tool_result" and self.tool_started_at:
            candidates = [
                index
                for index in reversed(self.tool_started_at)
                if not evt.tool_use_id
                or blocks[index].get("tool_use_id") == evt.tool_use_id
            ]
            # If an ID is missing or does not match, finish the latest
            # unresolved tool instead of silently losing its timing.
            index = candidates[0] if candidates else next(reversed(self.tool_started_at))
            self._finish_tool(blocks, index, now)
        elif evt.type in {"text", "thinking", "done", "error"}:
            for index in list(self.tool_started_at):
                self._finish_tool(blocks, index, now)

    def after_event(self, blocks: list[dict], evt: RuntimeEvent, now: float) -> None:
        if evt.type == "thinking" and self.thinking_started_at is None:
            self.thinking_started_at = now
            self.thinking_block_index = len(blocks) - 1
        elif evt.type == "tool_use" and blocks:
            self.tool_started_at[len(blocks) - 1] = now

    def finish_all(self, blocks: list[dict], now: float | None = None) -> None:
        finished_at = time.monotonic() if now is None else now
        self._finish_thinking(blocks, finished_at)
        for index in list(self.tool_started_at):
            self._finish_tool(blocks, index, finished_at)


def _append_event_block(
    blocks: list[dict],
    evt: RuntimeEvent,
    *,
    timing: _BlockTimingState | None = None,
    now: float | None = None,
) -> None:
    should_time = timing is not None and timing.needs_timestamp(evt)
    event_time = (time.monotonic() if now is None else now) if should_time else 0.0
    if should_time:
        timing.before_event(blocks, evt, event_time)

    if evt.type == "text":
        if blocks and blocks[-1].get("type") == "text":
            blocks[-1]["content"] += evt.content
        else:
            blocks.append({"type": "text", "content": evt.content})
    elif evt.type == "thinking":
        if blocks and blocks[-1].get("type") == "thinking":
            blocks[-1]["content"] += evt.content
        else:
            blocks.append({"type": "thinking", "content": evt.content})
    elif evt.type == "tool_use":
        blocks.append({
            "type": "tool_use",
            "name": evt.tool_name,
            "input": evt.tool_input,
            "tool_use_id": evt.tool_use_id,
        })
    elif evt.type == "tool_result":
        blocks.append({
            "type": "tool_result",
            "tool_use_id": evt.tool_use_id,
            "content": evt.content,
            "is_error": evt.is_error,
        })
    elif evt.type == "usage":
        blocks.append({"type": "usage", "usage": evt.usage})
    elif evt.type == "artifacts":
        blocks.append({"type": "artifacts", "files": (evt.metadata or {}).get("files", [])})
    elif evt.type == "error":
        # Keep the selected diagnostic in permanent history as well as SSE.
        blocks[:] = [block for block in blocks if block.get("type") != "error"]
        blocks.append({"type": "error", "content": evt.content,
                       "error_code": evt.error_code, "metadata": evt.metadata})

    if should_time:
        timing.after_event(blocks, evt, event_time)


def _ensure_run_record(
    *,
    db: Session,
    run_id: str,
    agent: Agent,
    session_id: int,
    user_id: int,
    source: str,
    model_id: int | None,
    skill_id: int | None,
    permission_mode: str | None,
    runtime_type: str,
    workspace: UserWorkspace,
) -> AgentRun:
    now = datetime.now(timezone.utc)
    run = db.query(AgentRun).filter(AgentRun.id == run_id).populate_existing().with_for_update().first()
    if run is not None and (
        run.error_code in {"manual_recovery", "queue_timeout", "lease_expired"}
        or run.status in {"succeeded", "failed", "cancelled", "unknown"}
    ):
        db.rollback()
        raise asyncio.CancelledError
    snapshot = {
        "agent_id": agent.id,
        "workspace_id": workspace.id,
        "agent_updated_at": (
            agent.updated_at.isoformat() if getattr(agent, "updated_at", None) else None
        ),
        "system_prompt_sha256": hashlib.sha256(
            (getattr(agent, "system_prompt", None) or "").encode("utf-8")
        ).hexdigest(),
        "runtime_type": runtime_type,
        "model_id": model_id or agent.default_model_id,
        "config_version": getattr(agent, "settings_version", None),
        "skill_id": skill_id,
        "skills": [
            {"id": skill.id, "version": getattr(skill, "version", None)}
            for skill in (getattr(agent, "skills", None) or [])
        ],
        "mcp_ids": [m.id for m in agent.mcps],
        "permission_mode": permission_mode or "",
        "timeout_seconds": agent.timeout_seconds or 600,
        "max_turns": agent.max_turns or 50,
        "thinking_level": getattr(agent, "thinking_level", "inherit") or "inherit",
        "reasoning_visibility": (
            getattr(agent, "reasoning_visibility", "off") or "off"
        ),
    }
    if run is not None and source == "api":
        # Keep the accepted request available for owner audit, including failures
        # before a user message is written. Never copy credentials into snapshots.
        previous_snapshot = json.loads(run.config_snapshot or "{}")
        if "open_call_input" in previous_snapshot:
            snapshot["open_call_input"] = previous_snapshot["open_call_input"]
    if run is None:
        run = AgentRun(
            id=run_id,
            agent_id=agent.id,
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace.id,
            source=source,
            status="running",
            config_snapshot=json.dumps(snapshot, ensure_ascii=False),
            started_at=now,
            heartbeat_at=now,
            deadline_at=now + timedelta(seconds=agent.timeout_seconds or 600),
        )
        db.add(run)
    else:
        run.status = "running"
        run.session_id = session_id
        run.workspace_id = workspace.id
        run.config_snapshot = json.dumps(snapshot, ensure_ascii=False)
        run.started_at = run.started_at or now
        run.heartbeat_at = now
        run.deadline_at = run.deadline_at or (
            now + timedelta(seconds=agent.timeout_seconds or 600)
        )
        run.error_code = None
        run.error_message = None
    db.commit()
    return run


def _finish_run_record(
    db: Session,
    run: AgentRun | None,
    status: str,
    error: str | None = None,
    error_code: str | None = None,
    usage: dict | None = None,
    duration_ms: int | None = None,
) -> None:
    if run is None:
        return
    # A delayed worker must not overwrite a manual recovery from another process.
    with db.no_autoflush:
        run = db.query(AgentRun).filter(AgentRun.id == run.id).populate_existing().with_for_update().one()
    if run.error_code in {"manual_recovery", "queue_timeout", "lease_expired", "runtime_changed"} or run.status == "unknown":
        db.rollback()
        return
    now = datetime.now(timezone.utc)
    run.status = status
    run.heartbeat_at = now
    run.finished_at = now
    if duration_ms is None and run.started_at is not None:
        started_at = run.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        duration_ms = max(0, round((now - started_at).total_seconds() * 1000))
    apply_run_metrics(run, usage, duration_ms)
    run.lease_until = None
    run.error_code = (error_code or status) if error else None
    run.error_message = error[:2000] if error else None
    db.commit()
    try:
        settle_platform_run(db, run, status)
    except Exception:
        logger.exception("Platform credit settlement failed: run_id=%s", run.id)


async def _monitor_metered_run(run_id, owner_task, emit, *, interval=0.5):
    previous = None
    while True:
        snapshot = await asyncio.to_thread(metered_run_snapshot, run_id)
        if snapshot is not None:
            if snapshot != previous:
                await emit(RuntimeEvent(type="credit_usage", usage=snapshot["usage"], metadata=snapshot))
                previous = snapshot
            if snapshot["error_code"]:
                owner_task.cancel()
                return
        await asyncio.sleep(interval)


async def execute_agent_turn(
    *,
    agent: Agent,
    user_input: str,
    session_id: int | None,
    user_id: int,
    db: Session,
    on_event: EventCallback | None = None,
    on_started: StartedCallback | None = None,
    runtime_type_override: str | None = None,
    model_id_override: int | None = None,
    skill_id_override: int | None = None,
    attached_files: list[str] | None = None,
    permission_mode: str | None = None,
    run_id: str | None = None,
    page_context: dict | None = None,
    request_authorization: str | None = None,
    interactive_permissions: bool = False,
    source: str = "web",
    source_binding_id: int | None = None,
    manage_run_record: bool = True,
    run_guard: RunGuardCallback | None = None,
    workspace_commit: Callable | None = None,
    on_persist_started: PersistStartedCallback | None = None,
) -> AgentRunResult:
    """Execute one agent turn and emit structured RuntimeEvent objects.

    Callers own transport concerns. The Web adapter serializes events as SSE;
    channel workers collect the final text and enqueue an outbound message.
    """
    agent = runtime_agent(db, agent)
    # Every transport uses the same published runtime; per-request overrides
    # cannot bypass it. Resolve once so commits/publications cannot change a turn.
    runtime_type_override = agent.runtime_type
    turn_started_at = time.monotonic()
    current_run_id = run_id or uuid.uuid4().hex
    if source == "api" and (
        getattr(agent, "open_call_run_id", None) != current_run_id or agent.user_id != user_id
    ):
        raise RuntimeError("开放调用必须使用独立运行环境和智能体创建者身份")
    current_session_id = session_id or 0
    blocks: list[dict] = []
    block_timing = _BlockTimingState()
    usage: dict | None = None
    captured_runtime_session_id: str | None = None
    done_content = ""
    error_message: str | None = None
    error_code: str | None = None
    runtime_error_priority = 0
    status = "running"
    workspace_provider = None
    ws_ctx: WorkspaceContext | None = None
    artifact_baseline = None
    artifacts = []
    workspace_committed = False
    rt = None
    run_record: AgentRun | None = None
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    gateway_token = ""
    gateway_base_url = ""
    pending_thinking = ""
    last_cancel_check = 0.0
    agent = agent_for_user(db, agent, user_id)
    workspace, runtime_cell = bind_agent_workspace(db, agent)
    available_models = _agent_available_models(db, agent, user_id)
    resolved_default_model_id = _agent_default_model_id(db, agent, user_id, models=available_models)

    async def emit(evt: RuntimeEvent) -> None:
        if on_event is not None:
            await on_event(evt)

    async def guard_allows_persist() -> bool:
        if run_guard is None:
            return True
        try:
            return bool(await run_guard())
        except Exception:
            logger.exception("Agent run guard failed: run_id=%s", current_run_id)
            return False

    requested_runtime = runtime_type_override or agent.runtime_type or "claude_code"
    session = _resolve_session(
        agent=agent,
        user_input=user_input,
        session_id=session_id,
        user_id=user_id,
        db=db,
        source=source,
        source_binding_id=source_binding_id,
        runtime_type=requested_runtime,
        model_id=model_id_override or resolved_default_model_id,
        workspace_id=workspace.id,
    )
    if session is None:
        error_message = "会话不存在"
        await emit(RuntimeEvent(type="error", content=error_message))
        if manage_run_record:
            existing_run = db.query(AgentRun).filter(
                AgentRun.id == current_run_id
            ).first()
            _finish_run_record(db, existing_run, "failed", error_message)
        return AgentRunResult(
            run_id=current_run_id,
            session_id=current_session_id,
            blocks=[],
            final_text="",
            usage=None,
            runtime_session_id=None,
            status="failed",
            error=error_message,
        )

    current_session_id = session.id
    pinned_runtime = getattr(session, "runtime_type", None)
    if pinned_runtime and pinned_runtime != agent.runtime_type:
        session.runtime_type = agent.runtime_type
        session.runtime_session_id = None
        session.claude_session_id = None
        session.runtime_instance_id = None
        pinned_runtime = agent.runtime_type
    session.config_version = agent.settings_version
    if pinned_runtime and runtime_type_override and pinned_runtime != runtime_type_override:
        error_message = "当前会话已固定使用其他 Runtime，请新建会话后再切换"
        error_code = "runtime_session_mismatch"
        await emit(RuntimeEvent(
            type="error",
            content=error_message,
            error_code=error_code,
        ))
        return AgentRunResult(
            run_id=current_run_id,
            session_id=current_session_id,
            blocks=[],
            final_text="",
            usage=None,
            runtime_session_id=getattr(session, "runtime_session_id", None),
            status="failed",
            error=error_message,
        )
    effective_runtime = pinned_runtime or requested_runtime
    if not pinned_runtime:
        session.runtime_type = effective_runtime
    db.commit()
    captured_runtime_session_id = getattr(session, "runtime_session_id", None)
    if manage_run_record:
        run_record = _ensure_run_record(
            db=db,
            run_id=current_run_id,
            agent=agent,
            session_id=current_session_id,
            user_id=user_id,
            source=source,
            model_id=model_id_override,
            skill_id=skill_id_override,
            permission_mode=permission_mode,
            runtime_type=effective_runtime,
            workspace=workspace,
        )
    else:
        run_record = db.query(AgentRun).filter(
            AgentRun.id == current_run_id,
            AgentRun.agent_id == agent.id,
            AgentRun.user_id == user_id,
            AgentRun.session_id == current_session_id,
        ).first()
        if run_record is not None:
            snapshot = json.loads(run_record.config_snapshot or "{}")
            snapshot.update(runtime_snapshot(agent))
            snapshot["model_id"] = session.model_id or resolved_default_model_id
            run_record.config_snapshot = json.dumps(snapshot, ensure_ascii=False)
            run_record.deadline_at = datetime.now(timezone.utc) + timedelta(seconds=agent.timeout_seconds)
            db.commit()
    if on_started is not None:
        await on_started(current_run_id, current_session_id)

    effective_model_id = session.model_id or model_id_override or resolved_default_model_id
    model = db.query(AIModel).filter(
        AIModel.id == effective_model_id,
        AIModel.is_deleted == False,
    ).first()
    if not model:
        error_message = "智能体未绑定有效模型"
        await emit(RuntimeEvent(type="error", content=error_message))
        if manage_run_record:
            _finish_run_record(db, run_record, "failed", error_message)
        return AgentRunResult(
            run_id=current_run_id,
            session_id=current_session_id,
            blocks=[],
            final_text="",
            usage=None,
            runtime_session_id=None,
            status="failed",
            error=error_message,
        )

    bound_model_ids = {bound_model.id for bound_model in available_models}
    model_is_accessible = (
        model.user_id == user_id
        or (
            getattr(model, "scope", "user") == "platform"
            and getattr(model, "is_enabled", True)
        )
    )
    if (
        not model_is_accessible
        or not getattr(model, "is_enabled", True)
        or model.id not in bound_model_ids
    ):
        error_message = "所选模型未绑定到该智能体或无权访问"
        await emit(RuntimeEvent(type="error", content=error_message))
        if manage_run_record:
            _finish_run_record(db, run_record, "failed", error_message)
        return AgentRunResult(
            run_id=current_run_id,
            session_id=current_session_id,
            blocks=[],
            final_text="",
            usage=None,
            runtime_session_id=None,
            status="failed",
            error=error_message,
        )

    if not configured_model_protocol(model):
        error_message = f"{model_identity(model)} 尚未配置 API 协议"
    elif not model_supports_runtime(model, effective_runtime):
        error_message = (
            f"{effective_runtime} 不兼容 {model_identity(model)} "
            f"[{protocol_label(model.api_protocol)}]"
        )
    else:
        error_message = ""
    if error_message:
        await emit(RuntimeEvent(type="error", content=error_message))
        if manage_run_record:
            _finish_run_record(db, run_record, "failed", error_message)
        return AgentRunResult(
            run_id=current_run_id,
            session_id=current_session_id,
            blocks=[],
            final_text="",
            usage=None,
            runtime_session_id=None,
            status="failed",
            error=error_message,
        )

    if not await guard_allows_persist():
        error_message = "运行租约已失效，已停止保存结果"
        await emit(RuntimeEvent(type="error", content=error_message))
        return AgentRunResult(
            run_id=current_run_id,
            session_id=current_session_id,
            blocks=[],
            final_text="",
            usage=None,
            runtime_session_id=None,
            status="unknown",
            error=error_message,
        )

    if on_persist_started is not None:
        try:
            persist_started = bool(await on_persist_started())
        except Exception:
            logger.exception(
                "Agent persist-start callback failed: run_id=%s", current_run_id
            )
            persist_started = False
        if not persist_started:
            error_message = "运行租约已失效，未开始写入会话"
            await emit(RuntimeEvent(type="error", content=error_message))
            return AgentRunResult(
                run_id=current_run_id,
                session_id=current_session_id,
                blocks=[],
                final_text="",
                usage=None,
                runtime_session_id=None,
                status="unknown",
                error=error_message,
            )

    try:
        runtime_environment = {} if source == "api" else load_global_runtime_environment(db)
        runtime_assets = load_runtime_assets(
            db,
            agent,
            user_id,
            source=source,
            interactive_permissions=interactive_permissions,
            request_authorization=request_authorization,
        )
    except Exception as exc:
        logger.exception("Run asset resolution failed: run_id=%s", current_run_id)
        error_message = f"运行资产加载失败: {exc}"
        await emit(RuntimeEvent(type="error", content=error_message))
        if manage_run_record:
            _finish_run_record(db, run_record, "failed", error_message, error_code="asset_resolution_failed")
        return AgentRunResult(
            run_id=current_run_id,
            session_id=current_session_id,
            blocks=[],
            final_text="",
            usage=None,
            runtime_session_id=None,
            status="failed",
            error=error_message,
        )
    agent.runtime_skills = runtime_assets["skills"]
    agent.runtime_mcps = runtime_assets["mcps"]
    agent.runtime_secret_env = {**runtime_environment, **runtime_assets["secret_env"]}
    agent.runtime_capabilities = runtime_assets["effective_capabilities"]
    agent.runtime_requires_confirmation = runtime_assets["requires_confirmation"]
    # Bound templates are chat shortcuts, used only after the user selects and
    # fills them in. Reset each turn so an earlier combined prompt cannot leak
    # templates into the system instructions (including channel executions).
    agent.effective_system_prompt = getattr(agent, "system_prompt", None) or ""
    if run_record is not None:
        snapshot = json.loads(run_record.config_snapshot or "{}")
        snapshot["skill_installations"] = runtime_assets["skill_snapshot"]
        snapshot["mcp_connections"] = runtime_assets["mcp_snapshot"]
        snapshot["effective_asset_capabilities"] = runtime_assets["effective_capabilities"]
        snapshot["requires_tool_confirmation"] = runtime_assets["requires_confirmation"]
        if page_context:
            snapshot["page_context"] = page_context
        run_record.config_snapshot = json.dumps(snapshot, ensure_ascii=False)
        db.commit()

    if getattr(model, "scope", "user") == "platform":
        if run_record is None:
            error_message = "平台模型运行缺少可审计的 Run 记录"
            await emit(RuntimeEvent(type="error", content=error_message))
            return AgentRunResult(
                run_id=current_run_id,
                session_id=current_session_id,
                blocks=[],
                final_text="",
                usage=None,
                runtime_session_id=None,
                status="failed",
                error=error_message,
            )
        try:
            gateway_token, gateway_base_url = prepare_platform_run(
                db,
                run_record,
                model,
                agent.timeout_seconds or 600,
                effective_runtime,
            )
        except CreditBillingError as exc:
            error_message = str(exc)
            error_code = exc.code
            await emit(RuntimeEvent(
                type="error", content=error_message, error_code=error_code
            ))
            _finish_run_record(
                db, run_record, "failed", error_message, error_code=error_code
            )
            return AgentRunResult(
                run_id=current_run_id,
                session_id=current_session_id,
                blocks=[],
                final_text="",
                usage=None,
                runtime_session_id=None,
                status="failed",
                error=error_message,
            )

    memory = AgentMemory(db, current_session_id)

    # History must stop before the current prompt. This also prevents queued
    # channel messages from leaking into an earlier run.
    history = memory.load_history()
    history_info = getattr(memory, "history_info", None)
    if source == "web" and isinstance(history_info, dict) and history_info.get("compacted"):
        await emit(RuntimeEvent(
            type="context_notice",
            content="较早对话已精简，本轮已优先保留最近上下文。",
            metadata=history_info,
        ))
    available_skills = (
        agent.runtime_skills if hasattr(agent, "runtime_skills") else agent.skills
    )
    selected_skill = next((s for s in available_skills if s.id == skill_id_override), None)
    skill_reference = {"id": selected_skill.id, "name": selected_skill.name} if selected_skill else None
    user_message = memory.save_user_message(pack_user_content(user_input, attached_files, skill_reference))
    user_message_id = user_message.id
    should_generate_session_title = session.message_count <= 1
    if should_generate_session_title:
        session.title = fallback_session_title(user_input)
        db.commit()

    prompt_parts: list[str] = []
    if attached_files:
        image_links = [path for path in attached_files if path.startswith("https://")]
        workspace_files = [path for path in attached_files if not path.startswith("https://")]
        if image_links:
            prompt_parts.append("[用户上传了以下图片，请参考图片内容及其公网链接来回答问题：]")
            prompt_parts.extend(f"  图片公网链接: {path}" for path in image_links)
        if workspace_files:
            prompt_parts.append("[用户引用了以下工作区文件，请参考这些文件来回答问题：]")
            prompt_parts.extend(f"  文件: {path}" for path in workspace_files)
    if selected_skill:
        prompt_parts.append(
            f"[用户选定了技能「{selected_skill.name}」，请基于该技能的规则和知识来思考和执行]"
        )
    if prompt_parts:
        prompt_parts.append("")
    prompt_parts.append(user_input)
    effective_user_input = "\n".join(prompt_parts)

    filter_skills = None
    if skill_id_override is not None:
        filter_skills = [s for s in available_skills if s.id == skill_id_override]
        if source == "api" and not filter_skills:
            _finish_run_record(db, run_record, "failed", "开放技能已不可用", error_code="open_call_config_changed")
            return AgentRunResult(
                run_id=current_run_id, session_id=current_session_id, blocks=[], final_text="",
                usage=None, runtime_session_id=None, status="failed", error="开放技能已不可用",
            )

    try:
        workspace_provider = get_workspace_provider(agent)
        filesystem_agent = agent_workspace_snapshot(agent)
        filesystem_workspace = workspace_snapshot(workspace)
        filesystem_model = workspace_model_snapshot(model)
        try:
            def prepare_workspace():
                prepared = []
                def prepare():
                    prepared.append(workspace_provider.prepare_execution(
                        filesystem_agent, filesystem_model, run_id=current_run_id,
                        workspace=filesystem_workspace, filter_skills=filter_skills,
                    ))
                if workspace_commit is None:
                    prepare()
                elif not workspace_commit(prepare):
                    raise RuntimeError("execution lease lost before workspace preparation")
                return prepared[0]

            prepare_task = asyncio.create_task(asyncio.to_thread(prepare_workspace))
            try:
                ws_ctx = await asyncio.shield(prepare_task)
            except asyncio.CancelledError:
                # Preparation may create OS users or directories. Wait for the
                # thread so the outer cleanup can deterministically undo it.
                try:
                    ws_ctx = await drain_worker(prepare_task)
                except Exception:
                    logger.exception("Workspace preparation failed during cancellation")
                raise
            if ws_ctx is None:
                raise RuntimeError("workspace provider returned no runtime context")
            if getattr(filesystem_workspace, "migration_status", None) == "completed":
                workspace.migration_status = "completed"
            record_run_view(
                db,
                run_id=current_run_id,
                workspace=workspace,
                agent_id=agent.id,
                host_path=ws_ctx.execution_view_path or ws_ctx.host_workspace_path,
                sandbox_ref=(
                    ws_ctx.handle.get("container_name")
                    or ws_ctx.handle.get("username")
                    or ws_ctx.sandbox_type
                ),
                config_hash=runtime_cell.desired_config_hash,
            )
        except Exception as exc:
            logger.exception("Agent workspace preparation failed: agent_id=%s", agent.id)
            if isinstance(exc, WorkspacePreparationError):
                error_message = exc.public_message
            else:
                error_message = f"工作区准备失败（运行编号：{current_run_id}）"
            error_code = "workspace_preparation_failed"
            await emit(RuntimeEvent(
                type="error",
                content=error_message,
                error_code=error_code,
            ))
            status = "failed"
            if manage_run_record:
                _finish_run_record(
                    db,
                    run_record,
                    status,
                    error_message,
                    error_code=error_code,
                )
            return AgentRunResult(
                run_id=current_run_id,
                session_id=current_session_id,
                blocks=blocks,
                final_text="",
                usage=usage,
                runtime_session_id=None,
                status=status,
                error=error_message,
            )

        try:
            rt = get_runtime(effective_runtime)
        except ValueError as exc:
            error_message = str(exc)
            await emit(RuntimeEvent(type="error", content=error_message))
            status = "failed"
            if manage_run_record:
                _finish_run_record(db, run_record, status, error_message)
            return AgentRunResult(
                run_id=current_run_id,
                session_id=current_session_id,
                blocks=blocks,
                final_text="",
                usage=usage,
                runtime_session_id=None,
                status=status,
                error=error_message,
            )

        effective_permission_mode = permission_mode or ""
        if runtime_assets["requires_confirmation"]:
            effective_permission_mode = "default"
        runtime_config = _build_runtime_config(
            agent,
            model,
            current_run_id,
            permission_mode=effective_permission_mode,
            gateway_token=gateway_token,
            gateway_base_url=gateway_base_url,
        )
        if (
            ws_ctx.sandbox_type == "container"
            and getattr(model, "scope", "user") == "platform"
        ):
            runtime_config.api_base_url = settings.model_gateway_container_base_url
        runtime_config.runtime_type = effective_runtime
        resume_id = memory.get_runtime_session_id()
        if resume_id:
            runtime_config.extra["resume_id"] = resume_id

        runtime_run_context = RuntimeRunContext(
            run_id=current_run_id,
            session_id=current_session_id,
            runtime_session_id=captured_runtime_session_id,
            source=source,
            source_binding_id=source_binding_id,
            attached_files=await asyncio.to_thread(
                build_runtime_attachments, workspace_provider, filesystem_workspace,
                attached_files, effective_runtime,
            ),
            permission_mode=effective_permission_mode,
            include_history=True,
        )

        async def on_runtime_event(evt: RuntimeEvent) -> None:
            nonlocal captured_runtime_session_id, done_content, error_message, error_code, usage
            nonlocal pending_thinking, last_cancel_check, runtime_error_priority

            if source == "web" and run_record is not None:
                now_monotonic = asyncio.get_running_loop().time()
                if now_monotonic - last_cancel_check >= 0.5:
                    last_cancel_check = now_monotonic
                    if hasattr(db, "refresh"):
                        db.refresh(run_record, attribute_names=["cancel_requested"])
                    if run_record.cancel_requested:
                        raise asyncio.CancelledError

            reasoning_visibility = (
                getattr(agent, "reasoning_visibility", "off") or "off"
            )
            if source != "web":
                reasoning_visibility = "off"

            if evt.type == "thinking":
                if reasoning_visibility == "off":
                    return
                _append_event_block(blocks, evt, timing=block_timing)
                if reasoning_visibility == "on":
                    pending_thinking += evt.content
                    return
                await emit(evt)
                return

            if pending_thinking:
                await emit(RuntimeEvent(type="thinking", content=pending_thinking))
                pending_thinking = ""

            if evt.type == "permission_request" and not interactive_permissions:
                error_message = "当前渠道不支持交互授权，工具请求已拒绝"
                await emit(RuntimeEvent(type="error", content=error_message))
                return

            if evt.type == "info" and evt.tool_use_id:
                captured_runtime_session_id = evt.tool_use_id
            if evt.runtime_session_id:
                captured_runtime_session_id = evt.runtime_session_id
            if evt.runtime_run_id and run_record is not None and not run_record.runtime_run_id:
                run_record.runtime_run_id = evt.runtime_run_id
                db.commit()
            if evt.type == "usage":
                usage = _merge_usage(usage, evt.usage)
            elif evt.type == "done" and evt.content:
                done_content = evt.content
            elif evt.type == "error":
                evt, priority = _normalize_runtime_error_event(evt)
                if error_message and priority <= runtime_error_priority:
                    return
                runtime_error_priority = priority
                error_message = evt.content or "智能体执行失败"
                error_code = evt.error_code or "runtime_error"

            _append_event_block(blocks, evt, timing=block_timing)
            await emit(evt)

        if source != "api" and callable(getattr(workspace_provider, "snapshot_execution_files", None)):
            try:
                artifact_baseline = await asyncio.to_thread(
                    workspace_provider.snapshot_execution_files, ws_ctx, effective_runtime,
                )
            except Exception:
                logger.warning("Unable to snapshot output files: run_id=%s", current_run_id, exc_info=True)

        billing_task = None
        if gateway_token and is_realtime_run(run_record):
            billing_task = asyncio.create_task(_monitor_metered_run(
                current_run_id, asyncio.current_task(), emit,
            ))
        try:
            await rt.run(
                config=runtime_config,
                ctx=ws_ctx,
                user_input=effective_user_input,
                history=history,
                on_event=on_runtime_event,
                run_context=runtime_run_context,
            )
        finally:
            if billing_task is not None:
                billing_task.cancel()
                await asyncio.gather(billing_task, return_exceptions=True)
                snapshot = await asyncio.to_thread(metered_run_snapshot, current_run_id)
                if snapshot is not None:
                    usage = snapshot["usage"]
                    await emit(RuntimeEvent(type="credit_usage", usage=usage, metadata=snapshot))
                    if snapshot["error_code"]:
                        error_code = snapshot["error_code"].lower()
                        error_message = snapshot["error_message"]
        if error_code in {"credits_exhausted", "credit_account_unavailable"}:
            await emit(RuntimeEvent(type="error", content=error_message, error_code=error_code))
        status = "failed" if error_message else "succeeded"
        if error_message and "超时" in error_message:
            status = "timed_out"
    except asyncio.CancelledError:
        async def finish_cancellation():
            nonlocal status, error_code, error_message
            lease_valid = await guard_allows_persist()
            status = "cancelled" if lease_valid else "unknown"
            credit_stopped = lease_valid and error_code in {"credits_exhausted", "credit_account_unavailable"}
            if credit_stopped:
                status = "failed"
            else:
                error_code = "cancelled" if lease_valid else "lease_lost"
                error_message = (
                    "智能体运行已取消"
                    if lease_valid
                    else "运行租约已失效，执行结果需要人工核查"
                )
            if rt is not None:
                try:
                    await rt.cancel()
                except Exception:
                    logger.exception("Runtime cancellation failed: run_id=%s", current_run_id)
            if manage_run_record and not lease_valid:
                _finish_run_record(
                    db,
                    run_record,
                    status,
                    error_message,
                    error_code=error_code,
                    usage=usage,
                    duration_ms=max(0, round((time.monotonic() - turn_started_at) * 1000)),
                )
            if not lease_valid:
                raise asyncio.CancelledError
            await emit(RuntimeEvent(
                type="error" if credit_stopped else "cancelled",
                content=error_message,
                error_code=error_code,
            ))

        await _complete_turn_finalization(finish_cancellation())
    except Exception as exc:
        logger.exception("Agent execution failed: run_id=%s", current_run_id)
        error_message = safe_error_detail(str(exc))
        error_code = "execution_error"
        status = "failed"
        event = RuntimeEvent(type="error", content=error_message, error_code=error_code,
                             metadata={"error_origin": "aihub", "error_detail": error_message})
        _append_event_block(blocks, event)
        await _complete_turn_finalization(emit(event))
    finally:
        async def finalize_workspace():
            nonlocal workspace_committed, artifacts, status, error_message, error_code
            block_timing.finish_all(blocks)
            if workspace_provider is not None and ws_ctx is not None:
                try:
                    if artifact_baseline is not None:
                        try:
                            artifact_snapshot = await asyncio.to_thread(
                                workspace_provider.snapshot_execution_files, ws_ctx, effective_runtime,
                            )
                            artifacts = changed_artifacts(artifact_baseline, artifact_snapshot)
                        except Exception:
                            logger.warning("Unable to collect output files: run_id=%s", current_run_id, exc_info=True)
                    async def cleanup_workspace():
                        may_write = await guard_allows_persist()
                        def write_or_discard():
                            committed = False
                            if may_write:
                                if workspace_commit is None:
                                    workspace_provider.cleanup(ws_ctx)
                                    committed = True
                                else:
                                    committed = workspace_commit(lambda: workspace_provider.cleanup(ws_ctx))
                            if not committed:
                                workspace_provider.discard_execution(ws_ctx)
                            return committed
                        committed = await _run_sync_atomic(write_or_discard)
                        try:
                            finish_run_view(
                                db, current_run_id, success=committed,
                                error=None if committed else "execution lease lost; workspace discarded",
                            )
                        except Exception:
                            db.rollback()
                            logger.exception(
                                "Run view audit update failed: run_id=%s", current_run_id
                            )
                        return committed

                    workspace_committed = await cleanup_workspace()
                except Exception as cleanup_exc:
                    logger.exception("Workspace cleanup failed: run_id=%s", current_run_id)
                    workspace_error = f"工作区文件保存失败，文件改动未确认保存（运行编号：{current_run_id}）"
                    error_message = (
                        f"{error_message}；{workspace_error}" if error_message else workspace_error
                    )
                    error_code = error_code or "workspace_writeback_failed"
                    if status == "succeeded":
                        status = "failed"
                    try:
                        finish_run_view(
                            db,
                            current_run_id,
                            success=False,
                            error=str(cleanup_exc),
                        )
                    except Exception:
                        db.rollback()
                        logger.exception(
                            "Run view audit update failed: run_id=%s", current_run_id
                        )
                    if status not in {"cancelled", "unknown"}:
                        try:
                            await emit(RuntimeEvent(
                                type="error", content=error_message, error_code=error_code,
                            ))
                        except Exception:
                            logger.exception(
                                "Workspace failure event delivery failed: run_id=%s", current_run_id
                            )

        await _complete_turn_finalization(finalize_workspace())

    async def persist_turn():
        nonlocal assistant_message_id, status, error_code, error_message
        if not any(block.get("type") == "text" for block in blocks) and done_content:
            blocks.append({"type": "text", "content": done_content})
        final_text = "".join(
            block.get("content", "")
            for block in blocks
            if block.get("type") == "text"
        ).strip()
        if not await guard_allows_persist():
            return AgentRunResult(
                run_id=current_run_id,
                session_id=current_session_id,
                blocks=blocks,
                final_text=final_text,
                usage=usage,
                runtime_session_id=captured_runtime_session_id,
                status="unknown",
                user_message_id=user_message_id,
                error="运行租约已失效，结果未写入会话",
            )
        duration_ms = max(0, round((time.monotonic() - turn_started_at) * 1000))
        if workspace_committed and artifacts:
            artifact_event = RuntimeEvent(type="artifacts", metadata={"files": artifacts})
            _append_event_block(blocks, artifact_event)
            await emit(artifact_event)
        if blocks:
            assistant_message = memory.save_assistant_message(
                blocks,
                usage=usage,
                duration_ms=duration_ms,
            )
            if assistant_message is not None:
                assistant_message_id = assistant_message.id
                if run_record is not None:
                    run_record.assistant_message_id = assistant_message_id
                # Knowledge base searches made through the agent's MCP server count toward the
                # knowledge usage board, on a background thread; nothing here may fail the turn.
                try:
                    from knowledge_routes import record_chat_knowledge_safely
                    record_chat_knowledge_safely(db.get_bind(), blocks, user_id=user_id,
                                                 session_id=current_session_id)
                except Exception:
                    logger.warning("knowledge usage hook skipped: run_id=%s", current_run_id, exc_info=True)
            else:
                status = "failed"
                error_code = "assistant_message_save_failed"
                error_message = (
                    "回复保存失败，请勿关闭当前页面；请联系管理员处理"
                    f"（运行编号：{current_run_id}）"
                )
                logger.error("Assistant output was not saved: run_id=%s", current_run_id)
                await emit(RuntimeEvent(type="error", content=error_message, error_code=error_code))
        if captured_runtime_session_id:
            memory.set_runtime_session_id(captured_runtime_session_id)
        if source != "api" and should_generate_session_title and status == "succeeded" and final_text:
            session.title = await generate_session_title(model, user_input)
        db.commit()
        if manage_run_record:
            _finish_run_record(
                db,
                run_record,
                status,
                error_message,
                error_code=error_code,
                usage=usage,
                duration_ms=duration_ms,
            )

        charged_points = recorded_charged_points(run_record)

        return AgentRunResult(
            run_id=current_run_id,
            session_id=current_session_id,
            blocks=blocks,
            final_text=final_text,
            usage=usage,
            runtime_session_id=captured_runtime_session_id,
            status=status,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            error=error_message,
            duration_ms=duration_ms,
            charged_points=charged_points,
        )

    return await _complete_turn_finalization(persist_turn())


def _lock_user_queue_gate(db: Session, user_id: int) -> None:
    """Serialize Web queue admission for one user across API workers."""
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        from sqlalchemy.dialects.mysql import insert
        db.execute(insert(UserExecutionGate).values(user_id=user_id).on_duplicate_key_update(user_id=user_id))
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        db.execute(insert(UserExecutionGate).values(user_id=user_id).on_conflict_do_nothing())
    else:
        if db.query(UserExecutionGate.user_id).filter_by(user_id=user_id).first() is None:
            db.add(UserExecutionGate(user_id=user_id))
            db.flush()
    db.query(UserExecutionGate.user_id).filter_by(user_id=user_id).with_for_update().one()


def _queue_web_run(
    agent_id: int,
    user_input: str,
    session_id: int | None,
    user_id: int,
    runtime_type_override: str | None,
    model_id_override: int | None,
    run_id: str,
    idempotency_key: str | None = None,
    idempotency_fingerprint: str | None = None,
) -> dict:
    db = SessionLocal()
    try:
        if idempotency_key:
            existing = db.query(AgentRun).filter(
                AgentRun.user_id == user_id,
                AgentRun.source == "web",
                AgentRun.idempotency_key == idempotency_key,
            ).first()
            if existing is not None:
                if (
                    idempotency_fingerprint
                    and existing.idempotency_fingerprint
                    and existing.idempotency_fingerprint != idempotency_fingerprint
                ):
                    raise RuntimeError("Idempotency-Key 已用于其他请求")
                return {
                    "session_id": existing.session_id,
                    "run_id": existing.id,
                    "reused": True,
                }

        _lock_user_queue_gate(db, user_id)
        queued_count = db.query(AgentRun.id).filter(
            AgentRun.user_id == user_id,
            AgentRun.source == "web",
            AgentRun.status == "queued",
        ).count()
        if queued_count >= max(1, int(settings.agent_max_queued_runs)):
            raise RuntimeError("当前排队中的运行过多，请稍后再试")

        agent = get_usable_agent(db, agent_id, user_id)
        agent = runtime_agent(db, agent)
        workspace, _ = bind_agent_workspace(db, agent)
        requested_runtime = agent.runtime_type or "claude_code"
        session = _resolve_session(
            agent=agent,
            user_input=user_input,
            session_id=session_id,
            user_id=user_id,
            db=db,
            source="web",
            source_binding_id=None,
            runtime_type=requested_runtime,
            model_id=model_id_override or _agent_default_model_id(db, agent, user_id),
            workspace_id=workspace.id,
        )
        if session is None:
            raise RuntimeError("会话不存在")
        now = datetime.now(timezone.utc)
        db.add(AgentRun(
            id=run_id,
            agent_id=agent_id,
            session_id=session.id,
            user_id=user_id,
            workspace_id=workspace.id,
            source="web",
            idempotency_key=idempotency_key,
            idempotency_fingerprint=idempotency_fingerprint,
            status="queued",
            config_snapshot=json.dumps({
                **runtime_snapshot(agent),
                "queued_at": now.isoformat(),
            }, ensure_ascii=False),
            deadline_at=now + timedelta(seconds=agent.timeout_seconds or 600),
        ))
        db.commit()
        if idempotency_key:
            return {"session_id": session.id, "run_id": run_id, "reused": False}
        # Keep the helper's long-standing return contract for internal callers
        # that do not opt into idempotency.
        return session.id
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.query(AgentRun).filter(
                AgentRun.user_id == user_id,
                AgentRun.source == "web",
                AgentRun.idempotency_key == idempotency_key,
            ).first()
            if existing is not None:
                if (
                    idempotency_fingerprint
                    and existing.idempotency_fingerprint
                    and existing.idempotency_fingerprint != idempotency_fingerprint
                ):
                    raise RuntimeError("Idempotency-Key 已用于其他请求")
                return {
                    "session_id": existing.session_id,
                    "run_id": existing.id,
                    "reused": True,
                }
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _queued_web_run_is_active(run_id: str) -> bool:
    db = SessionLocal()
    try:
        run = db.query(AgentRun.id).filter(
            AgentRun.id == run_id,
            AgentRun.status == "queued",
            AgentRun.cancel_requested == False,
        ).first()
        return run is not None
    finally:
        db.close()


def _web_run_workspace_id(run_id: str) -> int:
    db = SessionLocal()
    try:
        row = db.query(AgentRun.workspace_id).filter(AgentRun.id == run_id).first()
        if row is None or row[0] is None:
            raise RuntimeError("run is not bound to a user workspace")
        return int(row[0])
    finally:
        db.close()


def _web_run_cancel_requested(run_id: str) -> bool:
    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        return run is None or bool(run.cancel_requested)
    finally:
        db.close()


def _cancel_queued_web_run(run_id: str) -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        db.query(AgentRun).filter(
            AgentRun.id == run_id,
            AgentRun.status == "queued",
        ).update({
            AgentRun.status: "cancelled",
            AgentRun.cancel_requested: True,
            AgentRun.finished_at: now,
            AgentRun.error_code: "cancelled",
            AgentRun.error_message: "智能体运行已取消",
        }, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Unable to cancel queued Web run: run_id=%s", run_id)
    finally:
        db.close()


def _finalize_unresolved_web_run(
    run_id: str,
    status: str,
    error_message: str | None = None,
    error_code: str | None = None,
) -> None:
    """Idempotently close a Web run left unresolved by an early exit."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        values = {
            AgentRun.status: status,
            AgentRun.heartbeat_at: now,
            AgentRun.finished_at: now,
            AgentRun.lease_until: None,
            AgentRun.error_code: (error_code or status) if error_message else None,
            AgentRun.error_message: error_message[:2000] if error_message else None,
        }
        if status == "cancelled":
            values[AgentRun.cancel_requested] = True
        db.query(AgentRun).filter(
            AgentRun.id == run_id,
            AgentRun.status.in_(["queued", "running"]),
        ).update(values, synchronize_session=False)
        db.commit()
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if run is not None and run.status not in {"queued", "running"}:
            try:
                settle_platform_run(db, run, run.status)
            except Exception:
                logger.exception("Platform credit settlement failed: run_id=%s", run.id)
    except Exception:
        db.rollback()
        logger.exception(
            "Unable to finalize unresolved Web run: run_id=%s status=%s",
            run_id,
            status,
        )
    finally:
        db.close()


def _cleanup_deleted_agent_workspace(agent_id: int) -> None:
    db = SessionLocal()
    try:
        _cleanup_deleted_agent_workspace_if_idle(db, agent_id)
    finally:
        db.close()


async def _monitor_web_run_controls(
    run_id: str,
    owner_task: asyncio.Task,
    queue: asyncio.Queue[str],
    *,
    interval: float | None = None,
) -> None:
    poll_interval = max(
        0.01,
        float(
            settings.agent_run_control_poll_seconds
            if interval is None
            else interval
        ),
    )
    cancel_failures = 0
    permission_failures = 0
    while True:
        await asyncio.sleep(poll_interval)
        try:
            cancelled = await asyncio.to_thread(_web_run_cancel_requested, run_id)
            cancel_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            cancel_failures += 1
            if cancel_failures == 1 or cancel_failures % 20 == 0:
                logger.exception(
                    "Web run cancellation poll failed; retrying: run_id=%s",
                    run_id,
                )
            cancelled = False

        # Cancellation must not wait for permission delivery or its database query.
        if cancelled:
            if not owner_task.done():
                owner_task.cancel()
            return

        try:
            permission_events = await asyncio.to_thread(
                claim_pending_permission_events,
                run_id,
            )
            permission_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            permission_failures += 1
            if permission_failures == 1 or permission_failures % 20 == 0:
                logger.exception(
                    "Permission event poll failed; retrying: run_id=%s",
                    run_id,
                )
            continue
        for event in permission_events:
            await queue.put(
                f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            )


async def _run_agent_chat_feed(
    agent_id: int,
    user_input: str,
    session_id: int | None,
    user_id: int,
    runtime_type_override: str | None = None,
    model_id_override: int | None = None,
    skill_id_override: int | None = None,
    attached_files: list[str] | None = None,
    permission_mode: str | None = None,
    page_context: dict | None = None,
    request_authorization: str | None = None,
    idempotency_key: str | None = None,
    idempotency_fingerprint: str | None = None,
) -> AsyncGenerator[str, None]:
    """Web transport adapter that serializes structured events as SSE."""

    def sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    run_id = uuid.uuid4().hex
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)

    try:
        queued = await asyncio.to_thread(
            _queue_web_run,
            agent_id,
            user_input,
            session_id,
            user_id,
            runtime_type_override,
            model_id_override,
            run_id,
            idempotency_key,
            idempotency_fingerprint,
        )
    except Exception as exc:
        logger.exception("Unable to queue Web Agent run: agent_id=%s", agent_id)
        yield sse({"type": "error", "content": str(exc)})
        return

    if isinstance(queued, dict):
        queued_session_id = queued["session_id"]
        run_id = queued["run_id"]
        reused = queued["reused"]
    else:
        queued_session_id = queued
        reused = False
    if reused:
        yield sse({
            "type": "run_queued",
            "run_id": run_id,
            "session_id": queued_session_id,
            "user_content": user_input,
        })
        async for chunk in replay_events(SessionLocal, run_id):
            yield chunk
        return

    async def on_started(started_run_id: str, started_session_id: int) -> None:
        # Force small status frames through proxy buffers before model output starts.
        flush_padding = ": " + (" " * 4096) + "\n\n"
        def read_started_at():
            with SessionLocal() as started_db:
                started_run = started_db.get(AgentRun, started_run_id)
                return started_run.started_at if started_run is not None else None

        started_at = await asyncio.to_thread(read_started_at)
        await queue.put(flush_padding + sse({
            "type": "run_start",
            "run_id": started_run_id,
            "session_id": started_session_id,
            "started_at": (started_at or datetime.now(timezone.utc)).isoformat(),
        }))

    async def on_event(evt: RuntimeEvent) -> None:
        await queue.put(evt.to_sse())

    async def wait_guard() -> bool:
        return await asyncio.to_thread(_queued_web_run_is_active, run_id)

    async def run_feed() -> None:
        execution_db: Session | None = None
        control_task: asyncio.Task | None = None
        try:
            workspace_id = await asyncio.to_thread(_web_run_workspace_id, run_id)
            execution_lease = await acquire_agent_execution_lease(
                workspace_id=workspace_id,
                run_id=run_id,
                wait_guard=wait_guard,
                session_factory=SessionLocal,
            )
            async with execution_lease:
                if not await wait_guard():
                    raise asyncio.CancelledError
                execution_db = SessionLocal()
                agent = get_usable_agent(execution_db, agent_id, user_id)
                owner_task = asyncio.current_task()
                control_task = asyncio.create_task(
                    _monitor_web_run_controls(run_id, owner_task, queue),
                    name=f"agent-run-control-{run_id}",
                )
                result = await execute_agent_turn(
                    agent=agent,
                    user_input=user_input,
                    session_id=queued_session_id,
                    user_id=user_id,
                    db=execution_db,
                    on_event=on_event,
                    on_started=on_started,
                    runtime_type_override=runtime_type_override,
                    model_id_override=model_id_override,
                    skill_id_override=skill_id_override,
                    attached_files=attached_files,
                    permission_mode=permission_mode,
                    run_id=run_id,
                    interactive_permissions=True,
                    page_context=page_context,
                    request_authorization=request_authorization,
                    source="web",
                    run_guard=execution_lease.is_owned,
                    workspace_commit=execution_lease.commit_workspace,
                )
                await queue.put(sse({
                    "type": "turn_metrics",
                    "usage": result.usage,
                    "duration_ms": result.duration_ms,
                    "assistant_message_id": result.assistant_message_id,
                    "charged_points": result.charged_points,
                }))
                await asyncio.to_thread(
                    _finalize_unresolved_web_run,
                    run_id,
                    result.status,
                    result.error,
                )
        except asyncio.CancelledError:
            await asyncio.to_thread(
                _finalize_unresolved_web_run,
                run_id,
                "cancelled",
                "智能体运行已取消",
                "cancelled",
            )
            raise
        except Exception as exc:
            logger.exception("Web agent stream failed: run_id=%s", run_id)
            detail = safe_error_detail(str(exc))
            await asyncio.to_thread(
                _finalize_unresolved_web_run,
                run_id,
                "failed",
                detail,
                "execution_error",
            )
            await queue.put(sse({"type": "error", "content": detail,
                                 "error_code": "execution_error",
                                 "metadata": {"error_origin": "aihub", "error_detail": detail}}))
        finally:
            if control_task is not None:
                control_task.cancel()
                await asyncio.gather(control_task, return_exceptions=True)
            if execution_db is not None:
                execution_db.close()
            await asyncio.to_thread(_cleanup_deleted_agent_workspace, agent_id)

    feed_task = asyncio.create_task(run_feed())
    _ACTIVE_WEB_RUNS[run_id] = (asyncio.get_running_loop(), feed_task)
    try:
        yield sse({
            "type": "run_queued",
            "run_id": run_id,
            "session_id": queued_session_id,
            "user_content": user_input,
            "attached_files": attached_files or [],
        })
        while True:
            if feed_task.done() and queue.empty():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.25)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            # Batch fast token deltas into one journal transaction. The bounded
            # queue is drained by a background owner, even with zero browsers.
            chunks = [item]
            await asyncio.sleep(0.05)
            while not queue.empty() and len(chunks) < 100:
                chunks.append(queue.get_nowait())
            yield "".join(chunks)
    finally:
        active_entry = _ACTIVE_WEB_RUNS.get(run_id)
        if active_entry is not None and active_entry[1] is feed_task:
            _ACTIVE_WEB_RUNS.pop(run_id, None)
        if not feed_task.done():
            feed_task.cancel()
        # Execution may emit its cancellation event while unwinding. Drain the
        # bounded queue even when the journal itself failed, to avoid deadlock.
        while not feed_task.done():
            while not queue.empty():
                queue.get_nowait()
            await asyncio.wait({feed_task}, timeout=0.05)
        try:
            await feed_task
        except asyncio.CancelledError:
            pass
        await asyncio.to_thread(cleanup_run, run_id)


async def run_agent_chat(**kwargs) -> AsyncGenerator[str, None]:
    """Start a detached owner, then observe its recoverable output.

    Even disconnecting before the first status frame cannot cancel submission.
    Only explicit run controls cancel the execution registered above.
    """
    started = asyncio.get_running_loop().create_future()

    async def persist_output():
        run_id = None
        snapshot = StreamSnapshot()
        feed = _run_agent_chat_feed(**kwargs)
        batches = 0
        delta_bytes = 0
        next_attempt = 0
        last_publish = 0
        failed = False

        async def publish(urgent=False):
            nonlocal batches, delta_bytes, next_attempt, last_publish, failed
            now = time.monotonic()
            if now < next_attempt and not urgent:
                return
            checkpoint = (failed or snapshot.should_save(urgent) or
                          batches >= MAX_BATCHES or delta_bytes >= MAX_DELTA_BYTES)
            if not snapshot.batch and not checkpoint and now - last_publish < 30:
                return
            try:
                store = get_store()
                ok = await store.publish(run_id, snapshot.revision, snapshot.batch,
                                         snapshot.payload() if checkpoint else None)
                if not ok:  # Cache was evicted/expired: restore it from the owner.
                    checkpoint = True
                    await store.publish(run_id, snapshot.revision, [], snapshot.payload())
                if checkpoint:
                    snapshot.saved()
                    batches = delta_bytes = 0
                last_publish = now
                failed = False
                next_attempt = 0
            except Exception:
                if not failed:
                    logger.warning("Web output cache unavailable; execution continues: run_id=%s", run_id)
                failed = True
                next_attempt = now + 5

        try:
            async for chunk in feed:
                if run_id is None:
                    first = next((json.loads(line[6:]) for line in chunk.splitlines()
                                  if line.startswith("data: ")), {})
                    run_id = first.get("run_id")
                    if not run_id:
                        started.set_result((None, chunk))
                        return
                urgent = snapshot.consume(chunk)
                if snapshot.batch:
                    batches += 1
                    delta_bytes += len(chunk.encode('utf-8'))
                await publish(urgent)
                if not started.done():
                    started.set_result((run_id, None))
            if run_id:
                _, state, _ = await asyncio.to_thread(read_events, SessionLocal, run_id, snapshot.revision)
                snapshot.consume('data: ' + json.dumps({"type": "stream_end", **(state or {})}) + '\n\n')
                await publish(urgent=True)
        except Exception:
            logger.exception("Web output owner failed: run_id=%s", run_id)
            if not started.done():
                started.set_result((None, 'data: {"type":"error","content":"无法保存对话，请稍后重试"}\n\n'))
            # Unexpected owner/feed failures must unwind the underlying execution.
            if run_id:
                cancel_web_run(run_id)
        finally:
            await feed.aclose()

    owner = asyncio.create_task(persist_output(), name="web-chat-output")
    _WEB_STREAM_TASKS.add(owner)
    owner.add_done_callback(_WEB_STREAM_TASKS.discard)
    run_id, error = await asyncio.shield(started)
    if error:
        yield error
        return
    async for chunk in replay_events(SessionLocal, run_id):
        yield chunk
