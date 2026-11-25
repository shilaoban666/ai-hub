"""智能体路由

- Agent CRUD（配置持久化，运行时准备工作区，删除时清理工作区）
- AgentSession CRUD
- 发消息（SSE 流式，通过 AgentService 编排）
"""

from datetime import datetime, time as datetime_time, timedelta, timezone
import asyncio
import hashlib
import json
import logging
import math
import posixpath
import secrets
import statistics
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, lazyload
from agent_prompts import load_agent_prompts_many, prompt_access_filter, set_agent_prompts, copy_agent_prompts

from agent_access import agent_publication_errors as _agent_publication_errors, get_usable_agent
from agent_service import _agent_default_model_id, cancel_web_run, run_agent_chat
from agent_stream import replay_events
from agent_stream_redis import check_stream_store, StreamUnavailable
from agent_execution_lease import acquire_agent_execution_lease, _run_sync_atomic
from credit_labels import credit_display_name
from credit_billing import recorded_charged_points
from asset_runtime import load_runtime_assets
from agent_workspace import (
    is_managed_workspace_path,
    is_text_preview_path,
    normalize_workspace_relative_path,
)
from credential_crypto import AgentCredentialError
from auth import CurrentUser, get_current_active_user
from database import SessionLocal, get_db, settings
from chat_image_storage import MAX_IMAGE_BYTES, ImageStorageError, upload_chat_image
from agent_settings import runtime_agent, published_agent_settings, RUNTIME_DEFAULTS
from message_content import pack_user_content, unpack_user_content
from feedback_routes import feedback_value
from models import AgentMessageFeedback
from enterprise_workspace import (
    bind_agent_workspace, ensure_user_workspace, reset_runtime_workspace,
    runtime_workspace_change_required,
    WorkspaceRuntimeChangeBlocked,
)
from model_catalog import chat_model_payload, workbench_models
from model_compat import (
    configured_model_protocol,
    model_identity,
    model_supports_runtime,
    protocol_label,
)
from skill_access import skill_access_filter, visible_skill_filter
from skill_release_policy import published_release_filter
from mcp_publication import shareable_mcp_definition
from models import (
    Agent,
    AgentConversationShare,
    AgentMessage,
    AgentRun,
    AgentSession,
    AIModel,
    PlatformAgentSettings,
    McpService,
    Skill,
    SkillRelease,
    PromptTemplate,
    agent_prompt_templates,
    SkillInstallation,
    ExpertSkillBinding,
    McpConnection,
    ExpertMcpBinding,
    McpDefinition,
    McpRevision,
)
from runtimes import get_runtime_info, RUNTIME_REGISTRY
from workspace_provider import get_workspace_provider, agent_workspace_snapshot, workspace_snapshot
from schemas import (
    AgentCreate,
    AgentListResponse,
    AgentResponse,
    AgentSessionCreate,
    AgentSessionListResponse,
    AgentSessionMessagesResponse,
    AgentSessionResponse,
    AgentStatisticsResponse,
    AgentUpdate,
    AgentMessageRequest,
    AgentConversationShareResponse,
    PublicConversationShareResponse,
    SaveMessagesRequest,
    RuntimeInstanceResponse,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])
public_router = APIRouter(
    prefix="/api/public/conversation-shares",
    tags=["public-conversation-shares"],
)
shared_router = APIRouter(
    prefix="/api/public/agents",
    tags=["public-agents"],
)
logger = logging.getLogger(__name__)
LOCAL_TZ = timezone(timedelta(hours=8))
WORKSPACE_PREVIEW_MAX_BYTES = 1024 * 1024
WORKSPACE_PREVIEW_MAX_LINES = 1000


def _agent_response_page(db, agents, viewer_id=None):
    ids = [agent.id for agent in agents]
    data = {"models": {}, "sessions": {}, "prompts": {},
            "skills": {key: [] for key in ids}, "mcps": {key: [] for key in ids}}
    if not ids:
        return data
    data["policy"] = published_agent_settings(db)
    data["models"] = {key: workbench_models(db, key) for key in ({viewer_id} if viewer_id is not None else {a.user_id for a in agents})}
    data["sessions"] = dict(db.query(AgentSession.agent_id, func.count(AgentSession.id)).join(Agent, Agent.id == AgentSession.agent_id).filter(
        AgentSession.agent_id.in_(ids), AgentSession.is_deleted == False,
        AgentSession.user_id == (viewer_id if viewer_id is not None else Agent.user_id),
    ).group_by(AgentSession.agent_id).all())
    data["prompts"] = load_agent_prompts_many(db, ids)
    skill_rows = db.query(ExpertSkillBinding.agent_id, SkillInstallation.id, Skill.id, Skill.name, Skill.conversation_examples).select_from(
        SkillInstallation,
    ).join(ExpertSkillBinding, ExpertSkillBinding.installation_id == SkillInstallation.id).join(
        Skill, Skill.id == SkillInstallation.skill_id,
    ).join(SkillRelease, SkillRelease.id == SkillInstallation.release_id).filter(
        ExpertSkillBinding.agent_id.in_(ids), SkillInstallation.status == "active",
        SkillInstallation.scope_agent_id == ExpertSkillBinding.agent_id,
        visible_skill_filter(viewer_id if viewer_id is not None else SkillInstallation.user_id),
        Skill.is_deleted == False,
        or_(
            published_release_filter(),
            and_(
                SkillRelease.status == "workspace",
                Skill.user_id == SkillInstallation.user_id,
                Skill.user_id == (viewer_id if viewer_id is not None else SkillInstallation.user_id),
            ),
        ),
    ).order_by(Skill.name.asc()).all()
    mcp_rows = db.query(ExpertMcpBinding.agent_id, McpConnection.id, McpDefinition.id, McpDefinition.name, McpConnection.auth_mode).select_from(
        McpConnection,
    ).join(ExpertMcpBinding, ExpertMcpBinding.connection_id == McpConnection.id).join(
        McpDefinition, McpDefinition.id == McpConnection.definition_id,
    ).join(McpRevision, McpRevision.id == McpConnection.revision_id).filter(
        ExpertMcpBinding.agent_id.in_(ids), ExpertMcpBinding.status == "active",
        McpConnection.status != "deleted", McpDefinition.status == "published",
        McpRevision.status == "published",
    ).order_by(McpDefinition.name.asc()).all()
    for row in skill_rows:
        data["skills"][row[0]].append(tuple(row[1:]))
    for row in mcp_rows:
        data["mcps"][row[0]].append(tuple(row[1:]))
    return data


def _to_response(
    agent: Agent,
    db: Session,
    *,
    include_mcp_overrides: bool = False,
    page_data: dict | None = None,
    viewer_id: int | None = None,
) -> AgentResponse:
    """ORM → Response，附带 session_count"""
    data = page_data if page_data is not None else _agent_response_page(db, [agent], viewer_id)
    agent = runtime_agent(db, agent, policy=data["policy"])
    session_count = data["sessions"].get(agent.id, 0)
    # Expert agents follow the same model catalog as the AI workbench. Model
    # credentials are user-scoped and therefore never become part of a shared
    # agent template.
    models = data["models"][viewer_id if viewer_id is not None else agent.user_id]
    runtime_type = agent.runtime_type or "claude_code"
    compatible_models = [
        model for model in models
        if model_supports_runtime(model, runtime_type)
    ]
    active_prompt_templates = data["prompts"][agent.id]
    skill_binding_rows = data["skills"][agent.id]
    mcp_binding_rows = data["mcps"][agent.id]
    bound_skills = (
        [(None, skill.id, skill.name, skill.conversation_examples) for skill in agent.skills]
        if agent.kind == "personal_default" else skill_binding_rows
    )
    bound_mcps = (
        [(None, mcp.id, mcp.name) for mcp in agent.mcps]
        if agent.kind == "personal_default" else mcp_binding_rows
    )

    return AgentResponse(
        id=agent.id,
        user_id=agent.user_id,
        can_edit=viewer_id is None or viewer_id == agent.user_id,
        kind=agent.kind or "expert",
        settings_version=agent.settings_version,
        name=agent.name,
        description=agent.description,
        icon=agent.icon,
        cover=agent.cover,
        system_prompt=agent.system_prompt,
        default_model_id=(
            agent.default_model_id
            if agent.default_model_id in {model.id for model in compatible_models}
            else (compatible_models[0].id if compatible_models else None)
        ),
        runtime_type=agent.runtime_type or "claude_code",
        thinking_level=agent.thinking_level or "inherit",
        reasoning_visibility=agent.reasoning_visibility or "off",
        max_turns=agent.max_turns,
        timeout_seconds=agent.timeout_seconds,
        is_public=bool(agent.is_public),
        skill_ids=[row[1] for row in bound_skills],
        mcp_ids=[row[1] for row in bound_mcps],
        mcp_overrides=agent.mcp_overrides if include_mcp_overrides else [],
        model_ids=[m.id for m in models],
        models=[chat_model_payload(m) for m in models],
        skills=[{"id": row[1], "name": row[2], "conversation_examples": row[3] or []} for row in bound_skills],
        skill_installation_ids=[row[0] for row in skill_binding_rows if row[0] is not None],
        skill_bindings=[{"installation_id": row[0], "skill_id": row[1], "name": row[2]} for row in skill_binding_rows if row[0] is not None],
        mcp_connection_ids=[row[0] for row in mcp_binding_rows if row[0] is not None],
        mcp_connections=[{"id": row[0], "definition_id": row[1], "name": row[2], "auth_mode": row[3]} for row in mcp_binding_rows],
        prompt_template_ids=[template.id for template in active_prompt_templates],
        prompt_templates=[
            {
                "id": template.id,
                "name": template.name,
                "category": template.category,
                "content": template.content,
                "variables": template.variables,
                "description": template.description,
                "source_template_id": template.source_template_id,
                "is_public": bool(template.is_public),
                "is_system": bool(template.is_system),
                "author": "平台" if template.is_system else template.author,
            }
            for template in active_prompt_templates
        ],
        session_count=session_count,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _get_agent_or_404(db: Session, agent_id: int, user: CurrentUser) -> Agent:
    # Ownership checks must not materialize all sessions or asset relationships.
    # Callers that use a relationship load it explicitly on access.
    agent = db.query(Agent).options(lazyload("*")).filter(
        Agent.id == agent_id,
        Agent.is_deleted == False,
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if agent.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此智能体")
    return agent


def _get_model_or_400(
    db: Session,
    model_id: int | None,
    user: CurrentUser,
) -> AIModel | None:
    """取模型，校验是否存在"""
    if not model_id:
        return None
    model = db.query(AIModel).filter(
        AIModel.id == model_id,
        AIModel.is_deleted == False,
        or_(
            AIModel.user_id == user.user_id,
            and_(AIModel.scope == "platform", AIModel.is_enabled == True),
        ),
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    return model


def _get_models_or_400(
    db: Session,
    model_ids: list[int] | None,
    user: CurrentUser,
) -> list[AIModel]:
    requested_ids = list(dict.fromkeys(model_ids or []))
    if not requested_ids:
        return []
    selected_models = db.query(AIModel).filter(
        AIModel.id.in_(requested_ids),
        AIModel.is_deleted == False,
        or_(
            AIModel.user_id == user.user_id,
            and_(AIModel.scope == "platform", AIModel.is_enabled == True),
        ),
    ).all()
    found_ids = {model.id for model in selected_models}
    missing_ids = [model_id for model_id in requested_ids if model_id not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"模型不存在或无权访问: {', '.join(map(str, missing_ids))}",
        )
    return selected_models


def _get_skills_or_400(
    db: Session,
    skill_ids: list[int] | None,
    user: CurrentUser,
) -> list[Skill]:
    requested_ids = list(dict.fromkeys(skill_ids or []))
    if not requested_ids:
        return []
    selected = db.query(Skill).filter(
        Skill.id.in_(requested_ids),
        Skill.is_deleted == False,
        or_(skill_access_filter(user.user_id), Skill.is_public == True),
    ).all()
    found_ids = {skill.id for skill in selected}
    missing_ids = [skill_id for skill_id in requested_ids if skill_id not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"技能不存在或无权访问: {', '.join(map(str, missing_ids))}",
        )
    return selected


def _get_mcps_or_400(
    db: Session,
    mcp_ids: list[int] | None,
    user: CurrentUser,
) -> list[McpService]:
    requested_ids = list(dict.fromkeys(mcp_ids or []))
    if not requested_ids:
        return []
    selected = db.query(McpService).filter(
        McpService.id.in_(requested_ids),
        McpService.is_deleted == False,
        or_(
            McpService.user_id == user.user_id,
            McpService.is_public == True,
        ),
    ).all()
    found_ids = {mcp.id for mcp in selected}
    missing_ids = [mcp_id for mcp_id in requested_ids if mcp_id not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"MCP 不存在或无权访问: {', '.join(map(str, missing_ids))}",
        )
    return selected


def _get_prompt_templates_or_400(
    db: Session,
    prompt_template_ids: list[int] | None,
    user: CurrentUser,
    *,
    agent_id: int | None = None,
) -> list[PromptTemplate]:
    requested_ids = list(dict.fromkeys(prompt_template_ids or []))
    if not requested_ids:
        return []
    selected = db.query(PromptTemplate).filter(
        PromptTemplate.id.in_(requested_ids), prompt_access_filter(user.user_id),
    ).all()
    found_ids = {template.id for template in selected}
    missing_ids = [item for item in requested_ids if item not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"提示词不存在或无权访问: {', '.join(map(str, missing_ids))}",
        )
    by_id = {template.id: template for template in selected}
    return [by_id[item] for item in requested_ids]


def _normalize_mcp_overrides(overrides, mcps, runtime_type: str) -> list[dict]:
    selected = {mcp.id: mcp for mcp in mcps}
    normalized: list[dict] = []
    seen: set[int] = set()
    for override in overrides or []:
        payload = override.model_dump() if hasattr(override, "model_dump") else dict(override)
        mcp_id = int(payload.get("mcp_id") or 0)
        if mcp_id in seen:
            raise HTTPException(status_code=400, detail=f"MCP {mcp_id} 配置重复")
        seen.add(mcp_id)
        service = selected.get(mcp_id)
        if service is None:
            raise HTTPException(status_code=400, detail=f"MCP {mcp_id} 尚未绑定到智能体")

        env = {
            str(key).strip(): str(value)
            for key, value in (payload.get("env") or {}).items()
            if str(key).strip()
        }
        headers = {
            str(key).strip(): str(value)
            for key, value in (payload.get("headers") or {}).items()
            if str(key).strip()
        }
        service_type = (service.type or "").strip().lower()
        if service_type == "stdio" and headers:
            raise HTTPException(status_code=400, detail=f"MCP {service.name} 仅支持 env 覆盖")
        if service_type in {"sse", "http", "streamable_http", "streamable-http"} and env:
            raise HTTPException(status_code=400, detail=f"MCP {service.name} 仅支持 header 覆盖")
        if env or headers:
            normalized.append({"mcp_id": mcp_id, "env": env, "headers": headers})

    return sorted(normalized, key=lambda item: item["mcp_id"])


def _validate_models_for_runtime_or_400(
    selected_models: list[AIModel],
    runtime_type: str,
) -> None:
    unconfigured = [
        model for model in selected_models
        if not configured_model_protocol(model)
    ]
    if unconfigured:
        names = "、".join(model_identity(model) for model in unconfigured)
        raise HTTPException(
            status_code=400,
            detail=f"以下模型尚未配置 API 协议，请先到模型管理设置: {names}",
        )

    incompatible = [
        model for model in selected_models
        if not model_supports_runtime(model, runtime_type)
    ]
    if incompatible:
        descriptions = "、".join(
            f"{model_identity(model)} [{protocol_label(model.api_protocol)}]"
            for model in incompatible
        )
        raise HTTPException(
            status_code=400,
            detail=f"{runtime_type} 不兼容以下模型: {descriptions}",
        )


def _validate_agent_models_or_400(
    selected_models: list[AIModel],
    default_model: AIModel | None,
    runtime_type: str,
) -> None:
    if not selected_models:
        raise HTTPException(status_code=400, detail="请至少绑定一个模型")
    if default_model is None:
        raise HTTPException(status_code=400, detail="请选择默认模型")
    if default_model.id not in {model.id for model in selected_models}:
        raise HTTPException(status_code=400, detail="默认模型必须包含在已绑定模型中")
    _validate_models_for_runtime_or_400(selected_models, runtime_type)


def _validate_runtime_or_400(runtime_type: str | None) -> None:
    if (runtime_type or "claude_code") not in RUNTIME_REGISTRY:
        raise HTTPException(status_code=400, detail="不支持的 Runtime，请使用可用的运行时")


def _validate_reasoning_config_or_400(
    runtime_type: str | None,
    thinking_level: str | None,
) -> None:
    runtime = runtime_type or "claude_code"
    level = thinking_level or "inherit"
    levels = get_runtime_info().get(runtime, {}).get("thinking_levels")
    supported = set(levels) if levels is not None else None
    if supported is not None and level not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"{runtime} 不支持推理强度 {level}",
        )


# ============= Runtime 信息 =============

@router.get("/runtimes")
def list_runtimes():
    """列出所有可用的 runtime 类型及其信息"""
    return {
        "items": [
            {
                "type": key,
                "label": info["label"],
                "description": info["description"],
                "icon": info["icon"],
                "available": info.get("available", True),
                "hint": info.get("hint"),
                "version": info.get("version"),
                "deployment_mode": info.get("deployment_mode"),
                "capabilities": info.get("capabilities", []),
                "model_protocols": info.get("model_protocols", []),
                "thinking_levels": info.get("thinking_levels", ["inherit"]),
                "reasoning_visibility_modes": info.get(
                    "reasoning_visibility_modes", ["off"]
                ),
            }
            for key, info in get_runtime_info().items()
        ]
    }


# ============= Agent CRUD =============

@router.get("", response_model=AgentListResponse)
def list_agents(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    search: str = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """列出当前用户的智能体"""
    query = db.query(Agent).options(lazyload("*")).filter(
        Agent.is_deleted == False,
        Agent.user_id == current_user.user_id,
        Agent.kind == "expert",
    )
    if search:
        query = query.filter(Agent.name.like(f"%{search}%"))

    total = query.count()
    items = query.order_by(Agent.created_at.desc()).offset(skip).limit(limit).all()
    page_data = _agent_response_page(db, items)
    return AgentListResponse(total=total, items=[_to_response(a, db, page_data=page_data) for a in items])


@router.post("", response_model=AgentResponse)
def create_agent(
    data: AgentCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """创建智能体并绑定工作区；实际运行时准备沙箱。"""
    effective = runtime_agent(db, data)
    runtime_type = effective.runtime_type
    _validate_runtime_or_400(runtime_type)
    _validate_reasoning_config_or_400(runtime_type, effective.thinking_level)
    available_models = workbench_models(db, current_user.user_id)
    requested_model = _get_model_or_400(db, data.default_model_id, current_user)
    if requested_model is not None and requested_model.id not in {item.id for item in available_models}:
        raise HTTPException(status_code=404, detail="模型不存在或无权访问")
    model = requested_model or next(
        (
            candidate for candidate in available_models
            if model_supports_runtime(candidate, runtime_type)
        ),
        None,
    )
    if model is not None:
        _validate_models_for_runtime_or_400([model], runtime_type)

    agent = Agent(
        user_id=current_user.user_id,
        kind="expert",
        name=data.name,
        description=data.description,
        icon=data.icon,
        cover=data.cover,
        system_prompt=data.system_prompt,
        default_model_id=model.id if model is not None else None,
        runtime_type=runtime_type,
        thinking_level=effective.thinking_level,
        reasoning_visibility=effective.reasoning_visibility,
        max_turns=effective.max_turns,
        timeout_seconds=effective.timeout_seconds,
        settings_version=effective.settings_version,
    )

    agent.skills = _get_skills_or_400(db, data.skill_ids, current_user)
    selected_mcps = _get_mcps_or_400(db, data.mcp_ids, current_user)
    agent.mcps = selected_mcps
    selected_prompts = _get_prompt_templates_or_400(
        db, data.prompt_template_ids, current_user
    )

    # 绑定 models
    # Keep the legacy relation empty for expert agents. The runtime resolves
    # system + current-user custom models dynamically, like the workbench.
    agent.models = []

    db.add(agent)
    try:
        db.flush()
        set_agent_prompts(db, agent.id, selected_prompts)
        bind_agent_workspace(db, agent, commit=False)
        agent.store_mcp_overrides(
            _normalize_mcp_overrides(data.mcp_overrides, selected_mcps, runtime_type)
        )
        db.commit()
    except AgentCredentialError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Agent configuration creation failed: agent_id=%s", agent.id)
        raise HTTPException(
            status_code=503,
            detail="智能体创建失败：配置未保存，请稍后重试",
        ) from exc

    db.refresh(agent)

    return _to_response(agent, db, include_mcp_overrides=True)


@router.get("/{agent_id}/models")
def list_agent_models(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    models = workbench_models(db, current_user.user_id)
    return {"items": [chat_model_payload(model) for model in models]}


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    return _to_response(agent, db, include_mcp_overrides=agent.user_id == current_user.user_id,
                        viewer_id=current_user.user_id)


@router.post("/{agent_id}/skills/sync")
async def sync_agent_skill_installations(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Reconcile physical skills on chat entry without starting a runtime."""
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    workspace, _ = bind_agent_workspace(db, agent)
    db.commit()
    try:
        lease = await asyncio.wait_for(acquire_agent_execution_lease(
            workspace_id=workspace.id, run_id=secrets.token_hex(16),
        ), timeout=0.5)
    except asyncio.TimeoutError:
        # An executing conversation owns these files. Its next run checks again.
        return {"status": "deferred", "reason": "workspace_busy"}

    # Every operation after acquisition must be covered by lease cleanup,
    # including metadata resolution, its commit and provider initialization.
    async with lease:
        # Keep the request-owned SQLAlchemy session on this thread. Only the
        # filesystem operation is dispatched to a worker.
        try:
            assets = load_runtime_assets(
                db,
                agent,
                current_user.user_id,
                skills_only=True,
            )
            agent.runtime_skills = assets["skills"]
            db.commit()
            provider = get_workspace_provider(agent)
            filesystem_agent = agent_workspace_snapshot(agent, skills_only=True)
            filesystem_workspace = workspace_snapshot(workspace)
        except Exception as exc:
            db.rollback()
            logger.exception("Skill sync preparation failed: agent_id=%s", agent_id)
            raise HTTPException(status_code=503, detail="技能同步失败，请稍后重试") from exc

        def synchronize():
            names = []
            def write():
                names.extend(provider.sync_skill_installations(filesystem_agent, filesystem_workspace))
            if not lease.commit_workspace(write):
                return {"status": "deferred", "reason": "workspace_busy"}
            return {"status": "synced", "skills": names}

        task = asyncio.create_task(asyncio.to_thread(synchronize))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A thread cannot be cancelled. Keep the writer lease until it
            # finishes, even if the request receives another cancellation.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                error = task.exception()
                if error is not None:
                    logger.error(
                        "Skill installation sync failed after cancellation: agent_id=%s", agent_id,
                        exc_info=(type(error), error, error.__traceback__),
                    )
            raise
        except Exception as exc:
            db.rollback()
            logger.exception("Skill installation sync failed: agent_id=%s", agent_id)
            raise HTTPException(status_code=503, detail="技能同步失败，请稍后重试") from exc


@router.put("/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: int,
    data: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = _get_agent_or_404(db, agent_id, current_user)
    if agent.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权修改此智能体")

    effective = runtime_agent(db, agent)
    policy = published_agent_settings(db)
    effective_runtime = effective.runtime_type if policy else (data.runtime_type or agent.runtime_type or "claude_code")
    runtime_changed = runtime_workspace_change_required(db, agent, effective_runtime)
    if runtime_changed and data.confirm_runtime_change != effective_runtime:
        raise HTTPException(status_code=409, detail={
            "message": "更换 runtime 将强制终止此 Agent 的所有未结束任务（包括其他用户正在使用的任务），清空工作区文件，并重置会话运行状态。未完成的输出将丢失，是否确认？",
            "data": {
                "code": "RUNTIME_CHANGE_CONFIRMATION_REQUIRED",
                "target_runtime": effective_runtime,
            },
        })
    if policy is not None:
        for field in RUNTIME_DEFAULTS:
            setattr(agent, field, getattr(effective, field))
        agent.settings_version = effective.settings_version
    if policy is None and (data.runtime_type or agent.runtime_type) != agent.runtime_type:
        _validate_runtime_or_400(data.runtime_type)
    _validate_reasoning_config_or_400(
        effective.runtime_type if policy else (data.runtime_type or agent.runtime_type),
        effective.thinking_level if policy else (data.thinking_level if data.thinking_level is not None else agent.thinking_level),
    )

    available_models = workbench_models(db, current_user.user_id)
    available_model_ids = {model.id for model in available_models}
    requested_model_ids = list(dict.fromkeys(data.model_ids or []))
    if requested_model_ids and not set(requested_model_ids).issubset(available_model_ids):
        raise HTTPException(status_code=404, detail="模型不存在或无权访问")
    effective_models = available_models
    if data.default_model_id is not None:
        effective_default_model_id = data.default_model_id
    elif (
        agent.default_model_id is not None
        and any(
            model.id == agent.default_model_id
            and model_supports_runtime(model, effective_runtime)
            for model in available_models
        )
    ):
        effective_default_model_id = agent.default_model_id
    else:
        # An invalid model selection must not prevent saving
        # the agent after it is moved to Claude Code.
        effective_default_model_id = next(
            (
                model.id for model in available_models
                if model_supports_runtime(model, effective_runtime)
            ),
            None,
        )
    effective_default_model = (
        next((model for model in available_models if model.id == effective_default_model_id), None)
        if effective_default_model_id is not None else None
    )
    if effective_default_model_id is not None and effective_default_model is None:
        raise HTTPException(status_code=404, detail="默认模型不存在或无权访问")
    if effective_default_model is not None:
        _validate_models_for_runtime_or_400([effective_default_model], effective_runtime)
    if agent.kind == "expert" and agent.is_public:
        _validate_public_default_model(effective_default_model, effective_runtime)

    # 更新标量字段
    for field in ["name", "description", "icon", "cover", "system_prompt",
                  "default_model_id", "runtime_type", "thinking_level",
                  "reasoning_visibility", "max_turns", "timeout_seconds"]:
        value = getattr(data, field, None)
        if policy is not None and field in RUNTIME_DEFAULTS:
            continue
        if value is not None:
            setattr(agent, field, value)

    # 更新 skills
    if data.skill_ids is not None:
        agent.skills = _get_skills_or_400(db, data.skill_ids, current_user)

    if data.prompt_template_ids is not None:
        selected_prompts = _get_prompt_templates_or_400(
            db, data.prompt_template_ids, current_user, agent_id=agent.id,
        )
        set_agent_prompts(db, agent.id, selected_prompts)
        db.expire(agent, ["prompt_templates"])

    # 更新 MCP，并清理已解绑 MCP 的覆盖值。
    effective_mcps = (
        _get_mcps_or_400(db, data.mcp_ids, current_user)
        if data.mcp_ids is not None
        else list(agent.mcps)
    )
    if data.mcp_ids is not None:
        agent.mcps = effective_mcps

    current_overrides = agent.mcp_overrides
    requested_overrides = (
        data.mcp_overrides if data.mcp_overrides is not None else current_overrides
    )
    normalized_overrides = _normalize_mcp_overrides(
        requested_overrides,
        effective_mcps,
        effective_runtime,
    )

    # Expert agent models are always resolved from the current user's catalog.
    agent.models = []
    if data.default_model_id is None and (
        agent.default_model_id not in available_model_ids
        or not any(
            model.id == agent.default_model_id
            and model_supports_runtime(model, effective_runtime)
            for model in available_models
        )
    ):
        agent.default_model_id = effective_default_model_id

    stopped_run_ids = []
    try:
        # Configuration writes must not initialize an execution sandbox. Runs
        # resolve the latest assets and build their own disposable view.
        if runtime_changed:
            stopped_run_ids = reset_runtime_workspace(db, agent, effective_runtime, force_stop=True)
        bind_agent_workspace(db, agent, commit=False)
        agent.store_mcp_overrides(normalized_overrides)
        db.commit()
    except WorkspaceRuntimeChangeBlocked as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentCredentialError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Agent configuration update failed: agent_id=%s", agent.id)
        raise HTTPException(
            status_code=503,
            detail="配置未保存，请稍后重试",
        ) from exc

    # Only cancel processes after the configuration and fencing commit, so a
    # failed save leaves existing work running. Usage still reconciles normally.
    from credit_billing import settle_platform_run
    for run_id in stopped_run_ids:
        try:
            cancel_web_run(run_id)
        except Exception:
            logger.exception("Runtime switch process cancellation failed: run_id=%s", run_id)
        try:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
            if run is not None:
                settle_platform_run(db, run, run.status)
        except Exception:
            db.rollback()
            logger.exception("Runtime switch task settlement failed: run_id=%s", run_id)

    db.refresh(agent)

    return _to_response(agent, db, include_mcp_overrides=True)


def _validate_public_default_model(model, runtime_type):
    if (model is None or model.scope != "platform" or model.is_deleted
            or not model.is_enabled):
        raise HTTPException(status_code=409, detail="公开智能体的默认模型必须是可用的平台模型，请选择平台模型并保存")
    _validate_models_for_runtime_or_400([model], runtime_type)


@router.post("/{agent_id}/publish", response_model=AgentResponse)
def publish_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = _get_agent_or_404(db, agent_id, current_user)
    if agent.kind == "expert":
        model = db.get(AIModel, agent.default_model_id) if agent.default_model_id is not None else None
        _validate_public_default_model(model, runtime_agent(db, agent).runtime_type)
    errors = _agent_publication_errors(db, agent)
    if errors:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "智能体包含私有资源，全部公开后才能发布",
                "data": {"items": errors},
            },
        )
    agent.is_public = True
    db.commit()
    db.refresh(agent)
    return _to_response(agent, db, include_mcp_overrides=True)


@router.post("/{agent_id}/unpublish", response_model=AgentResponse)
def unpublish_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = _get_agent_or_404(db, agent_id, current_user)
    agent.is_public = False
    db.commit()
    db.refresh(agent)
    return _to_response(agent, db, include_mcp_overrides=True)


@router.post("/{agent_id}/copy", response_model=AgentResponse)
def copy_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Copy a published expert agent without copying models or credentials."""
    source = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.is_deleted == False,
        Agent.is_public == True,
        Agent.kind == "expert",
    ).first()
    if source is None:
        raise HTTPException(status_code=404, detail="公开智能体不存在")
    errors = _agent_publication_errors(db, source)
    if errors:
        raise HTTPException(status_code=409, detail="公开智能体包含私有资源，无法复制")

    available_models = workbench_models(db, current_user.user_id)
    copied_runtime = source.runtime_type or "claude_code"
    copied_thinking_level = source.thinking_level or "inherit"
    if copied_runtime == "claude_code" and copied_thinking_level not in {
        "inherit", "low", "medium", "high", "xhigh", "max",
    }:
        copied_thinking_level = "inherit"
    model = next(
        (
            candidate for candidate in available_models
            if model_supports_runtime(candidate, copied_runtime)
        ),
        None,
    )
    copied = Agent(
        user_id=current_user.user_id,
        kind="expert",
        name=f"{source.name}（副本）",
        description=source.description,
        icon=source.icon,
        cover=source.cover,
        system_prompt=source.system_prompt,
        default_model_id=model.id if model else None,
        runtime_type=copied_runtime,
        thinking_level=copied_thinking_level,
        reasoning_visibility=source.reasoning_visibility,
        max_turns=source.max_turns,
        timeout_seconds=source.timeout_seconds,
        is_public=False,
    )
    # Only public resource definitions are copied. MCP credentials and model
    # bindings are intentionally omitted and resolved for the new owner.
    copied.skills = []
    copied.mcps = []
    # Copy references below; author changes remain visible to both agents.
    copied.prompt_templates = []
    copied.models = []
    db.add(copied)
    try:
        db.flush()
        copy_agent_prompts(db, source.id, copied.id)
        workspace, _ = bind_agent_workspace(db, copied, commit=False)
        # Recreate public skill installations for the new owner so the source
        # user's installation and its private workspace are never referenced.
        for binding in db.query(ExpertSkillBinding).filter(
            ExpertSkillBinding.agent_id == source.id,
        ).all():
            source_installation = db.query(SkillInstallation).filter(
                SkillInstallation.id == binding.installation_id,
                SkillInstallation.status == "active",
            ).first()
            if source_installation is None:
                continue
            target_installation = db.query(SkillInstallation).filter(
                SkillInstallation.user_id == current_user.user_id,
                SkillInstallation.scope_agent_id == copied.id,
                SkillInstallation.skill_id == source_installation.skill_id,
            ).first()
            if target_installation is None:
                target_installation = SkillInstallation(
                    user_id=current_user.user_id,
                    scope_agent_id=copied.id,
                    workspace_id=workspace.id,
                    skill_id=source_installation.skill_id,
                    release_id=source_installation.release_id,
                    previous_release_id=None,
                    status="active",
                    granted_capabilities=source_installation.granted_capabilities,
                )
                db.add(target_installation)
                db.flush()
            else:
                target_installation.status = "active"
            db.add(ExpertSkillBinding(agent_id=copied.id, installation_id=target_installation.id))

        # Recreate MCP connections without copying config overrides or
        # credential references. The consumer fills those on their account.
        for binding in db.query(ExpertMcpBinding).filter(
            ExpertMcpBinding.agent_id == source.id,
            ExpertMcpBinding.status == "active",
        ).all():
            source_connection = db.query(McpConnection).filter(
                McpConnection.id == binding.connection_id,
                McpConnection.status != "deleted",
            ).first()
            if source_connection is None:
                continue
            definition = db.query(McpDefinition).filter(
                McpDefinition.id == source_connection.definition_id,
                McpDefinition.status == "published",
                shareable_mcp_definition(),
            ).first()
            if definition is None:
                continue
            revision = db.query(McpRevision).filter(
                McpRevision.id == source_connection.revision_id,
                McpRevision.status == "published",
            ).first()
            if revision is None:
                continue
            target_connection = db.query(McpConnection).filter(
                McpConnection.user_id == current_user.user_id,
                McpConnection.scope_agent_id == copied.id,
                McpConnection.definition_id == definition.id,
                McpConnection.status == "active",
            ).first()
            if target_connection is None:
                base_name = definition.name
                target_name = base_name
                suffix = 2
                while db.query(McpConnection.id).filter(
                    McpConnection.user_id == current_user.user_id,
                    McpConnection.scope_agent_id == copied.id,
                    McpConnection.name == target_name,
                ).first() is not None:
                    target_name = f"{base_name}（{suffix}）"
                    suffix += 1
                target_connection = McpConnection(
                    user_id=current_user.user_id,
                    scope_agent_id=copied.id,
                    workspace_id=workspace.id,
                    definition_id=definition.id,
                    revision_id=revision.id,
                    credential_reference_id=None,
                    name=target_name,
                    config_overrides_json="{}",
                    auth_mode=getattr(source_connection, "auth_mode", None) or "manual",
                    tool_policy_json=source_connection.tool_policy_json,
                    status="active",
                )
                db.add(target_connection)
                db.flush()
            db.add(ExpertMcpBinding(agent_id=copied.id, connection_id=target_connection.id))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Published agent copy failed: source_agent_id=%s", agent_id)
        raise HTTPException(status_code=503, detail="智能体副本创建失败，请稍后重试") from exc
    db.refresh(copied)
    return _to_response(copied, db, include_mcp_overrides=True)


def _statistics_rate(succeeded: int, failed: int) -> tuple[float, float]:
    completed = succeeded + failed
    if completed == 0:
        return 0.0, 0.0
    return round(succeeded * 100 / completed, 1), round(failed * 100 / completed, 1)


def _statistics_local_date(value: datetime | None):
    if value is None:
        return None
    normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return normalized.astimezone(LOCAL_TZ).date()


def _statistics_credit_display_name(db: Session) -> str:
    policy = (
        db.query(PlatformAgentSettings)
        .filter(PlatformAgentSettings.status == "published")
        .order_by(PlatformAgentSettings.version.desc())
        .first()
    )
    return credit_display_name(policy)


@router.get("/{agent_id}/statistics", response_model=AgentStatisticsResponse)
def get_agent_statistics(
    agent_id: int,
    days: int = Query(default=7),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    get_usable_agent(db, agent_id, current_user.user_id)
    if days not in {1, 7, 30}:
        raise HTTPException(status_code=400, detail="统计周期仅支持今天、7 天或 30 天")

    end_at = datetime.now(timezone.utc)
    start_date = end_at.astimezone(LOCAL_TZ).date() - timedelta(days=days - 1)
    start_at = datetime.combine(start_date, datetime_time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    rows = (
        db.query(
            AgentRun.id,
            AgentRun.status,
            AgentRun.source,
            AgentRun.duration_ms,
            AgentRun.input_tokens,
            AgentRun.output_tokens,
            AgentRun.cache_read_tokens,
            AgentRun.cache_creation_tokens,
            AgentRun.total_tokens,
            AgentRun.charged_points,
            AgentRun.error_code,
            AgentRun.error_message,
            AgentRun.created_at,
        )
        .filter(
            AgentRun.agent_id == agent_id,
            AgentRun.user_id == current_user.user_id,
            AgentRun.created_at >= start_at,
            AgentRun.created_at <= end_at,
        )
        .order_by(AgentRun.created_at.asc())
        .all()
    )

    status_counts = {status: 0 for status in ("succeeded", "failed", "cancelled", "active", "abnormal")}
    duration_values = []
    token_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "total_tokens": 0,
    }
    charged_points = Decimal("0.00")
    trend_by_date = {}
    sources = {}
    errors = {}
    failures = []

    for offset in range(days):
        day = start_date + timedelta(days=offset)
        trend_by_date[day] = {
            "date": day.isoformat(),
            "charged_points": Decimal("0.00"),
            "total_runs": 0,
            "succeeded_runs": 0,
            "failed_runs": 0,
            "cancelled_runs": 0,
            "active_runs": 0,
            "abnormal_runs": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "total_tokens": 0,
        }

    for row in rows:
        status = row.status or "unknown"
        source = row.source or "web"
        if status in {"queued", "running"}:
            status_key = "active"
        elif status in {"succeeded", "failed", "cancelled"}:
            status_key = status
        else:
            status_key = "abnormal"
        status_counts[status_key] += 1

        if status in {"succeeded", "failed"} and row.duration_ms is not None:
            duration_values.append(max(0, int(row.duration_ms)))
        row_tokens = {}
        for field in token_totals:
            row_tokens[field] = max(0, int(getattr(row, field) or 0))
            token_totals[field] += row_tokens[field]
        row_points = max(Decimal("0.00"), Decimal(str(row.charged_points or "0")))
        charged_points += row_points

        source_item = sources.setdefault(source, {
            "source": source,
            "charged_points": Decimal("0.00"),
            "total_runs": 0,
            "succeeded_runs": 0,
            "failed_runs": 0,
            "cancelled_runs": 0,
            "active_runs": 0,
            "abnormal_runs": 0,
        })
        source_item["total_runs"] += 1
        source_item["charged_points"] += row_points
        source_field = {
            "succeeded": "succeeded_runs",
            "failed": "failed_runs",
            "cancelled": "cancelled_runs",
            "active": "active_runs",
            "abnormal": "abnormal_runs",
        }.get(status_key)
        if source_field:
            source_item[source_field] += 1

        local_date = _statistics_local_date(row.created_at)
        trend_item = trend_by_date.get(local_date)
        if trend_item is not None:
            trend_item["charged_points"] += row_points
            trend_item["total_runs"] += 1
            if source_field:
                trend_item[source_field] += 1
            for field, value in row_tokens.items():
                trend_item[field] += value

        if status_key in {"failed", "abnormal"}:
            error_code = row.error_code or ("unknown_status" if status_key == "abnormal" else "runtime_error")
            error_item = errors.setdefault(error_code, {
                "error_code": error_code,
                "count": 0,
                "last_occurred_at": row.created_at,
                "latest_message": None,
            })
            error_item["count"] += 1
            error_item["last_occurred_at"] = row.created_at
            if row.error_message:
                error_item["latest_message"] = row.error_message[:500]
            failures.append({
                "run_id": row.id,
                "status": status,
                "source": source,
                "duration_ms": row.duration_ms,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "created_at": row.created_at,
            })

    succeeded = status_counts["succeeded"]
    failed = status_counts["failed"]
    success_rate, failure_rate = _statistics_rate(succeeded, failed)
    sorted_durations = sorted(duration_values)
    median_duration = round(statistics.median(sorted_durations)) if sorted_durations else None
    p95_duration = (
        sorted_durations[max(0, math.ceil(len(sorted_durations) * 0.95) - 1)]
        if sorted_durations else None
    )

    trend = []
    for item in trend_by_date.values():
        item["success_rate"], _ = _statistics_rate(item["succeeded_runs"], item["failed_runs"])
        trend.append(item)

    source_items = []
    for item in sources.values():
        item["success_rate"], _ = _statistics_rate(item["succeeded_runs"], item["failed_runs"])
        source_items.append(item)
    source_items.sort(key=lambda item: (-item["total_runs"], item["source"]))

    error_items = sorted(
        errors.values(),
        key=lambda item: (-item["count"], item["error_code"]),
    )[:8]

    return {
        "days": days,
        "start_at": start_at,
        "end_at": end_at,
        "credit_display_name": _statistics_credit_display_name(db),
        "summary": {
            "total_runs": len(rows),
            "succeeded_runs": succeeded,
            "failed_runs": failed,
            "cancelled_runs": status_counts["cancelled"],
            "active_runs": status_counts["active"],
            "abnormal_runs": status_counts["abnormal"],
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "median_duration_ms": median_duration,
            "p95_duration_ms": p95_duration,
            **token_totals,
            "charged_points": charged_points,
            "average_tokens_per_run": round(token_totals["total_tokens"] / len(rows)) if rows else 0,
        },
        "trend": trend,
        "sources": source_items,
        "errors": error_items,
        "recent_failures": list(reversed(failures[-10:])),
    }


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = _get_agent_or_404(db, agent_id, current_user)
    if agent.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权删除此智能体")

    unresolved_runs = db.query(AgentRun).filter(
        AgentRun.agent_id == agent.id,
        AgentRun.status.in_(["queued", "running"]),
    ).all()
    for run in unresolved_runs:
        run.cancel_requested = True
    db.commit()
    for run in unresolved_runs:
        cancel_web_run(run.id)

    agent.is_deleted = True
    db.commit()

    remaining_runs = db.query(AgentRun).filter(
        AgentRun.agent_id == agent.id,
        AgentRun.status.in_(["queued", "running"]),
    ).count()
    if remaining_runs == 0:
        try:
            get_workspace_provider(agent).delete(agent.id)
        except Exception as e:
            print(f"[Agent] 工作区清理失败 agent_id={agent.id}: {e}")
    else:
        print(
            f"[Agent] 工作区清理已延后 agent_id={agent.id} "
            f"unresolved_runs={remaining_runs}"
        )

    return {"message": "已删除"}


# ============= Runtime instance =============


@router.get("/{agent_id}/runtime-status", response_model=RuntimeInstanceResponse)
def get_agent_runtime_status(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    return RuntimeInstanceResponse(
        agent_id=agent.id,
        runtime_type=agent.runtime_type or "claude_code",
        deployment_mode="local",
        external_agent_id=f"aihub-{agent.id}",
        status="not_applicable",
    )


# ============= AgentSession =============

@router.get("/{agent_id}/sessions", response_model=AgentSessionListResponse)
def list_sessions(
    agent_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    query = db.query(AgentSession).filter(
        AgentSession.agent_id == agent_id,
        AgentSession.user_id == current_user.user_id,
        AgentSession.is_deleted == False,
        AgentSession.source != "api",
    )
    total = query.count()
    sort_time = func.coalesce(
        AgentSession.last_message_at,
        AgentSession.updated_at,
        AgentSession.created_at,
    )
    active_run = db.query(AgentRun.id).filter(
        AgentRun.session_id == AgentSession.id,
        AgentRun.user_id == current_user.user_id,
        AgentRun.source == "web",
        or_(AgentRun.status == "queued", AgentRun.status == "running"),
    ).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1).correlate(AgentSession).scalar_subquery()
    active_run_started_at = db.query(
        func.coalesce(AgentRun.started_at, AgentRun.created_at)
    ).filter(
        AgentRun.session_id == AgentSession.id,
        AgentRun.user_id == current_user.user_id,
        AgentRun.source == "web",
        or_(AgentRun.status == "queued", AgentRun.status == "running"),
    ).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1).correlate(AgentSession).scalar_subquery()
    rows = (
        query.add_columns(
            active_run.label("active_run_id"),
            active_run_started_at.label("active_run_started_at"),
        )
        .order_by(sort_time.desc(), AgentSession.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    items = []
    for session, run_id, run_started_at in rows:
        item = AgentSessionResponse.model_validate(session)
        item.active_run_id = run_id
        item.active_run_started_at = run_started_at
        items.append(item)
    return AgentSessionListResponse(total=total, items=items)


@router.post("/{agent_id}/sessions", response_model=AgentSessionResponse)
def create_session(
    agent_id: int,
    data: AgentSessionCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    agent = runtime_agent(db, agent)
    workspace, _ = bind_agent_workspace(db, agent)
    now = datetime.now(timezone.utc)
    effective_model_id = _agent_default_model_id(db, agent, current_user.user_id)
    session = AgentSession(
        agent_id=agent_id,
        user_id=current_user.user_id,
        workspace_id=workspace.id,
        runtime_type=agent.runtime_type or "claude_code",
        model_id=effective_model_id,
        config_version=agent.settings_version,
        updated_at=now,
        title=data.title or f"与 {agent.name} 的新对话",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/{agent_id}/sessions/{session_id}")
def delete_session(
    agent_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.agent_id == agent_id,
        AgentSession.user_id == current_user.user_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.source == "api":
        raise HTTPException(status_code=409, detail="开放调用会话只读")
    session.is_deleted = True
    db.query(AgentConversationShare).filter(
        AgentConversationShare.session_id == session.id,
        AgentConversationShare.is_active == True,
    ).update({
        AgentConversationShare.is_active: False,
        AgentConversationShare.revoked_at: datetime.now(timezone.utc),
    }, synchronize_session=False)
    db.commit()
    return {"message": "已删除"}


def _get_owned_session_or_404(
    db: Session,
    agent_id: int,
    session_id: int,
    user_id: int,
) -> AgentSession:
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.agent_id == agent_id,
        AgentSession.user_id == user_id,
        AgentSession.is_deleted == False,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.get(
    "/{agent_id}/sessions/{session_id}/share",
    response_model=Optional[AgentConversationShareResponse],
)
def get_conversation_share(
    agent_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    get_usable_agent(db, agent_id, current_user.user_id)
    _get_owned_session_or_404(db, agent_id, session_id, current_user.user_id)
    return db.query(AgentConversationShare).filter(
        AgentConversationShare.session_id == session_id,
        AgentConversationShare.agent_id == agent_id,
        AgentConversationShare.user_id == current_user.user_id,
        AgentConversationShare.is_active == True,
    ).order_by(AgentConversationShare.id.desc()).first()


@router.post(
    "/{agent_id}/sessions/{session_id}/share",
    response_model=AgentConversationShareResponse,
)
def create_conversation_share(
    agent_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    get_usable_agent(db, agent_id, current_user.user_id)
    _get_owned_session_or_404(db, agent_id, session_id, current_user.user_id)
    existing = db.query(AgentConversationShare).filter(
        AgentConversationShare.session_id == session_id,
        AgentConversationShare.agent_id == agent_id,
        AgentConversationShare.user_id == current_user.user_id,
        AgentConversationShare.is_active == True,
    ).order_by(AgentConversationShare.id.desc()).first()
    if existing:
        return existing

    while True:
        token = secrets.token_urlsafe(32)
        if not db.query(AgentConversationShare.id).filter(
            AgentConversationShare.token == token,
        ).first():
            break
    share = AgentConversationShare(
        session_id=session_id,
        agent_id=agent_id,
        user_id=current_user.user_id,
        token=token,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return share


@router.delete("/{agent_id}/sessions/{session_id}/share")
def revoke_conversation_share(
    agent_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    get_usable_agent(db, agent_id, current_user.user_id)
    _get_owned_session_or_404(db, agent_id, session_id, current_user.user_id)
    shares = db.query(AgentConversationShare).filter(
        AgentConversationShare.session_id == session_id,
        AgentConversationShare.agent_id == agent_id,
        AgentConversationShare.user_id == current_user.user_id,
        AgentConversationShare.is_active == True,
    ).all()
    now = datetime.now(timezone.utc)
    for share in shares:
        share.is_active = False
        share.revoked_at = now
    db.commit()
    return {"message": "已取消分享"}


@public_router.get("/{token}", response_model=PublicConversationShareResponse)
def get_public_conversation_share(
    token: str,
    before_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    share = db.query(AgentConversationShare).filter(
        AgentConversationShare.token == token,
        AgentConversationShare.is_active == True,
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="分享不存在或已取消")

    session = db.query(AgentSession).filter(
        AgentSession.id == share.session_id,
        AgentSession.agent_id == share.agent_id,
        AgentSession.is_deleted == False,
    ).first()
    agent = db.query(Agent).filter(
        Agent.id == share.agent_id,
        Agent.is_deleted == False,
    ).first()
    if not session or not agent:
        raise HTTPException(status_code=404, detail="分享不存在或已取消")

    message_query = db.query(AgentMessage).filter(
        AgentMessage.session_id == session.id,
    )
    if before_id is not None:
        message_query = message_query.filter(AgentMessage.id < before_id)
    newest_first = message_query.order_by(AgentMessage.id.desc()).limit(limit + 1).all()
    has_more = len(newest_first) > limit
    messages = list(reversed(newest_first[:limit]))
    return {
        "title": session.title,
        "agent_name": agent.name,
        "agent_icon": agent.icon,
        "shared_at": share.created_at,
        "has_more": has_more,
        "items": [
            {
                "id": message.id,
                "role": message.role,
                "content": unpack_user_content(message.content)["content"] if message.role == "user" else message.content,
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }


@shared_router.get("")
def list_public_agents(
    q: str = Query(default="", max_length=200),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    private_skill = db.query(ExpertSkillBinding.agent_id).join(
        SkillInstallation, SkillInstallation.id == ExpertSkillBinding.installation_id,
    ).join(Skill, Skill.id == SkillInstallation.skill_id).join(
        SkillRelease, SkillRelease.id == SkillInstallation.release_id,
    ).filter(
        ExpertSkillBinding.agent_id == Agent.id,
        SkillInstallation.status == "active", published_release_filter(),
        Skill.is_public == False,
    ).exists()
    private_mcp = db.query(ExpertMcpBinding.agent_id).join(
        McpConnection, McpConnection.id == ExpertMcpBinding.connection_id,
    ).join(McpDefinition, McpDefinition.id == McpConnection.definition_id).join(
        McpRevision, McpRevision.id == McpConnection.revision_id,
    ).filter(
        ExpertMcpBinding.agent_id == Agent.id, ExpertMcpBinding.status == "active",
        McpConnection.status != "deleted", McpDefinition.status == "published",
        McpRevision.status == "published", ~shareable_mcp_definition(),
    ).exists()
    bindings = agent_prompt_templates
    private_source = db.query(PromptTemplate.id).join(
        bindings, bindings.c.prompt_template_id == PromptTemplate.id,
    ).filter(
        bindings.c.agent_id == Agent.id,
        or_(PromptTemplate.is_deleted == True,
            and_(PromptTemplate.is_public == False, PromptTemplate.is_system == False)),
    ).exists()
    query = db.query(Agent).options(lazyload("*")).filter(
        Agent.is_deleted == False,
        Agent.is_public == True,
        Agent.kind == "expert",
        ~private_skill, ~private_mcp, ~private_source,
    )
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(Agent.name.like(pattern), Agent.description.like(pattern)))
    total = query.count()
    items = query.order_by(Agent.updated_at.desc(), Agent.id.desc()).offset(skip).limit(limit).all()
    ids = [agent.id for agent in items]
    skill_rows = db.query(ExpertSkillBinding.agent_id, Skill.id, Skill.name).select_from(ExpertSkillBinding).join(
            SkillInstallation,
            SkillInstallation.id == ExpertSkillBinding.installation_id,
        ).join(SkillRelease, SkillRelease.id == SkillInstallation.release_id).join(
            Skill, Skill.id == SkillInstallation.skill_id,
        ).filter(
            ExpertSkillBinding.agent_id.in_(ids),
            SkillInstallation.status == "active",
            Skill.is_deleted == False,
            Skill.is_public == True,
            published_release_filter(),
        ).order_by(Skill.name.asc(), Skill.id.asc()).all() if ids else []
    skills_by_agent = {agent_id: [] for agent_id in ids}
    for agent_id, skill_id, skill_name in skill_rows:
        skills_by_agent[agent_id].append({"id": skill_id, "name": skill_name})
    mcp_counts = dict(db.query(ExpertMcpBinding.agent_id, func.count()).join(
            McpConnection,
            McpConnection.id == ExpertMcpBinding.connection_id,
        ).join(McpDefinition, McpDefinition.id == McpConnection.definition_id).join(
            McpRevision, McpRevision.id == McpConnection.revision_id,
        ).filter(
            ExpertMcpBinding.agent_id.in_(ids),
            ExpertMcpBinding.status == "active",
            McpConnection.status != "deleted",
            McpDefinition.status == "published",
            McpRevision.status == "published",
        ).group_by(ExpertMcpBinding.agent_id).all()) if ids else {}
    prompt_counts = dict(db.query(bindings.c.agent_id, func.count()).filter(
        bindings.c.agent_id.in_(ids),
    ).group_by(bindings.c.agent_id).all()) if ids else {}
    payload = []
    for agent in items:
        payload.append({
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "icon": agent.icon,
            "runtime_type": agent.runtime_type,
            "user_id": agent.user_id,
            "skills": skills_by_agent[agent.id],
            "skill_count": len(skills_by_agent[agent.id]),
            "mcp_count": mcp_counts.get(agent.id, 0),
            "prompt_count": prompt_counts.get(agent.id, 0),
            "created_at": agent.created_at,
            "updated_at": agent.updated_at,
        })
    return {
        "total": total,
        "items": payload,
    }


# ============= 消息历史 =============

@router.get(
    "/{agent_id}/sessions/{session_id}/messages",
    response_model=AgentSessionMessagesResponse,
)
def get_messages(
    agent_id: int,
    session_id: int,
    before_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.agent_id == agent_id,
        AgentSession.user_id == current_user.user_id,
        AgentSession.is_deleted == False,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    active_run = db.query(AgentRun).filter(
        AgentRun.session_id == session_id,
        AgentRun.user_id == current_user.user_id,
        AgentRun.source == "web",
        AgentRun.status.in_(["queued", "running"]),
    ).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).first()
    session_payload = AgentSessionResponse.model_validate(session)
    if active_run is not None:
        session_payload.active_run_id = active_run.id
        session_payload.active_run_status = active_run.status
        session_payload.active_run_started_at = active_run.started_at or active_run.created_at

    message_query = db.query(AgentMessage).filter(
        AgentMessage.session_id == session_id,
    )
    if before_id is not None:
        message_query = message_query.filter(AgentMessage.id < before_id)
    newest_first = message_query.order_by(AgentMessage.id.desc()).limit(limit + 1).all()
    has_more = len(newest_first) > limit
    messages = list(reversed(newest_first[:limit]))
    assistant_message_ids = [m.id for m in messages if m.role == "assistant"]
    feedback_by_message = {
        row.message_id: feedback_value(row)
        for row in db.query(AgentMessageFeedback).filter(
            AgentMessageFeedback.message_id.in_(assistant_message_ids),
            AgentMessageFeedback.user_id == current_user.user_id,
        ).all()
    } if assistant_message_ids else {}
    charged_points_by_message = {}
    run_id_by_message = {}
    if assistant_message_ids:
        for run in db.query(
            AgentRun.assistant_message_id, AgentRun.id, AgentRun.charged_points,
            AgentRun.settlement_status, AgentRun.pricing_snapshot,
        ).filter(AgentRun.assistant_message_id.in_(assistant_message_ids)).all():
            charged_points_by_message[run.assistant_message_id] = recorded_charged_points(run)
            run_id_by_message[run.assistant_message_id] = run.id

    return {
        "session": session_payload,
        "has_more": has_more,
        "items": [
            {
                "id": m.id,
                "role": m.role,
                "run_id": run_id_by_message.get(m.id),
                **(unpack_user_content(m.content) if m.role == "user" else {"content": m.content}),
                "charged_points": charged_points_by_message.get(m.id),
                "feedback": feedback_by_message.get(m.id),
                "created_at": m.created_at,
            }
            for m in messages
        ]
    }


@router.post("/{agent_id}/sessions/{session_id}/messages")
def save_messages(
    agent_id: int,
    session_id: int,
    body: SaveMessagesRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.agent_id == agent_id,
        AgentSession.user_id == current_user.user_id,
        AgentSession.is_deleted == False,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.source == "api":
        raise HTTPException(status_code=409, detail="开放调用会话只读")

    saved = []
    for msg in body.messages:
        m = AgentMessage(
            session_id=session_id,
            role=msg.role,
            content=pack_user_content(msg.content) if msg.role == "user" else msg.content,
        )
        db.add(m)
        saved.append(m)

    db.commit()
    return {"count": len(saved)}


# ============= 发消息（SSE） =============


@router.get("/{agent_id}/runs/{run_id}/events")
def resume_agent_run(
    agent_id: int,
    run_id: str,
    after: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    run = db.query(AgentRun).join(AgentSession, AgentSession.id == AgentRun.session_id).filter(
        AgentRun.id == run_id,
        AgentRun.agent_id == agent_id,
        AgentRun.user_id == current_user.user_id,
        AgentRun.source == "web",
        AgentSession.is_deleted == False,
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    db.close()
    return StreamingResponse(
        replay_events(SessionLocal, run_id, after), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{agent_id}/runs/{run_id}/cancel")
def cancel_agent_run(
    agent_id: int,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    run = db.query(AgentRun).filter(
        AgentRun.id == run_id,
        AgentRun.agent_id == agent_id,
        AgentRun.user_id == current_user.user_id,
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.status not in {"queued", "running", "unknown"}:
        return {"run_id": run.id, "status": run.status, "cancel_requested": False}

    run.cancel_requested = True
    db.commit()
    cancelled_in_process = cancel_web_run(run.id)
    return {
        "run_id": run.id,
        "status": run.status,
        "cancel_requested": True,
        "cancelled_in_process": cancelled_in_process,
    }


def _migrate_web_session_runtime(
    session: AgentSession,
    runtime_type: str,
) -> bool:
    """Move a Web session to the agent's current runtime without losing DB history."""
    if (session.source or "web") != "web" or session.runtime_type == runtime_type:
        return False

    session.runtime_type = runtime_type
    session.runtime_session_id = None
    session.claude_session_id = None
    session.runtime_instance_id = None
    session.runtime_state = "active"
    return True


@router.post("/{agent_id}/messages")
async def send_message(
    agent_id: int,
    data: AgentMessageRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
    authorization: Optional[str] = Header(default=None),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """给智能体发消息，SSE 流式返回"""
    agent = get_usable_agent(db, agent_id, current_user.user_id)

    target_session = None
    agent = runtime_agent(db, agent)
    if data.runtime_type and data.runtime_type != agent.runtime_type:
        raise HTTPException(status_code=400, detail="Runtime 由全局智能体设置统一管理")
    if data.session_id:
        target_session = db.query(AgentSession).filter(
            AgentSession.id == data.session_id,
            AgentSession.agent_id == agent_id,
            AgentSession.user_id == current_user.user_id,
            AgentSession.is_deleted == False,
        ).first()
        if not target_session:
            raise HTTPException(status_code=404, detail="会话不存在")
        if target_session.source == "api":
            raise HTTPException(status_code=409, detail="开放调用会话只读")

    # 确定使用的模型
    if target_session is not None:
        current_runtime = agent.runtime_type or "claude_code"
        if _migrate_web_session_runtime(target_session, current_runtime):
            db.commit()

    if (
        target_session is not None
        and target_session.model_id is not None
        and data.model_id is not None
        and data.model_id != target_session.model_id
    ):
        raise HTTPException(status_code=409, detail="当前会话已固定使用其他模型，请新建会话后切换")
    available_models = workbench_models(db, current_user.user_id)
    available_model_ids = {model.id for model in available_models}
    effective_runtime = (
        getattr(target_session, "runtime_type", None)
        or data.runtime_type
        or agent.runtime_type
        or "claude_code"
    )
    # A session pins its model for history consistency. Repair a stale pin
    # when the user did not explicitly request a different model, otherwise a
    # deleted/disabled or OpenAI-only model can make an old conversation
    # permanently unusable under Claude Code.
    session_model_repaired = False
    session_model_id = getattr(target_session, "model_id", None)
    if target_session is not None and data.model_id is None and session_model_id:
        session_model = next(
            (model for model in available_models if model.id == session_model_id),
            None,
        )
        if session_model is None or not model_supports_runtime(session_model, effective_runtime):
            session_model_id = _agent_default_model_id(db, agent, current_user.user_id)
            session_model_repaired = session_model_id != target_session.model_id
    effective_model_id = (
        session_model_id
        or data.model_id
        or _agent_default_model_id(db, agent, current_user.user_id)
        or (available_models[0].id if available_models else None)
    )
    if not effective_model_id:
        raise HTTPException(status_code=400, detail="智能体未绑定模型，请选择模型后发送")
    selected_model = _get_model_or_400(db, effective_model_id, current_user)

    # Workbench models are resolved per user, including newly configured models.
    if effective_model_id not in available_model_ids:
        raise HTTPException(status_code=400, detail="当前用户没有可用模型")
    if not selected_model.is_enabled:
        raise HTTPException(status_code=400, detail="所选模型已停用")
    _validate_models_for_runtime_or_400([selected_model], effective_runtime)
    if session_model_repaired:
        target_session.model_id = effective_model_id
        db.commit()

    normalized_idempotency_key = idempotency_key.strip() if isinstance(idempotency_key, str) else None
    if normalized_idempotency_key == "":
        normalized_idempotency_key = None
    if normalized_idempotency_key and len(normalized_idempotency_key) > 100:
        raise HTTPException(status_code=400, detail="Idempotency-Key 长度不能超过 100 个字符")

    request_fingerprint = hashlib.sha256(json.dumps({
        "agent_id": int(agent.id),
        "session_id": data.session_id,
        "content": data.content,
        "model_id": effective_model_id,
        "runtime_type": effective_runtime,
        "skill_id": data.skill_id,
        "attached_files": list(data.attached_files or []),
        "permission_mode": data.permission_mode,
        "page_context": data.page_context.model_dump() if data.page_context else None,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    stream_args = {
        "agent_id": int(agent.id),
        "user_input": data.content,
        "session_id": data.session_id,
        "user_id": int(current_user.user_id),
        "runtime_type_override": data.runtime_type,
        "model_id_override": effective_model_id,
        "skill_id_override": data.skill_id,
        "attached_files": list(data.attached_files or []),
        "permission_mode": data.permission_mode,
        "page_context": data.page_context.model_dump() if data.page_context else None,
        "request_authorization": (
            authorization.strip()
            if isinstance(authorization, str)
            and authorization.lower().startswith("bearer ")
            and authorization[7:].strip()
            else None
        ),
        "idempotency_key": normalized_idempotency_key,
        "idempotency_fingerprint": request_fingerprint,
    }

    # Streaming may last minutes; release the request-scoped connection before it starts.
    db.close()
    try:
        await check_stream_store()
    except StreamUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None

    async def generate():
        async for sse in run_agent_chat(
            **stream_args,
        ):
            yield sse

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============= 工作区文件浏览 =============

@router.post("/{agent_id}/images/upload")
async def upload_conversation_image(
    agent_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Store chat images in OSS and return a permanent public URL."""
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    workspace, _ = bind_agent_workspace(db, agent)
    workspace_id = workspace.id
    content = await file.read(MAX_IMAGE_BYTES + 1)
    db.commit()
    try:
        url = await asyncio.to_thread(upload_chat_image, content, file.content_type, workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except ImageStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"name": file.filename, "url": url}


@router.post("/{agent_id}/files/upload")
async def upload_workspace_files(
    agent_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """上传文件到工作区（文件名自动 sanitize 防路径穿越）"""
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    workspace, _ = bind_agent_workspace(db, agent)
    workspace_provider = get_workspace_provider(agent)
    if len(files) > settings.agent_max_upload_files:
        raise HTTPException(
            status_code=413,
            detail=f"单次最多上传 {settings.agent_max_upload_files} 个文件",
        )

    pending_uploads = []
    total_bytes = 0
    chunk_size = 1024 * 1024
    for file in files:
        parts = []
        file_bytes = 0
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            file_bytes += len(chunk)
            total_bytes += len(chunk)
            if file_bytes > settings.agent_max_upload_file_bytes:
                raise HTTPException(status_code=413, detail=f"文件过大: {file.filename}")
            if total_bytes > settings.agent_max_upload_total_bytes:
                raise HTTPException(status_code=413, detail="上传文件总大小超过限制")
            parts.append(chunk)
        pending_uploads.append((file, b"".join(parts)))

    db.commit()
    filesystem_workspace = workspace_snapshot(workspace)
    lease = await _file_mutation_lease(workspace.id)
    uploaded = []
    def write_files():
        for file, content in pending_uploads:
            safe_path = workspace_provider.write_file(
                filesystem_workspace, file.filename or "untitled", content,
            )
            uploaded.append({"name": file.filename, "path": safe_path})
    async with lease:
        try:
            committed = await _run_sync_atomic(lease.commit_workspace, write_files)
            if not committed:
                raise HTTPException(status_code=409, detail="工作区执行权已失效，请重试")
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"uploaded": uploaded}


@router.get("/{agent_id}/files")
def list_workspace_files(
    agent_id: int,
    path: str = "",
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """列出工作区文件及其平台托管状态。"""
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    workspace, _ = bind_agent_workspace(db, agent)
    try:
        result = get_workspace_provider(agent).list_dir(workspace, path)
        if result.get("type") == "dir":
            runtime_type = getattr(agent, "runtime_type", "claude_code")
            for item in result.get("items", []):
                item["is_managed"] = is_managed_workspace_path(runtime_type, item["path"])
                item["is_previewable"] = (
                    item.get("type") == "file" and is_text_preview_path(item["path"])
                )
        return result
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{agent_id}/files/download")
def download_workspace_file(
    agent_id: int,
    path: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """下载工作区文件"""
    from urllib.parse import quote

    from fastapi.responses import Response
    from sandbox.base import WorkspaceDownloadTooLarge

    agent = get_usable_agent(db, agent_id, current_user.user_id)
    workspace, _ = bind_agent_workspace(db, agent)
    try:
        content, filename = get_workspace_provider(agent).read_file_for_download(workspace, path)
    except WorkspaceDownloadTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.delete("/{agent_id}/files")
async def delete_workspace_file(
    agent_id: int,
    path: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Delete a user-created file or directory from an Agent workspace."""
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    workspace, _ = bind_agent_workspace(db, agent)
    try:
        normalized_path = normalize_workspace_relative_path(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if is_managed_workspace_path(
        getattr(agent, "runtime_type", "claude_code"), normalized_path
    ):
        raise HTTPException(status_code=403, detail="智能体托管内容不可删除")
    db.commit()
    provider = get_workspace_provider(agent)
    filesystem_workspace = workspace_snapshot(workspace)
    lease = await _file_mutation_lease(workspace.id)
    try:
        async with lease:
            committed = await _run_sync_atomic(
                lease.commit_workspace,
                lambda: provider.delete_path(filesystem_workspace, normalized_path),
            )
            if not committed:
                raise HTTPException(status_code=409, detail="工作区执行权已失效，请重试")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "工作区内容已删除"}


async def _file_mutation_lease(workspace_id):
    lease = await acquire_agent_execution_lease(
        workspace_id=workspace_id, run_id=secrets.token_hex(16), wait=False,
    )
    if lease is None:
        raise HTTPException(status_code=409, detail="工作区正在使用，请运行结束后重试")
    return lease


@router.get("/{agent_id}/files/preview")
def preview_workspace_file(
    agent_id: int,
    path: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Preview a UTF-8 text file without executing its content.

    HTML artifacts are read in full so generated pages are not truncated by
    the bounded text preview limits used for other source files.
    """
    if not is_text_preview_path(path):
        raise HTTPException(status_code=415, detail="该文件类型不支持文本预览")
    agent = get_usable_agent(db, agent_id, current_user.user_id)
    workspace, _ = bind_agent_workspace(db, agent)
    is_html = posixpath.splitext(str(path or '').replace('\\', '/'))[1].casefold() in {'.html', '.htm'}
    try:
        provider = get_workspace_provider(agent)
        if is_html:
            content_bytes, filename = provider.read_file(workspace, path)
        else:
            content_bytes, filename = provider.read_file_limited(
                workspace, path, WORKSPACE_PREVIEW_MAX_BYTES
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not is_html and len(content_bytes) > WORKSPACE_PREVIEW_MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 1 MiB，无法预览")
    try:
        content = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="文件不是有效的 UTF-8 文本")
    if "\x00" in content:
        raise HTTPException(status_code=415, detail="文件包含二进制内容，无法预览")
    line_count = len(content.splitlines())
    if not is_html and line_count > WORKSPACE_PREVIEW_MAX_LINES:
        raise HTTPException(status_code=413, detail="文件超过 1000 行，无法预览")
    return {
        "name": filename,
        "path": path,
        "content": content,
        "size": len(content_bytes),
        "line_count": line_count,
    }
