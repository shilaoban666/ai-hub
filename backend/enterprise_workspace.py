"""User workspace, Runtime Cell and isolated execution-view lifecycle."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import settings
from models import (
    Agent, AgentRun, AgentSession, RuntimeCell, UserWorkspace, WorkspaceRunView,
    WorkspaceExecutionLease, RuntimeInstance,
    ChannelMessage, ModelRunCredential,
)


class WorkspaceRuntimeChangeBlocked(RuntimeError):
    pass


def runtime_workspace_change_required(db: Session, agent: Agent, runtime_type: str) -> bool:
    if (agent.runtime_type or "claude_code") != runtime_type:
        return True
    # A previous cutover may have updated the Agent before its workspace. Do
    # not mistake that pending import for an ordinary same-runtime migration.
    pending_workspace = db.query(UserWorkspace.id).filter(
        (UserWorkspace.agent_id == agent.id) | (UserWorkspace.id == agent.workspace_id),
        UserWorkspace.migration_status == "pending",
    ).first()
    if pending_workspace is None:
        return False
    return db.query(RuntimeInstance.id).filter(
        RuntimeInstance.agent_id == agent.id,
        RuntimeInstance.runtime_type != runtime_type,
    ).first() is not None


def reset_runtime_workspace(
    db: Session, agent: Agent, runtime_type: str, *, force_stop: bool = False,
) -> list[str]:
    """Start with empty files/sessions without opening the previous filesystem.

    Keep workspace IDs stable for installed assets and audit references. The
    new key selects a fresh physical root; a rollback restores the old key.
    The caller commits the runtime, configuration and reset together.
    """
    scope = (
        UserWorkspace.agent_id == agent.id
        if (agent.kind or "expert") == "expert"
        else UserWorkspace.id == agent.workspace_id
    )
    workspaces = db.query(UserWorkspace).filter(scope).with_for_update().all()
    workspace_ids = [workspace.id for workspace in workspaces]
    leases = db.query(WorkspaceExecutionLease).filter(
        WorkspaceExecutionLease.workspace_id.in_(workspace_ids),
    ).with_for_update().all() if workspace_ids else []
    active_runs = db.query(AgentRun).filter(
        (AgentRun.agent_id == agent.id) | AgentRun.workspace_id.in_(workspace_ids),
        AgentRun.status.in_(["queued", "running", "unknown"]),
    ).populate_existing().with_for_update().all()
    now = utcnow()
    if not force_stop and (active_runs or any(
        lease.run_id and lease.lease_until and (
            lease.lease_until.replace(tzinfo=timezone.utc)
            if lease.lease_until.tzinfo is None else lease.lease_until
        ) > now for lease in leases
    )):
        raise WorkspaceRuntimeChangeBlocked("工作区正在使用中，请等待任务结束后再更换runtime")

    stopped_run_ids = []
    if force_stop:
        # Fence old workers before changing the physical root. Cancellation
        # alone cannot prevent a delayed worker from writing old files back.
        for lease in leases:
            lease.fencing_token = (lease.fencing_token or 0) + 1
            lease.run_id = None
            lease.owner_id = None
            lease.lease_until = now
            lease.heartbeat_at = now
        for run in active_runs:
            run.status = "cancelled"
            run.cancel_requested = True
            run.finished_at = run.finished_at or now
            run.heartbeat_at = now
            run.worker_id = None
            run.lease_until = None
            run.error_code = "runtime_changed"
            run.error_message = "更换 runtime，任务已被强制终止，未完成的输出不再保存"
            stopped_run_ids.append(run.id)
            if run.source_message_id is not None:
                source = db.query(ChannelMessage).filter(
                    ChannelMessage.id == run.source_message_id,
                ).with_for_update().first()
                if source is not None:
                    source.status = "cancelled"
                    source.error_code = run.error_code
                    source.error_message = run.error_message
        # Stop new model requests while allowing in-flight usage to reconcile.
        for credential in db.query(ModelRunCredential).filter(
            ModelRunCredential.run_id.in_(stopped_run_ids),
            ModelRunCredential.status == "active",
        ).with_for_update().all():
            credential.status = "reconciliation"

    for workspace in workspaces:
        workspace.workspace_key = uuid.uuid4().hex
        workspace.storage_path = workspace_root(workspace)
        workspace.used_bytes = 0
        workspace.migration_status = "not_required"
        workspace.legacy_agent_ids = []
        workspace.status = "ready"
    for cell in db.query(RuntimeCell).filter(RuntimeCell.workspace_id.in_(workspace_ids)).all():
        cell.runtime_type = runtime_type
        cell.status = "unprovisioned"
        cell.container_name = None
        cell.desired_config_hash = None
        cell.applied_config_hash = None
        cell.last_error_code = None
        cell.last_error_message = None
    for session in db.query(AgentSession).filter(AgentSession.agent_id == agent.id).all():
        session.runtime_type = runtime_type
        session.runtime_session_id = None
        session.claude_session_id = None
        session.runtime_instance_id = None
        session.runtime_state = "active"
    for instance in db.query(RuntimeInstance).filter(
        RuntimeInstance.agent_id == agent.id,
        RuntimeInstance.runtime_type != runtime_type,
    ).all():
        instance.status = "retired"
        instance.endpoint = None
        instance.auth_secret_encrypted = None
        instance.worker_id = None
        instance.lease_until = None
    return stopped_run_ids


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def configured_sandbox_type() -> str:
    from sandbox import get_configured_sandbox_type

    return get_configured_sandbox_type()


def workspace_root(workspace: UserWorkspace) -> str:
    configured = os.path.realpath(settings.user_workspace_root)
    target = os.path.realpath(os.path.join(configured, workspace.workspace_key))
    if target == configured or not target.startswith(configured + os.sep):
        raise ValueError("invalid user workspace path")
    return target


def workspace_files_root(workspace: UserWorkspace) -> str:
    return os.path.join(workspace_root(workspace), "files")


def _cell_config_hash(runtime_type: str, sandbox_type: str) -> str:
    payload = {
        "runtime_type": runtime_type,
        "sandbox_type": sandbox_type,
        "container_image": settings.claude_code_container_image,
        "container_network": settings.claude_code_container_network,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def ensure_user_workspace(
    db: Session,
    user_id: int,
    *,
    runtime_type: str = "claude_code",
    agent_id: int | None = None,
    commit: bool = True,
) -> tuple[UserWorkspace, RuntimeCell]:
    workspace_query = db.query(UserWorkspace).filter(UserWorkspace.user_id == user_id)
    workspace_query = workspace_query.filter(
        UserWorkspace.agent_id == agent_id if agent_id is not None else UserWorkspace.agent_id.is_(None)
    )
    workspace = workspace_query.first()
    if workspace is not None and workspace.is_deleted:
        workspace.is_deleted = False
        workspace.status = "ready"
    if workspace is None:
        workspace = UserWorkspace(
            workspace_key=uuid.uuid4().hex,
            user_id=user_id,
            agent_id=agent_id,
            status="ready",
            quota_bytes=max(0, int(settings.user_workspace_quota_bytes)),
            migration_status="not_required",
        )
        try:
            # Use a savepoint so a concurrent insert does not roll back the
            # caller's pending Agent/asset changes. The old implementation
            # rolled back the whole session and then assumed the competing
            # row was visible, which produced NoResultFound when the failure
            # came from a stale pre-045 unique constraint instead.
            with db.begin_nested():
                db.add(workspace)
                db.flush()
        except IntegrityError as exc:
            workspace = workspace_query.filter(UserWorkspace.is_deleted == False).first()
            if workspace is None:
                if agent_id is not None:
                    raise RuntimeError(
                        "专家智能体工作区约束未完成，请依次执行 migrations/045_agent_scoped_workspaces.sql、046_agent_workspace_uniqueness.sql 和 047_workspace_scope_keys.sql"
                    ) from exc
                raise

    physical_root = workspace_root(workspace)
    if workspace.storage_path != physical_root:
        workspace.storage_path = physical_root

    sandbox_type = configured_sandbox_type()
    if sandbox_type not in {"native", "container"}:
        raise RuntimeError(
            "enterprise user workspaces require CLAUDE_CODE_SANDBOX_TYPE=native or container"
        )
    cell = db.query(RuntimeCell).filter(
        RuntimeCell.workspace_id == workspace.id
    ).first()
    desired_hash = _cell_config_hash(runtime_type, sandbox_type)
    if cell is None:
        candidate = RuntimeCell(
            workspace_id=workspace.id,
            user_id=user_id,
            agent_id=agent_id,
            runtime_type=runtime_type,
            sandbox_type=sandbox_type,
            status="ready" if sandbox_type == "native" else "unprovisioned",
            image_ref=(
                settings.claude_code_container_image
                if sandbox_type == "container"
                else None
            ),
            desired_config_hash=desired_hash,
            applied_config_hash=desired_hash if sandbox_type == "native" else None,
        )
        try:
            # The workspace row is unique, but two first requests can still
            # race while creating its RuntimeCell. Keep the caller's pending
            # changes and reuse the winner's cell after the savepoint rolls
            # back the losing insert only.
            with db.begin_nested():
                db.add(candidate)
                db.flush()
            cell = candidate
        except IntegrityError as exc:
            cell = db.query(RuntimeCell).filter(
                RuntimeCell.workspace_id == workspace.id
            ).first()
            if cell is None:
                if agent_id is not None:
                    raise RuntimeError(
                        "专家智能体运行单元约束未完成，请检查 runtime_cells 的工作区唯一约束"
                    ) from exc
                raise
    previous_sandbox_type = cell.sandbox_type
    cell.runtime_type = runtime_type
    cell.sandbox_type = sandbox_type
    cell.image_ref = (
        settings.claude_code_container_image if sandbox_type == "container" else None
    )
    cell.desired_config_hash = desired_hash
    if sandbox_type == "native":
        cell.status = "ready"
        cell.applied_config_hash = desired_hash
    elif previous_sandbox_type != sandbox_type or cell.applied_config_hash != desired_hash:
        cell.status = "unprovisioned"
        cell.applied_config_hash = None
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(workspace)
    db.refresh(cell)
    return workspace, cell


def bind_agent_workspace(db: Session, agent: Agent, *, commit: bool = True) -> tuple[UserWorkspace, RuntimeCell]:
    # Expert agents get an isolated workspace. The personal-default assistant
    # is the AI workbench itself and must keep using the user's legacy
    # workspace so its system assets and existing files remain available.
    scoped_agent_id = (
        int(agent.id)
        if agent.id is not None and (agent.kind or "expert") == "expert"
        else None
    )
    execution_user_id = int(getattr(agent, "execution_user_id", agent.user_id))
    shared_execution = execution_user_id != int(agent.user_id)
    workspace, cell = ensure_user_workspace(
        db,
        execution_user_id,
        runtime_type=(agent.runtime_type or "claude_code"),
        agent_id=scoped_agent_id,
        commit=commit,
    )
    if shared_execution:
        # The wrapper owns this pointer; never replace the publisher workspace.
        agent.workspace_id = workspace.id
        workspace.legacy_agent_ids = []
        return workspace, cell
    if agent.workspace_id != workspace.id:
        agent.workspace_id = workspace.id
        if commit:
            db.commit()
        else:
            db.flush()
    if scoped_agent_id is not None:
        workspace.legacy_agent_ids = [agent.id]
    elif workspace.migration_status == "pending":
        workspace.legacy_agent_ids = [row.id for row in db.query(Agent.id).filter(
            Agent.workspace_id == workspace.id, Agent.user_id == execution_user_id,
        ).all()]
    return workspace, cell


def get_user_workspace(db: Session, user_id: int, agent_id: int | None = None) -> UserWorkspace | None:
    return db.query(UserWorkspace).filter(
        UserWorkspace.user_id == user_id,
        UserWorkspace.agent_id == agent_id if agent_id is not None else UserWorkspace.agent_id.is_(None),
        UserWorkspace.is_deleted == False,
    ).first()


def record_run_view(
    db: Session,
    *,
    run_id: str,
    workspace: UserWorkspace,
    agent_id: int,
    host_path: str,
    sandbox_ref: str,
    config_hash: str | None = None,
) -> WorkspaceRunView:
    view = db.query(WorkspaceRunView).filter(WorkspaceRunView.run_id == run_id).first()
    if view is None:
        view = WorkspaceRunView(
            run_id=run_id,
            workspace_id=workspace.id,
            agent_id=agent_id,
        )
        db.add(view)
    view.status = "ready"
    view.host_path = host_path
    view.sandbox_ref = sandbox_ref
    view.config_hash = config_hash
    view.cleanup_status = "pending"
    view.prepared_at = utcnow()
    view.last_error = None
    cell = db.query(RuntimeCell).filter(RuntimeCell.workspace_id == workspace.id).first()
    if cell is not None:
        cell.status = "running"
        cell.last_started_at = utcnow()
        cell.last_active_at = utcnow()
        cell.last_error_code = None
        cell.last_error_message = None
    workspace.last_accessed_at = utcnow()
    db.commit()
    return view


def finish_run_view(
    db: Session,
    run_id: str,
    *,
    success: bool,
    error: str | None = None,
) -> None:
    view = db.query(WorkspaceRunView).filter(WorkspaceRunView.run_id == run_id).first()
    if view is None:
        return
    view.status = "cleaned" if success else "cleanup_failed"
    view.cleanup_status = "complete" if success else "failed"
    view.cleaned_at = utcnow()
    view.last_error = error[:2000] if error else None
    lease = db.query(WorkspaceExecutionLease).filter(
        WorkspaceExecutionLease.workspace_id == view.workspace_id,
    ).populate_existing().with_for_update().first()
    if lease is not None and lease.run_id != run_id:
        # An old Run can update its audit record, never a successor's Cell.
        db.commit()
        return
    workspace = db.query(UserWorkspace).filter(
        UserWorkspace.id == view.workspace_id
    ).first()
    if workspace is not None:
        files_root = workspace_files_root(workspace)
        used_bytes = 0
        if os.path.isdir(files_root):
            for current, _, filenames in os.walk(files_root, followlinks=False):
                for filename in filenames:
                    path = os.path.join(current, filename)
                    if not os.path.islink(path):
                        used_bytes += os.path.getsize(path)
        workspace.used_bytes = used_bytes
        workspace.last_accessed_at = utcnow()
    cell = db.query(RuntimeCell).filter(
        RuntimeCell.workspace_id == view.workspace_id
    ).first()
    if cell is not None:
        cell.status = "ready" if success else "error"
        cell.last_active_at = utcnow()
        cell.hibernated_at = utcnow()
        cell.last_error_code = None if success else "workspace_cleanup_failed"
        cell.last_error_message = None if success else (error or "workspace cleanup failed")[:2000]
    db.commit()


def workspace_payload(workspace: UserWorkspace, cell: RuntimeCell) -> dict:
    return {
        "id": workspace.id,
        "workspace_key": workspace.workspace_key,
        "status": workspace.status,
        "quota_bytes": workspace.quota_bytes,
        "used_bytes": workspace.used_bytes,
        "migration_status": workspace.migration_status,
        "runtime_cell": {
            "id": cell.id,
            "runtime_type": cell.runtime_type,
            "sandbox_type": cell.sandbox_type,
            "status": cell.status,
            "image_ref": cell.image_ref,
            "last_active_at": cell.last_active_at,
        },
    }
