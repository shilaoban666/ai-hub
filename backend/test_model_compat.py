from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError

from agent_routes import _validate_agent_models_or_400
from model_compat import (
    compatible_runtime_types,
    model_supports_runtime,
    resolve_model_protocol,
    normalize_thinking_level,
)
from schemas import ModelCreate


def _model(protocol, model_id=1):
    return SimpleNamespace(
        id=model_id,
        name="same-model",
        provider="provider-a",
        remarks="company-account",
        api_protocol=protocol,
        api_proxy_url="https://models.example.com",
    )


def test_runtime_model_protocol_matrix():
    anthropic = _model("anthropic-messages")
    openai = _model("openai-completions", model_id=2)

    assert compatible_runtime_types(anthropic) == ["claude_code"]
    assert compatible_runtime_types(openai) == []
    assert model_supports_runtime(anthropic, "claude_code") is True
    assert model_supports_runtime(openai, "claude_code") is False


def test_anthropic_deepseek_reasoning_normalization_is_preserved():
    model = _model("anthropic-messages")
    model.name = "deepseek-v4-flash"
    assert normalize_thinking_level(model, "max") == "high"
    assert normalize_thinking_level(model, "xhigh") == "high"
    assert normalize_thinking_level(model, "medium") == "medium"
    model.name = "claude-sonnet"
    assert normalize_thinking_level(model, "max") == "max"


def test_legacy_auto_is_not_bindable_or_inferred():
    legacy = _model("auto")
    legacy.name = "deepseek-v4-flash"
    legacy.api_proxy_url = "https://sub2api.fancyqube.net"

    assert compatible_runtime_types(legacy) == []
    try:
        resolve_model_protocol(legacy)
    except ValueError as exc:
        assert "尚未配置 API 协议" in str(exc)
    else:
        raise AssertionError("Legacy auto records must not be inferred")


def test_agent_model_validation_requires_runtime_compatibility_and_default_binding():
    openai = _model("openai-completions")
    try:
        _validate_agent_models_or_400([openai], openai, "claude_code")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "不兼容" in str(exc.detail)
    else:
        raise AssertionError("Claude Code must reject OpenAI-protocol models")

    anthropic = _model("anthropic-messages")
    _validate_agent_models_or_400([anthropic], anthropic, "claude_code")

    try:
        _validate_agent_models_or_400([anthropic], _model("anthropic-messages", 9), "claude_code")
    except HTTPException as exc:
        assert "默认模型必须包含" in str(exc.detail)
    else:
        raise AssertionError("Default model must be bound to the agent")


def test_model_create_requires_explicit_protocol():
    payload = {
        "name": "model-a",
        "provider": "provider-a",
        "api_key": "secret",
        "api_proxy_url": "https://models.example.com",
    }
    try:
        ModelCreate(**payload)
    except ValidationError:
        pass
    else:
        raise AssertionError("ModelCreate must require an explicit API protocol")

    model = ModelCreate(**payload, api_protocol="anthropic-messages")
    assert model.api_protocol == "anthropic-messages"


if __name__ == "__main__":
    test_runtime_model_protocol_matrix()
    test_legacy_auto_is_not_bindable_or_inferred()
    test_agent_model_validation_requires_runtime_compatibility_and_default_binding()
    test_model_create_requires_explicit_protocol()
    print("model compatibility tests passed")
