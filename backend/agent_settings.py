"""Resolve shared policy once per execution, without rewriting agent records."""
from models import PlatformAgentSettings, WorkbenchSettings


RUNTIME_DEFAULTS = {
    "runtime_type": "claude_code", "thinking_level": "inherit",
    "reasoning_visibility": "off", "max_turns": 50, "timeout_seconds": 600,
}
WORKBENCH_FIELDS = (
    "assistant_name", "assistant_icon", "assistant_mascot",
    "assistant_description", "system_prompt", "default_model_id",
)


def published_agent_settings(db):
    return db.query(PlatformAgentSettings).filter_by(status="published").order_by(
        PlatformAgentSettings.version.desc(),
    ).populate_existing().first()


def published_workbench_settings(db):
    value = db.query(WorkbenchSettings).filter_by(status="published").order_by(
        WorkbenchSettings.version.desc(),
    ).first()
    # Existing installations keep working before their first split publication.
    return value if value is not None else published_agent_settings(db)


def seed_workbench_settings(db):
    """Preserve the old assistant independently before changing global policy."""
    if db.query(WorkbenchSettings.id).first() is not None:
        return
    for status in ("published", "draft"):
        old = db.query(PlatformAgentSettings).filter_by(status=status).order_by(
            PlatformAgentSettings.version.desc(),
        ).first()
        if old is None:
            continue
        db.add(WorkbenchSettings(
            **{key: getattr(old, key, None)
               for key in WORKBENCH_FIELDS},
            version=old.version, status=status, created_by=old.created_by,
            published_by=old.published_by, published_at=old.published_at,
        ))
    db.flush()


class RuntimeAgent:
    """An immutable policy snapshot over a live ORM agent and its own resources."""
    def __init__(self, agent, values):
        object.__setattr__(self, "_agent", agent)
        object.__setattr__(self, "_values", values)

    def __getattr__(self, name):
        if name in self._values:
            return self._values[name]
        return getattr(self._agent, name)

    def __setattr__(self, name, value):
        if name in self._values:
            self._values[name] = value
        else:
            setattr(self._agent, name, value)


_UNSET = object()


def runtime_agent(db, agent, *, policy=_UNSET):
    if isinstance(agent, RuntimeAgent):
        return agent
    policy = published_agent_settings(db) if policy is _UNSET else policy
    if policy is None:
        # Compatibility for installations that have not published a policy yet.
        values = {key: getattr(agent, key, None) or default for key, default in RUNTIME_DEFAULTS.items()}
        values["settings_version"] = None
    else:
        values = {key: getattr(policy, key) for key in RUNTIME_DEFAULTS}
        values["settings_version"] = policy.version
    return RuntimeAgent(agent, values)


def runtime_snapshot(agent):
    return {
        **{key: getattr(agent, key) for key in RUNTIME_DEFAULTS},
        "config_version": getattr(agent, "settings_version", None),
    }
