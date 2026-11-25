"""Runtime-aware workspace lifecycle and file access."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from sandbox import get_sandbox
from sandbox.base import Sandbox


def workspace_snapshot(workspace):
    """Read filesystem inputs on the Session-owning thread."""
    fields = ("id", "user_id", "workspace_key", "migration_status", "legacy_agent_ids", "quota_bytes")
    return SimpleNamespace(**{
        key: deepcopy(getattr(workspace, key)) for key in fields if hasattr(workspace, key)
    })


def agent_workspace_snapshot(agent, *, skills_only=False):
    fields = ("id", "name", "description", "system_prompt", "runtime_type",
              "effective_system_prompt", "runtime_secret_env", "runtime_capabilities",
              "runtime_requires_confirmation")
    result = SimpleNamespace(**{
        key: deepcopy(getattr(agent, key)) for key in fields if hasattr(agent, key)
    })
    # Resolved runtime assets contain plain values, never ORM relationships.
    result.runtime_skills = deepcopy(getattr(agent, "runtime_skills", []))
    result.skills = result.runtime_skills
    if not skills_only:
        result.runtime_mcps = deepcopy(getattr(agent, "runtime_mcps", []))
        result.mcps = result.runtime_mcps
        result.mcp_overrides = deepcopy(getattr(agent, "mcp_overrides", []))
    return result


def workspace_model_snapshot(model):
    if model is None:
        return None
    fields = ("id", "name", "scope", "api_proxy_url", "api_protocol", "provider")
    snapshot = SimpleNamespace(**{
        key: getattr(model, key) for key in fields if hasattr(model, key)
    })
    snapshot.api_key = "" if getattr(model, "scope", "user") == "platform" else (model.api_key or "")
    return snapshot


def get_workspace_provider(agent) -> Sandbox:
    if getattr(agent, "open_call_run_id", None):
        from sandbox.open_call import get_open_call_sandbox
        return get_open_call_sandbox()
    return get_sandbox()
