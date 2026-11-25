"""Claude Code sandbox factory."""
from __future__ import annotations

import logging

from database import settings
from sandbox.base import Sandbox, WorkspaceContext
from sandbox.directory import DirectorySandbox
from sandbox.native import NativeSandbox
from sandbox.container import ContainerSandbox

__all__ = [
    "get_configured_sandbox_type",
    "get_sandbox",
    "Sandbox",
    "WorkspaceContext",
]

logger = logging.getLogger(__name__)
_legacy_warning_emitted = False

_REGISTRY: dict[str, type[Sandbox]] = {
    "directory": DirectorySandbox,
    "native": NativeSandbox,
    "linux_user": NativeSandbox,
    "container": ContainerSandbox,
}


def get_configured_sandbox_type() -> str:
    """Return Claude Code isolation with legacy AGENT_* fallback."""
    global _legacy_warning_emitted
    configured = str(
        getattr(settings, "claude_code_sandbox_type", "") or ""
    ).strip().lower()
    if configured:
        return configured

    legacy = str(
        getattr(settings, "agent_sandbox_type", "") or "directory"
    ).strip().lower()
    fields_set = getattr(settings, "model_fields_set", set())
    if "agent_sandbox_type" in fields_set and not _legacy_warning_emitted:
        logger.warning(
            "AGENT_SANDBOX_TYPE is deprecated; use CLAUDE_CODE_SANDBOX_TYPE"
        )
        _legacy_warning_emitted = True
    return legacy or "directory"


def get_sandbox(sandbox_type: str | None = None) -> Sandbox:
    """Return the configured Claude Code sandbox implementation."""
    selected = sandbox_type or get_configured_sandbox_type()
    sandbox_name = selected.strip().lower()
    sandbox_class = _REGISTRY.get(sandbox_name)
    if sandbox_class is None:
        raise ValueError(
            f"Unknown Claude Agent sandbox type: {sandbox_name}; "
            f"available: {', '.join(_REGISTRY.keys())}"
        )
    return sandbox_class()
