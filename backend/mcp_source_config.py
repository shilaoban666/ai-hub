"""Resolve executable MCP configuration without using public display values."""
import json
from urllib.parse import urlsplit

from mcp_headers import ENCRYPTED_ENV, ENCRYPTED_HEADERS
from models import McpService


class McpSourceConfigError(ValueError):
    pass


def normalize_json_mcp_config(config):
    if not isinstance(config, dict):
        raise McpSourceConfigError("JSON MCP 配置必须是对象")
    candidate = config
    if "mcpServers" in config:
        servers = config["mcpServers"]
        if not isinstance(servers, dict) or len(servers) != 1:
            raise McpSourceConfigError("JSON MCP 配置的 mcpServers 必须包含一个服务，请拆分后添加")
        candidate = next(iter(servers.values()))
    if not isinstance(candidate, dict):
        raise McpSourceConfigError("JSON MCP 服务配置必须是对象")
    candidate = dict(candidate)
    declared = str(candidate.get("type") or "").replace("-", "_").lower()
    if declared in {"stdio", "http", "sse", "streamable_http"}:
        transport = declared
    elif candidate.get("command"):
        transport = "stdio"
    elif candidate.get("url"):
        transport = "http"
    else:
        transport = "json"
    if transport != "json":
        candidate.pop("type", None)
    return transport, candidate


def source_mcp_config(source):
    """Read the stored source, excluding its author's connection credentials."""
    try:
        config = json.loads(source.config or "{}")
    except (TypeError, ValueError) as exc:
        raise McpSourceConfigError("MCP 源配置无效") from exc
    if not isinstance(config, dict):
        raise McpSourceConfigError("MCP 源配置必须是对象")
    transport = source.type.replace("-", "_")
    if transport == "json":
        transport, config = normalize_json_mcp_config(config)
    for key in ("headers", "env", ENCRYPTED_HEADERS, ENCRYPTED_ENV):
        config.pop(key, None)
    return transport, config


def system_mcp_config(db, definition, config):
    """Recover URLs saved by the old public-catalog import, without editing releases.

    Only a linked, still-public source on the same origin may repair the exact
    public URL placeholder. Saved destination credentials remain independent.
    """
    transport = definition.transport_type.replace("-", "_")
    if transport == "json":
        transport, config = normalize_json_mcp_config(config)
    if definition.scope != "system":
        return transport, config
    url = str(config.get("url") or "").strip()
    if urlsplit(url).path != "/REDACTED":
        return transport, config
    source = db.query(McpService).filter(
        McpService.id == definition.source_mcp_service_id,
        McpService.is_deleted == False,
        McpService.is_public == True,
    ).first() if definition.source_mcp_service_id else None
    if source is None:
        raise McpSourceConfigError("系统 MCP 保存了脱敏地址，源服务已不可用，请管理员重新添加连接器")
    source_transport, original = source_mcp_config(source)
    original_url = str(original.get("url") or "").strip()
    parsed, source_parsed = urlsplit(url), urlsplit(original_url)
    if (
        (parsed.scheme, parsed.netloc) != (source_parsed.scheme, source_parsed.netloc)
        or source_parsed.path == "/REDACTED"
        or source_transport not in {"http", "sse", "streamable_http"}
    ):
        raise McpSourceConfigError("系统 MCP 保存了脱敏地址，源服务地址已变更，请管理员重新添加连接器")
    restored = dict(config, url=original_url)
    # Old public imports also saved display placeholders as HTTP headers.
    # Preserve credentials subsequently entered for the destination connector.
    if isinstance(restored.get("headers"), dict):
        restored["headers"] = {
            name: value for name, value in restored["headers"].items()
            if value not in ("隐藏", "{{credential}}")
        }
    return transport, restored
