"""Independent mutable asset records for a workbench (0) or an expert agent."""
import json

from fastapi import HTTPException
from sqlalchemy.orm import defer, noload

from models import (
    Agent, CredentialReference, ExpertMcpBinding, ExpertSkillBinding,
    McpConnection, McpRevision, SkillInstallation,
)
from mcp_headers import ENCRYPTED_ENV, ENCRYPTED_HEADERS


def merge_config(base, overrides):
    result = dict(base)
    for key, value in overrides.items():
        result[key] = merge_config(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def connection_config(connection, revision):
    base = json.loads(revision.config_json or "{}")
    if connection.scope_agent_id:
        # Expert authentication always comes from its own connection, never
        # a resource definition or a personal workbench's saved headers.
        base.pop("headers", None)
        base.pop(ENCRYPTED_HEADERS, None)
        base.pop(ENCRYPTED_ENV, None)
    return merge_config(base, json.loads(connection.config_overrides_json or "{}"))


def public_connection_config(revision):
    """Use published configuration without the publisher's authentication."""
    config = json.loads(revision.config_json or "{}")
    if isinstance(config, dict):
        for key in ("headers", ENCRYPTED_HEADERS, "env", ENCRYPTED_ENV):
            config.pop(key, None)
    return config


def scoped_credential(db, user_id, credential_id, scope_agent_id, *, require_active=True):
    """Snapshot an explicitly selected Vault credential into the target scope.

    The encryption purpose uses user/name, so ciphertext can be copied without
    decrypting or logging it. Personal credential rotation cannot change a copy.
    """
    if credential_id is None:
        return None
    source = db.query(CredentialReference).filter_by(
        id=credential_id, user_id=user_id,
    ).first()
    if source is None or (require_active and source.status != "active"):
        raise HTTPException(status_code=404, detail="Credential not found")
    if source.scope_agent_id == scope_agent_id:
        return source.id
    if source.scope_agent_id != 0:
        raise HTTPException(status_code=404, detail="Credential not found")
    target = db.query(CredentialReference).filter_by(
        user_id=user_id, scope_agent_id=scope_agent_id, name=source.name,
    ).first()
    if target is None:
        target = CredentialReference(
            user_id=user_id, scope_agent_id=scope_agent_id, name=source.name,
            secret_encrypted=source.secret_encrypted, version=source.version,
            fingerprint=source.fingerprint, status=source.status,
            last_rotated_at=source.last_rotated_at,
        )
        db.add(target)
        db.flush()
    else:
        target.secret_encrypted = source.secret_encrypted
        target.version = source.version
        target.fingerprint = source.fingerprint
        target.status = source.status
        target.last_rotated_at = source.last_rotated_at
    return target.id


def migrate_agent_asset_scopes(db, workspace_for_agent):
    """Detach existing bindings once, preserving their effective configuration.

    Caller runs this with application writers stopped and commits atomically.
    Already scoped bindings are skipped, so repeat runs cannot reset changes.
    """
    counts = {"skills": 0, "mcps": 0}
    workspaces = {}

    def workspace(agent_id, user_id):
        if agent_id not in workspaces:
            # Migration 049 runs before 057 adds the chat presentation fields.
            agent = db.query(Agent).options(
                noload("*"), defer(Agent.noun_highlight_enabled), defer(Agent.noun_explanation_url),
            ).filter_by(id=agent_id, user_id=user_id).one()
            workspaces[agent_id] = workspace_for_agent(db, agent)
        return workspaces[agent_id]

    for binding in db.query(ExpertSkillBinding).order_by(ExpertSkillBinding.id).all():
        source = db.get(SkillInstallation, binding.installation_id)
        if source is None or source.scope_agent_id == binding.agent_id:
            continue
        target = db.query(SkillInstallation).filter_by(
            user_id=source.user_id, scope_agent_id=binding.agent_id, skill_id=source.skill_id,
        ).first()
        if target is None:
            target = SkillInstallation(
                user_id=source.user_id, scope_agent_id=binding.agent_id,
                workspace_id=workspace(binding.agent_id, source.user_id).id,
                skill_id=source.skill_id, release_id=source.release_id,
                previous_release_id=source.previous_release_id, status=source.status,
                granted_capabilities=source.granted_capabilities,
                installed_at=source.installed_at,
            )
            db.add(target)
            db.flush()
        binding.installation_id = target.id
        counts["skills"] += 1

    for binding in db.query(ExpertMcpBinding).order_by(ExpertMcpBinding.id).all():
        source = db.get(McpConnection, binding.connection_id)
        if source is None or source.scope_agent_id == binding.agent_id:
            continue
        target = db.query(McpConnection).filter_by(
            user_id=source.user_id, scope_agent_id=binding.agent_id, name=source.name,
        ).first()
        if target is None:
            # Pin the full effective config, including encrypted headers and env.
            revision = db.get(McpRevision, source.revision_id)
            config = connection_config(source, revision)
            credential_id = scoped_credential(db, source.user_id, source.credential_reference_id, binding.agent_id, require_active=False)
            target = McpConnection(
                user_id=source.user_id, scope_agent_id=binding.agent_id,
                workspace_id=workspace(binding.agent_id, source.user_id).id,
                definition_id=source.definition_id, revision_id=source.revision_id,
                credential_reference_id=credential_id, name=source.name,
                config_overrides_json=json.dumps(config, ensure_ascii=False),
                auth_mode=source.auth_mode, tool_policy_json=source.tool_policy_json,
                status="deleted" if source.status == "deleted" else binding.status,
            )
            db.add(target)
            db.flush()
        binding.connection_id = target.id
        counts["mcps"] += 1
    db.flush()
    return counts
