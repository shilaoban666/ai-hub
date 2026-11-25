"""Resolve immutable user assets into one Run without exposing stored secrets."""
from __future__ import annotations
from asset_scopes import connection_config, public_connection_config

import hashlib
import json
import os
from types import SimpleNamespace

from sqlalchemy import and_, or_

from credential_crypto import decrypt_agent_credential
from mcp_headers import ENCRYPTED_ENV, ENCRYPTED_HEADERS, resolve_env, resolve_headers, system_auth_mode
from mcp_source_config import system_mcp_config
from asset_security import (
    HIGH_RISK_LEVELS,
    AssetPolicyError,
    normalize_tool_policy,
    read_skill_manifest,
    validate_mcp_config,
)
from database import settings
from models import (
    CredentialReference,
    ExpertMcpBinding,
    ExpertSkillBinding,
    McpConnection,
    McpUserHeaders,
    McpDefinition,
    McpRevision,
    Skill,
    SkillInstallation,
    SkillRelease,
    SystemSkillInstallation,
)
from skill_utils import resolve_release_file_path
from skill_release_cache import get_cached_release
from skill_development import get_development_snapshot
from skill_release_policy import published_release_filter, restore_scan_rejected_release
from skill_access import visible_skill_filter


BACKGROUND_CHANNEL_SOURCES = {"weixin_clawbot", "dingtalk_clawbot", "api"}


def _validate_runtime_auth_mode(source, auth_mode, request_authorization):
    """Reject browser-only identity reuse before a background channel run."""
    if (
        source in BACKGROUND_CHANNEL_SOURCES
        and auth_mode == "current_user"
        and not request_authorization
    ):
        raise RuntimeError(
            "当前登录身份认证仅支持工作台在线对话；微信、钉钉和开放调用等后台渠道没有可复用的浏览器 Bearer Token。"
            "请将此 MCP 改为“手动配置”并填写渠道可用凭据，或选择“不发送认证”"
        )


def _json_object(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _merge(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _replace_credential(value, replacement: str):
    if isinstance(value, dict):
        return {key: _replace_credential(item, replacement) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_credential(item, replacement) for item in value]
    if isinstance(value, str):
        return value.replace("{{credential}}", replacement).replace(
            "${AIHUB_MCP_CREDENTIAL}", replacement
        )
    return value


def _release_hash(release: SkillRelease) -> str:
    digest = hashlib.sha256()
    archive_path = resolve_release_file_path(release.file_path, release.file_url)
    with open(archive_path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    if release.content_sha256 and release.content_sha256 != value:
        raise RuntimeError(f"skill release {release.id} failed integrity verification")
    if not release.content_sha256:
        release.content_sha256 = value
    return value


def scoped_skill_query(db, agent, asset_user_id):
    """Match ordinary execution and external skill selection to current bindings."""
    inherit_system_assets = getattr(agent, "kind", "expert") == "personal_default"
    skill_query = (
        db.query(SkillInstallation, SkillRelease, Skill)
        .join(SkillRelease, SkillRelease.id == SkillInstallation.release_id)
        .join(Skill, Skill.id == SkillInstallation.skill_id)
        .filter(
            SkillInstallation.user_id == asset_user_id,
            SkillInstallation.scope_agent_id == (0 if inherit_system_assets else agent.id),
            SkillInstallation.status == "active",
            or_(
                published_release_filter(),
                and_(SkillRelease.status == "workspace", Skill.user_id == asset_user_id),
            ),
            Skill.is_deleted == False,
        )
    )
    # A personal installation does not preserve access to somebody else's
    # skill after it is made private. Keep owner and collaborator access, but
    # exclude hidden third-party skills so the runtime matches the catalog.
    skill_query = skill_query.filter(visible_skill_filter(asset_user_id))
    if getattr(agent, "kind", "expert") != "personal_default":
        skill_query = skill_query.join(
            ExpertSkillBinding,
            ExpertSkillBinding.installation_id == SkillInstallation.id,
        ).filter(ExpertSkillBinding.agent_id == agent.id)

    return skill_query


def load_runtime_assets(
    db,
    agent,
    user_id: int,
    *,
    source: str = "web",
    interactive_permissions: bool = False,
    skills_only: bool = False,
    request_authorization: str | None = None,
) -> dict:
    shared_execution = getattr(agent, "execution_user_id", None) is not None
    asset_user_id = agent.user_id if shared_execution else user_id
    inherit_system_assets = getattr(agent, "kind", "expert") == "personal_default"
    system_rows = (
        db.query(SystemSkillInstallation, SkillRelease, Skill)
        .join(SkillRelease, SkillRelease.id == SystemSkillInstallation.release_id)
        .join(Skill, Skill.id == SystemSkillInstallation.skill_id)
        .filter(
            SystemSkillInstallation.status == "active",
            published_release_filter(),
            Skill.is_deleted == False,
            Skill.is_public == True,
        )
        .all()
    ) if inherit_system_assets else []
    skill_query = scoped_skill_query(db, agent, asset_user_id)

    effective_rows = {}
    for installation, release, skill in skill_query.all():
        effective_rows[skill.id] = ("user", installation, release, skill)
    for installation, release, skill in system_rows:
        effective_rows[skill.id] = ("system_default", installation, release, skill)

    runtime_skills = []
    skill_snapshot = []
    effective_capabilities: set[str] = set()
    for asset_source, installation, release, skill in effective_rows.values():
        is_owner = skill.user_id == asset_user_id
        is_latest_requested = bool(
            asset_source == "user" and release.status == "workspace" and is_owner
        )
        is_latest = bool(
            is_latest_requested
            and skill.user_id == user_id
            and not shared_execution
        )
        if is_latest_requested and not is_latest and release.status == "workspace":
            # Workspace latest is author-private. A shared/background run keeps
            # the newest published release instead of exposing draft files.
            fallback = db.get(SkillRelease, installation.previous_release_id) if installation.previous_release_id else None
            if fallback is not None:
                restore_scan_rejected_release(fallback)
                if fallback.skill_id != skill.id or fallback.status != "published":
                    fallback = None
            release = fallback or db.query(SkillRelease).filter(
                SkillRelease.skill_id == skill.id,
                published_release_filter(),
            ).order_by(SkillRelease.created_at.desc(), SkillRelease.id.desc()).first()
            if release is None:
                raise RuntimeError(f"skill latest workspace version is not available to this run: {skill.id}")
        restore_scan_rejected_release(release)
        if release.status == "revoked":
            raise RuntimeError(f"skill release is not approved: {release.id}")
        if asset_source == "user" and not is_owner and release.status != "published":
            raise RuntimeError(f"marketplace skill release is not approved: {release.id}")
        if is_latest:
            cached = get_development_snapshot(skill.id)
            manifest = read_skill_manifest(json.loads(cached.files_json))
        else:
            archive_path = resolve_release_file_path(release.file_path, release.file_url)
            if not os.path.isfile(archive_path):
                raise RuntimeError(f"skill release archive is missing: {release.id}")
            cached = get_cached_release(release)
            manifest = _json_object(release.manifest_json)
            if "capabilities" not in manifest:
                manifest = read_skill_manifest(json.loads(cached.files_json))
        content_hash = cached.content_sha256
        version = "latest" if is_latest else release.version
        identity = {
            "skill_id": skill.id,
            "release_id": None if is_latest else release.id,
            "version": version,
            "content_sha256": content_hash,
            **({"source": "workspace"} if is_latest else {}),
        }
        required = set(manifest.get("capabilities") or [])
        if is_latest:
            granted = set(required)
        elif installation.granted_capabilities is None and (
            is_owner or asset_source == "system_default"
        ):
            granted = set(required)
            if not shared_execution:
                installation.granted_capabilities = json.dumps(
                    sorted(granted), separators=(",", ":")
                )
        else:
            granted = set(json.loads(installation.granted_capabilities or "[]"))
        if not required.issubset(granted):
            missing = ", ".join(sorted(required - granted))
            raise RuntimeError(f"skill capability grant is incomplete ({release.id}): {missing}")
        effective_capabilities.update(granted)
        runtime_skills.append(SimpleNamespace(
            id=skill.id,
            name=skill.name,
            version=version,
            files=cached.files_json,
            cached_files_dir=cached.directory,
            installation_release=identity,
            content=skill.content,
        ))
        skill_snapshot.append({
            "source": "workspace" if is_latest else asset_source,
            "installation_id": installation.id if asset_source == "user" else None,
            "system_installation_id": (
                installation.id if asset_source == "system_default" else None
            ),
            "skill_id": skill.id,
            "release_id": None if is_latest else release.id,
            "version": version,
            "content_sha256": content_hash,
            "manifest": manifest,
            "granted_capabilities": sorted(granted),
        })

    if skills_only:
        db.flush()
        return {"skills": runtime_skills, "skill_snapshot": skill_snapshot}

    system_mcp_rows = (
        db.query(McpDefinition, McpRevision)
        .join(McpRevision, McpRevision.definition_id == McpDefinition.id)
        .filter(
            McpDefinition.scope == "system",
            McpDefinition.status == "published",
            McpRevision.status == "published",
        )
        .order_by(McpDefinition.updated_at.desc(), McpRevision.version.desc())
        .all()
    ) if inherit_system_assets else []
    connection_query = (
        db.query(McpConnection, McpDefinition, McpRevision, CredentialReference)
        .join(McpDefinition, McpDefinition.id == McpConnection.definition_id)
        .join(McpRevision, McpRevision.id == McpConnection.revision_id)
        .outerjoin(
            CredentialReference,
            CredentialReference.id == McpConnection.credential_reference_id,
        )
        .filter(
            McpConnection.user_id == asset_user_id,
            McpConnection.scope_agent_id == (0 if inherit_system_assets else agent.id),
            McpConnection.status != "deleted",
            McpRevision.status == "published",
            McpDefinition.status == "published",
        )
    )
    if getattr(agent, "kind", "expert") != "personal_default":
        connection_query = connection_query.join(
            ExpertMcpBinding,
            ExpertMcpBinding.connection_id == McpConnection.id,
        ).filter(
            ExpertMcpBinding.agent_id == agent.id,
            ExpertMcpBinding.status == "active",
        )
    else:
        connection_query = connection_query.filter(McpConnection.status == "active")

    personal_system_headers = {
        row.definition_id: row
        for row in db.query(McpUserHeaders).filter(
            McpUserHeaders.user_id == user_id,
            McpUserHeaders.definition_id.in_({definition.id for definition, _ in system_mcp_rows}),
        ).all()
    } if system_mcp_rows else {}
    runtime_mcps = []
    secret_env = {}
    mcp_snapshot = []
    requires_confirmation = False
    uses_current_user_authorization = False
    system_definition_ids = set()
    system_names = set()
    for definition, revision in system_mcp_rows:
        if definition.id in system_definition_ids or definition.name in system_names:
            continue
        system_definition_ids.add(definition.id)
        system_names.add(definition.name)
        transport_type, config = system_mcp_config(db, definition, _json_object(revision.config_json))
        try:
            security_report = validate_mcp_config(transport_type, config)
        except AssetPolicyError as exc:
            raise RuntimeError(f"System MCP definition rejected {definition.id}: {exc}") from exc
        if (
            transport_type in {"http", "sse", "streamable_http"}
            and settings.mcp_egress_proxy_url
        ):
            secret_env.update({
                "HTTP_PROXY": settings.mcp_egress_proxy_url,
                "HTTPS_PROXY": settings.mcp_egress_proxy_url,
                "http_proxy": settings.mcp_egress_proxy_url,
                "https_proxy": settings.mcp_egress_proxy_url,
            })
        tool_policy = normalize_tool_policy(None)
        personal_headers = personal_system_headers.get(definition.id)
        auth_mode = system_auth_mode(definition, personal_headers)
        uses_current_user_authorization = (
            uses_current_user_authorization or auth_mode == "current_user"
        )
        _validate_runtime_auth_mode(source, auth_mode, request_authorization)
        config = resolve_env(config, secret_env, f"SYSTEM_{definition.id}")
        config = resolve_headers(
            config,
            secret_env,
            f"SYSTEM_{definition.id}",
            personal_headers=(
                personal_headers.headers_encrypted if personal_headers else None
            ),
            auth_mode=auth_mode,
            request_authorization=request_authorization,
        )
        runtime_mcps.append(SimpleNamespace(
            id=-definition.id,
            name=definition.name,
            type=transport_type,
            config=json.dumps(config, ensure_ascii=False),
            risk_level=tool_policy["risk_level"],
            allowed_tools=tool_policy["allowed_tools"],
            require_confirmation=tool_policy["require_confirmation"],
        ))
        mcp_snapshot.append({
            "source": "system_default",
            "connection_id": None,
            "definition_id": definition.id,
            "revision_id": revision.id,
            "revision_version": revision.version,
            "credential_reference_id": None,
            "credential_version": None,
            "auth_mode": auth_mode,
            "tool_policy": tool_policy,
            "security_report": security_report,
        })

    for connection, definition, revision, credential in connection_query.all():
        if definition.id in system_definition_ids or connection.name in system_names:
            continue
        if shared_execution:
            # Public consumers use the published definition, never publisher
            # overrides, saved headers, or Vault credentials.
            config = public_connection_config(revision)
            credential = None
        else:
            config = connection_config(connection, revision)
        try:
            security_report = validate_mcp_config(definition.transport_type, config)
            tool_policy = normalize_tool_policy(_json_object(connection.tool_policy_json))
        except AssetPolicyError as exc:
            raise RuntimeError(f"MCP connection policy rejected {connection.id}: {exc}") from exc
        high_risk = tool_policy["risk_level"] in HIGH_RISK_LEVELS
        if high_risk and (source != "web" or not interactive_permissions):
            raise RuntimeError(
                f"high-risk MCP connection requires an interactive web run: {connection.id}"
            )
        requires_confirmation = requires_confirmation or high_risk
        if (
            definition.transport_type.replace("-", "_") in {"http", "sse", "streamable_http"}
            and settings.mcp_egress_proxy_url
        ):
            secret_env.update({
                "HTTP_PROXY": settings.mcp_egress_proxy_url,
                "HTTPS_PROXY": settings.mcp_egress_proxy_url,
                "http_proxy": settings.mcp_egress_proxy_url,
                "https_proxy": settings.mcp_egress_proxy_url,
            })
        credential_version = None
        if credential is not None:
            if credential.status != "active":
                raise RuntimeError(f"MCP credential is unavailable: {credential.id}")
            env_name = f"AIHUB_MCP_CREDENTIAL_{credential.id}"
            secret_env[env_name] = decrypt_agent_credential(
                credential.secret_encrypted,
                purpose=f"mcp-vault:{user_id}:{credential.name}",
            )
            config = _replace_credential(config, "${" + env_name + "}")
            credential_version = credential.version
        auth_mode = getattr(connection, "auth_mode", None) or "manual"
        uses_current_user_authorization = (
            uses_current_user_authorization or auth_mode == "current_user"
        )
        _validate_runtime_auth_mode(source, auth_mode, request_authorization)
        config = resolve_env(config, secret_env, f"CONNECTION_{connection.id}")
        config = resolve_headers(
            config,
            secret_env,
            f"CONNECTION_{connection.id}",
            auth_mode=auth_mode,
            request_authorization=request_authorization,
        )
        runtime_mcps.append(SimpleNamespace(
            id=connection.id,
            name=connection.name,
            type=definition.transport_type,
            config=json.dumps(config, ensure_ascii=False),
            risk_level=tool_policy["risk_level"],
            allowed_tools=tool_policy["allowed_tools"],
            require_confirmation=tool_policy["require_confirmation"],
        ))
        mcp_snapshot.append({
            "source": "personal",
            "connection_id": connection.id,
            "definition_id": definition.id,
            "revision_id": revision.id,
            "revision_version": revision.version,
            "credential_reference_id": credential.id if credential else None,
            "credential_version": credential_version,
            "auth_mode": auth_mode,
            "tool_policy": tool_policy,
            "security_report": security_report,
        })

    db.flush()
    return {
        "skills": runtime_skills,
        "mcps": runtime_mcps,
        "secret_env": secret_env,
        "skill_snapshot": skill_snapshot,
        "mcp_snapshot": mcp_snapshot,
        "effective_capabilities": sorted(effective_capabilities),
        "requires_confirmation": requires_confirmation,
        "uses_current_user_authorization": uses_current_user_authorization,
    }
