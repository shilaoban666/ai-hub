"""Read-only MCP capability discovery used by the workbench.

This deliberately implements the small client surface needed by the workbench
instead of importing the optional MCP SDK.  It supports the HTTP transports
already accepted by the asset model and keeps tool/resource metadata opaque.
"""
from __future__ import annotations

import json
import os
import asyncio
from typing import Any
from urllib.parse import urljoin

import httpx


class McpInspectError(RuntimeError):
    """A user-facing error while discovering an MCP server."""


def _json_from_sse(payload: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []
    for line in payload.splitlines() + [""]:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue
        if line.strip() or not data_lines:
            continue
        raw = "\n".join(data_lines).strip()
        data_lines = []
        if raw and raw != "[DONE]":
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                messages.append(value)
    return messages


def _response_messages(response: httpx.Response) -> list[dict[str, Any]]:
    content_type = response.headers.get("content-type", "").lower()
    text = response.text
    if "text/event-stream" in content_type or text.lstrip().startswith("event:") or text.lstrip().startswith("data:"):
        return _json_from_sse(text)
    if not text.strip():
        return []
    try:
        value = response.json()
    except ValueError as exc:
        raise McpInspectError("MCP 服务返回了无法解析的响应") from exc
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    raise McpInspectError("MCP 服务返回了无效的 JSON-RPC 响应")


def _message_for_id(messages: list[dict[str, Any]], request_id: int) -> dict[str, Any]:
    for message in messages:
        if message.get("id") == request_id:
            if "error" in message:
                error = message.get("error") or {}
                code = error.get("code")
                if code == -32601:
                    raise LookupError(error.get("message") or "Method not found")
                raise McpInspectError(error.get("message") or "MCP 服务返回了错误")
            result = message.get("result")
            if not isinstance(result, dict):
                raise McpInspectError("MCP 服务返回了无效的结果")
            return result
    raise McpInspectError("MCP 服务没有返回对应的 JSON-RPC 响应")


def _set_default_header(headers: dict[str, str], name: str, value: str) -> None:
    """Set a protocol header without replacing a user-supplied casing variant."""
    if not any(key.lower() == name.lower() for key in headers):
        headers[name] = value


def _set_header(headers: dict[str, str], name: str, value: str) -> None:
    """Set a negotiated protocol header while avoiding duplicate casing."""
    for key in list(headers):
        if key.lower() == name.lower() and key != name:
            headers.pop(key, None)
    headers[name] = value


async def _open_sse_endpoint(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> str:
    sse_headers = {**headers, "Accept": "text/event-stream"}
    try:
        async with client.stream("GET", url, headers=sse_headers) as response:
            response.raise_for_status()
            event = ""
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event == "endpoint":
                    endpoint = line[5:].strip()
                    return urljoin(str(response.url), endpoint)
    except httpx.HTTPError as exc:
        raise McpInspectError(f"无法连接 MCP 服务：{exc}") from exc
    raise McpInspectError("MCP SSE 服务没有返回消息端点")


async def inspect_mcp_server(
    transport_type: str,
    config: dict[str, Any],
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Initialize an MCP server and collect its read-only capability lists."""
    transport = str(transport_type or "").replace("-", "_")
    if transport == "stdio":
        return await _inspect_stdio(config, timeout=timeout)
    if transport not in {"http", "sse", "streamable_http"}:
        raise McpInspectError("当前 MCP 传输类型不支持资源查看")
    url = str(config.get("url") or "").strip()
    if not url:
        raise McpInspectError("MCP 配置缺少服务地址")
    headers = {str(key): str(value) for key, value in (config.get("headers") or {}).items()}
    # Keep manually configured headers (including Authorization) intact. The
    # transport defaults are only added when the user did not configure the
    # same header under a different casing.
    _set_default_header(headers, "Content-Type", "application/json")
    _set_default_header(headers, "Accept", "application/json, text/event-stream")
    request_number = 0
    session_id: str | None = None
    negotiated_protocol_version: str | None = None

    timeout_config = httpx.Timeout(timeout, connect=min(timeout, 8.0))
    async with httpx.AsyncClient(timeout=timeout_config, follow_redirects=False, trust_env=True) as client:
        endpoint = url
        if transport == "sse":
            endpoint = await _open_sse_endpoint(client, url, headers)

        async def request(method: str, params: dict[str, Any] | None = None, *, optional: bool = False) -> dict[str, Any] | None:
            nonlocal request_number, session_id
            request_number += 1
            request_id = request_number
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params:
                payload["params"] = params
            request_headers = dict(headers)
            if session_id:
                _set_header(request_headers, "Mcp-Session-Id", session_id)
            if negotiated_protocol_version:
                _set_header(request_headers, "MCP-Protocol-Version", negotiated_protocol_version)
            try:
                response = await client.post(endpoint, headers=request_headers, json=payload)
                response.raise_for_status()
                session_id = response.headers.get("mcp-session-id") or session_id
                result = _message_for_id(_response_messages(response), request_id)
                return result
            except LookupError:
                if optional:
                    return None
                raise
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:300].strip()
                raise McpInspectError(f"MCP 服务请求失败（HTTP {exc.response.status_code}）{(': ' + detail) if detail else ''}") from exc
            except httpx.HTTPError as exc:
                raise McpInspectError(f"无法连接 MCP 服务：{exc}") from exc

        initialize = await request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "aihub-workbench", "version": "1.0"},
        })
        negotiated_protocol_version = str(initialize.get("protocolVersion") or "").strip() or None
        # Notifications do not require a response. Servers that only support
        # the older transport may reject it; discovery can still proceed.
        notification_headers = dict(headers)
        if session_id:
            _set_header(notification_headers, "Mcp-Session-Id", session_id)
        if negotiated_protocol_version:
            _set_header(notification_headers, "MCP-Protocol-Version", negotiated_protocol_version)
        try:
            await client.post(endpoint, headers=notification_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        except httpx.HTTPError:
            pass

        async def collect(method: str, key: str) -> list[dict[str, Any]]:
            values: list[dict[str, Any]] = []
            cursor: str | None = None
            for _ in range(100):
                params = {"cursor": cursor} if cursor else None
                result = await request(method, params, optional=True)
                if result is None:
                    break
                page = result.get(key)
                if isinstance(page, list):
                    values.extend(item for item in page if isinstance(item, dict))
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            return values

        capabilities = initialize.get("capabilities")
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        # MCP servers must advertise the capability before clients call its
        # list method. This avoids turning a valid tools-only server into a
        # failed resource inspection when resources/list is unsupported.
        tools = await collect("tools/list", "tools") if "tools" in capabilities else []
        has_resources = "resources" in capabilities
        resources = await collect("resources/list", "resources") if has_resources else []
        resource_templates = (
            await collect("resources/templates/list", "resourceTemplates")
            if has_resources else []
        )
        prompts = await collect("prompts/list", "prompts") if "prompts" in capabilities else []
        return {
            "server": initialize.get("serverInfo") or {},
            "protocol_version": initialize.get("protocolVersion"),
            "capabilities": initialize.get("capabilities") or {},
            "tools": tools,
            "resources": resources,
            "resource_templates": resource_templates,
            "prompts": prompts,
        }


async def _inspect_stdio(config: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    command = str(config.get("command") or "").strip()
    args = config.get("args") or []
    if not command or not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise McpInspectError("stdio MCP 配置无效")
    env = os.environ.copy()
    configured_env = config.get("env") or {}
    if isinstance(configured_env, dict):
        env.update({str(key): str(value) for key, value in configured_env.items()})
    try:
        process = await asyncio.create_subprocess_exec(
            command, *args, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except (OSError, ValueError) as exc:
        raise McpInspectError(f"无法启动 stdio MCP 服务：{exc}") from exc

    request_number = 0
    async def request(method: str, params: dict[str, Any] | None = None, *, optional: bool = False):
        nonlocal request_number
        request_number += 1
        payload = {"jsonrpc": "2.0", "id": request_number, "method": method}
        if params:
            payload["params"] = params
        try:
            process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            await process.stdin.drain()
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
                if not line:
                    raise McpInspectError("stdio MCP 服务提前退出")
                try:
                    message = json.loads(line.decode(errors="replace"))
                except json.JSONDecodeError:
                    continue
                if message.get("id") != request_number:
                    continue
                if "error" in message:
                    error = message.get("error") or {}
                    if optional and error.get("code") == -32601:
                        return None
                    raise McpInspectError(error.get("message") or "MCP 服务返回了错误")
                return message.get("result") or {}
        except (asyncio.TimeoutError, BrokenPipeError) as exc:
            raise McpInspectError("stdio MCP 服务响应超时") from exc

    try:
        initialize = await request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "aihub-workbench", "version": "1.0"},
        })
        try:
            process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            await process.stdin.drain()
        except (BrokenPipeError, AttributeError):
            pass

        async def collect(method: str, key: str):
            values = []
            cursor = None
            for _ in range(100):
                result = await request(method, {"cursor": cursor} if cursor else None, optional=True)
                if result is None:
                    break
                page = result.get(key)
                if isinstance(page, list):
                    values.extend(item for item in page if isinstance(item, dict))
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            return values

        return {
            "server": initialize.get("serverInfo") or {},
            "protocol_version": initialize.get("protocolVersion"),
            "capabilities": initialize.get("capabilities") or {},
            "tools": await collect("tools/list", "tools"),
            "resources": await collect("resources/list", "resources"),
            "resource_templates": await collect("resources/templates/list", "resourceTemplates"),
            "prompts": await collect("prompts/list", "prompts"),
        }
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except (asyncio.TimeoutError, ProcessLookupError):
            if process.returncode is None:
                process.kill()
