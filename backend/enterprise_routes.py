"""Enterprise assistant bootstrap, platform models and authoritative credits."""

from datetime import datetime, timezone
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload

from auth import CurrentUser, get_current_active_user
from agent_settings import (
    published_agent_settings, published_workbench_settings, runtime_agent,
    seed_workbench_settings,
)
from credit_accounts import _ensure_account, _grant_claim, _local_date, ensure_initial_credits
from credit_billing import reconcile_pending_platform_runs
from credit_labels import credit_display_name
from model_catalog import chat_model_payload, workbench_models
from database import get_db, settings
from enterprise_schemas import (
    AssistantSettingsDraft,
    AssistantSettingsResponse,
    AssistantSettingsState,
    AgentSettingsDraft, AgentSettingsResponse, AgentSettingsState,
    WorkbenchSettingsDraft, WorkbenchSettingsResponse, WorkbenchSettingsState,
    BootstrapResponse,
    CreditAccountResponse,
    CreditBalanceResponse,
    CreditAdjustmentRequest,
    CreditLedgerList,
    GlobalSettingsResponse,
    GlobalSettingsUpdate,
    GlobalRuntimeEnvironment,
    PlatformModelUpsert,
)
from enterprise_workspace import bind_agent_workspace, ensure_user_workspace, workspace_payload
from model_compat import model_supports_runtime
from model_gateway import validate_upstream_url
from skill_release_policy import published_release_filter
from skill_access import visible_skill_filter
from runtime_environment import load_global_runtime_environment
from models import (
    Agent,
    AIModel,
    CreditAccount,
    CreditClaimRecord,
    CreditLedger,
    ModelPricingVersion,
    PlatformAgentSettings,
    PlatformGlobalSettings,
    WorkbenchSettings,
)

router = APIRouter(tags=["enterprise-assistant"])
ADMIN_PERMISSION = "aihub:assistant:settings:manage"


def _require_admin(user: CurrentUser) -> None:
    if not (user.is_superuser or user.is_staff or user.has_permission(ADMIN_PERMISSION)):
        raise HTTPException(status_code=403, detail=f"Permission denied: {ADMIN_PERMISSION} required")


def _published_settings(db: Session) -> PlatformAgentSettings | None:
    return published_agent_settings(db)


def _legacy_settings_payload(db: Session, status: str):
    """Expose one coherent read-only snapshot for clients of the retired endpoint."""
    policy = db.query(PlatformAgentSettings).filter_by(status=status).order_by(
        PlatformAgentSettings.version.desc(),
    ).first()
    if policy is None:
        return None
    identity = db.query(WorkbenchSettings).filter_by(status=status).order_by(
        WorkbenchSettings.version.desc(),
    ).first()
    if identity is None and status == "draft":
        identity = db.query(WorkbenchSettings).filter_by(status="published").order_by(
            WorkbenchSettings.version.desc(),
        ).first()
    source = identity or policy
    payload = {
        **{field: getattr(policy, field) for field in AgentSettingsDraft.model_fields},
        **{field: getattr(source, field, definition.default)
           for field, definition in WorkbenchSettingsDraft.model_fields.items()},
        **{
            field: getattr(policy, field)
            for field in ("id", "version", "status", "created_by", "published_by", "published_at", "created_at", "updated_at")
        },
    }
    return AssistantSettingsResponse.model_validate(payload)


@router.get("/api/global-settings", response_model=GlobalSettingsResponse)
def get_global_settings(
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(get_current_active_user),
):
    global_settings = db.query(PlatformGlobalSettings).filter(
        PlatformGlobalSettings.id == 1
    ).first()
    return global_settings or GlobalSettingsResponse()


@router.put("/api/admin/global-settings", response_model=GlobalSettingsResponse)
def update_global_settings(
    data: GlobalSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    global_settings = db.query(PlatformGlobalSettings).filter(
        PlatformGlobalSettings.id == 1
    ).first()
    if global_settings is None:
        global_settings = PlatformGlobalSettings(id=1)
        db.add(global_settings)
    for field, value in data.model_dump().items():
        setattr(global_settings, field, value)
    global_settings.updated_by = current_user.user_id
    db.commit()
    db.refresh(global_settings)
    return global_settings


@router.get("/api/admin/global-settings/runtime-environment", response_model=GlobalRuntimeEnvironment)
def get_global_runtime_environment(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    return GlobalRuntimeEnvironment(variables=load_global_runtime_environment(db))


@router.put("/api/admin/global-settings/runtime-environment", response_model=GlobalRuntimeEnvironment)
def update_global_runtime_environment(
    data: GlobalRuntimeEnvironment,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    global_settings = db.query(PlatformGlobalSettings).filter(
        PlatformGlobalSettings.id == 1,
    ).first()
    if global_settings is None:
        global_settings = PlatformGlobalSettings(id=1)
        db.add(global_settings)
    global_settings.runtime_environment = dict(data.variables)
    global_settings.updated_by = current_user.user_id
    db.commit()
    return data


def _credit_response(db: Session, user_id: int, policy: PlatformAgentSettings) -> CreditAccountResponse:
    reconcile_pending_platform_runs(db, user_id=user_id)
    account = ensure_initial_credits(db, user_id, policy)
    today = _local_date(policy)
    claimed = db.query(CreditClaimRecord.id).filter(
        CreditClaimRecord.user_id == user_id,
        CreditClaimRecord.claim_type == "daily",
        CreditClaimRecord.claim_date == today,
    ).first() is not None
    return CreditAccountResponse(
        available_balance=account.available_balance,
        reserved_balance=account.reserved_balance,
        status=account.status,
        version=account.version,
        display_name=credit_display_name(policy),
        display_name_en=policy.credit_display_name_en,
        daily_claim_amount=policy.daily_claim_amount,
        today=today,
        claimed_today=claimed,
        low_balance_threshold=policy.low_balance_threshold,
    )


def _platform_model_or_404(db: Session, model_id: int) -> AIModel:
    model = db.query(AIModel).filter(
        AIModel.id == model_id,
        AIModel.scope == "platform",
        AIModel.is_deleted == False,
    ).first()
    if model is None:
        raise HTTPException(status_code=404, detail="平台模型不存在")
    return model


def _agents_using_platform_model(db: Session, model_id: int) -> list[Agent]:
    return db.query(Agent).filter(
        Agent.is_deleted == False,
        or_(
            Agent.default_model_id == model_id,
            Agent.models.any(AIModel.id == model_id),
        ),
    ).all()


def _pricing_payload(pricing: ModelPricingVersion | None) -> dict:
    fields = ("input_rate", "output_rate", "cache_read_rate", "cache_creation_rate", "rate_scale")
    return {field: int(getattr(pricing, field, 0) or 0) for field in fields}


def _platform_model_payload(db: Session, model: AIModel) -> dict:
    pricing = db.query(ModelPricingVersion).filter(
        ModelPricingVersion.model_id == model.id,
        ModelPricingVersion.effective_to.is_(None),
    ).order_by(ModelPricingVersion.version.desc()).first()
    return {
        "id": model.id,
        "name": model.name,
        "provider": model.provider,
        "api_proxy_url": model.api_proxy_url,
        "api_protocol": model.api_protocol,
        "reasoning_support": model.reasoning_support,
        "remarks": model.remarks,
        "scope": model.scope,
        "is_enabled": model.is_enabled,
        "health_status": model.health_status,
        "has_api_key": model.has_api_key,
        "pricing_version": pricing.version if pricing else None,
        **_pricing_payload(pricing),
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


def _replace_pricing(db: Session, model_id: int, data: PlatformModelUpsert) -> None:
    current = db.query(ModelPricingVersion).filter(
        ModelPricingVersion.model_id == model_id,
        ModelPricingVersion.effective_to.is_(None),
    ).order_by(ModelPricingVersion.version.desc()).first()
    now = datetime.now(timezone.utc)
    if current:
        current.effective_to = now
    next_version = (current.version + 1) if current else 1
    db.add(ModelPricingVersion(
        model_id=model_id,
        version=next_version,
        input_rate=data.input_rate,
        output_rate=data.output_rate,
        cache_read_rate=data.cache_read_rate,
        cache_creation_rate=data.cache_creation_rate,
        rate_scale=data.rate_scale,
        effective_from=now,
    ))


@router.get("/api/public/assistant-appearance")
def public_assistant_appearance(db: Session = Depends(get_db)):
    """Only public mascot artwork; never expose the assistant's private settings."""
    policy = published_workbench_settings(db)
    return {"mascot": policy.assistant_mascot if policy else "@cow"}


def _versioned_state(db, model, response):
    def get(status):
        row = db.query(model).filter_by(status=status).order_by(model.version.desc()).first()
        return response.model_validate(row) if row else None
    return {"draft": get("draft"), "published": get("published")}


def _save_versioned_draft(db, model, data, user):
    draft = db.query(model).filter_by(status="draft").order_by(model.version.desc()).first()
    if draft is None:
        draft = model(version=(db.query(func.max(model.version)).scalar() or 0) + 1,
                      created_by=user.user_id)
        db.add(draft)
    for field, value in data.model_dump().items():
        setattr(draft, field, value)
    return draft


def _publish_version(db, model, draft, user):
    for current in db.query(model).filter_by(status="published").populate_existing().with_for_update().all():
        current.status = "superseded"
    draft.status = "published"
    draft.published_by = user.user_id
    draft.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/api/admin/agent-settings", response_model=AgentSettingsState)
def get_agent_settings(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_active_user)):
    _require_admin(current_user)
    return _versioned_state(db, PlatformAgentSettings, AgentSettingsResponse)


@router.get("/api/agent-settings/runtime", response_model=AgentSettingsResponse | None)
def get_agent_runtime_settings(db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_active_user)):
    policy = _published_settings(db)
    return AgentSettingsResponse.model_validate(policy) if policy else None


@router.put("/api/admin/agent-settings/draft", response_model=AgentSettingsResponse)
def save_agent_settings_draft(data: AgentSettingsDraft, db: Session = Depends(get_db),
                              current_user: CurrentUser = Depends(get_current_active_user)):
    _require_admin(current_user)
    seed_workbench_settings(db)
    draft = _save_versioned_draft(db, PlatformAgentSettings, data, current_user)
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/api/admin/agent-settings/publish", response_model=AgentSettingsResponse)
def publish_agent_settings(data: AgentSettingsDraft | None = None, db: Session = Depends(get_db),
                           current_user: CurrentUser = Depends(get_current_active_user)):
    _require_admin(current_user)
    seed_workbench_settings(db)
    draft = _save_versioned_draft(db, PlatformAgentSettings, data, current_user) if data else (
        db.query(PlatformAgentSettings).filter_by(status="draft").order_by(PlatformAgentSettings.version.desc()).first()
    )
    if draft is None:
        raise HTTPException(status_code=409, detail="没有可发布的草稿")
    AgentSettingsDraft.model_validate(draft, from_attributes=True)
    if draft.runtime_type != "claude_code":
        raise HTTPException(status_code=400, detail="当前平台全局设置仅支持 Claude Code Runtime")
    if draft.daily_claim_amount <= 0:
        raise HTTPException(status_code=400, detail="每日领取额度必须大于 0")
    return _publish_version(db, PlatformAgentSettings, draft, current_user)


@router.get("/api/admin/workbench-settings", response_model=WorkbenchSettingsState)
def get_workbench_settings(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_active_user)):
    _require_admin(current_user)
    state = _versioned_state(db, WorkbenchSettings, WorkbenchSettingsResponse)
    if db.query(WorkbenchSettings.id).first() is None:
        state = _versioned_state(db, PlatformAgentSettings, WorkbenchSettingsResponse)
    return state


@router.put("/api/admin/workbench-settings/draft", response_model=WorkbenchSettingsResponse)
def save_workbench_settings_draft(data: WorkbenchSettingsDraft, db: Session = Depends(get_db),
                                  current_user: CurrentUser = Depends(get_current_active_user)):
    _require_admin(current_user)
    seed_workbench_settings(db)
    versions = _lock_workbench_settings(db)
    if any(row.status == "draft" for row in versions):
        raise HTTPException(status_code=409, detail="已有待发布草稿，请刷新后发布该草稿，不允许修改或覆盖")
    draft = _new_workbench_draft(db, versions, data, current_user)
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/api/admin/workbench-settings/publish", response_model=WorkbenchSettingsResponse)
def publish_workbench_settings(data: WorkbenchSettingsDraft | None = None, db: Session = Depends(get_db),
                               current_user: CurrentUser = Depends(get_current_active_user)):
    _require_admin(current_user)
    seed_workbench_settings(db)
    versions = _lock_workbench_settings(db)
    draft = next((row for row in reversed(versions) if row.status == "draft"), None)
    if draft is not None and data is not None:
        raise HTTPException(status_code=409, detail="已有待发布草稿，请刷新后原样发布，不允许编辑后发布")
    if draft is None and data is not None:
        draft = _new_workbench_draft(db, versions, data, current_user)
    if draft is None:
        raise HTTPException(status_code=409, detail="没有可发布的草稿")
    current = next((row for row in reversed(versions) if row.status == "published"), None)
    if not _workbench_changes(current, draft):
        raise HTTPException(status_code=409, detail="与后台已发布配置一致，无需发布")
    if draft.default_model_id is None:
        raise HTTPException(status_code=400, detail="必须选择默认平台模型")
    model = _platform_model_or_404(db, draft.default_model_id)
    policy = _published_settings(db)
    runtime_type = policy.runtime_type if policy else "claude_code"
    if not model.is_enabled or not model.has_api_key:
        raise HTTPException(status_code=400, detail="默认平台模型未启用或未配置 API Key")
    if not model_supports_runtime(model, runtime_type):
        raise HTTPException(status_code=400, detail="默认平台模型与 Runtime 不兼容")
    return _publish_version(db, WorkbenchSettings, draft, current_user)


def _lock_workbench_settings(db):
    """Use current locking reads even under MySQL repeatable-read isolation."""
    return db.query(WorkbenchSettings).order_by(WorkbenchSettings.version).populate_existing().with_for_update().all()


def _new_workbench_draft(db, versions, data, user):
    current = next((row for row in reversed(versions) if row.status == "published"), None)
    if not _workbench_changes(current, data):
        raise HTTPException(status_code=409, detail="与后台已发布配置一致，无需保存或发布")
    draft = WorkbenchSettings(
        version=max((row.version for row in versions), default=0) + 1,
        created_by=user.user_id, **data.model_dump(),
    )
    db.add(draft)
    return draft


def _workbench_changes(previous, current):
    """Compare persisted configuration values, treating optional blank text equally."""
    changes = {}
    for field in WorkbenchSettingsDraft.model_fields:
        before = getattr(previous, field, None)
        after = getattr(current, field, None)
        before_empty = before is None or isinstance(before, str) and not before.strip()
        after_empty = after is None or isinstance(after, str) and not after.strip()
        if before != after and not (before_empty and after_empty):
            changes[field] = {"before": before, "after": after}
    return changes


@router.get("/api/admin/workbench-settings/history")
def get_workbench_settings_history(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    model = WorkbenchSettings if db.query(WorkbenchSettings.id).first() else PlatformAgentSettings
    rows = db.query(model).filter(model.status.in_(("published", "superseded"))).order_by(model.version).all()
    items = []
    previous = None
    for row in rows:
        changes = _workbench_changes(previous, row)
        if changes:
            items.append({
                **{field: getattr(row, field) for field in (
                    "id", "version", "status", "created_by", "published_by", "published_at",
                )},
                "changes": changes,
            })
        previous = row
    items.reverse()
    return {
        "total": len(items),
        "items": items[skip:skip + limit],
    }


@router.get("/api/admin/assistant-settings", response_model=AssistantSettingsState, deprecated=True)
def get_assistant_settings(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    return {
        "draft": _legacy_settings_payload(db, "draft"),
        "published": _legacy_settings_payload(db, "published"),
    }


@router.put("/api/admin/assistant-settings/draft", deprecated=True)
def save_assistant_settings_draft(
    data: AssistantSettingsDraft,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    raise HTTPException(status_code=410, detail="设置已拆分，请使用智能体设置或工作台设置分别保存草稿")


@router.post("/api/admin/assistant-settings/publish", deprecated=True)
def publish_assistant_settings(
    data: AssistantSettingsDraft | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    raise HTTPException(status_code=410, detail="设置已拆分，请使用智能体设置或工作台设置分别发布")


@router.get("/api/admin/platform-models")
def list_platform_models(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    items = db.query(AIModel).filter(
        AIModel.scope == "platform", AIModel.is_deleted == False
    ).order_by(AIModel.created_at.desc()).all()
    return {"total": len(items), "items": [_platform_model_payload(db, item) for item in items]}


@router.post("/api/admin/platform-models")
def create_platform_model(
    data: PlatformModelUpsert,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    if not data.api_key:
        raise HTTPException(status_code=400, detail="平台模型 API Key 不能为空")
    if not settings.agent_credential_encryption_key:
        raise HTTPException(
            status_code=503,
            detail="未配置 AGENT_CREDENTIAL_ENCRYPTION_KEY，禁止保存平台模型密钥",
        )
    if data.api_proxy_url:
        try:
            validate_upstream_url(data.api_proxy_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    model = AIModel(
        user_id=0,
        scope="platform",
        name=data.name,
        provider=data.provider,
        api_proxy_url=data.api_proxy_url,
        api_protocol=data.api_protocol,
        reasoning_support=data.reasoning_support,
        remarks=data.remarks,
        is_enabled=data.is_enabled,
    )
    db.add(model)
    db.flush()
    model.store_api_key(data.api_key, app_settings=settings)
    _replace_pricing(db, model.id, data)
    db.commit()
    db.refresh(model)
    return _platform_model_payload(db, model)


@router.put("/api/admin/platform-models/{model_id}")
def update_platform_model(
    model_id: int,
    data: PlatformModelUpsert,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    model = _platform_model_or_404(db, model_id)
    assistant = published_workbench_settings(db)
    policy = _published_settings(db)
    if assistant is not None and assistant.default_model_id == model_id:
        runtime_type = policy.runtime_type if policy else "claude_code"
        if not data.is_enabled or not model_supports_runtime(data, runtime_type):
            raise HTTPException(
                status_code=400,
                detail="该模型是工作台当前默认模型，请先更换默认模型并发布，再停用或修改为不兼容的协议",
            )
    if data.api_key and not settings.agent_credential_encryption_key:
        raise HTTPException(
            status_code=503,
            detail="未配置 AGENT_CREDENTIAL_ENCRYPTION_KEY，禁止更新平台模型密钥",
        )
    if data.api_proxy_url:
        try:
            validate_upstream_url(data.api_proxy_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    for field in (
        "name", "provider", "api_proxy_url", "api_protocol", "reasoning_support", "remarks", "is_enabled"
    ):
        setattr(model, field, getattr(data, field))
    if data.api_key:
        model.store_api_key(data.api_key, app_settings=settings)
    _replace_pricing(db, model.id, data)
    db.commit()
    db.refresh(model)
    return _platform_model_payload(db, model)


@router.delete("/api/admin/platform-models/{model_id}")
def delete_platform_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    model = _platform_model_or_404(db, model_id)

    configured_defaults = db.query(WorkbenchSettings.id).filter(
        WorkbenchSettings.default_model_id == model_id,
        WorkbenchSettings.status.in_(("draft", "published")),
    ).all()
    if configured_defaults:
        raise HTTPException(
            status_code=409,
            detail="该平台模型仍是工作台默认模型，请先更换默认模型并发布后再删除",
        )

    affected_agents = _agents_using_platform_model(db, model_id)
    if affected_agents:
        agent_names = "、".join(agent.name for agent in affected_agents)
        raise HTTPException(
            status_code=409,
            detail=(
                f"平台模型仍被以下智能体使用: {agent_names}。"
                "请先解除模型绑定后再删除。"
            ),
        )

    model.is_deleted = True
    db.commit()
    return {"message": "平台模型删除成功"}


@router.get("/api/credits/me", response_model=CreditAccountResponse)
def get_my_credits(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    policy = _published_settings(db)
    if policy is None:
        raise HTTPException(
            status_code=409,
            detail={"message": "管理员尚未发布智能体设置", "data": {"code": "ASSISTANT_SETTINGS_NOT_PUBLISHED"}},
        )
    return _credit_response(db, current_user.user_id, policy)


@router.get("/api/credits/me/ledger", response_model=CreditLedgerList)
def get_my_credit_ledger(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    query = db.query(CreditLedger).filter(CreditLedger.user_id == current_user.user_id)
    return {
        "total": query.count(),
        "items": query.order_by(CreditLedger.id.desc()).offset(skip).limit(limit).all(),
    }


@router.post("/api/credits/me/daily-claim", response_model=CreditAccountResponse)
def claim_daily_credits(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    policy = _published_settings(db)
    if policy is None:
        raise HTTPException(
            status_code=409,
            detail={"message": "管理员尚未发布智能体设置", "data": {"code": "ASSISTANT_SETTINGS_NOT_PUBLISHED"}},
        )
    ensure_initial_credits(db, current_user.user_id, policy)
    _, _, created = _grant_claim(
        db, user_id=current_user.user_id, policy=policy, claim_type="daily"
    )
    if not created:
        raise HTTPException(
            status_code=409,
            detail={"message": "今日已领取", "data": {"code": "CREDIT_ALREADY_CLAIMED"}},
        )
    return _credit_response(db, current_user.user_id, policy)


@router.get("/api/admin/users/{user_id}/credits", response_model=CreditBalanceResponse)
def get_user_credit_balance(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Read the stored balance without creating an account or granting credits."""
    _require_admin(current_user)
    policy = _published_settings(db)
    if policy is None:
        raise HTTPException(status_code=409, detail="请先发布智能体设置")
    account = db.query(CreditAccount).filter(CreditAccount.user_id == user_id).first()
    return CreditBalanceResponse(
        available_balance=account.available_balance if account else 0,
        reserved_balance=account.reserved_balance if account else 0,
        display_name=credit_display_name(policy),
    )


@router.post("/api/admin/users/{user_id}/credits/adjust", response_model=CreditAccountResponse)
def adjust_user_credits(
    user_id: int,
    data: CreditAdjustmentRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_admin(current_user)
    policy = _published_settings(db)
    if policy is None:
        raise HTTPException(status_code=409, detail="请先发布智能体设置")
    _ensure_account(db, user_id)
    account = db.query(CreditAccount).filter(
        CreditAccount.user_id == user_id
    ).populate_existing().with_for_update().one()
    if account.available_balance + data.amount < 0:
        raise HTTPException(status_code=409, detail="调整后余额不能小于 0")
    account.available_balance += data.amount
    account.version += 1
    db.add(CreditLedger(
        user_id=user_id,
        entry_type="admin_adjustment",
        amount=data.amount,
        available_after=account.available_balance,
        reserved_after=account.reserved_balance,
        business_key=f"admin-adjustment:{uuid.uuid4().hex}",
        operator_user_id=current_user.user_id,
        reason=data.reason,
    ))
    db.commit()
    return _credit_response(db, user_id, policy)


@router.post("/api/bootstrap", response_model=BootstrapResponse)
def bootstrap_user(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    # This request commits several idempotent initialization steps. Expiring
    # everything at each commit reloads Agent's selectin relationships,
    # including the entire session history, when building the response.
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        return _bootstrap_user(db, current_user)
    finally:
        db.expire_on_commit = expire_on_commit


def _bootstrap_user(db: Session, current_user: CurrentUser):
    policy = _published_settings(db)
    assistant_settings = published_workbench_settings(db)
    if policy is None:
        raise HTTPException(
            status_code=409,
            detail={"message": "管理员尚未发布智能体设置", "data": {"code": "ASSISTANT_SETTINGS_NOT_PUBLISHED"}},
        )
    if assistant_settings is None or assistant_settings.default_model_id is None:
        raise HTTPException(status_code=409, detail={"message": "管理员尚未发布工作台默认助手设置", "data": {"code": "WORKBENCH_SETTINGS_NOT_PUBLISHED"}})
    model = _platform_model_or_404(db, assistant_settings.default_model_id)
    if not model.is_enabled:
        raise HTTPException(
            status_code=503,
            detail={"message": "默认平台模型不可用", "data": {"code": "DEFAULT_MODEL_UNAVAILABLE"}},
        )

    _grant_claim(db, user_id=current_user.user_id, policy=policy, claim_type="initial")

    agent = db.query(Agent).options(lazyload("*")).filter(
        Agent.default_agent_user_id == current_user.user_id
    ).first()
    created = agent is None
    if created:
        agent = Agent(
            user_id=current_user.user_id,
            kind="personal_default",
            default_agent_user_id=current_user.user_id,
            settings_version=policy.version,
            name=assistant_settings.assistant_name,
            icon=assistant_settings.assistant_icon,
            description=assistant_settings.assistant_description,
            system_prompt=assistant_settings.system_prompt,
            default_model_id=model.id,
            runtime_type=policy.runtime_type,
            thinking_level=policy.thinking_level,
            reasoning_visibility=policy.reasoning_visibility,
            max_turns=policy.max_turns,
            timeout_seconds=policy.timeout_seconds,
            is_public=False,
        )
        agent.models = [model]
        db.add(agent)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            agent = db.query(Agent).options(lazyload("*")).filter(
                Agent.default_agent_user_id == current_user.user_id
            ).first()
            if agent is None:
                raise
    else:
        if agent.is_deleted:
            agent.is_deleted = False
        identity_changed = (
            agent.name != assistant_settings.assistant_name
            or agent.icon != assistant_settings.assistant_icon
            or agent.description != assistant_settings.assistant_description
            or agent.system_prompt != assistant_settings.system_prompt
            or agent.default_model_id != model.id
        )
        if agent.settings_version != policy.version or identity_changed:
            agent.name = assistant_settings.assistant_name
            agent.icon = assistant_settings.assistant_icon
            agent.description = assistant_settings.assistant_description
            agent.system_prompt = assistant_settings.system_prompt
            agent.default_model_id = model.id
            agent.runtime_type = policy.runtime_type
            agent.thinking_level = policy.thinking_level
            agent.reasoning_visibility = policy.reasoning_visibility
            agent.max_turns = policy.max_turns
            agent.timeout_seconds = policy.timeout_seconds
            agent.settings_version = policy.version
    try:
        # Resolve and bind once, including visits with no policy changes.
        workspace, cell = bind_agent_workspace(db, agent, commit=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "message": "用户工作区准备失败" if created else "默认助手配置更新失败",
                "data": {"code": "WORKSPACE_PREPARE_FAILED", "reason": str(exc)},
            },
        ) from exc
    # Personal models are available before their first conversation too.
    available_models = workbench_models(db, current_user.user_id)
    agent.models = [model] + [item for item in available_models if item.id != model.id]
    # Reuse the already resolved model list; avoid loading bindings again after
    # persisting the bindings. Send only fields needed by chat.
    chat_models = [chat_model_payload(item) for item in agent.models]
    db.commit()
    # The default assistant's expertise is the effective workbench skill set:
    # platform defaults plus this user's personal installations.
    from models import Skill, SkillInstallation, SkillRelease, SystemSkillInstallation
    skill_columns = (Skill.id, Skill.name)
    personal_skills = db.query(*skill_columns).select_from(SkillInstallation).join(
        Skill, Skill.id == SkillInstallation.skill_id,
    ).join(SkillRelease, SkillRelease.id == SkillInstallation.release_id).filter(
        SkillInstallation.user_id == current_user.user_id,
        SkillInstallation.scope_agent_id == 0,
        SkillInstallation.status == "active",
        Skill.is_deleted == False,
        visible_skill_filter(current_user.user_id),
        or_(
            published_release_filter(),
            and_(SkillRelease.status == "workspace", Skill.user_id == current_user.user_id),
        ),
    ).all()
    system_skills = db.query(*skill_columns).select_from(SystemSkillInstallation).join(
        Skill, Skill.id == SystemSkillInstallation.skill_id,
    ).join(SkillRelease, SkillRelease.id == SystemSkillInstallation.release_id).filter(
        SystemSkillInstallation.status == "active",
        Skill.is_deleted == False,
        Skill.is_public == True,
        published_release_filter(),
    ).all()
    default_skills = {skill_id: {"id": skill_id, "name": name}
                      for skill_id, name in [*system_skills, *personal_skills]}
    return BootstrapResponse(
        assistant_id=agent.id,
        assistant_name=agent.name,
        assistant_icon=agent.icon or "H",
        settings_version=policy.version,
        default_model_id=agent.default_model_id,
        runtime_type=agent.runtime_type,
        workspace_status=workspace.status,
        workspace=workspace_payload(workspace, cell),
        credit=_credit_response(db, current_user.user_id, policy),
        assistant={
            "id": agent.id, "name": agent.name, "icon": agent.icon or "H",
            "description": agent.description,
            "provider": "平台",
            "skills": sorted(default_skills.values(), key=lambda item: (item["name"].casefold(), item["id"])),
            "default_model_id": agent.default_model_id, "runtime_type": agent.runtime_type,
            "thinking_level": agent.thinking_level, "reasoning_visibility": agent.reasoning_visibility,
            "models": chat_models,
        },
    )
