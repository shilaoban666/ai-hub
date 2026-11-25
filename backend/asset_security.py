"""Server-side security policy for installable skills and MCP connections."""
from __future__ import annotations

import fnmatch
import ipaddress
import json
import socket
from urllib.parse import parse_qsl, urlparse

from database import settings
from models import AssetSecurityEvent


SKILL_CAPABILITIES = {
    "workspace_read",
    "workspace_write",
    "command_execute",
    "network_access",
    "mcp_access",
}
MCP_RISK_LEVELS = {"read", "write", "delete", "notify", "cost"}
HIGH_RISK_LEVELS = {"write", "delete", "notify", "cost"}


class AssetPolicyError(ValueError):
    pass


def _flatten_tree(nodes: list, output: dict[str, str] | None = None) -> dict[str, str]:
    output = output if output is not None else {}
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        path = str(node.get("path") or node.get("label") or "").replace("\\", "/")
        if node.get("type") == "file":
            output[path] = str(node.get("content") or "")
        elif node.get("type") == "folder":
            _flatten_tree(node.get("children") or [], output)
    return output


def read_skill_manifest(tree: list) -> dict:
    """Read optional runtime metadata without scanning or rejecting skill content."""
    manifest = {}
    for path, content in _flatten_tree(tree).items():
        if path.rsplit("/", 1)[-1] == "aihub-manifest.json":
            try:
                value = json.loads(content)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                manifest = value
                break

    def strings(key):
        value = manifest.get(key, [])
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    return {
        "schema_version": 1,
        "capabilities": sorted(set(strings("capabilities")) & SKILL_CAPABILITIES),
        "network_domains": sorted({item.strip().lower() for item in strings("network_domains") if item.strip()}),
        "mcp_dependencies": manifest.get("mcp_dependencies", []) if isinstance(manifest.get("mcp_dependencies"), list) else [],
    }


def normalize_grants(manifest: dict, requested: list[str] | None) -> list[str]:
    required = set(manifest.get("capabilities") or [])
    granted = required if requested is None else set(requested)
    unknown = granted - SKILL_CAPABILITIES
    if unknown:
        raise AssetPolicyError("unknown granted capabilities: " + ", ".join(sorted(unknown)))
    missing = required - granted
    if missing:
        raise AssetPolicyError("required capabilities were not granted: " + ", ".join(sorted(missing)))
    return sorted(granted)


def _host_allowed(host: str, patterns: list[str]) -> bool:
    return not patterns or any(fnmatch.fnmatch(host, pattern) for pattern in patterns)


def _validate_ip(value: str) -> None:
    address = ipaddress.ip_address(value)
    if settings.mcp_allow_private_networks:
        if address.is_loopback:
            return
        private_networks = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("fc00::/7"),
        )
        if any(address in network for network in private_networks):
            return
    if (
        address.is_loopback or address.is_private or address.is_link_local
        or address.is_multicast or address.is_reserved or address.is_unspecified
    ):
        raise AssetPolicyError(f"MCP target resolves to a non-public address: {address}")


def validate_http_target(url: str) -> dict:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AssetPolicyError("HTTP MCP requires an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise AssetPolicyError("MCP URL userinfo is forbidden")
    if parsed.fragment:
        raise AssetPolicyError("MCP URL fragment is forbidden")
    sensitive_query_keys = {
        "api_key", "apikey", "token", "secret", "password", "access_token", "key",
    }
    if any(
        key.lower() in sensitive_query_keys and value
        for key, value in parse_qsl(parsed.query)
    ):
        raise AssetPolicyError("MCP URL must not contain credentials in query parameters")
    host = parsed.hostname.rstrip(".").lower()
    if host == "metadata.google.internal" or (
        host == "localhost" and not settings.mcp_allow_private_networks
    ):
        raise AssetPolicyError("MCP target host is forbidden")
    allowed = [item.strip().lower() for item in settings.mcp_allowed_hosts.split(",") if item.strip()]
    if allowed and not _host_allowed(host, allowed):
        raise AssetPolicyError(f"MCP target host is not approved: {host}")
    try:
        literal_address = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)})
        except socket.gaierror as exc:
            raise AssetPolicyError(f"MCP target DNS resolution failed: {host}") from exc
        if not addresses:
            raise AssetPolicyError(f"MCP target DNS returned no addresses: {host}")
        for address in addresses:
            _validate_ip(address)
    else:
        _validate_ip(str(literal_address))
        addresses = [str(literal_address)]
    return {"url": parsed.geturl(), "host": host, "resolved_addresses": addresses}


def _find_urls(value, key: str = "") -> list[str]:
    urls = []
    if isinstance(value, dict):
        for item_key, item in value.items():
            urls.extend(_find_urls(item, str(item_key)))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_find_urls(item, key))
    elif isinstance(value, str) and key.lower().replace("-", "_") in {"url", "endpoint", "base_url"}:
        urls.append(value)
    return urls


def validate_mcp_config(transport_type: str, config: dict) -> dict:
    transport = str(transport_type or "").replace("-", "_")
    if not isinstance(config, dict):
        raise AssetPolicyError("MCP configuration must be an object")
    report = {"transport_type": transport, "targets": []}
    if transport in {"http", "sse", "streamable_http"}:
        urls = _find_urls(config)
        if not urls:
            raise AssetPolicyError("HTTP MCP configuration requires a URL")
        report["targets"] = [validate_http_target(url) for url in urls]
        report["egress_proxy"] = settings.mcp_egress_proxy_url
    elif transport == "stdio":
        command = str(config.get("command") or "").strip()
        allowed = [item.strip() for item in settings.mcp_stdio_allowed_commands.split(",") if item.strip()]
        if not command or command not in allowed:
            raise AssetPolicyError("stdio MCP command is not in MCP_STDIO_ALLOWED_COMMANDS")
        if "/" in command or "\\" in command:
            raise AssetPolicyError("stdio MCP must reference an approved artifact command, not a host path")
        report["command"] = command
    return report


def normalize_tool_policy(value: dict | None) -> dict:
    value = value if isinstance(value, dict) else {}
    risk_level = str(value.get("risk_level") or "read").lower()
    if risk_level not in MCP_RISK_LEVELS:
        raise AssetPolicyError("invalid MCP risk_level")
    allowed_tools = value.get("allowed_tools", [])
    if not isinstance(allowed_tools, list) or any(not isinstance(item, str) for item in allowed_tools):
        raise AssetPolicyError("allowed_tools must be a string array")
    allowed_tools = sorted(set(item.strip() for item in allowed_tools if item.strip()))
    if risk_level in HIGH_RISK_LEVELS and (not allowed_tools or "*" in allowed_tools):
        raise AssetPolicyError("high-risk MCP connections require explicit allowed_tools")
    return {
        "risk_level": risk_level,
        "allowed_tools": allowed_tools,
        "require_confirmation": risk_level in HIGH_RISK_LEVELS,
    }


def audit_asset(db, *, asset_type: str, asset_id: int, action: str, actor_user_id: int, reason: str | None = None, details: dict | None = None) -> None:
    db.add(AssetSecurityEvent(
        asset_type=asset_type,
        asset_id=asset_id,
        action=action,
        actor_user_id=actor_user_id,
        reason=reason,
        details_json=json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
    ))
