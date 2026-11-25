"""Installable skills, MCP revisions/connections, Vault and prompt snapshots."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import uuid
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, noload

from asset_runtime import _release_hash, _replace_credential
from asset_scopes import scoped_credential, connection_config, public_connection_config
from agent_prompts import prompt_access_filter
from asset_security import (
    AssetPolicyError,
    audit_asset,
    normalize_grants,
    normalize_tool_policy,
    read_skill_manifest,
    validate_mcp_config,
)
from asset_schemas import (
    AssetBindingRequest,
    CredentialCreateRequest,
    CredentialRotateRequest,
    McpConnectionCreateRequest,
    McpConnectionStatusRequest,
    McpConnectionUpdateRequest,
    McpDefinitionCreateRequest,
    McpImportRequest,
    McpHeadersUpdateRequest,
    McpSecretUpdateRequest,
    McpRevisionCreateRequest,
    PromptImportRequest,
    PromptBindingRequest,
    SkillChangeReleaseRequest,
    SkillDevelopmentRequest,
    SkillInstallRequest,
    SkillReviewRequest,
    SkillRevokeRequest,
    SystemSkillInstallRequest,
    SystemPromptCreateRequest,
    SystemPromptUpdateRequest,
)
from auth import CurrentUser, get_current_active_user
from credential_crypto import AgentCredentialError, decrypt_agent_credential, encrypt_agent_credential
from mcp_headers import ENCRYPTED_ENV, ENCRYPTED_HEADERS, read_env, read_headers, store_env, store_headers, system_auth_mode
from mcp_inspector import McpInspectError, inspect_mcp_server
from mcp_source_config import (
    McpSourceConfigError, normalize_json_mcp_config, source_mcp_config, system_mcp_config,
)
from database import get_db
from skill_release_policy import published_release_filter, restore_scan_rejected_release
from skill_metadata import apply_skill_metadata_filters
from skill_access import skill_access_filter, visible_skill_filter
from models import SkillCollaborator
from enterprise_workspace import bind_agent_workspace, configured_sandbox_type, ensure_user_workspace
from models import (
    Agent,
    AgentRun,
    AssetSecurityEvent,
    CredentialReference,
    ExpertMcpBinding,
    ExpertSkillBinding,
    McpConnection,
    McpUserHeaders,
    McpDefinition,
    McpRevision,
    McpService,
    PromptTemplate,
    Skill,
    SkillInstallation,
    SkillRelease,
    SystemSkillInstallation,
    WorkspacePromptReference,
    WorkspacePromptRemoval,
    WorkspaceRunView,
    agent_prompt_templates,
)
from skill_utils import (
    RELEASES_DIR,
    build_skill_archive,
    load_release_file_tree,
    load_skill_files,
    resolve_release_file_path,
)


router = APIRouter(prefix="/api/assets", tags=["enterprise-assets"])
ASSET_REVIEW_PERMISSION = "aihub:assets:review"
SKILL_CATALOG_SORTS = {"created_at", "download_count", "install_count"}
logger = logging.getLogger("aihub.assets")


def _now():
    return datetime.now(timezone.utc)


def _lock_skill_installations(db: Session, skill_id: int) -> None:
    # Both personal and global writes lock the same parent, including first installs.
    db.query(Skill.id).filter(Skill.id == skill_id).with_for_update().one()


def _locked_skill_installation(db: Session, user_id: int, installation_id: int, agent_id: int | None):
    filters = (
        SkillInstallation.id == installation_id,
        SkillInstallation.user_id == user_id,
        SkillInstallation.scope_agent_id == (agent_id or 0),
    )
    row = db.query(SkillInstallation.skill_id).filter(*filters).first()
    if row is None:
        return None
    _lock_skill_installations(db, row.skill_id)
    return db.query(SkillInstallation).filter(*filters).populate_existing().with_for_update().first()


def _record_skill_install(db: Session, skill_id: int) -> None:
    # Keep the counter in the installation transaction without changing catalog order.
    db.query(Skill).filter(Skill.id == skill_id).update({
        Skill.install_count: Skill.install_count + 1,
        Skill.updated_at: Skill.updated_at,
    }, synchronize_session="fetch")


def _require_personal_skill_installable(db: Session, skill_id: int, *, expert: bool = False) -> None:
    _lock_skill_installations(db, skill_id)
    if expert:
        return
    system_installation = db.query(SystemSkillInstallation.id).filter(
        SystemSkillInstallation.skill_id == skill_id,
        SystemSkillInstallation.status == "active",
    ).with_for_update().first()
    if system_installation is not None:
        raise HTTPException(status_code=409, detail="该技能已全局安装，请使用全局版本")


def _uninstall_personal_skill_copies(db: Session, skill_id: int) -> int:
    """Global defaults may replace workbench copies, never expert bindings."""
    return db.query(SkillInstallation).filter(
        SkillInstallation.skill_id == skill_id,
        SkillInstallation.scope_agent_id == 0,
        SkillInstallation.status != "uninstalled",
        ~db.query(ExpertSkillBinding.id).filter(
            ExpertSkillBinding.installation_id == SkillInstallation.id,
        ).exists(),
    ).update({SkillInstallation.status: "uninstalled"}, synchronize_session="fetch")


def _require_asset_reviewer(user: CurrentUser) -> None:
    if not _is_asset_reviewer(user):
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: {ASSET_REVIEW_PERMISSION} required",
        )


def _is_asset_reviewer(user: CurrentUser) -> bool:
    return bool(
        user.is_superuser
        or user.is_staff
        or user.has_permission(ASSET_REVIEW_PERMISSION)
    )


def _agent(db: Session, user_id: int, agent_id: int) -> Agent:
    agent = db.query(Agent).options(noload("*")).filter(
        Agent.id == agent_id,
        Agent.user_id == user_id,
        Agent.is_deleted == False,
    ).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _accessible_skill_release(db: Session, user: CurrentUser, release_id: int):
    query = (
        db.query(SkillRelease, Skill)
        .join(Skill, Skill.id == SkillRelease.skill_id)
        .filter(SkillRelease.id == release_id, Skill.is_deleted == False)
    )
    if not _is_asset_reviewer(user):
        query = query.filter(or_(skill_access_filter(user.user_id), Skill.is_public == True))
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Skill release not found")
    return row


def _skill_release(db: Session, user: CurrentUser, release_id: int):
    release, skill = _accessible_skill_release(db, user, release_id)
    if _auto_publish_public_release(release, skill):
        audit_asset(
            db,
            asset_type="skill_release",
            asset_id=release.id,
            action="auto_published",
            actor_user_id=user.user_id,
            details={"reason": "release_policy_retired"},
        )
        db.commit()
    if release.status == "revoked":
        raise HTTPException(status_code=409, detail="Skill release has been revoked")
    if release.status != "published":
        raise HTTPException(status_code=409, detail="Skill release is not installable")
    archive_path = resolve_release_file_path(release.file_path, release.file_url)
    if not os.path.isfile(archive_path):
        raise HTTPException(status_code=409, detail="Skill release archive is missing")
    try:
        tree = load_release_file_tree(archive_path)
        content_hash = _release_hash(release)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Invalid skill release: {exc}") from exc
    manifest = read_skill_manifest(tree)
    release.manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    return release, skill, content_hash, manifest


@contextmanager
def _workspace_release(db: Session, skill: Skill):
    """Return one stable ``latest`` release backed by the editable workspace.

    The release row is only an installation pointer and metadata record. Runtime
    loading still snapshots the workspace on every run, so changing a skill file
    never requires creating another release row. Keep this context open through
    the caller's commit so failures remove only the new, uncommitted archive.
    """
    _lock_skill_installations(db, skill.id)
    try:
        file_tree = load_skill_files(skill.id, include_binary=True)
        if not file_tree:
            raise ValueError("技能工作区没有文件")
        archive_content = build_skill_archive(file_tree, f"skill-{skill.id}-workspace")
        manifest = read_skill_manifest(file_tree)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=f"技能工作区不可用：{exc}") from exc

    release = db.query(SkillRelease).filter(
        SkillRelease.skill_id == skill.id,
        SkillRelease.status == "workspace",
        SkillRelease.version == "latest",
    ).order_by(SkillRelease.id.desc()).populate_existing().with_for_update().first()
    previous_file_path = release.file_path if release is not None else None
    filename = f"skill-{skill.id}-workspace-{uuid.uuid4().hex}.zip"
    releases_root = os.path.realpath(RELEASES_DIR)
    os.makedirs(releases_root, exist_ok=True)
    file_path = os.path.join(releases_root, filename)
    try:
        with open(file_path, "xb") as archive_file:
            archive_file.write(archive_content)
        if release is None:
            release = SkillRelease(
                skill_id=skill.id,
                version="latest",
                description="当前工作区版本",
                status="workspace",
                scan_status="workspace",
            )
            db.add(release)
        release.description = "当前工作区版本"
        release.file_path = file_path
        release.file_url = f"/releases/{filename}"
        release.content_sha256 = hashlib.sha256(archive_content).hexdigest()
        release.manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
        release.status = "workspace"
        release.scan_status = "workspace"
        db.flush()
        yield release, manifest, previous_file_path
    except BaseException:
        try:
            db.rollback()
        finally:
            _cleanup_workspace_archive(file_path, keep_path=previous_file_path)
        raise
    _cleanup_workspace_archive(previous_file_path, keep_path=file_path)


def _cleanup_workspace_archive(file_path: str | None, keep_path: str | None = None) -> None:
    """Remove an obsolete workspace archive without affecting the request."""
    if not file_path:
        return
    releases_root = os.path.realpath(RELEASES_DIR)
    candidate = os.path.realpath(file_path)
    if candidate == os.path.realpath(keep_path or ""):
        return
    try:
        if os.path.commonpath([releases_root, candidate]) != releases_root:
            return
    except ValueError:
        return
    try:
        os.remove(candidate)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Unable to remove obsolete workspace archive: %s", candidate, exc_info=True)


def _refresh_skill_development_flag(db: Session, skill: Skill, user_id: int | None = None) -> None:
    """Keep the legacy skill flag as an aggregate compatibility indicator."""
    db.flush()
    query = db.query(SkillInstallation.id).filter(
        SkillInstallation.skill_id == skill.id,
        SkillInstallation.status == "active",
        SkillInstallation.release_id.in_(
            db.query(SkillRelease.id).filter(
                SkillRelease.skill_id == skill.id,
                SkillRelease.status == "workspace",
            )
        ),
    )
    if user_id is not None:
        query = query.filter(SkillInstallation.user_id == user_id)
    skill.development_mode = bool(query.first())


def _latest_published_release(db: Session, skill_id: int):
    return db.query(SkillRelease).filter(
        SkillRelease.skill_id == skill_id,
        published_release_filter(),
    ).order_by(SkillRelease.created_at.desc(), SkillRelease.id.desc()).first()


def _installation_payload(row, release, skill):
    return {
        "id": row.id,
        "skill_id": skill.id,
        "skill_name": skill.name,
        "release_id": release.id,
        "version": release.version,
        "previous_release_id": row.previous_release_id,
        "status": row.status,
        "content_sha256": release.content_sha256,
        "granted_capabilities": json.loads(row.granted_capabilities or "[]"),
        "required_capabilities": json.loads(release.manifest_json or "{}").get("capabilities", []),
        "native_approved": bool(release.native_approved),
        "installed_at": row.installed_at,
        "updated_at": row.updated_at,
    }


def _system_installation_payload(row, release, skill):
    payload = _installation_payload(row, release, skill)
    payload.update({
        "source": "system_default",
        "created_by": row.created_by,
    })
    return payload


def _release_payload(release, *, installable: bool, reason: str | None = None):
    return {
        "id": release.id,
        "version": release.version,
        "description": release.description,
        "status": release.status,
        "native_approved": bool(release.native_approved),
        "manifest": json.loads(release.manifest_json or "{}"),
        "content_sha256": release.content_sha256,
        "installable": installable,
        "unavailable_reason": reason,
        "created_at": release.created_at,
    }


def _auto_publish_public_release(release: SkillRelease, skill: Skill) -> bool:
    """Restore scanner rejections and retired public manual-review states."""
    if restore_scan_rejected_release(release):
        return True
    if (
        skill.is_public
        and release.status == "pending_review"
    ):
        release.status = "published"
        return True
    return False


def _catalog_release_access(
    release: SkillRelease,
    skill: Skill,
    user: CurrentUser,
    system_release_id: int | None,
    is_collaborator: bool = False,
) -> tuple[bool, str | None]:
    is_owner = skill.user_id == user.user_id
    is_system_release = release.id == system_release_id
    if release.status == "revoked":
        return False, "版本已被撤销"
    if not os.path.isfile(resolve_release_file_path(release.file_path, release.file_url)):
        return False, "版本发布文件缺失"
    if not (is_owner or is_collaborator or is_system_release or skill.is_public or _is_asset_reviewer(user)):
        return False, "版本未向当前用户发布"
    if release.status != "published":
        return False, "版本不可安装"
    return True, None


def _admin_skill_release(db: Session, user: CurrentUser, release_id: int):
    _require_asset_reviewer(user)
    row = (
        db.query(SkillRelease, Skill)
        .join(Skill, Skill.id == SkillRelease.skill_id)
        .filter(SkillRelease.id == release_id, Skill.is_deleted == False)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Skill release not found")
    release, skill = row
    db.refresh(skill, with_for_update=True)
    if not skill.is_public:
        raise HTTPException(status_code=409, detail="全局安装仅支持公开技能，请先将技能设为公开")
    restore_scan_rejected_release(release)
    if release.status != "published":
        raise HTTPException(status_code=409, detail="System default release must be published")
    archive_path = resolve_release_file_path(release.file_path, release.file_url)
    if not os.path.isfile(archive_path):
        raise HTTPException(status_code=409, detail="Skill release archive is missing")
    try:
        tree = load_release_file_tree(archive_path)
        content_hash = _release_hash(release)
        manifest = read_skill_manifest(tree)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Invalid skill release: {exc}") from exc
    release.manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    if configured_sandbox_type() == "native" and not release.native_approved:
        release.native_approved = True
        release.reviewed_by = user.user_id
        release.reviewed_at = _now()
    return release, skill, content_hash, manifest


@router.get("/skills/catalog")
def list_skill_catalog(
    q: str = "",
    source: str = "all",
    system_mode: bool = False,
    module: str = "",
    role: str = "",
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
    agent_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
    installed_only: bool = False,
    skill_id: int | None = None,
    sort_by: str = "created_at",
):
    if skip < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "skip must be nonnegative and limit must be between 1 and 100")
    if sort_by not in SKILL_CATALOG_SORTS:
        raise HTTPException(422, "sort_by must be one of: created_at, download_count, install_count")
    resource_user_id = current_user.user_id
    if agent_id is not None:
        from agent_access import get_usable_agent
        resource_user_id = get_usable_agent(db, agent_id, current_user.user_id).user_id
    if system_mode:
        _require_asset_reviewer(current_user)
    installation_query = db.query(SkillInstallation).filter(
            SkillInstallation.user_id == resource_user_id,
            SkillInstallation.scope_agent_id == (agent_id or 0),
            SkillInstallation.status == "active",
            *([db.query(ExpertSkillBinding.id).filter(
                ExpertSkillBinding.installation_id == SkillInstallation.id,
                ExpertSkillBinding.agent_id == agent_id,
            ).exists()] if agent_id is not None else []),
        )
    system_query = db.query(SystemSkillInstallation).join(
            Skill, Skill.id == SystemSkillInstallation.skill_id,
        ).filter(
            SystemSkillInstallation.status == "active",
            Skill.is_public == True,
            Skill.is_deleted == False,
        )
    if agent_id is not None:
        system_query = system_query.filter(False)
    query = db.query(Skill).filter(Skill.is_deleted == False)
    collaboration_query = db.query(SkillCollaborator.skill_id).filter(
            SkillCollaborator.user_id == current_user.user_id,
        )
    visibility = visible_skill_filter(current_user.user_id)
    query = query.filter(visibility)
    if system_mode:
        query = query.filter(Skill.is_public == True)
    if source == "mine":
        query = query.filter(Skill.user_id == current_user.user_id)
    elif source == "collaboration":
        query = query.filter(Skill.user_id != current_user.user_id, Skill.id.in_(collaboration_query))
    elif source in {"public", "enterprise"}:
        # Keep the legacy filter name as an alias; ownership and visibility overlap.
        query = query.filter(Skill.is_public == True)
    elif source == "system_default":
        query = query.filter(Skill.id.in_(system_query.with_entities(SystemSkillInstallation.skill_id)))
    elif source not in {"all", "system_default"}:
        return {"total": 0, "items": []}
    term = q.strip()
    if term:
        like = f"%{term}%"
        query = query.filter(or_(Skill.name.like(like), Skill.description.like(like), Skill.author.like(like)))

    query = apply_skill_metadata_filters(query, module, role)
    if skill_id is not None:
        query = query.filter(Skill.id == skill_id)
    if installed_only:
        query = query.filter(or_(
            Skill.id.in_(system_query.with_entities(SystemSkillInstallation.skill_id)),
            Skill.id.in_(installation_query.with_entities(SkillInstallation.skill_id)) if not system_mode else False,
        ))
    # Publication/installation eligibility precedes count and pagination. Missing
    # archives stay visible as unavailable instead of producing empty page slots.
    release_visible = or_(
        published_release_filter(),
        and_(Skill.is_public == True, SkillRelease.status == "pending_review"),
        SkillRelease.id.in_(installation_query.with_entities(SkillInstallation.release_id)),
        SkillRelease.id.in_(system_query.with_entities(SystemSkillInstallation.release_id)),
        _is_asset_reviewer(current_user),
    )
    visible_release_exists = db.query(SkillRelease.id).filter(
        SkillRelease.skill_id == Skill.id, release_visible,
    ).correlate(Skill).exists()
    # A newly created skill has no release yet. Keep that draft in the author's
    # workbench and custom-agent catalogs as a development preview, while
    # preserving the published-release requirement for other users/system mode.
    own_unreleased_skill = and_(
        not system_mode,
        Skill.user_id == current_user.user_id,
        ~db.query(SkillRelease.id).filter(
            SkillRelease.skill_id == Skill.id,
            published_release_filter(),
        ).correlate(Skill).exists(),
    )
    query = query.filter(or_(visible_release_exists, own_unreleased_skill))
    total = query.count()
    download_count_expr = db.query(func.count(AssetSecurityEvent.id)).filter(
        AssetSecurityEvent.asset_type == "skill",
        AssetSecurityEvent.asset_id == Skill.id,
        AssetSecurityEvent.action == "downloaded",
    ).correlate(Skill).scalar_subquery()
    if sort_by == "download_count":
        catalog_order = (download_count_expr.desc(), Skill.created_at.desc(), Skill.id.desc())
    elif sort_by == "install_count":
        catalog_order = (func.coalesce(Skill.install_count, 0).desc(), Skill.created_at.desc(), Skill.id.desc())
    else:
        catalog_order = (Skill.created_at.desc(), Skill.id.desc())
    catalog_skills = query.order_by(*catalog_order).offset(skip).limit(limit).all()
    skill_ids = [skill.id for skill in catalog_skills]
    if not skill_ids:
        return {"total": total, "items": []}
    installations = {row.skill_id: row for row in installation_query.filter(SkillInstallation.skill_id.in_(skill_ids)).all()}
    system_installations = {row.skill_id: row for row in system_query.filter(SystemSkillInstallation.skill_id.in_(skill_ids)).all()}
    collaborated_ids = {row.skill_id for row in collaboration_query.filter(SkillCollaborator.skill_id.in_(skill_ids)).all()}
    releases_by_skill = {value: [] for value in skill_ids}
    for release in db.query(SkillRelease).filter(SkillRelease.skill_id.in_(skill_ids)).order_by(
        SkillRelease.created_at.desc(), SkillRelease.id.desc(),
    ).all():
        releases_by_skill[release.skill_id].append(release)
    installed_users = dict(db.query(
        SkillInstallation.skill_id, func.count(func.distinct(SkillInstallation.user_id)),
    ).filter(
        SkillInstallation.skill_id.in_(skill_ids), SkillInstallation.status == "active",
    ).group_by(SkillInstallation.skill_id).all()) if skill_ids else {}
    downloads = dict(db.query(
        AssetSecurityEvent.asset_id, func.count(AssetSecurityEvent.id),
    ).filter(
        AssetSecurityEvent.asset_type == "skill",
        AssetSecurityEvent.asset_id.in_(skill_ids),
        AssetSecurityEvent.action == "downloaded",
    ).group_by(AssetSecurityEvent.asset_id).all()) if skill_ids else {}
    items = []
    catalog_changed = False
    for skill in catalog_skills:
        system_installation = system_installations.get(skill.id)
        user_installation = installations.get(skill.id)
        is_collaborator = skill.user_id != current_user.user_id and skill.id in collaborated_ids
        item_source = "mine" if skill.user_id == current_user.user_id else ("collaboration" if is_collaborator else "enterprise")
        if source == "system_default" and not system_installation:
            continue
        releases = releases_by_skill[skill.id]
        release_items = []
        system_release_id = system_installation.release_id if system_installation else None
        workspace_visible = not system_mode and skill.user_id == current_user.user_id
        for release in releases:
            if _auto_publish_public_release(release, skill):
                audit_asset(
                    db,
                    asset_type="skill_release",
                    asset_id=release.id,
                    action="auto_published",
                    actor_user_id=current_user.user_id,
                    details={"reason": "release_policy_retired"},
                )
                catalog_changed = True
            installable, reason = _catalog_release_access(
                release, skill, current_user, system_release_id, is_collaborator=is_collaborator
            )
            if release.status == "workspace" and workspace_visible:
                installable, reason = True, None
            if (
                release.status == "published"
                or (release.status == "workspace" and workspace_visible)
                or release.id in {
                user_installation.release_id if user_installation else None,
                system_release_id,
                }
                or _is_asset_reviewer(current_user)
            ):
                release_items.append(_release_payload(release, installable=installable, reason=reason))
        if not release_items and skill.user_id != current_user.user_id:
            continue
        latest = next((release for release in release_items
                       if release["status"] == "published" and release["installable"]), None)
        if latest is None:
            latest = next((release for release in release_items if release["status"] == "published"), None)
        workspace = next((release for release in release_items
                          if release["status"] == "workspace" and release["version"] == "latest"), None)
        latest_workspace = workspace
        if latest_workspace is None and workspace_visible:
            latest_workspace = {
                "id": None,
                "version": "latest",
                "description": "当前工作区版本",
                "status": "workspace",
                "native_approved": False,
                "manifest": {},
                "content_sha256": None,
                "installable": True,
                "unavailable_reason": None,
                "created_at": None,
            }
        current_release_id = user_installation.release_id if user_installation else system_release_id
        if system_release_id is not None:
            current_release_id = system_release_id
        items.append({
            "skill_id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "conversation_examples": skill.conversation_examples or [],
            "author": skill.author,
            "module": skill.module,
            "roles": skill.roles,
            "install_count": skill.install_count,
            "installed_user_count": installed_users.get(skill.id, 0),
            "download_count": downloads.get(skill.id, 0),
            "cover": skill.cover,
            "icon": skill.icon,
            "source": item_source,
            "is_mine": skill.user_id == current_user.user_id,
            "is_collaborator": is_collaborator,
            "is_public": bool(skill.is_public),
            "owner_user_id": skill.user_id,
            "latest_release": latest,
            "latest_workspace": latest_workspace,
            "releases": release_items,
            "user_installation": (
                {
                    "id": user_installation.id,
                    "release_id": user_installation.release_id,
                    "version": next((value["version"] for value in release_items
                                      if value["id"] == user_installation.release_id), None),
                    "is_latest": bool(workspace and user_installation.release_id == workspace["id"]),
                }
                if user_installation else None
            ),
            "system_installation": (
                {"id": system_installation.id, "release_id": system_installation.release_id}
                if system_installation else None
            ),
            "effective_release_id": current_release_id,
            "has_update": bool(current_release_id and latest and latest["id"] != current_release_id),
            **({"development_mode": bool(
                user_installation
                and workspace
                and user_installation.release_id == workspace["id"]
            )}
               if skill.user_id == current_user.user_id and resource_user_id == current_user.user_id
               and not system_mode else {}),
        })
    if catalog_changed:
        db.commit()
    return {"total": total, "items": items}


def _owned_development_skill(db, user_id, skill_id):
    skill = db.query(Skill).filter(
        Skill.id == skill_id, Skill.user_id == user_id, Skill.is_deleted == False,
    ).first()
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在或不是你创建的技能")
    return skill


@router.put("/skills/{skill_id}/development")
def set_skill_development_mode(
    skill_id: int,
    data: SkillDevelopmentRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    with ExitStack() as archives:
        skill = _owned_development_skill(db, current_user.user_id, skill_id)
        if data.agent_id:
            _agent(db, current_user.user_id, data.agent_id)
        _lock_skill_installations(db, skill.id)
        installation = db.query(SkillInstallation).filter(
            SkillInstallation.user_id == current_user.user_id,
            SkillInstallation.skill_id == skill.id,
            SkillInstallation.scope_agent_id == (data.agent_id or 0),
            SkillInstallation.status == "active",
        ).populate_existing().with_for_update().first()
        if installation is None:
            raise HTTPException(status_code=409, detail="请先安装技能，再切换调试模式")
        workspace_release = None
        if data.enabled:
            from skill_development import get_development_snapshot
            try:
                get_development_snapshot(skill.id)
            except (OSError, ValueError, RuntimeError) as exc:
                raise HTTPException(status_code=409, detail="技能工作区文件不可用，请先保存文件后重试") from exc
            workspace_release, manifest, _ = archives.enter_context(_workspace_release(db, skill))
            if installation.release_id != workspace_release.id:
                installation.previous_release_id = installation.release_id
            installation.release_id = workspace_release.id
            try:
                installation.granted_capabilities = json.dumps(
                    normalize_grants(manifest, None), separators=(",", ":")
                )
            except AssetPolicyError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            current_release = db.query(SkillRelease).filter(
                SkillRelease.id == installation.release_id,
                SkillRelease.skill_id == skill.id,
            ).first()
            if current_release is not None and current_release.status == "workspace":
                fallback = db.query(SkillRelease).filter(
                    SkillRelease.id == installation.previous_release_id,
                    SkillRelease.skill_id == skill.id,
                    published_release_filter(),
                ).first() if installation.previous_release_id else None
                fallback = fallback or _latest_published_release(db, skill.id)
                if fallback is None:
                    raise HTTPException(status_code=409, detail="技能尚未发布版本，无法关闭保持最新模式")
                fallback, _, _, manifest = _skill_release(db, current_user, fallback.id)
                installation.previous_release_id = installation.release_id
                installation.release_id = fallback.id
                try:
                    installation.granted_capabilities = json.dumps(
                        normalize_grants(manifest, None),
                        separators=(",", ":"),
                    )
                except AssetPolicyError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
        _refresh_skill_development_flag(db, skill, current_user.user_id)
        db.commit()
        archives.close()
        return {
            "skill_id": skill.id,
            "development_mode": bool(installation.release_id == workspace_release.id)
            if workspace_release is not None else False,
        }


@router.get("/skills/{skill_id}/development/files")
def get_skill_development_files(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    skill = _owned_development_skill(db, current_user.user_id, skill_id)
    from skill_development import get_development_snapshot
    try:
        snapshot = get_development_snapshot(skill.id)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail="技能工作区文件不可用，请先保存文件后重试") from exc
    return {"skill_id": skill.id, "version": "latest", "files": json.loads(snapshot.files_json)}


@router.get("/skills/catalog/{skill_id}/releases")
def list_catalog_skill_releases(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    catalog = list_skill_catalog(db=db, current_user=current_user, skill_id=skill_id, limit=1)
    item = next((value for value in catalog["items"] if value["skill_id"] == skill_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Skill not found in catalog")
    return {"total": len(item["releases"]), "items": item["releases"]}


@router.get("/skills/releases/{release_id}")
def get_skill_release_detail(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    release, skill, content_hash, manifest = _skill_release(
        db, current_user, release_id
    )
    db.commit()
    return {
        "release_id": release.id,
        "skill_id": skill.id,
        "skill_name": skill.name,
        "version": release.version,
        "content_sha256": content_hash,
        "status": release.status,
        "manifest": manifest,
        "native_approved": bool(release.native_approved),
    }


@router.get("/skills/releases/{release_id}/files")
def get_catalog_skill_release_files(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    release, skill = _accessible_skill_release(db, current_user, release_id)
    if release.status == "workspace":
        if skill.user_id != current_user.user_id:
            raise HTTPException(status_code=404, detail="Skill release not found")
        from skill_development import get_development_snapshot
        try:
            snapshot = get_development_snapshot(skill.id)
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail="技能工作区文件无法读取") from exc
        return {
            "release_id": release.id,
            "skill_id": skill.id,
            "version": "latest",
            "files": json.loads(snapshot.files_json),
        }
    # Preview the immutable release archive, never the owner's editable draft.
    archive_path = resolve_release_file_path(release.file_path, release.file_url)
    if not os.path.isfile(archive_path):
        raise HTTPException(status_code=409, detail="版本文件不存在，无法查看内容")
    try:
        tree = load_release_file_tree(archive_path)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="版本文件无法读取，请检查版本包是否完整且文件路径合法") from exc
    return {"release_id": release.id, "skill_id": skill.id, "version": release.version, "files": tree}


@router.post("/skills/releases/{release_id}/download", response_class=FileResponse)
def download_catalog_skill_release(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    # Reuse release access/integrity checks; rejected requests never count as downloads.
    release, skill, _, _ = _skill_release(db, current_user, release_id)
    archive_path = resolve_release_file_path(release.file_path, release.file_url)
    response = FileResponse(
        archive_path,
        filename=f"skill-{skill.id}-release-{release.id}.zip",
        media_type="application/zip",
        stat_result=os.stat(archive_path),
        headers={"Cache-Control": "no-store"},
    )
    audit_asset(
        db, asset_type="skill", asset_id=skill.id, action="downloaded",
        actor_user_id=current_user.user_id,
        details={"release_id": release.id, "version": release.version, "source": "skill_market"},
    )
    db.commit()
    return response


@router.get("/skills/installations")
def list_skill_installations(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    rows = (
        db.query(SkillInstallation, SkillRelease, Skill)
        .join(SkillRelease, SkillRelease.id == SkillInstallation.release_id)
        .join(Skill, Skill.id == SkillInstallation.skill_id)
        .filter(
            SkillInstallation.user_id == current_user.user_id,
            SkillInstallation.scope_agent_id == 0,
            SkillInstallation.status == "active",
            Skill.is_deleted == False,
            visible_skill_filter(current_user.user_id),
            or_(
                published_release_filter(),
                and_(SkillRelease.status == "workspace", Skill.user_id == current_user.user_id),
            ),
        )
        .order_by(SkillInstallation.updated_at.desc())
        .all()
    )
    return {"total": len(rows), "items": [_installation_payload(*row) for row in rows]}


@router.get("/skills/available")
def list_available_skills(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Chat picker: current personal/global releases only, with no archive I/O.

    Archive integrity and capability grants are checked before execution.
    Selecting scalar columns avoids loading skill content and release history.
    """
    columns = (Skill.id, Skill.name, SkillRelease.id, SkillRelease.version, Skill.user_id, Skill.development_mode,
               Skill.conversation_examples)
    personal = db.query(*columns).select_from(SkillInstallation).join(
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
    global_rows = db.query(*columns).select_from(SystemSkillInstallation).join(
        Skill, Skill.id == SystemSkillInstallation.skill_id,
    ).join(SkillRelease, SkillRelease.id == SystemSkillInstallation.release_id).filter(
        SystemSkillInstallation.status == "active",
        Skill.is_deleted == False,
        Skill.is_public == True,
        published_release_filter(),
    ).all()
    effective = {}
    for source, rows in (("personal", personal), ("system_default", global_rows)):
        for skill_id, name, release_id, version, owner_id, development, examples in rows:
            effective[skill_id] = {
                "skill_id": skill_id, "name": name, "release_id": release_id,
                "version": version, "source": source,
                "conversation_examples": examples or [],
            }
    items = sorted(effective.values(), key=lambda item: (item["name"].casefold(), item["skill_id"]))
    return {"total": len(items), "items": items}


@router.post("/skills/install")
def install_skill(
    data: SkillInstallRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    with ExitStack() as archives:
        target_agent = None
        if data.release_id is not None:
            release, skill, _, manifest = _skill_release(db, current_user, data.release_id)
        elif data.skill_id is not None:
            skill = db.query(Skill).filter(
                Skill.id == data.skill_id,
                Skill.user_id == current_user.user_id,
                Skill.is_deleted == False,
            ).first()
            if skill is None:
                raise HTTPException(status_code=404, detail="Skill not found")
            target_agent = _agent(db, current_user.user_id, data.agent_id) if data.agent_id else None
            _require_personal_skill_installable(
                db, skill.id, expert=target_agent is not None and target_agent.kind != "personal_default",
            )
            release, manifest, _ = archives.enter_context(_workspace_release(db, skill))
        else:
            raise HTTPException(status_code=422, detail="release_id 或 skill_id 至少提供一个")
        if data.release_id is not None:
            target_agent = _agent(db, current_user.user_id, data.agent_id) if data.agent_id else None
            _require_personal_skill_installable(
                db, skill.id, expert=target_agent is not None and target_agent.kind != "personal_default",
            )
        try:
            grants = normalize_grants(manifest, None)
        except AssetPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        workspace, _ = (
            bind_agent_workspace(db, target_agent, commit=False)
            if target_agent is not None
            else ensure_user_workspace(db, current_user.user_id, commit=False)
        )
        installation = db.query(SkillInstallation).filter(
            SkillInstallation.user_id == current_user.user_id,
            SkillInstallation.skill_id == skill.id,
            SkillInstallation.scope_agent_id == (data.agent_id or 0),
        ).populate_existing().with_for_update().first()
        if installation is None or installation.status == "uninstalled":
            _record_skill_install(db, skill.id)
        if installation is None:
            installation = SkillInstallation(
                user_id=current_user.user_id,
                scope_agent_id=data.agent_id or 0,
                workspace_id=workspace.id,
                skill_id=skill.id,
                release_id=release.id,
                status="active",
                granted_capabilities=json.dumps(grants, separators=(",", ":")),
            )
            db.add(installation)
            db.flush()
        else:
            if installation.release_id != release.id:
                installation.previous_release_id = installation.release_id
            installation.release_id = release.id
            installation.status = "active"
            installation.granted_capabilities = json.dumps(grants, separators=(",", ":"))
        if data.agent_id:
            exists = db.query(ExpertSkillBinding).filter(
                ExpertSkillBinding.agent_id == data.agent_id,
                ExpertSkillBinding.installation_id == installation.id,
            ).first()
            if exists is None:
                db.add(ExpertSkillBinding(agent_id=data.agent_id, installation_id=installation.id))
        _refresh_skill_development_flag(db, skill, current_user.user_id)
        db.commit()
        archives.close()
        return _installation_payload(installation, release, skill)


@router.put("/skills/installations/{installation_id}/release")
def change_skill_release(
    installation_id: int,
    data: SkillChangeReleaseRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    with ExitStack() as archives:
        installation = _locked_skill_installation(db, current_user.user_id, installation_id, data.agent_id)
        if installation is None:
            raise HTTPException(status_code=404, detail="Skill installation not found")
        skill = db.query(Skill).filter(
            Skill.id == installation.skill_id,
            Skill.is_deleted == False,
        ).first()
        if skill is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        if data.use_latest:
            if skill.user_id != current_user.user_id:
                raise HTTPException(status_code=403, detail="只有技能作者可以使用 latest 工作区版本")
            release, manifest, _ = archives.enter_context(_workspace_release(db, skill))
        elif data.release_id is not None:
            release, release_skill, _, manifest = _skill_release(db, current_user, data.release_id)
            if release_skill.id != skill.id:
                raise HTTPException(status_code=409, detail="Release belongs to another skill")
        else:
            raise HTTPException(status_code=422, detail="release_id 或 use_latest 至少提供一个")
        if release.skill_id != installation.skill_id:
            raise HTTPException(status_code=409, detail="Release belongs to another skill")
        _require_personal_skill_installable(db, skill.id, expert=db.query(ExpertSkillBinding.id).filter(
            ExpertSkillBinding.installation_id == installation.id,
        ).first() is not None)
        if installation.release_id != release.id:
            installation.previous_release_id = installation.release_id
        installation.release_id = release.id
        installation.status = "active"
        try:
            installation.granted_capabilities = json.dumps(
                normalize_grants(manifest, None),
                separators=(",", ":"),
            )
        except AssetPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _refresh_skill_development_flag(db, skill, current_user.user_id)
        db.commit()
        archives.close()
        return _installation_payload(installation, release, skill)


@router.post("/skills/installations/{installation_id}/rollback")
def rollback_skill(
    installation_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
    agent_id: int | None = None,
):
    with ExitStack() as archives:
        installation = _locked_skill_installation(db, current_user.user_id, installation_id, agent_id)
        if installation is None or installation.previous_release_id is None:
            raise HTTPException(status_code=409, detail="No previous release is available")
        previous_id = installation.previous_release_id
        current_id = installation.release_id
        previous_release = db.query(SkillRelease).filter(SkillRelease.id == previous_id).first()
        if previous_release is not None and previous_release.status == "workspace":
            skill = db.query(Skill).filter(
                Skill.id == installation.skill_id,
                Skill.user_id == current_user.user_id,
                Skill.is_deleted == False,
            ).first()
            if skill is None:
                raise HTTPException(status_code=403, detail="只有技能作者可以使用 latest 工作区版本")
            release, manifest, _ = archives.enter_context(_workspace_release(db, skill))
            previous_id = release.id
        else:
            release, skill, _, manifest = _skill_release(db, current_user, previous_id)
        _require_personal_skill_installable(db, skill.id, expert=db.query(ExpertSkillBinding.id).filter(
            ExpertSkillBinding.installation_id == installation.id,
        ).first() is not None)
        installation.release_id = previous_id
        installation.previous_release_id = current_id
        installation.status = "active"
        installation.granted_capabilities = json.dumps(
            normalize_grants(manifest, None), separators=(",", ":")
        )
        _refresh_skill_development_flag(db, skill, current_user.user_id)
        db.commit()
        archives.close()
        return _installation_payload(installation, release, skill)


@router.delete("/skills/installations/{installation_id}")
def uninstall_skill(
    installation_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
    agent_id: int | None = None,
):
    installation = _locked_skill_installation(db, current_user.user_id, installation_id, agent_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Skill installation not found")
    installation.status = "uninstalled"
    db.query(ExpertSkillBinding).filter(
        ExpertSkillBinding.installation_id == installation.id
    ).delete(synchronize_session=False)
    skill = db.query(Skill).filter(Skill.id == installation.skill_id).first()
    if skill is not None:
        _refresh_skill_development_flag(db, skill, current_user.user_id)
    db.commit()
    return {"status": "uninstalled"}


@router.get("/admin/skills/defaults")
def list_system_skill_installations(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    rows = (
        db.query(SystemSkillInstallation, SkillRelease, Skill)
        .join(SkillRelease, SkillRelease.id == SystemSkillInstallation.release_id)
        .join(Skill, Skill.id == SystemSkillInstallation.skill_id)
        .filter(
            SystemSkillInstallation.status == "active",
            Skill.is_public == True,
            Skill.is_deleted == False,
        )
        .order_by(SystemSkillInstallation.updated_at.desc())
        .all()
    )
    return {"total": len(rows), "items": [_system_installation_payload(*row) for row in rows]}


@router.post("/admin/skills/defaults")
def install_system_skill(
    data: SystemSkillInstallRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    release, skill, _, manifest = _admin_skill_release(db, current_user, data.release_id)
    try:
        grants = normalize_grants(manifest, None)
    except AssetPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _lock_skill_installations(db, skill.id)
    installation = db.query(SystemSkillInstallation).filter(
        SystemSkillInstallation.skill_id == skill.id
    ).populate_existing().with_for_update().first()
    if installation is None or installation.status == "uninstalled":
        _record_skill_install(db, skill.id)
    if installation is None:
        installation = SystemSkillInstallation(
            skill_id=skill.id,
            release_id=release.id,
            granted_capabilities=json.dumps(grants, separators=(",", ":")),
            status="active",
            created_by=current_user.user_id,
        )
        db.add(installation)
        db.flush()
        action = "system_default_installed"
    else:
        if installation.release_id != release.id:
            installation.previous_release_id = installation.release_id
        installation.release_id = release.id
        installation.granted_capabilities = json.dumps(grants, separators=(",", ":"))
        installation.status = "active"
        action = "system_default_reinstalled"
    removed_count = _uninstall_personal_skill_copies(db, skill.id)
    audit_asset(
        db,
        asset_type="system_skill_installation",
        asset_id=installation.id,
        action=action,
        actor_user_id=current_user.user_id,
        details={"skill_id": skill.id, "release_id": release.id,
                 "personal_installations_removed": removed_count},
    )
    db.commit()
    return _system_installation_payload(installation, release, skill)


@router.put("/admin/skills/defaults/{installation_id}/release")
def change_system_skill_release(
    installation_id: int,
    data: SkillChangeReleaseRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    installation = db.query(SystemSkillInstallation).filter(
        SystemSkillInstallation.id == installation_id,
        SystemSkillInstallation.status == "active",
    ).first()
    if installation is None:
        raise HTTPException(status_code=404, detail="System skill installation not found")
    release, skill, _, manifest = _admin_skill_release(db, current_user, data.release_id)
    if release.skill_id != installation.skill_id:
        raise HTTPException(status_code=409, detail="Release belongs to another skill")
    try:
        grants = normalize_grants(manifest, None)
    except AssetPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _lock_skill_installations(db, skill.id)
    removed_count = _uninstall_personal_skill_copies(db, skill.id)
    installation.previous_release_id = installation.release_id
    installation.release_id = release.id
    installation.granted_capabilities = json.dumps(grants, separators=(",", ":"))
    audit_asset(
        db,
        asset_type="system_skill_installation",
        asset_id=installation.id,
        action="system_default_updated",
        actor_user_id=current_user.user_id,
        details={"skill_id": skill.id, "release_id": release.id,
                 "personal_installations_removed": removed_count},
    )
    db.commit()
    return _system_installation_payload(installation, release, skill)


@router.post("/admin/skills/defaults/{installation_id}/rollback")
def rollback_system_skill(
    installation_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    installation = db.query(SystemSkillInstallation).filter(
        SystemSkillInstallation.id == installation_id,
        SystemSkillInstallation.status == "active",
    ).first()
    if installation is None or installation.previous_release_id is None:
        raise HTTPException(status_code=409, detail="No previous release is available")
    previous_id = installation.previous_release_id
    current_id = installation.release_id
    release, skill, _, manifest = _admin_skill_release(db, current_user, previous_id)
    _lock_skill_installations(db, skill.id)
    removed_count = _uninstall_personal_skill_copies(db, skill.id)
    installation.release_id = previous_id
    installation.previous_release_id = current_id
    installation.granted_capabilities = json.dumps(
        normalize_grants(manifest, None), separators=(",", ":")
    )
    audit_asset(
        db,
        asset_type="system_skill_installation",
        asset_id=installation.id,
        action="system_default_rolled_back",
        actor_user_id=current_user.user_id,
        details={"skill_id": skill.id, "release_id": release.id,
                 "personal_installations_removed": removed_count},
    )
    db.commit()
    return _system_installation_payload(installation, release, skill)


@router.delete("/admin/skills/defaults/{installation_id}")
def uninstall_system_skill(
    installation_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    installation = db.query(SystemSkillInstallation).filter(
        SystemSkillInstallation.id == installation_id,
        SystemSkillInstallation.status == "active",
    ).first()
    if installation is None:
        raise HTTPException(status_code=404, detail="System skill installation not found")
    _lock_skill_installations(db, installation.skill_id)
    removed_count = _uninstall_personal_skill_copies(db, installation.skill_id)
    installation.status = "uninstalled"
    audit_asset(
        db,
        asset_type="system_skill_installation",
        asset_id=installation.id,
        action="system_default_uninstalled",
        actor_user_id=current_user.user_id,
        details={"skill_id": installation.skill_id, "release_id": installation.release_id,
                 "personal_installations_removed": removed_count},
    )
    db.commit()
    return {"status": "uninstalled"}


@router.post("/skills/installations/{installation_id}/bindings")
def bind_skill(
    installation_id: int,
    data: AssetBindingRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    installation = db.query(SkillInstallation).filter(
        SkillInstallation.id == installation_id,
        SkillInstallation.user_id == current_user.user_id,
        SkillInstallation.status == "active",
    ).first()
    if installation is None:
        raise HTTPException(status_code=404, detail="Skill installation not found")
    result = install_skill(SkillInstallRequest(release_id=installation.release_id, agent_id=data.agent_id), db, current_user)
    return {"status": "bound", "installation_id": result["id"]}


@router.delete("/skills/installations/{installation_id}/bindings/{agent_id}")
def unbind_skill(
    installation_id: int,
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    installation = db.query(SkillInstallation).filter(
        SkillInstallation.id == installation_id,
        SkillInstallation.user_id == current_user.user_id,
    ).first()
    if installation is None:
        raise HTTPException(status_code=404, detail="Skill installation not found")
    _agent(db, current_user.user_id, agent_id)
    result = db.query(ExpertSkillBinding).filter(
        ExpertSkillBinding.agent_id == agent_id,
        ExpertSkillBinding.installation_id == installation_id,
    ).delete(synchronize_session=False)
    db.commit()
    return {"status": "unbound", "removed": bool(result)}


@router.get("/admin/skills/review-queue")
def list_skill_review_queue(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    legacy_or_native_review = and_(
        Skill.is_public == True,
        published_release_filter(),
        or_(
            SkillRelease.reviewed_at.is_(None),
            and_(
                configured_sandbox_type() == "native",
                SkillRelease.native_approved == False,
            ),
        ),
    )
    rows = (
        db.query(SkillRelease, Skill)
        .join(Skill, Skill.id == SkillRelease.skill_id)
        .filter(or_(
            SkillRelease.status.in_(["pending_review", "rejected"]),
            legacy_or_native_review,
        ))
        .order_by(SkillRelease.created_at.asc())
        .all()
    )
    return {
        "total": len(rows),
        "items": [{
            "release_id": release.id,
            "skill_id": skill.id,
            "skill_name": skill.name,
            "owner_user_id": skill.user_id,
            "version": release.version,
            "status": release.status,
            "reviewed_at": release.reviewed_at,
            "native_approved": bool(release.native_approved),
            "manifest": json.loads(release.manifest_json or "{}"),
            "created_at": release.created_at,
        } for release, skill in rows],
    }


@router.post("/admin/skills/releases/{release_id}/approve")
def approve_skill_release(
    release_id: int,
    data: SkillReviewRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    release = db.query(SkillRelease).filter(SkillRelease.id == release_id).first()
    if release is None:
        raise HTTPException(status_code=404, detail="Skill release not found")
    release.status = "published"
    release.reviewed_by = current_user.user_id
    release.reviewed_at = _now()
    release.native_approved = data.native_approved
    release.revoked_by = None
    release.revoked_at = None
    release.revocation_reason = None
    audit_asset(
        db,
        asset_type="skill_release",
        asset_id=release.id,
        action="approved",
        actor_user_id=current_user.user_id,
        reason=data.reason,
        details={"native_approved": data.native_approved},
    )
    db.commit()
    return {
        "release_id": release.id,
        "status": release.status,
        "native_approved": release.native_approved,
        "reviewed_at": release.reviewed_at,
    }


@router.post("/admin/skills/releases/{release_id}/revoke")
def revoke_skill_release(
    release_id: int,
    data: SkillRevokeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    release = db.query(SkillRelease).filter(SkillRelease.id == release_id).first()
    if release is None:
        raise HTTPException(status_code=404, detail="Skill release not found")
    release.status = "revoked"
    release.revoked_by = current_user.user_id
    release.revoked_at = _now()
    release.revocation_reason = data.reason
    db.query(SkillInstallation).filter(
        SkillInstallation.release_id == release.id,
        SkillInstallation.status == "active",
    ).update({SkillInstallation.status: "disabled_by_policy"}, synchronize_session=False)
    db.query(SystemSkillInstallation).filter(
        SystemSkillInstallation.release_id == release.id,
        SystemSkillInstallation.status == "active",
    ).update({SystemSkillInstallation.status: "disabled_by_policy"}, synchronize_session=False)
    audit_asset(
        db,
        asset_type="skill_release",
        asset_id=release.id,
        action="revoked",
        actor_user_id=current_user.user_id,
        reason=data.reason,
    )
    db.commit()
    return {"release_id": release.id, "status": "revoked"}


def _credential_payload(row: CredentialReference):
    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "fingerprint": row.fingerprint,
        "status": row.status,
        "last_rotated_at": row.last_rotated_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _encrypt_secret(user_id: int, name: str, secret: str) -> str:
    try:
        encrypted = encrypt_agent_credential(
            secret,
            purpose=f"mcp-vault:{user_id}:{name}",
        )
    except AgentCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if encrypted is None:
        raise HTTPException(
            status_code=503,
            detail="AGENT_CREDENTIAL_ENCRYPTION_KEY is required for MCP Vault",
        )
    return encrypted


@router.get("/credentials")
def list_credentials(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    rows = db.query(CredentialReference).filter(
        CredentialReference.user_id == current_user.user_id,
        CredentialReference.scope_agent_id == 0
    ).order_by(CredentialReference.updated_at.desc()).all()
    return {"total": len(rows), "items": [_credential_payload(row) for row in rows]}


@router.post("/credentials")
def create_credential(
    data: CredentialCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    name = data.name.strip()
    row = CredentialReference(
        user_id=current_user.user_id,
        name=name,
        secret_encrypted=_encrypt_secret(current_user.user_id, name, data.secret),
        fingerprint=hashlib.sha256(data.secret.encode("utf-8")).hexdigest(),
        version=1,
        status="active",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Credential name already exists") from exc
    return _credential_payload(row)


@router.put("/credentials/{credential_id}/rotate")
def rotate_credential(
    credential_id: int,
    data: CredentialRotateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    row = db.query(CredentialReference).filter(
        CredentialReference.id == credential_id,
        CredentialReference.user_id == current_user.user_id,
        CredentialReference.scope_agent_id == 0,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    row.secret_encrypted = _encrypt_secret(current_user.user_id, row.name, data.secret)
    row.fingerprint = hashlib.sha256(data.secret.encode("utf-8")).hexdigest()
    row.version += 1
    row.status = "active"
    row.last_rotated_at = _now()
    db.commit()
    return _credential_payload(row)


@router.delete("/credentials/{credential_id}")
def delete_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    row = db.query(CredentialReference).filter(
        CredentialReference.id == credential_id,
        CredentialReference.user_id == current_user.user_id,
        CredentialReference.scope_agent_id == 0,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    active_connections = db.query(McpConnection.id).filter(
        McpConnection.credential_reference_id == row.id,
        McpConnection.status != "deleted",
    ).count()
    if active_connections:
        raise HTTPException(status_code=409, detail="Credential is used by an active MCP connection")
    row.status = "deleted"
    row.secret_encrypted = "deleted"
    db.commit()
    return {"status": "deleted"}


def _workspace_prompt_query(db, user_id):
    return db.query(PromptTemplate).filter(
        prompt_access_filter(user_id),
        or_(
            PromptTemplate.user_id == user_id,
            PromptTemplate.is_system == True,
            db.query(WorkspacePromptReference).filter(
                WorkspacePromptReference.user_id == user_id,
                WorkspacePromptReference.template_id == PromptTemplate.id,
            ).exists(),
        ),
        ~db.query(WorkspacePromptRemoval).filter(
            WorkspacePromptRemoval.user_id == user_id,
            WorkspacePromptRemoval.template_id == PromptTemplate.id,
        ).exists(),
    )


def _added_prompt_ids(db, user_id, system_mode=False):
    query = db.query(PromptTemplate).filter(
        PromptTemplate.is_deleted == False,
    )
    if system_mode:
        query = query.filter(PromptTemplate.is_system == True)
        query = query.with_entities(PromptTemplate.id, PromptTemplate.source_template_id)
        return {value for row in query.all() for value in row if value is not None}
    else:
        query = _workspace_prompt_query(db, user_id)
    # Retained legacy copies are independent templates. Their provenance does
    # not mean the source itself is present in this user's workbench.
    return {row[0] for row in query.with_entities(PromptTemplate.id).all()}


def _added_mcp_ids(db, user_id, system_mode=False, lock=False, include_system=True, agent_id=None):
    query = db.query(McpDefinition.source_mcp_service_id).filter(
        McpDefinition.status != "deleted",
        McpDefinition.source_mcp_service_id.isnot(None),
    )
    system = McpDefinition.scope == "system"
    if system_mode:
        query = query.filter(system)
    else:
        query = query.filter(or_(system if include_system else False, db.query(McpConnection.id).filter(
            McpConnection.definition_id == McpDefinition.id,
            McpConnection.user_id == user_id,
            McpConnection.scope_agent_id == (agent_id or 0),
            McpConnection.status != "deleted",
        ).exists()))
    if lock:
        query = query.with_for_update()
    return {row[0] for row in query.all()}


@router.get("/import-status")
def get_resource_import_status(
    system_mode: bool = False,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    if system_mode:
        _require_asset_reviewer(current_user)
    prompt_ids = _added_prompt_ids(db, current_user.user_id, system_mode)
    return {
        "prompt_ids": sorted(prompt_ids),
        "mcp_ids": sorted(_added_mcp_ids(db, current_user.user_id, system_mode)),
    }


def _resource_origins(owner_user_id, is_public: bool, user_id: int):
    origins = []
    if owner_user_id == user_id:
        origins.append("mine")
    if is_public:
        origins.append("public")
    return origins


def _origin_payload(origins):
    # Retain the single-origin field for older clients.
    return {"origin": origins[0] if origins else None, "origins": origins}


def _mcp_metadata(db: Session, definitions, user_id: int):
    source_ids = {row.source_mcp_service_id for row in definitions if row.source_mcp_service_id}
    sources = {
        row.id: row for row in db.query(McpService.id, McpService.user_id, McpService.is_public, McpService.author).filter(
            McpService.id.in_(source_ids),
        ).all()
    } if source_ids else {}
    metadata = {}
    for definition in definitions:
        source = sources.get(definition.source_mcp_service_id)
        if definition.source_mcp_service_id:
            origins = (
                _resource_origins(source.user_id, source.is_public, user_id) if source else []
            )
        else:
            origins = _resource_origins(
                definition.owner_user_id, definition.scope in {"public", "system"}, user_id,
            )
        author = (source.author or "").strip() if source else ""
        metadata[definition.id] = {
            **_origin_payload(origins),
            "author": author or None,
        }
    return metadata


def _prompt_origins(db: Session, rows, user_id: int):
    source_ids = {row.source_template_id for row in rows if row.source_template_id}
    sources = {
        row.id: row for row in db.query(PromptTemplate.id, PromptTemplate.user_id, PromptTemplate.is_public).filter(
            PromptTemplate.id.in_(source_ids),
        ).all()
    } if source_ids else {}
    origins = {}
    for row in rows:
        source = sources.get(row.source_template_id) if row.source_template_id else row
        origins[row.id] = _resource_origins(source.user_id, source.is_public, user_id) if source else []
    return origins


def _definition_payload(definition: McpDefinition, revision: McpRevision | None = None):
    return {
        "id": definition.id,
        "owner_user_id": definition.owner_user_id,
        "name": definition.name,
        "description": definition.description,
        "transport_type": definition.transport_type,
        "auth_mode": system_auth_mode(definition),
        "scope": definition.scope,
        "status": definition.status,
        "source_mcp_service_id": definition.source_mcp_service_id,
        "latest_revision": ({
            "id": revision.id,
            "version": revision.version,
            "content_sha256": revision.content_sha256,
            "status": revision.status,
        } if revision else None),
    }


def _can_manage_mcp_definition(definition: McpDefinition, user: CurrentUser) -> bool:
    if definition.scope == "system":
        return _is_asset_reviewer(user)
    return definition.owner_user_id == user.user_id


def _sanitize_mcp_config(value, key: str = ""):
    normalized = key.lower().replace("-", "_")
    sensitive = (
        normalized in {"authorization", "api_key", "apikey", "token", "secret", "password", "access_token"}
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
        or normalized.endswith("_password")
    )
    if sensitive and value not in (None, ""):
        return "{{credential}}"
    if isinstance(value, dict):
        return {
            item_key: _sanitize_mcp_config(item, item_key)
            for item_key, item in value.items()
            if item_key not in {ENCRYPTED_HEADERS, ENCRYPTED_ENV}
        }
    if isinstance(value, list):
        return [_sanitize_mcp_config(item, key) for item in value]
    return value


def _merge_config(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_config(result[key], value)
        else:
            result[key] = value
    return result


def _validated_mcp_config(transport_type: str, config: dict) -> tuple[dict, dict]:
    sanitized = _sanitize_mcp_config(config)
    try:
        report = validate_mcp_config(transport_type, sanitized)
    except AssetPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sanitized, report


def _normalize_json_mcp_config(config: dict) -> tuple[str, dict]:
    """Turn a standard mcpServers JSON export into one installable server."""
    try:
        return normalize_json_mcp_config(config)
    except McpSourceConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _store_connector_headers(transport_type, config, headers):
    if transport_type.replace("-", "_") not in {"http", "sse", "streamable_http"}:
        raise HTTPException(status_code=400, detail="Only HTTP MCP connectors support request headers")
    try:
        return store_headers(config, headers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _store_connector_env(config, env):
    try:
        return store_env(config, env)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _store_connection_secrets(transport_type, config, *, headers=None, env=None):
    result = dict(config)
    if headers:
        result = _store_connector_headers(transport_type, result, headers)
    if env:
        result = _store_connector_env(result, env)
    return result


def _validate_connector_auth_mode(transport_type: str, auth_mode: str) -> None:
    if auth_mode == "current_user" and transport_type.replace("-", "_") not in {
        "http", "sse", "streamable_http",
    }:
        raise HTTPException(
            status_code=400,
            detail="Only HTTP MCP connectors can reuse the current login identity",
        )


def _headers_for_auth_mode(headers: dict, auth_mode: str) -> dict:
    if auth_mode == "manual":
        return headers
    return {
        name: value
        for name, value in headers.items()
        if name.lower() != "authorization"
    }


def _connector_header_target(db, resource, resource_id, user, agent_id=None):
    connection = None
    if agent_id is not None:
        _agent(db, user.user_id, agent_id)
        if resource != "connections":
            raise HTTPException(status_code=400, detail="Agent authentication must target its own connection")
    if resource == "connections":
        connection = db.query(McpConnection).filter(
            McpConnection.id == resource_id,
            McpConnection.user_id == user.user_id,
            McpConnection.scope_agent_id == (agent_id or 0),
            McpConnection.status != "deleted",
        ).first()
        if connection is None:
            raise HTTPException(status_code=404, detail="MCP connection not found")
        definition, revision = _accessible_definition(db, user.user_id, connection.definition_id, connection.revision_id)
        if definition.scope == "system":
            raise HTTPException(status_code=403, detail="System MCP headers are managed by administrators")
    elif resource == "definitions":
        definition = db.query(McpDefinition).filter(
            McpDefinition.id == resource_id, McpDefinition.status != "deleted",
        ).first()
        if definition is None or not _can_manage_mcp_definition(definition, user):
            raise HTTPException(status_code=404, detail="MCP definition not found")
        if definition.scope == "public":
            raise HTTPException(status_code=400, detail="Configure headers on a personal connection")
        revision = db.query(McpRevision).filter(
            McpRevision.definition_id == definition.id,
            McpRevision.status == "published",
        ).order_by(McpRevision.version.desc()).first()
        if revision is None:
            raise HTTPException(status_code=404, detail="MCP revision not found")
    else:
        raise HTTPException(status_code=404, detail="MCP connector not found")
    config = json.loads(revision.config_json or "{}")
    if connection is not None:
        config = connection_config(connection, revision)
    return connection, definition, revision, config


def _system_header_target(db, user, definition_id, *, for_update=False):
    query = db.query(McpDefinition).filter(
        McpDefinition.id == definition_id,
        McpDefinition.scope == "system",
        McpDefinition.status == "published",
        db.query(McpRevision.id).filter(
            McpRevision.definition_id == McpDefinition.id,
            McpRevision.status == "published",
        ).exists(),
    )
    if for_update:
        query = query.with_for_update()
    definition = query.first()
    if definition is None:
        raise HTTPException(status_code=404, detail="System MCP not found")
    personal = db.query(McpUserHeaders).filter(
        McpUserHeaders.user_id == user.user_id,
        McpUserHeaders.definition_id == definition_id,
    ).first()
    return definition, personal


@router.get("/mcp/{resource}/{resource_id}/headers")
def get_mcp_headers(resource: str, resource_id: int, db: Session = Depends(get_db),
                    current_user: CurrentUser = Depends(get_current_active_user), agent_id: int | None = None):
    if agent_id is not None and resource != "connections":
        raise HTTPException(status_code=400, detail="Agent authentication must target its own connection")
    inheritance = {}
    if resource == "system":
        definition, personal = _system_header_target(db, current_user, resource_id)
        config = {ENCRYPTED_HEADERS: personal.headers_encrypted} if personal else {}
        auth_mode = system_auth_mode(definition, personal)
        inheritance = {
            "inherit_system": personal is None,
            "system_auth_mode": system_auth_mode(definition),
        }
    else:
        connection, definition, _, config = _connector_header_target(db, resource, resource_id, current_user, agent_id)
        auth_mode = system_auth_mode(definition, connection)
    try:
        return {
            **inheritance,
            "auth_mode": auth_mode,
            "headers": [
                # Header values are write-only.  The configured marker lets
                # the editor submit null to preserve an existing secret.
                {"name": name, "value": "", "configured": True}
                for name, value in read_headers(config).items()
            ]
        }
    except AgentCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("/mcp/{resource}/{resource_id}/headers")
def update_mcp_headers(resource: str, resource_id: int, data: McpHeadersUpdateRequest,
                       db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_active_user)):
    if data.agent_id is not None and resource != "connections":
        raise HTTPException(status_code=400, detail="Agent authentication must target its own connection")
    if resource == "system":
        definition, personal = _system_header_target(db, current_user, resource_id, for_update=True)
        if data.inherit_system:
            if personal is not None:
                db.delete(personal)
                audit_asset(db, asset_type="mcp_user_headers", asset_id=resource_id,
                            action="auth_inheritance_restored", actor_user_id=current_user.user_id,
                            details={})
            db.commit()
            return get_mcp_headers(resource, resource_id, db, current_user)
        _validate_connector_auth_mode(definition.transport_type, data.auth_mode)
        config = {ENCRYPTED_HEADERS: personal.headers_encrypted} if personal else {}
        headers = _headers_for_auth_mode(data.headers, data.auth_mode)
        protected = _store_connector_headers(definition.transport_type, config, headers)
        if personal is None:
            personal = McpUserHeaders(user_id=current_user.user_id, definition_id=resource_id)
            db.add(personal)
        personal.headers_encrypted = protected[ENCRYPTED_HEADERS]
        personal.auth_mode = data.auth_mode
        audit_asset(db, asset_type="mcp_user_headers", asset_id=resource_id,
                    action="headers_updated", actor_user_id=current_user.user_id,
                    details={"header_names": list(headers), "auth_mode": data.auth_mode})
        db.commit()
        return get_mcp_headers(resource, resource_id, db, current_user)
    if data.inherit_system:
        raise HTTPException(status_code=400, detail="Only system MCP user settings support inheritance")
    connection, definition, revision, config = _connector_header_target(db, resource, resource_id, current_user, data.agent_id)
    if connection is None and definition.scope != "system" and data.auth_mode != "manual":
        raise HTTPException(
            status_code=400,
            detail="Current login identity is configured on a personal connector, not a shared definition",
        )
    _validate_connector_auth_mode(definition.transport_type, data.auth_mode)
    headers = _headers_for_auth_mode(data.headers, data.auth_mode)
    protected = _store_connector_headers(definition.transport_type, config, headers)
    if connection is not None:
        overrides = json.loads(connection.config_overrides_json or "{}")
        overrides.pop("headers", None)
        overrides[ENCRYPTED_HEADERS] = protected[ENCRYPTED_HEADERS]
        connection.config_overrides_json = json.dumps(overrides)
        connection.auth_mode = data.auth_mode
    else:
        definition.auth_mode = data.auth_mode
        raw = json.dumps(protected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        latest_version = db.query(McpRevision.version).filter(
            McpRevision.definition_id == definition.id,
        ).order_by(McpRevision.version.desc()).first()[0]
        db.add(McpRevision(
            definition_id=definition.id, version=latest_version + 1, config_json=raw,
            content_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            status="published", security_report_json=revision.security_report_json,
            created_by=current_user.user_id,
        ))
    audit_asset(db, asset_type="mcp_connection" if connection else "mcp_definition",
                asset_id=resource_id, action="headers_updated", actor_user_id=current_user.user_id,
                details={"header_names": list(headers), "auth_mode": data.auth_mode})
    db.commit()
    return get_mcp_headers(
        resource,
        resource_id,
        db,
        current_user,
        agent_id=data.agent_id,
    )


def _mcp_secret_kind(transport_type: str) -> str:
    normalized = transport_type.replace("-", "_")
    if normalized == "stdio":
        return "env"
    if normalized in {"http", "sse", "streamable_http"}:
        return "headers"
    raise HTTPException(status_code=400, detail="当前 MCP 类型不支持认证配置")


@router.get("/mcp/{resource}/{resource_id}/secrets")
def get_mcp_secrets(
    resource: str,
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
    agent_id: int | None = None,
):
    if resource == "system":
        raise HTTPException(status_code=400, detail="系统 MCP 请使用管理员配置")
    connection, definition, _, config = _connector_header_target(
        db, resource, resource_id, current_user, agent_id,
    )
    kind = _mcp_secret_kind(definition.transport_type)
    try:
        values = read_headers(config) if kind == "headers" else read_env(config)
    except AgentCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "transport_type": definition.transport_type,
        "kind": kind,
        "fields": [
            {"name": name, "value": "", "configured": True}
            for name in values
        ],
    }


@router.put("/mcp/{resource}/{resource_id}/secrets")
def update_mcp_secrets(
    resource: str,
    resource_id: int,
    data: McpSecretUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    if data.agent_id is not None and resource != "connections":
        raise HTTPException(status_code=400, detail="智能体认证必须配置在对应连接上")
    connection, definition, revision, config = _connector_header_target(
        db, resource, resource_id, current_user, data.agent_id,
    )
    kind = _mcp_secret_kind(definition.transport_type)
    if not data.values:
        values = {}
    else:
        values = dict(data.values)
    try:
        protected = (
            _store_connector_headers(definition.transport_type, config, values)
            if kind == "headers"
            else _store_connector_env(config, values)
        )
    except AgentCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    encrypted_key = ENCRYPTED_HEADERS if kind == "headers" else ENCRYPTED_ENV
    if connection is not None:
        overrides = json.loads(connection.config_overrides_json or "{}")
        overrides.pop("headers", None)
        overrides.pop("env", None)
        overrides[encrypted_key] = protected[encrypted_key]
        connection.config_overrides_json = json.dumps(overrides, ensure_ascii=False)
    else:
        if definition.scope == "public":
            raise HTTPException(status_code=400, detail="公开 MCP 请先添加到工作台后再配置认证")
        raw = json.dumps(protected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        latest_version = db.query(McpRevision.version).filter(
            McpRevision.definition_id == definition.id,
        ).order_by(McpRevision.version.desc()).first()[0]
        db.add(McpRevision(
            definition_id=definition.id,
            version=latest_version + 1,
            config_json=raw,
            content_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            status="published",
            security_report_json=revision.security_report_json,
            created_by=current_user.user_id,
        ))
    audit_asset(
        db,
        asset_type="mcp_connection" if connection else "mcp_definition",
        asset_id=resource_id,
        action="secrets_updated",
        actor_user_id=current_user.user_id,
        details={"kind": kind, "field_names": list(values)},
    )
    db.commit()
    return get_mcp_secrets(resource, resource_id, db, current_user, agent_id=data.agent_id)


def _create_definition(db, user_id: int, *, name, description, transport_type, config, scope="user", source_id=None, headers=None, env=None):
    sanitized, security_report = _validated_mcp_config(transport_type, config)
    if headers is not None:
        if scope == "public":
            raise HTTPException(status_code=400, detail="Public definitions cannot store connector credentials")
        sanitized = _store_connector_headers(transport_type, sanitized, headers)
    if env is not None:
        sanitized = _store_connector_env(sanitized, env)
    definition = McpDefinition(
        owner_user_id=user_id,
        scope=scope,
        name=name,
        description=description,
        transport_type=transport_type,
        status="published",
        source_mcp_service_id=source_id,
    )
    db.add(definition)
    db.flush()
    raw = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    revision = McpRevision(
        definition_id=definition.id,
        version=1,
        config_json=raw,
        content_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        status="published",
        security_report_json=json.dumps(security_report, ensure_ascii=False, sort_keys=True),
        created_by=user_id,
    )
    db.add(revision)
    db.flush()
    audit_asset(
        db,
        asset_type="mcp_revision",
        asset_id=revision.id,
        action="validated",
        actor_user_id=user_id,
        details=security_report,
    )
    db.commit()
    return definition, revision


def sync_owned_mcp_source(db: Session, source: McpService) -> int:
    """Publish a source MCP config change to the owner's imported workbench copies.

    Imported MCP definitions are normally snapshots. The owner of a source
    resource is the one exception: their own workbench copies should follow
    edits made in MCP management, while other users' public imports remain
    isolated and keep their own credentials.
    """
    try:
        source_config = json.loads(source.config or "{}")
    except (TypeError, json.JSONDecodeError, AgentCredentialError) as exc:
        raise HTTPException(status_code=503, detail=f"MCP configuration is unavailable: {exc}") from exc
    if not isinstance(source_config, dict):
        source_config = {}

    source_transport = source.type.replace("-", "_")
    if source_transport == "json":
        source_transport, source_config = _normalize_json_mcp_config(source_config)
    source_config.pop("headers", None)
    source_config.pop("env", None)
    sanitized, security_report = _validated_mcp_config(source_transport, source_config)
    raw = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    definitions = db.query(McpDefinition).filter(
        McpDefinition.source_mcp_service_id == source.id,
        McpDefinition.owner_user_id == source.user_id,
        McpDefinition.scope == "user",
        McpDefinition.status == "published",
    ).all()
    synced = 0
    for definition in definitions:
        latest = db.query(McpRevision).filter(
            McpRevision.definition_id == definition.id,
            McpRevision.status == "published",
        ).order_by(McpRevision.version.desc()).first()
        if latest is None:
            continue
        # Source edits may update shared non-secret configuration, but must not
        # overwrite headers entered for the destination workbench connection.
        try:
            latest_config = json.loads(latest.config_json or "{}")
        except json.JSONDecodeError:
            latest_config = {}
        if isinstance(latest_config, dict) and (
            ENCRYPTED_HEADERS in latest_config or ENCRYPTED_ENV in latest_config
        ):
            synced_config = json.loads(raw)
            for key in (ENCRYPTED_HEADERS, ENCRYPTED_ENV):
                if key in latest_config:
                    synced_config[key] = latest_config[key]
            raw_for_revision = json.dumps(
                synced_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            content_sha256_for_revision = hashlib.sha256(raw_for_revision.encode("utf-8")).hexdigest()
        else:
            raw_for_revision = raw
            content_sha256_for_revision = content_sha256
        revision = McpRevision(
            definition_id=definition.id,
            version=latest.version + 1,
            config_json=raw_for_revision,
            content_sha256=content_sha256_for_revision,
            status="published",
            security_report_json=json.dumps(security_report, ensure_ascii=False, sort_keys=True),
            created_by=source.user_id,
        )
        db.add(revision)
        db.flush()
        definition.name = source.name
        definition.description = source.description
        definition.transport_type = source_transport
        db.query(McpConnection).filter(
            McpConnection.definition_id == definition.id,
            McpConnection.status != "deleted",
        ).update({McpConnection.revision_id: revision.id}, synchronize_session=False)
        audit_asset(
            db,
            asset_type="mcp_revision",
            asset_id=revision.id,
            action="source_synced",
            actor_user_id=source.user_id,
            details={"source_mcp_service_id": source.id, "definition_id": definition.id},
        )
        synced += 1
    return synced


def sync_owned_mcp_sources(db: Session, user_id: int) -> int:
    """Catch up owner snapshots whose source MCP changed before a refresh."""
    candidates = db.query(McpDefinition, McpService).join(
        McpService, McpService.id == McpDefinition.source_mcp_service_id,
    ).filter(
        McpDefinition.owner_user_id == user_id,
        McpDefinition.scope == "user",
        McpDefinition.status == "published",
        McpService.user_id == user_id,
        McpService.is_deleted == False,
    ).all()
    synced = 0
    for definition, source in candidates:
        latest = db.query(McpRevision).filter(
            McpRevision.definition_id == definition.id,
            McpRevision.status == "published",
        ).order_by(McpRevision.version.desc()).first()
        if (
            latest is None
            or source.updated_at is None
            or latest.created_at is None
            or source.updated_at <= latest.created_at
        ):
            continue
        synced += sync_owned_mcp_source(db, source)
    if synced:
        db.commit()
    return synced


@router.get("/mcp/definitions")
def list_mcp_definitions(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    definitions = db.query(McpDefinition).filter(
        McpDefinition.status != "deleted",
        or_(
            McpDefinition.owner_user_id == current_user.user_id,
            McpDefinition.scope.in_(["public", "system"]),
        ),
    ).order_by(McpDefinition.updated_at.desc()).all()
    items = []
    metadata = _mcp_metadata(db, definitions, current_user.user_id)
    for definition in definitions:
        revision = db.query(McpRevision).filter(
            McpRevision.definition_id == definition.id
        ).order_by(McpRevision.version.desc()).first()
        items.append({**_definition_payload(definition, revision), **metadata[definition.id]})
    return {"total": len(items), "items": items}


@router.get("/admin/mcp/definitions")
def list_system_mcp_definitions(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    definitions = db.query(McpDefinition).filter(
        McpDefinition.status != "deleted",
        McpDefinition.scope == "system",
    ).order_by(McpDefinition.updated_at.desc()).all()
    items = []
    metadata = _mcp_metadata(db, definitions, current_user.user_id)
    for definition in definitions:
        revision = db.query(McpRevision).filter(
            McpRevision.definition_id == definition.id
        ).order_by(McpRevision.version.desc()).first()
        items.append({**_definition_payload(definition, revision), **metadata[definition.id]})
    return {"total": len(items), "items": items}


@router.post("/admin/mcp/definitions")
def create_system_mcp_definition(
    data: McpDefinitionCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    transport_type, config = data.transport_type, data.config
    if data.source_mcp_service_id:
        source = db.query(McpService).filter(
            McpService.id == data.source_mcp_service_id,
            McpService.is_deleted == False,
            or_(McpService.user_id == current_user.user_id, McpService.is_public == True),
        ).with_for_update().first()
        if source is None:
            raise HTTPException(status_code=404, detail="MCP service not found")
        if not source.is_public:
            raise HTTPException(status_code=409, detail="系统资源仅支持公开 MCP，请先在 MCP 服务中公开该资源")
        if source.id in _added_mcp_ids(db, current_user.user_id, True):
            raise HTTPException(status_code=409, detail="该连接器已添加，请勿重复添加")
        # Public API config is a display-only, redacted projection. Always
        # resolve imports by source ID on the server, never by the client copy.
        try:
            transport_type, config = source_mcp_config(source)
        except (McpSourceConfigError, AgentCredentialError) as exc:
            raise HTTPException(status_code=409, detail="MCP 源配置不可用") from exc
    _validate_connector_auth_mode(transport_type, data.auth_mode)
    definition, revision = _create_definition(
        db,
        current_user.user_id,
        name=data.name.strip(),
        description=data.description,
        transport_type=transport_type,
        config=config,
        scope="system",
        source_id=data.source_mcp_service_id,
        headers=data.headers,
        env=data.env,
    )
    definition.auth_mode = data.auth_mode
    audit_asset(
        db,
        asset_type="system_mcp_definition",
        asset_id=definition.id,
        action="created",
        actor_user_id=current_user.user_id,
        details={"revision_id": revision.id},
    )
    db.commit()
    return _definition_payload(definition, revision)


@router.post("/mcp/definitions")
def create_mcp_definition(
    data: McpDefinitionCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    if data.is_public:
        _require_asset_reviewer(current_user)
    _validate_connector_auth_mode(data.transport_type, data.auth_mode)
    scope = "public" if data.is_public else "user"
    definition, revision = _create_definition(
        db, current_user.user_id,
        name=data.name.strip(), description=data.description,
        transport_type=data.transport_type, config=data.config, scope=scope, headers=data.headers,
    )
    definition.auth_mode = data.auth_mode
    db.commit()
    return _definition_payload(definition, revision)


@router.post("/mcp/definitions/import")
def import_mcp_definition(
    data: McpImportRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    source = db.query(McpService).filter(
        McpService.id == data.source_mcp_service_id,
        McpService.is_deleted == False,
        or_(McpService.user_id == current_user.user_id, McpService.is_public == True),
    ).with_for_update().first()
    if source is None:
        raise HTTPException(status_code=404, detail="MCP service not found")
    if data.agent_id is not None:
        _agent(db, current_user.user_id, data.agent_id)
        existing = db.query(McpDefinition, McpRevision).join(
            McpConnection, McpConnection.definition_id == McpDefinition.id,
        ).join(McpRevision, McpRevision.id == McpConnection.revision_id).filter(
            McpDefinition.source_mcp_service_id == source.id,
            McpDefinition.scope != "system",
            McpDefinition.status != "deleted",
            McpConnection.user_id == current_user.user_id,
            McpConnection.scope_agent_id == data.agent_id,
            McpConnection.status != "deleted",
        ).first()
        if existing:
            return _definition_payload(*existing)
    if source.id in _added_mcp_ids(db, current_user.user_id, include_system=data.agent_id is None, agent_id=data.agent_id):
        raise HTTPException(status_code=409, detail="该连接器已添加，请勿重复添加")
    try:
        config = json.loads(source.config or "{}")
    except (json.JSONDecodeError, AgentCredentialError) as exc:
        raise HTTPException(status_code=409, detail=f"MCP configuration is unavailable: {exc}") from exc
    secrets = data.secrets or {}
    if not isinstance(config, dict):
        config = {}
    else:
        config = dict(config)
    normalized_transport = source.type.replace("-", "_")
    if normalized_transport == "json":
        normalized_transport, config = _normalize_json_mcp_config(config)
    _validate_connector_auth_mode(normalized_transport, data.auth_mode)
    configured_kind = (
        "env" if normalized_transport == "stdio"
        else "headers" if normalized_transport in {"http", "sse", "streamable_http"}
        else None
    )
    source_secrets = {}
    for kind in ("headers", "env"):
        raw_values = config.pop(kind, {}) or {}
        if configured_kind is None or kind == configured_kind:
            source_secrets[kind] = raw_values
    required_secrets = {
        kind: values for kind, values in source_secrets.items()
        if isinstance(values, dict) and values
    }
    # An explicit HTTP header dictionary is the user's complete selection in
    # the connection editor, including deliberate additions and removals.
    # Never fill omitted values from the source author's credentials.
    if configured_kind == "headers" and "headers" in secrets:
        required_secrets.pop("headers", None)
    allowed_secret_kinds = {configured_kind} if configured_kind else {"headers", "env"}
    invalid_kinds = set(secrets) - allowed_secret_kinds
    if invalid_kinds:
        raise HTTPException(status_code=400, detail="Unsupported MCP secret field")
    unexpected_fields = {
        kind: sorted(set(values) - set(source_secrets.get(kind, {})))
        for kind, values in secrets.items()
        if kind != "headers"
        if set(values) - set(source_secrets.get(kind, {}))
    }
    if unexpected_fields:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "认证配置与 MCP 定义不匹配",
                "code": "MCP_SECRETS_UNEXPECTED",
                "fields": unexpected_fields,
            },
        )
    missing_kinds = [kind for kind in required_secrets if kind not in secrets]
    missing_fields = {
        kind: [
            name for name in names
            if not isinstance(secrets.get(kind, {}).get(name), str)
            or not secrets[kind][name].strip()
        ]
        for kind, names in (
            (kind, values.keys()) for kind, values in required_secrets.items()
        )
    }
    missing_fields = {kind: names for kind, names in missing_fields.items() if names}
    if missing_kinds or missing_fields:
        raise HTTPException(
            status_code=400 if missing_fields and not missing_kinds else 409,
            detail={
                "message": "请为本次资源中心连接填写全部认证配置",
                "code": "MCP_SECRETS_REQUIRED" if missing_kinds else "MCP_SECRETS_INCOMPLETE",
                "fields": {
                    kind: list(values.keys())
                    for kind, values in required_secrets.items()
                } if missing_kinds else missing_fields,
            },
        )
    definition, revision = _create_definition(
        db, current_user.user_id,
        name=source.name, description=source.description,
        transport_type=normalized_transport, config=config, source_id=source.id,
        # Secrets are stored on the destination connection by the follow-up
        # create-connection request, never on the shared definition.
    )
    return _definition_payload(definition, revision)


@router.post("/mcp/definitions/{definition_id}/revisions")
def create_mcp_revision(
    definition_id: int,
    data: McpRevisionCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    definition = db.query(McpDefinition).filter(
        McpDefinition.id == definition_id,
        McpDefinition.status != "deleted",
    ).first()
    if definition is None or not _can_manage_mcp_definition(definition, current_user):
        raise HTTPException(status_code=404, detail="MCP definition not found")
    version = (db.query(McpRevision.version).filter(
        McpRevision.definition_id == definition.id
    ).order_by(McpRevision.version.desc()).first() or (0,))[0] + 1
    sanitized, security_report = _validated_mcp_config(definition.transport_type, data.config)
    raw = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    revision = McpRevision(
        definition_id=definition.id, version=version, config_json=raw,
        content_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        status="published",
        security_report_json=json.dumps(security_report, ensure_ascii=False, sort_keys=True),
        created_by=current_user.user_id,
    )
    db.add(revision)
    db.flush()
    audit_asset(
        db,
        asset_type="mcp_revision",
        asset_id=revision.id,
        action="validated",
        actor_user_id=current_user.user_id,
        details=security_report,
    )
    db.commit()
    return _definition_payload(definition, revision)


@router.get("/mcp/definitions/{definition_id}/revisions")
def list_mcp_revisions(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    definition = db.query(McpDefinition).filter(
        McpDefinition.id == definition_id,
        McpDefinition.status != "deleted",
        or_(
            McpDefinition.owner_user_id == current_user.user_id,
            McpDefinition.scope.in_(["public", "system"]),
        ),
    ).first()
    if definition is None:
        raise HTTPException(status_code=404, detail="MCP definition not found")
    rows = db.query(McpRevision).filter(
        McpRevision.definition_id == definition.id
    ).order_by(McpRevision.version.desc()).all()
    return {
        "total": len(rows),
        "items": [{
            "id": row.id,
            "version": row.version,
            "content_sha256": row.content_sha256,
            "status": row.status,
            "created_at": row.created_at,
        } for row in rows],
    }


@router.delete("/mcp/definitions/{definition_id}")
def delete_mcp_definition(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    definition = db.query(McpDefinition).filter(
        McpDefinition.id == definition_id,
        McpDefinition.status != "deleted",
    ).first()
    if definition is None or not _can_manage_mcp_definition(definition, current_user):
        raise HTTPException(status_code=404, detail="MCP definition not found")
    active_connections = db.query(McpConnection.id).filter(
        McpConnection.definition_id == definition.id,
        McpConnection.status != "deleted",
    ).count()
    if active_connections:
        raise HTTPException(
            status_code=409,
            detail="Delete active MCP connections before deleting the definition",
        )
    definition.status = "deleted"
    db.query(McpRevision).filter(
        McpRevision.definition_id == definition.id
    ).update({McpRevision.status: "revoked"}, synchronize_session=False)
    if definition.scope == "system":
        audit_asset(
            db,
            asset_type="system_mcp_definition",
            asset_id=definition.id,
            action="deleted",
            actor_user_id=current_user.user_id,
        )
    db.commit()
    return {"status": "deleted"}


def _connection_payload(row: McpConnection, definition: McpDefinition, revision: McpRevision):
    return {
        "id": row.id,
        "name": row.name,
        "description": definition.description,
        "definition_id": definition.id,
        "definition_name": definition.name,
        "source_mcp_service_id": definition.source_mcp_service_id,
        "transport_type": definition.transport_type,
        "revision_id": revision.id,
        "revision_version": revision.version,
        "credential_reference_id": row.credential_reference_id,
        "auth_mode": getattr(row, "auth_mode", None) or "manual",
        "tool_policy": json.loads(row.tool_policy_json or "{}"),
        "security_report": json.loads(revision.security_report_json or "{}"),
        "status": row.status,
        "last_tested_at": row.last_tested_at,
        "last_test_status": row.last_test_status,
        "source": "personal",
        "provider": "公开" if definition.scope == "public" else "我的",
        "is_system": False,
    }


def _system_mcp_payload(
    definition: McpDefinition,
    revision: McpRevision,
    personal_headers: McpUserHeaders | None = None,
):
    return {
        "id": f"system-{definition.id}",
        "name": definition.name,
        "description": definition.description,
        "definition_id": definition.id,
        "source_mcp_service_id": definition.source_mcp_service_id,
        "definition_name": definition.name,
        "transport_type": definition.transport_type,
        "revision_id": revision.id,
        "revision_version": revision.version,
        "credential_reference_id": None,
        "auth_mode": system_auth_mode(definition, personal_headers),
        "inherit_system": personal_headers is None,
        "tool_policy": {"risk_level": "read", "allowed_tools": []},
        "security_report": json.loads(revision.security_report_json or "{}"),
        "status": "active",
        "last_tested_at": None,
        "last_test_status": None,
        "source": "system_default",
        "provider": "平台",
        "is_system": True,
    }


def _mcp_inspection_config(
    db: Session,
    user: CurrentUser,
    connection: McpConnection | None,
    definition: McpDefinition,
    revision: McpRevision,
    *,
    personal_headers: McpUserHeaders | None = None,
    authorization: str | None = None,
    shared_execution: bool = False,
) -> dict:
    if shared_execution:
        config = public_connection_config(revision)
    elif connection is not None:
        config = connection_config(connection, revision)
    else:
        config = json.loads(revision.config_json or "{}")
    if not isinstance(config, dict):
        raise HTTPException(status_code=409, detail="MCP 配置无效")
    transport = definition.transport_type.replace("-", "_")
    if definition.scope == "system":
        try:
            transport, config = system_mcp_config(db, definition, config)
        except (McpSourceConfigError, AgentCredentialError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Resolve encrypted connector headers only for this short-lived request.
    headers = read_headers(config)
    if personal_headers is not None:
        personal = read_headers({ENCRYPTED_HEADERS: personal_headers.headers_encrypted})
        personal_names = {name.lower() for name in personal}
        headers = {name: value for name, value in headers.items() if name.lower() not in personal_names}
        headers.update(personal)
    auth_mode = getattr(connection or personal_headers or definition, "auth_mode", None) or "manual"
    if auth_mode == "none":
        headers = {name: value for name, value in headers.items() if name.lower() != "authorization"}
    elif auth_mode == "current_user":
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=409, detail="当前登录身份认证需要有效的 Bearer Token")
        headers = {name: value for name, value in headers.items() if name.lower() != "authorization"}
        headers["Authorization"] = authorization.strip()
    config.pop(ENCRYPTED_HEADERS, None)
    if transport == "stdio":
        config["env"] = read_env(config)
    else:
        config.pop(ENCRYPTED_ENV, None)
        config["headers"] = headers

    if not shared_execution and connection is not None and connection.credential_reference_id:
        credential = db.query(CredentialReference).filter(
            CredentialReference.id == connection.credential_reference_id,
            CredentialReference.user_id == user.user_id,
            CredentialReference.status == "active",
        ).first()
        if credential is None:
            raise HTTPException(status_code=409, detail="MCP 凭据不可用")
        try:
            secret = decrypt_agent_credential(
                credential.secret_encrypted,
                purpose=f"mcp-vault:{user.user_id}:{credential.name}",
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="MCP 凭据解密失败") from exc
        config = _replace_credential(config, secret)
    try:
        validate_mcp_config(transport, config)
    except AssetPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return config


async def _run_mcp_inspection(*args, **kwargs):
    try:
        config = _mcp_inspection_config(*args, **kwargs)
        transport = args[3].transport_type
        if args[3].scope == "system" and transport == "json":
            transport, _ = _normalize_json_mcp_config(json.loads(args[4].config_json or "{}"))
        return await inspect_mcp_server(transport, config)
    except HTTPException:
        raise
    except McpInspectError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/mcp/connections/{connection_id}/inspect")
async def inspect_mcp_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
    agent_id: int | None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    resource_user_id = current_user.user_id
    if agent_id is not None:
        from agent_access import get_usable_agent
        resource_user_id = get_usable_agent(db, agent_id, current_user.user_id).user_id
    read_only = resource_user_id != current_user.user_id
    row = db.query(McpConnection).filter(
        McpConnection.id == connection_id,
        McpConnection.user_id == resource_user_id,
        McpConnection.scope_agent_id == (agent_id or 0),
        McpConnection.status != "deleted",
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    if agent_id is not None and not db.query(ExpertMcpBinding.id).filter(
        ExpertMcpBinding.connection_id == row.id,
        ExpertMcpBinding.agent_id == agent_id,
        ExpertMcpBinding.status == "active",
    ).first():
        raise HTTPException(status_code=404, detail="MCP connection is not bound to this agent")
    definition, revision = _accessible_definition(db, resource_user_id, row.definition_id, row.revision_id)
    if read_only:
        from mcp_publication import shareable_mcp_definition
        if not db.query(McpDefinition.id).filter(
            McpDefinition.id == definition.id,
            McpDefinition.status == "published",
            shareable_mcp_definition(),
        ).first():
            raise HTTPException(status_code=404, detail="MCP definition revision not found")
    result = await _run_mcp_inspection(
        db, current_user, row, definition, revision,
        authorization=authorization,
        shared_execution=read_only,
    )
    return {"name": row.name, "transport_type": definition.transport_type, **result}


@router.get("/mcp/definitions/{definition_id}/inspect")
async def inspect_system_mcp(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    definition, personal = _system_header_target(db, current_user, definition_id)
    revision = db.query(McpRevision).filter(
        McpRevision.definition_id == definition.id,
        McpRevision.status == "published",
    ).order_by(McpRevision.version.desc()).first()
    if revision is None:
        raise HTTPException(status_code=404, detail="MCP revision not found")
    result = await _run_mcp_inspection(
        db, current_user, None, definition, revision,
        personal_headers=personal,
        authorization=authorization,
    )
    return {"name": definition.name, "transport_type": definition.transport_type, **result}


@router.get("/mcp/connections")
def list_mcp_connections(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
    agent_id: int | None = None,
):
    resource_user_id = current_user.user_id
    if agent_id is not None:
        from agent_access import get_usable_agent
        resource_user_id = get_usable_agent(db, agent_id, current_user.user_id).user_id
    sync_owned_mcp_sources(db, current_user.user_id)
    read_only = resource_user_id != current_user.user_id
    system_rows = db.query(McpDefinition, McpRevision).join(
        McpRevision, McpRevision.definition_id == McpDefinition.id
    ).filter(
        McpDefinition.scope == "system",
        McpDefinition.status == "published",
        McpRevision.status == "published",
    ).order_by(
        McpDefinition.updated_at.desc(),
        McpRevision.version.desc(),
    ).all() if agent_id is None else []
    personal_system_headers = {
        row.definition_id: row
        for row in db.query(McpUserHeaders).filter(
            McpUserHeaders.user_id == current_user.user_id,
        ).all()
    }
    system_items = []
    seen_system_definitions = set()
    system_names = set()
    for definition, revision in system_rows:
        if definition.id in seen_system_definitions:
            continue
        seen_system_definitions.add(definition.id)
        system_names.add(definition.name)
        system_items.append(_system_mcp_payload(
            definition,
            revision,
            personal_system_headers.get(definition.id),
        ))

    from mcp_publication import shareable_mcp_definition
    rows = db.query(McpConnection, McpDefinition, McpRevision).join(
        McpDefinition, McpDefinition.id == McpConnection.definition_id
    ).join(McpRevision, McpRevision.id == McpConnection.revision_id).filter(
        McpConnection.user_id == resource_user_id,
        McpConnection.scope_agent_id == (agent_id or 0),
        McpConnection.status != "deleted",
        *([shareable_mcp_definition()] if read_only else []),
        *([db.query(ExpertMcpBinding.id).filter(
            ExpertMcpBinding.connection_id == McpConnection.id,
            ExpertMcpBinding.agent_id == agent_id,
        ).exists()] if agent_id is not None else []),
    ).order_by(McpConnection.updated_at.desc()).all()
    personal_items = [
        _connection_payload(*row)
        for row in rows
        if row[1].id not in seen_system_definitions and row[0].name not in system_names
    ]
    if agent_id is not None:
        binding_statuses = dict(db.query(
            ExpertMcpBinding.connection_id, ExpertMcpBinding.status,
        ).filter(ExpertMcpBinding.agent_id == agent_id).all())
        for item in personal_items:
            item["status"] = binding_statuses[item["id"]]
    if read_only:
        for item in personal_items:
            # Public configuration metadata does not carry owner credentials,
            # connection diagnostics, or private tool policy.
            item.update(credential_reference_id=None, tool_policy={}, security_report={},
                        last_tested_at=None, last_test_status=None)
    items = system_items + personal_items
    definitions = {definition.id: definition for definition, _ in system_rows}
    definitions.update({definition.id: definition for _, definition, _ in rows})
    metadata = _mcp_metadata(db, list(definitions.values()), current_user.user_id)
    for item in items:
        item.update(metadata[item["definition_id"]])
    return {"total": len(items), "items": items}


def _accessible_definition(db, user_id: int, definition_id: int, revision_id: int):
    row = db.query(McpDefinition, McpRevision).join(
        McpRevision, McpRevision.definition_id == McpDefinition.id
    ).filter(
        McpDefinition.id == definition_id,
        McpRevision.id == revision_id,
        McpDefinition.status != "deleted",
        McpRevision.status == "published",
        or_(
            McpDefinition.owner_user_id == user_id,
            McpDefinition.scope.in_(["public", "system"]),
        ),
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP definition revision not found")
    return row


def _credential(db, user_id: int, credential_id: int | None):
    if credential_id is None:
        return None
    row = db.query(CredentialReference).filter(
        CredentialReference.id == credential_id,
        CredentialReference.user_id == user_id,
        CredentialReference.status == "active",
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return row


def _require_connection_credential(revision: McpRevision, overrides: dict, credential_id: int | None, scope_agent_id=0):
    effective = connection_config(SimpleNamespace(scope_agent_id=scope_agent_id, config_overrides_json=json.dumps(overrides)), revision)
    serialized = json.dumps(effective, ensure_ascii=False)
    if "{{credential}}" in serialized and credential_id is None:
        raise HTTPException(
            status_code=409,
            detail="This MCP definition requires a Vault credential",
        )


@router.post("/mcp/connections")
def create_mcp_connection(
    data: McpConnectionCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    definition, revision = _accessible_definition(
        db, current_user.user_id, data.definition_id, data.revision_id
    )
    _validate_connector_auth_mode(definition.transport_type, data.auth_mode)
    if definition.scope == "system":
        raise HTTPException(
            status_code=409,
            detail="System MCP connections are managed by administrators and are already active",
        )
    if data.agent_id is not None:
        _agent(db, current_user.user_id, data.agent_id)
        existing = db.query(McpConnection).filter(
            McpConnection.user_id == current_user.user_id,
            McpConnection.scope_agent_id == (data.agent_id or 0),
            McpConnection.definition_id == definition.id,
            McpConnection.status != "deleted",
        ).first()
        if existing:
            binding = db.query(ExpertMcpBinding).filter_by(
                agent_id=data.agent_id, connection_id=existing.id,
            ).first()
            if binding is None:
                db.add(ExpertMcpBinding(agent_id=data.agent_id, connection_id=existing.id))
            else:
                binding.status = "active"
            db.commit()
            return {**_connection_payload(existing, definition, db.get(McpRevision, existing.revision_id)), "status": "active"}
    if definition.source_mcp_service_id:
        db.query(McpService.id).filter(
            McpService.id == definition.source_mcp_service_id,
        ).with_for_update().first()
        if definition.source_mcp_service_id in _added_mcp_ids(db, current_user.user_id, lock=True, include_system=data.agent_id is None, agent_id=data.agent_id):
            raise HTTPException(status_code=409, detail="该连接器已添加，请勿重复添加")
    elif db.query(McpConnection.id).filter(
        McpConnection.user_id == current_user.user_id,
        McpConnection.scope_agent_id == (data.agent_id or 0),
        McpConnection.definition_id == definition.id,
        McpConnection.status != "deleted",
    ).first():
        raise HTTPException(status_code=409, detail="该连接器已添加，请勿重复添加")
    _credential(db, current_user.user_id, data.credential_reference_id)
    config_overrides = dict(data.config_overrides or {})
    connection_headers = config_overrides.pop("headers", None)
    connection_env = config_overrides.pop("env", None)
    config_overrides = _sanitize_mcp_config(config_overrides)
    config_overrides = _store_connection_secrets(
        definition.transport_type,
        config_overrides,
        headers=connection_headers,
        env=connection_env,
    )
    _require_connection_credential(revision, config_overrides, data.credential_reference_id, data.agent_id or 0)
    try:
        tool_policy = normalize_tool_policy(data.tool_policy)
        effective_config = connection_config(SimpleNamespace(
            scope_agent_id=data.agent_id or 0,
            config_overrides_json=json.dumps(config_overrides),
        ), revision)
        validate_mcp_config(definition.transport_type, effective_config)
    except (AssetPolicyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target_agent = _agent(db, current_user.user_id, data.agent_id) if data.agent_id else None
    workspace, _ = (
        bind_agent_workspace(db, target_agent)
        if target_agent is not None
        else ensure_user_workspace(db, current_user.user_id)
    )
    connection_name = data.name.strip()
    row = db.query(McpConnection).filter(
        McpConnection.user_id == current_user.user_id,
        McpConnection.scope_agent_id == (data.agent_id or 0),
        McpConnection.name == connection_name,
    ).first()
    if row is not None and row.status != "deleted":
        raise HTTPException(status_code=409, detail="MCP connection name already exists")
    if row is None:
        row = McpConnection(user_id=current_user.user_id, scope_agent_id=data.agent_id or 0, name=connection_name)
        db.add(row)
    row.workspace_id = workspace.id
    row.definition_id = definition.id
    row.revision_id = revision.id
    row.credential_reference_id = scoped_credential(db, current_user.user_id, data.credential_reference_id, data.agent_id or 0)
    row.config_overrides_json = json.dumps(
        config_overrides, ensure_ascii=False
    )
    row.auth_mode = data.auth_mode
    row.tool_policy_json = json.dumps(tool_policy, ensure_ascii=False, sort_keys=True)
    row.status = "active"
    row.last_tested_at = None
    row.last_test_status = None
    try:
        db.flush()
        if data.agent_id:
            db.add(ExpertMcpBinding(agent_id=data.agent_id, connection_id=row.id))
        audit_asset(
            db,
            asset_type="mcp_connection",
            asset_id=row.id,
            action="created",
            actor_user_id=current_user.user_id,
            details={"tool_policy": tool_policy},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="MCP connection name already exists") from exc
    return _connection_payload(row, definition, revision)


@router.put("/mcp/connections/{connection_id}/status")
def update_mcp_connection_status(
    connection_id: int,
    data: McpConnectionStatusRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    row = db.query(McpConnection).filter(
        McpConnection.id == connection_id,
        McpConnection.user_id == current_user.user_id,
        McpConnection.scope_agent_id == (data.agent_id or 0),
        McpConnection.status != "deleted",
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    definition, revision = _accessible_definition(
        db, current_user.user_id, row.definition_id, row.revision_id
    )
    if data.agent_id is not None:
        _agent(db, current_user.user_id, data.agent_id)
        binding = db.query(ExpertMcpBinding).filter_by(
            agent_id=data.agent_id, connection_id=row.id,
        ).first()
        if binding is None:
            raise HTTPException(status_code=404, detail="MCP connection is not bound to this agent")
        binding.status = data.status
    else:
        row.status = data.status
    audit_asset(
        db,
        asset_type="mcp_connection",
        asset_id=row.id,
        action="enabled" if data.status == "active" else "disabled",
        actor_user_id=current_user.user_id,
        details={"agent_id": data.agent_id},
    )
    db.commit()
    return {**_connection_payload(row, definition, revision), "status": data.status}


@router.put("/mcp/connections/{connection_id}")
def update_mcp_connection(
    connection_id: int,
    data: McpConnectionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    row = db.query(McpConnection).filter(
        McpConnection.id == connection_id,
        McpConnection.user_id == current_user.user_id,
        McpConnection.scope_agent_id == (data.agent_id or 0),
        McpConnection.status != "deleted",
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    revision_id = data.revision_id or row.revision_id
    definition, revision = _accessible_definition(
        db, current_user.user_id, row.definition_id, revision_id
    )
    if data.revision_id:
        row.revision_id = revision.id
    if data.clear_credential:
        row.credential_reference_id = None
    elif data.credential_reference_id is not None:
        _credential(db, current_user.user_id, data.credential_reference_id)
        row.credential_reference_id = scoped_credential(db, current_user.user_id, data.credential_reference_id, row.scope_agent_id)
    if data.name is not None:
        row.name = data.name.strip()
    if data.config_overrides is not None:
        previous_overrides = json.loads(row.config_overrides_json or "{}")
        requested_overrides = dict(data.config_overrides)
        requested_headers = requested_overrides.pop("headers", None)
        requested_env = requested_overrides.pop("env", None)
        normalized_overrides = _sanitize_mcp_config(requested_overrides)
        if requested_headers is None and ENCRYPTED_HEADERS in previous_overrides:
            normalized_overrides[ENCRYPTED_HEADERS] = previous_overrides[ENCRYPTED_HEADERS]
        if requested_env is None and ENCRYPTED_ENV in previous_overrides:
            normalized_overrides[ENCRYPTED_ENV] = previous_overrides[ENCRYPTED_ENV]
        normalized_overrides = _store_connection_secrets(
            definition.transport_type,
            normalized_overrides,
            headers=requested_headers,
            env=requested_env,
        )
        row.config_overrides_json = json.dumps(normalized_overrides, ensure_ascii=False)
    if data.auth_mode is not None:
        _validate_connector_auth_mode(definition.transport_type, data.auth_mode)
        row.auth_mode = data.auth_mode
    if data.tool_policy is not None:
        try:
            row.tool_policy_json = json.dumps(
                normalize_tool_policy(data.tool_policy), ensure_ascii=False, sort_keys=True
            )
        except AssetPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    effective_credential_id = row.credential_reference_id
    effective_overrides = json.loads(row.config_overrides_json or "{}")
    _require_connection_credential(revision, effective_overrides, effective_credential_id, row.scope_agent_id)
    try:
        validate_mcp_config(
            definition.transport_type,
            connection_config(row, revision),
        )
    except (AssetPolicyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_asset(
        db,
        asset_type="mcp_connection",
        asset_id=row.id,
        action="updated",
        actor_user_id=current_user.user_id,
        details={"tool_policy": json.loads(row.tool_policy_json or "{}")},
    )
    db.commit()
    return _connection_payload(row, definition, revision)


@router.delete("/mcp/connections/{connection_id}")
def delete_mcp_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
    agent_id: int | None = None,
):
    row = db.query(McpConnection).filter(
        McpConnection.id == connection_id,
        McpConnection.user_id == current_user.user_id,
        McpConnection.scope_agent_id == (agent_id or 0),
        McpConnection.status != "deleted",
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    row.status = "deleted"
    db.query(ExpertMcpBinding).filter(
        ExpertMcpBinding.connection_id == row.id
    ).delete(synchronize_session=False)
    audit_asset(
        db,
        asset_type="mcp_connection",
        asset_id=row.id,
        action="deleted",
        actor_user_id=current_user.user_id,
    )
    db.commit()
    return {"status": "deleted"}


@router.post("/mcp/connections/{connection_id}/bindings")
def bind_mcp_connection(
    connection_id: int,
    data: AssetBindingRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    row = db.query(McpConnection).filter(
        McpConnection.id == connection_id,
        McpConnection.user_id == current_user.user_id,
        McpConnection.status != "deleted",
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    result = create_mcp_connection(McpConnectionCreateRequest(
        definition_id=row.definition_id, revision_id=row.revision_id,
        name=row.name, agent_id=data.agent_id,
        tool_policy=json.loads(row.tool_policy_json or "{}"),
    ), db, current_user)
    return {"status": "bound", "connection_id": result["id"]}


@router.delete("/mcp/connections/{connection_id}/bindings/{agent_id}")
def unbind_mcp_connection(
    connection_id: int,
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    row = db.query(McpConnection).filter(
        McpConnection.id == connection_id,
        McpConnection.user_id == current_user.user_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP connection not found")
    _agent(db, current_user.user_id, agent_id)
    result = db.query(ExpertMcpBinding).filter(
        ExpertMcpBinding.agent_id == agent_id,
        ExpertMcpBinding.connection_id == connection_id,
    ).delete(synchronize_session=False)
    db.commit()
    return {"status": "unbound", "removed": bool(result)}


@router.post("/prompts/import")
def import_prompt_snapshot(
    data: PromptImportRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    source = db.query(PromptTemplate).filter(
        PromptTemplate.id == data.source_template_id,
        prompt_access_filter(current_user.user_id),
    ).with_for_update().first()
    if source is None:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    if data.agent_id is not None:
        _agent(db, current_user.user_id, data.agent_id)
        # Both workbench and expert additions reference the author's record.
        position = db.query(func.max(agent_prompt_templates.c.position)).filter(
            agent_prompt_templates.c.agent_id == data.agent_id,
        ).scalar()
        position = position + 1 if position is not None else 0
        bind_prompt_template(source.id, PromptBindingRequest(agent_id=data.agent_id, position=position), db, current_user)
        return _system_prompt_payload(source)
    added = _added_prompt_ids(db, current_user.user_id)
    if source.id in added:
        raise HTTPException(status_code=409, detail="该提示词已添加，请勿重复添加")
    removal = db.get(WorkspacePromptRemoval, (current_user.user_id, source.id))
    if removal is not None:
        db.delete(removal)
    if source.user_id != current_user.user_id and not source.is_system:
        reference = db.get(WorkspacePromptReference, (current_user.user_id, source.id))
        if reference is None:
            db.add(WorkspacePromptReference(user_id=current_user.user_id, template_id=source.id))
    db.commit()
    return _system_prompt_payload(source)


def _system_prompt_payload(row: PromptTemplate):
    return {
        "id": row.id,
        "name": row.name,
        "category": row.category,
        "content": row.content,
        "variables": row.variables,
        "description": row.description,
        "author": row.author,
        "is_system": bool(row.is_system),
        "created_at": getattr(row, "created_at", None),
        "updated_at": getattr(row, "updated_at", None),
    }


@router.get("/prompts/catalog")
def list_prompt_catalog(
    q: str = "",
    source: str = "all",
    installed_only: bool = False,
    system_mode: bool = False,
    agent_id: int | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    if skip < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "skip must be nonnegative and limit must be between 1 and 100")
    if source not in {"all", "mine", "public", "system_default"}:
        raise HTTPException(422, "Invalid prompt source")
    if system_mode and agent_id is not None:
        raise HTTPException(422, "System catalog cannot be scoped to an agent")

    user_id = current_user.user_id
    query = db.query(PromptTemplate).filter(prompt_access_filter(user_id))
    if system_mode:
        _require_asset_reviewer(current_user)
        system_copy = aliased(PromptTemplate)
        has_system_copy = db.query(system_copy.id).filter(
            system_copy.source_template_id == PromptTemplate.id,
            system_copy.is_system == True,
            system_copy.is_deleted == False,
        ).exists()
        installed = PromptTemplate.is_system == True
        query = query.filter(or_(installed, and_(PromptTemplate.is_public == True, ~has_system_copy)))
    elif agent_id is not None:
        from agent_access import get_usable_agent

        agent = get_usable_agent(db, agent_id, user_id)
        installed = db.query(agent_prompt_templates.c.prompt_template_id).filter(
            agent_prompt_templates.c.agent_id == agent_id,
            agent_prompt_templates.c.prompt_template_id == PromptTemplate.id,
        ).exists()
        if agent.user_id != user_id:
            installed_only = True
    else:
        installed_ids = _workspace_prompt_query(db, user_id).with_entities(PromptTemplate.id)
        installed = PromptTemplate.id.in_(installed_ids)

    if installed_only:
        query = query.filter(installed)
    if source == "mine":
        query = query.filter(PromptTemplate.user_id == user_id)
    elif source == "public":
        query = query.filter(PromptTemplate.is_public == True)
    elif source == "system_default":
        query = query.filter(PromptTemplate.is_system == True)
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(
            PromptTemplate.name.like(pattern),
            PromptTemplate.author.like(pattern),
            PromptTemplate.category.like(pattern),
            PromptTemplate.description.like(pattern),
            PromptTemplate.content.like(pattern),
        ))

    total = query.count()
    rows = query.add_columns(installed.label("installed")).order_by(
        PromptTemplate.is_system.desc(), PromptTemplate.updated_at.desc(), PromptTemplate.id.desc(),
    ).offset(skip).limit(limit).all()
    return {"total": total, "items": [
        {
            **_system_prompt_payload(row),
            **_origin_payload(_resource_origins(row.user_id, row.is_public, user_id)),
            "installed": bool(is_installed),
        }
        for row, is_installed in rows
    ]}


@router.get("/prompts")
def list_workspace_prompts(
    q: str = "",
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    query = _workspace_prompt_query(db, current_user.user_id)
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(
            PromptTemplate.name.like(pattern),
            PromptTemplate.category.like(pattern),
            PromptTemplate.description.like(pattern),
        ))
    total = query.count()
    rows = query.order_by(
        PromptTemplate.is_system.desc(),
        PromptTemplate.updated_at.desc(),
    ).offset(max(0, skip)).limit(max(1, min(limit, 200))).all()
    origins = _prompt_origins(db, rows, current_user.user_id)
    return {
        "total": total,
        "items": [{
            **_system_prompt_payload(row),
            "is_public": bool(row.is_public),
            "source": "system_default" if row.is_system else (
                "personal" if row.user_id == current_user.user_id else "reference"
            ),
            **_origin_payload(origins[row.id]),
        } for row in rows],
    }


@router.delete("/prompts/{prompt_id}")
def remove_workspace_prompt(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    row = db.query(PromptTemplate).filter(
        PromptTemplate.id == prompt_id,
        PromptTemplate.is_deleted == False,
        PromptTemplate.is_system == False,
        or_(PromptTemplate.user_id == current_user.user_id, db.query(WorkspacePromptReference).filter(
            WorkspacePromptReference.user_id == current_user.user_id,
            WorkspacePromptReference.template_id == PromptTemplate.id,
        ).exists()),
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    removal = db.query(WorkspacePromptRemoval).filter(
        WorkspacePromptRemoval.user_id == current_user.user_id,
        WorkspacePromptRemoval.template_id == row.id,
    ).first()
    if removal is None:
        db.add(WorkspacePromptRemoval(user_id=current_user.user_id, template_id=row.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if db.get(WorkspacePromptRemoval, (current_user.user_id, row.id)) is None:
                raise
    return {"status": "removed"}


@router.post("/prompts/{prompt_id}/bindings")
def bind_prompt_template(
    prompt_id: int,
    data: PromptBindingRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    prompt = db.query(PromptTemplate).filter(
        PromptTemplate.id == prompt_id,
        prompt_access_filter(current_user.user_id),
    ).with_for_update().first()
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    _agent(db, current_user.user_id, data.agent_id)
    existing = db.execute(
        agent_prompt_templates.select().where(
            agent_prompt_templates.c.agent_id == data.agent_id,
            agent_prompt_templates.c.prompt_template_id == prompt_id,
        )
    ).first()
    if existing is None:
        db.execute(agent_prompt_templates.insert().values(
            agent_id=data.agent_id,
            prompt_template_id=prompt_id,
            position=data.position,
        ))
        db.commit()
    return {"status": "bound", "prompt_template_id": prompt_id, "position": data.position}


@router.delete("/prompts/{prompt_id}/bindings/{agent_id}")
def unbind_prompt_template(
    prompt_id: int,
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _agent(db, current_user.user_id, agent_id)
    result = db.execute(agent_prompt_templates.delete().where(
        agent_prompt_templates.c.agent_id == agent_id,
        agent_prompt_templates.c.prompt_template_id == prompt_id,
    ))
    db.commit()
    return {"status": "unbound", "removed": bool(result.rowcount)}


@router.get("/admin/prompts")
def list_system_prompts(
    q: str = "",
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    query = db.query(PromptTemplate).filter(
        PromptTemplate.is_deleted == False,
        PromptTemplate.is_system == True,
    )
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(
            PromptTemplate.name.like(pattern),
            PromptTemplate.category.like(pattern),
            PromptTemplate.description.like(pattern),
        ))
    total = query.count()
    rows = query.order_by(PromptTemplate.updated_at.desc()).offset(
        max(0, skip)
    ).limit(max(1, min(limit, 200))).all()
    origins = _prompt_origins(db, rows, current_user.user_id)
    return {"total": total, "items": [
        {**_system_prompt_payload(row), **_origin_payload(origins[row.id])} for row in rows
    ]}


@router.post("/admin/prompts")
def create_system_prompt(
    data: SystemPromptCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    if data.source_template_id:
        source = db.query(PromptTemplate.id, PromptTemplate.is_public, PromptTemplate.source_template_id).filter(
            PromptTemplate.id == data.source_template_id,
            PromptTemplate.is_deleted == False,
            or_(PromptTemplate.user_id == current_user.user_id, PromptTemplate.is_public == True),
        ).with_for_update().first()
        if source is None:
            raise HTTPException(status_code=404, detail="Prompt template not found")
        if not source.is_public:
            raise HTTPException(status_code=409, detail="系统资源仅支持公开提示词，请先在提示词管理中公开该资源")
        added = _added_prompt_ids(db, current_user.user_id, True)
        if source.id in added or source.source_template_id in added:
            raise HTTPException(status_code=409, detail="该提示词已添加，请勿重复添加")
    row = PromptTemplate(
        user_id=current_user.user_id,
        name=data.name.strip(),
        category=data.category.strip(),
        content=data.content,
        variables=data.variables,
        description=data.description,
        author=(current_user.first_name or current_user.username or "").strip() or "系统管理员",
        is_public=True,
        is_system=True,
        source_template_id=data.source_template_id,
        imported_at=_now() if data.source_template_id else None,
    )
    db.add(row)
    db.flush()
    audit_asset(
        db,
        asset_type="system_prompt",
        asset_id=row.id,
        action="created",
        actor_user_id=current_user.user_id,
    )
    db.commit()
    db.refresh(row)
    return _system_prompt_payload(row)


@router.put("/admin/prompts/{prompt_id}")
def update_system_prompt(
    prompt_id: int,
    data: SystemPromptUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    row = db.query(PromptTemplate).filter(
        PromptTemplate.id == prompt_id,
        PromptTemplate.is_deleted == False,
        PromptTemplate.is_system == True,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="System prompt not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        if key in {"name", "category"} and value is not None:
            value = value.strip()
        setattr(row, key, value)
    audit_asset(
        db,
        asset_type="system_prompt",
        asset_id=row.id,
        action="updated",
        actor_user_id=current_user.user_id,
    )
    db.commit()
    db.refresh(row)
    return _system_prompt_payload(row)


@router.delete("/admin/prompts/{prompt_id}")
def delete_system_prompt(
    prompt_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    row = db.query(PromptTemplate).filter(
        PromptTemplate.id == prompt_id,
        PromptTemplate.is_deleted == False,
        PromptTemplate.is_system == True,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="System prompt not found")
    row.is_deleted = True
    audit_asset(
        db,
        asset_type="system_prompt",
        asset_id=row.id,
        action="deleted",
        actor_user_id=current_user.user_id,
    )
    db.commit()
    return {"status": "deleted"}


@router.get("/audit/runs")
def list_run_audit(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    rows = db.query(AgentRun, WorkspaceRunView).outerjoin(
        WorkspaceRunView, WorkspaceRunView.run_id == AgentRun.id
    ).filter(AgentRun.user_id == current_user.user_id).order_by(
        AgentRun.created_at.desc()
    ).limit(max(1, min(limit, 200))).all()
    items = []
    for run, view in rows:
        items.append({
            "run_id": run.id,
            "agent_id": run.agent_id,
            "workspace_id": run.workspace_id,
            "source": run.source,
            "status": run.status,
            "config_snapshot": json.loads(run.config_snapshot or "{}"),
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "view": ({
                "status": view.status,
                "sandbox_ref": view.sandbox_ref,
                "config_hash": view.config_hash,
                "cleanup_status": view.cleanup_status,
                "prepared_at": view.prepared_at,
                "cleaned_at": view.cleaned_at,
                "last_error": view.last_error,
            } if view else None),
        })
    return {"total": len(items), "items": items}


@router.get("/audit/security")
def list_asset_security_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_asset_reviewer(current_user)
    rows = db.query(AssetSecurityEvent).order_by(
        AssetSecurityEvent.created_at.desc()
    ).limit(max(1, min(limit, 500))).all()
    return {
        "total": len(rows),
        "items": [{
            "id": row.id,
            "asset_type": row.asset_type,
            "asset_id": row.asset_id,
            "action": row.action,
            "actor_user_id": row.actor_user_id,
            "reason": row.reason,
            "details": json.loads(row.details_json or "{}"),
            "created_at": row.created_at,
        } for row in rows],
    }
