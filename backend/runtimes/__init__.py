"""Runtime 抽象层

每个 runtime 实现 AbstractRuntime 接口，通过 RuntimeFactory 获取实例。

已注册 runtime:
  - claude_code: Claude Code CLI subprocess

扩展方式:
  from runtimes import register_runtime
  from runtimes.base import AbstractRuntime

  class MyRuntime(AbstractRuntime): ...
  register_runtime("my_runtime", MyRuntime)
"""

from runtimes.base import (
    AbstractRuntime,
    RuntimeConfig,
    RuntimeEvent,
    RuntimeRunContext,
    RuntimeAttachment,
)
from runtimes.claude_code import ClaudeCodeRuntime

RUNTIME_REGISTRY: dict[str, type[AbstractRuntime]] = {
    "claude_code": ClaudeCodeRuntime,
}

# 每个 runtime 的显示名称和图标（用于前端展示）
RUNTIME_INFO = {
    "claude_code": {
        "label": "Claude Agent",
        "description": "Anthropic 官方 CLI agent，基于 Node.js，功能完整",
        "icon": "claude-code",
        "available": True,
        "model_protocols": ["anthropic-messages"],
        "thinking_levels": ["inherit", "low", "medium", "high", "xhigh", "max"],
        "reasoning_visibility_modes": ["off", "on", "stream"],
    },
}


def get_runtime_info() -> dict:
    result = {name: dict(info) for name, info in RUNTIME_INFO.items()}
    result["claude_code"]["available"] = True
    return result


def get_runtime(runtime_type: str) -> AbstractRuntime:
    """通过类型名获取 runtime 实例

    Args:
        runtime_type: 已注册的运行时类型

    Returns:
        对应 runtime 的新实例

    Raises:
        ValueError: 未知 runtime 类型
    """
    cls = RUNTIME_REGISTRY.get(runtime_type)
    if cls is None:
        raise ValueError(
            f"未知 runtime 类型: {runtime_type}，"
            f"可用: {', '.join(RUNTIME_REGISTRY.keys())}"
        )
    return cls()


def register_runtime(name: str, cls: type[AbstractRuntime], *, info: dict | None = None) -> None:
    """注册自定义 runtime（扩展点）"""
    RUNTIME_REGISTRY[name] = cls
    if info is not None:
        RUNTIME_INFO[name] = dict(info)
        from model_compat import RUNTIME_MODEL_PROTOCOLS
        RUNTIME_MODEL_PROTOCOLS[name] = set(info.get("model_protocols", []))


def validate_runtime_type(value: str) -> str:
    if value not in RUNTIME_REGISTRY:
        raise ValueError(f"不支持的 Runtime: {value}")
    return value
