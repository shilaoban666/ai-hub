"""Model wire-protocol and runtime compatibility rules."""

from __future__ import annotations

import re

OPENAI_COMPLETIONS = "openai-completions"
ANTHROPIC_MESSAGES = "anthropic-messages"
MODEL_API_PROTOCOLS = {OPENAI_COMPLETIONS, ANTHROPIC_MESSAGES}

RUNTIME_MODEL_PROTOCOLS = {
    "claude_code": {ANTHROPIC_MESSAGES},
}

def configured_model_protocol(model) -> str | None:
    protocol = str(getattr(model, "api_protocol", "") or "").strip()
    return protocol if protocol in MODEL_API_PROTOCOLS else None


def resolve_model_protocol(model) -> str:
    """Return the explicitly configured wire protocol."""
    configured = configured_model_protocol(model)
    if configured:
        return configured
    raise ValueError(f"{model_identity(model)} 尚未配置 API 协议")


def compatible_runtime_types(model) -> list[str]:
    protocol = configured_model_protocol(model)
    if not protocol:
        return []
    return [
        runtime_type
        for runtime_type, protocols in RUNTIME_MODEL_PROTOCOLS.items()
        if protocol in protocols
    ]


def model_supports_runtime(
    model,
    runtime_type: str,
) -> bool:
    return runtime_type in compatible_runtime_types(model)


def protocol_label(protocol: str | None) -> str:
    return {
        OPENAI_COMPLETIONS: "OpenAI Chat Completions",
        ANTHROPIC_MESSAGES: "Anthropic Messages",
    }.get(str(protocol or ""), "未配置")


def model_identity(model) -> str:
    name = str(getattr(model, "name", "") or "").strip() or f"Model {model.id}"
    provider = str(getattr(model, "provider", "") or "").strip()
    remarks = str(getattr(model, "remarks", "") or "").strip()
    details = [value for value in (provider, remarks) if value]
    return f"{name}（{' · '.join(details)}）" if details else name


def normalize_thinking_level(model, thinking_level: str | None) -> str:
    level = str(thinking_level or "inherit").strip().lower()
    model_name = str(getattr(model, "name", "") or "").strip().lower()
    if (
        configured_model_protocol(model) == ANTHROPIC_MESSAGES
        and re.search(r"(?:^|[/_-])deepseek[-_]?v4(?:$|[/_.-])", model_name)
    ):
        return {"xhigh": "high", "max": "high", "adaptive": "medium"}.get(level, level)
    return level
