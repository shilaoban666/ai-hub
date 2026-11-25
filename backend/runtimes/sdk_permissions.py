"""Claude Agent SDK control transport over AI Hub's existing sandbox pipes.

The sandbox runtime owns process creation, output translation and cancellation.
ClaudeSDKClient owns initialize/can_use_tool/control responses. Only control
frames are routed here; regular model events keep their existing SSE path.
"""

from __future__ import annotations

import asyncio
import json
from fnmatch import fnmatchcase
import logging
from uuid import uuid4

from claude_agent_sdk import (
    ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
    PermissionResultDeny, Transport, CLIConnectionError,
)

from runtimes.base import RuntimeRunContext


logger = logging.getLogger(__name__)
CONTROL_TYPES = {"control_request", "control_response", "control_cancel_request"}


class PermissionTransportClosed(CLIConnectionError):
    pass


class PermissionTransport(Transport):
    def __init__(self, write):
        self._write = write
        self._messages = asyncio.Queue()
        self._ready = True
        self._lock = asyncio.Lock()
        self._pending_controls = set()

    async def connect(self):
        pass  # The runtime has already launched the sandbox process.

    async def write(self, data: str):
        async with self._lock:
            if not self._ready:
                raise PermissionTransportClosed("智能体进程已结束，授权通道已关闭")
            message = json.loads(data)
            if message.get("type") == "control_request":
                self._pending_controls.add(message["request_id"])
            await self._write(data)

    async def read_messages(self):
        while True:
            message = await self._messages.get()
            if message is None:
                if self._pending_controls:
                    raise PermissionTransportClosed("智能体在 SDK 初始化或控制请求完成前退出")
                return
            yield message

    def feed(self, message: dict):
        if message.get("type") == "control_response":
            self._pending_controls.discard(message.get("response", {}).get("request_id"))
        if message.get("type") in CONTROL_TYPES:
            self._messages.put_nowait(message)

    def is_ready(self):
        return self._ready

    async def end_input(self):
        pass  # stdin must remain open until the runtime receives result.

    async def close(self):
        self.finish()

    def finish(self):
        if self._ready:
            self._ready = False
            self._messages.put_nowait(None)


async def request_tool_permission(run_context: RuntimeRunContext, tool_name, tool_input, _context, *, allowed_mcp_tools=()):
    """SDK can_use_tool callback. Persist first, then wait for the owning user."""
    if run_context.source != "web":
        return PermissionResultDeny(message="当前渠道不支持交互授权，工具请求已拒绝")
    if tool_name.startswith("mcp__") and not any(fnmatchcase(tool_name, rule) for rule in allowed_mcp_tools):
        return PermissionResultDeny(message="该 MCP 工具未在当前绑定的允许列表中")

    # Import lazily so the transport can also be exercised without a database.
    from agent_permission import permission_request, permission_decide
    from schemas import PermissionRequestInternal

    req_id = uuid4().hex
    try:
        created = await permission_request(PermissionRequestInternal(
            run_id=run_context.run_id, req_id=req_id,
            tool_name=tool_name, tool_input=tool_input,
        ))
        if not created.get("ok"):
            return PermissionResultDeny(message=created.get("detail") or "无法创建授权请求")
        decision = await permission_decide(run_context.run_id, req_id)
        if decision.get("decision") == "allow":
            # Keep remembering in AI Hub's run scope. Never apply SDK-suggested
            # broad allow rules, which could bypass a later confirmation.
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message=decision.get("reason") or "用户拒绝了本次工具调用")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Tool permission failed: run_id=%s", run_context.run_id)
        return PermissionResultDeny(message="授权服务暂不可用，工具请求已拒绝")


async def serve_permissions(transport, run_context, prompt_message, finished, *, allowed_mcp_tools=()):
    async def can_use_tool(name, data, context):
        return await request_tool_permission(run_context, name, data, context, allowed_mcp_tools=allowed_mcp_tools)

    client = ClaudeSDKClient(
        options=ClaudeAgentOptions(can_use_tool=can_use_tool), transport=transport,
    )

    async def prompt_stream():
        yield prompt_message

    try:
        await client.connect()
        await client.query(prompt_stream())
        await finished.wait()
    finally:
        await client.disconnect()
