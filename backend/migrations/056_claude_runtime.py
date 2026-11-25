"""Move retired runtime configuration to Claude; preserve messages and run audit.

Run with API and channel workers stopped. Preview is offline; --check reads
the configured database and --apply performs the transactional backfill.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LEGACY_RUNTIME = "openclaw"
THINKING_LEVELS = {"inherit", "low", "medium", "high", "xhigh", "max"}


def backfill(db, *, apply=True):
    from sqlalchemy.orm import defer
    from model_catalog import workbench_models
    from model_compat import model_supports_runtime
    from models import (Agent, AgentSession, AIModel, PlatformAgentSettings, RuntimeCell,
                        RuntimeInstance, UserWorkspace, WorkbenchSettings)

    # A running task may still hold a Gateway connection or write its workspace.
    # Fail before changing any data; settle/recover it through the existing UI.
    from models import AgentRun
    active = db.query(AgentRun.id).filter(
        (AgentRun.agent_id.in_(db.query(Agent.id).filter(Agent.runtime_type == LEGACY_RUNTIME)))
        | (AgentRun.session_id.in_(db.query(AgentSession.id).filter(AgentSession.runtime_type == LEGACY_RUNTIME)))
        | (AgentRun.runtime_instance_id.in_(db.query(RuntimeInstance.id).filter(RuntimeInstance.runtime_type == LEGACY_RUNTIME))),
        AgentRun.status.in_(["queued", "running", "unknown"]),
    ).count()
    if active:
        raise RuntimeError(f"{active} unresolved legacy runs; complete or recover them first")

    # These presentation columns are added by the following migration 057.
    agent_query = db.query(Agent).options(
        defer(Agent.noun_highlight_enabled), defer(Agent.noun_explanation_url),
    )
    agents = agent_query.filter(Agent.runtime_type == LEGACY_RUNTIME).all()
    policies = db.query(PlatformAgentSettings).filter(
        PlatformAgentSettings.runtime_type == LEGACY_RUNTIME,
    ).all()
    sessions = db.query(AgentSession).filter(
        (AgentSession.runtime_type == LEGACY_RUNTIME)
        | (AgentSession.agent_id.in_([agent.id for agent in agents])
           & AgentSession.runtime_type.is_(None)),
    ).all()
    instances = db.query(RuntimeInstance).filter(
        RuntimeInstance.runtime_type == LEGACY_RUNTIME, RuntimeInstance.status != "retired",
    ).all()
    cells = db.query(RuntimeCell).filter(RuntimeCell.runtime_type == LEGACY_RUNTIME).all()
    # Repair pending file imports left by an earlier version of this cutover.
    # Only identifiable legacy agents are included; Claude sandbox migrations
    # continue to import their own files normally.
    pending_agents = agent_query.join(
        UserWorkspace,
        (UserWorkspace.agent_id == Agent.id) | (UserWorkspace.id == Agent.workspace_id),
    ).filter(
        Agent.runtime_type == "claude_code", Agent.is_deleted == False,
        Agent.id.in_(db.query(RuntimeInstance.agent_id).filter(
            RuntimeInstance.runtime_type == LEGACY_RUNTIME,
        )),
        UserWorkspace.migration_status == "pending",
    ).distinct().all()
    choices = {}
    missing = []
    for agent in agents:
        catalog = [model for model in workbench_models(db, agent.user_id)
                   if model_supports_runtime(model, "claude_code")]
        selected = next((model for model in catalog if model.id == agent.default_model_id),
                        catalog[0] if catalog else None)
        choices[agent.id] = selected.id if selected else None
        if not agent.is_deleted and selected is None:
            missing.append(agent.id)
    if missing:
        raise RuntimeError(f"No available Anthropic Messages model for agents {missing}; configure one first")

    workbenches = db.query(WorkbenchSettings).options(
        defer(WorkbenchSettings.noun_highlight_enabled), defer(WorkbenchSettings.noun_explanation_url),
    ).all() if agents or policies else []
    replacement = db.query(AIModel).filter(
        AIModel.scope == "platform", AIModel.is_enabled == True,
        AIModel.is_deleted == False, AIModel.api_protocol == "anthropic-messages",
    ).order_by(AIModel.id).first() if policies or workbenches else None
    model_repairs = []
    for config in [*policies, *workbenches]:
        model = db.get(AIModel, config.default_model_id) if config.default_model_id else None
        if config.default_model_id and (model is None or not model.is_enabled or model.is_deleted
                                       or model.scope != "platform"
                                       or not model_supports_runtime(model, "claude_code")):
            if config.status == "published" and replacement is None:
                raise RuntimeError("Configure a platform Anthropic Messages model for the published assistant first")
            model_repairs.append(config)

    counts = {"agents": len(agents), "policies": len(policies), "sessions": len(sessions),
              "instances": len(instances), "cells": len(cells),
              "pending_workspaces": len(pending_agents)}
    if not apply:
        return counts

    for agent in agents:
        agent.runtime_type = "claude_code"
        agent.default_model_id = choices[agent.id]
        if agent.thinking_level not in THINKING_LEVELS:
            agent.thinking_level = "inherit"
    for policy in policies:
        policy.runtime_type = "claude_code"
        if policy.thinking_level not in THINKING_LEVELS:
            policy.thinking_level = "inherit"
    for config in model_repairs:
        config.default_model_id = replacement.id if replacement else None
    for session in sessions:
        session.runtime_type = "claude_code"
        session.runtime_session_id = None
        session.claude_session_id = None
        session.runtime_instance_id = None
        session.runtime_state = "active"
        catalog = [model for model in workbench_models(db, session.user_id)
                   if model_supports_runtime(model, "claude_code")]
        if session.model_id not in {model.id for model in catalog}:
            session.model_id = catalog[0].id if catalog else None
    for instance in instances:
        # Retain the row identity for historical AgentRun foreign keys.
        instance.status = "retired"
        instance.endpoint = None
        instance.auth_secret_encrypted = None
        instance.worker_id = None
        instance.lease_until = None
    for cell in cells:
        cell.runtime_type = "claude_code"
        cell.status = "unprovisioned"
        cell.desired_config_hash = None
        cell.applied_config_hash = None
        cell.container_name = None
        cell.image_ref = None
        cell.last_error_code = None
        cell.last_error_message = None
    # Runtime changes start with fresh files. Never read/import old workspaces;
    # preserve asset IDs, messages, MCP overrides and historical run records.
    for agent in [*agents, *pending_agents]:
        if agent.is_deleted:
            continue
        from enterprise_workspace import bind_agent_workspace, reset_runtime_workspace
        reset_runtime_workspace(db, agent, "claude_code")
        workspace, _ = bind_agent_workspace(db, agent, commit=False)
        workspace.migration_status = "not_required"
    db.flush()
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not (args.apply or args.check):
        parser.print_help()
        return
    from sqlalchemy.orm import Session
    from database import engine
    with Session(engine) as db, db.begin():
        counts = backfill(db, apply=args.apply)
    if args.check and any(counts.values()):
        print(f"Migration required: {counts}")
        raise SystemExit(1)
    # MySQL's legacy column default also needs changing for future inserts.
    if args.apply and engine.dialect.name == "mysql":
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE runtime_instances ALTER COLUMN runtime_type SET DEFAULT 'claude_code'"
            )
    print(f"Claude runtime migration {'applied' if args.apply else 'verified'}: {counts}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f"Migration failed: {detail}", file=sys.stderr)
        raise SystemExit(1) from None
