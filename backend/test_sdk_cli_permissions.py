"""Opt-in real Claude CLI integration against a local, deterministic model.

AIHUB_TEST_CLAUDE_BIN=/path/to/claude .venv/bin/python -m pytest -q test_sdk_cli_permissions.py
No model credentials, business database, or external services are used.
"""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import agent_permission
from agent_permission import claim_pending_permission_events, user_decide
from agent_workspace import build_claude_state_json, build_settings_json, build_mcp_json, get_mcp_tool_permissions
from auth import CurrentUser
from runtimes.base import RuntimeConfig, RuntimeRunContext
from runtimes.claude_code import ClaudeCodeRuntime
from sandbox.base import WorkspaceContext
from schemas import PermissionDecideRequest
from test_agent_permission import _factory


pytestmark = pytest.mark.skipif(not os.environ.get("AIHUB_TEST_CLAUDE_BIN"), reason="Set AIHUB_TEST_CLAUDE_BIN for real CLI tests")


def model_handler(tool_name, tool_input):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith("count_tokens"):
                body = b'{"input_tokens":100}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            has_result = any(block.get("type") == "tool_result"
                             for message in data.get("messages", [])
                             for block in message.get("content", []) if isinstance(block, dict))
            content = {"type": "text", "text": ""} if has_result else {"type": "tool_use", "id": "probe-tool", "name": tool_name, "input": {}}
            delta = {"type": "text_delta", "text": "completed"} if has_result else {"type": "input_json_delta", "partial_json": json.dumps(tool_input)}
            events = [
                {"type": "message_start", "message": {"id": "probe-message", "type": "message", "role": "assistant", "model": "claude-sonnet-4-5", "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}},
                {"type": "content_block_start", "index": 0, "content_block": content},
                {"type": "content_block_delta", "index": 0, "delta": delta},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn" if has_result else "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 20}},
                {"type": "message_stop"},
            ]
            body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Handler


@pytest.mark.parametrize("mode,decision", [("default", "allow"), ("default", "deny"), ("acceptEdits", None)])
@pytest.mark.parametrize("tool", ["Write", "Bash", "MCP", "ConfirmedMCP", "OutsideWrite", "BlockedMCP"])
def test_real_cli_permission_rules_and_sdk_decisions(tmp_path, mode, decision, tool):
    marker = tmp_path / "approved.txt"
    mcps = []
    if tool in {"MCP", "ConfirmedMCP", "BlockedMCP"}:
        server_script = tmp_path / "mcp_server.py"
        server_script.write_text(MCP_SERVER)
        mcps = [SimpleNamespace(id=1, name="knowledge", type="stdio", require_confirmation=tool == "ConfirmedMCP",
                                allowed_tools=["read"] if tool == "BlockedMCP" else ["update"],
                                config=json.dumps({"command": sys.executable, "args": [str(server_script)]}))]
        tool_name, tool_input = "mcp__knowledge__update", {"value": "ok"}
        if tool == "ConfirmedMCP" and decision is None:
            decision = "allow"
    elif tool in {"Write", "OutsideWrite"}:
        if tool == "OutsideWrite":
            marker = tmp_path.parent / f"{tmp_path.name}-outside.txt"
        tool_name, tool_input = "Write", {"file_path": str(marker), "content": "ok"}
    else:
        tool_name, tool_input = tool, {"command": "printf ok > approved.txt", "description": "write test marker"}
    server = ThreadingHTTPServer(("127.0.0.1", 0), model_handler(tool_name, tool_input))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    claude_dir = tmp_path / ".claude"
    hooks = claude_dir / "hooks"
    hooks.mkdir(parents=True)
    for name in ("pre_tool_use.py", "post_tool_use.py"):
        shutil.copy2(Path(__file__).parent / "agent_hooks" / name, hooks / name)
    (claude_dir / "settings.json").write_text(json.dumps(build_settings_json(SimpleNamespace(id=1), None, mcps=mcps)))
    (claude_dir / ".claude.json").write_text(json.dumps(build_claude_state_json([str(tmp_path)])))
    if mcps:
        mcp_config, _ = build_mcp_json(mcps)
        (tmp_path / ".mcp.json").write_text(json.dumps(mcp_config))
    mcp_permissions = get_mcp_tool_permissions(mcps)

    async def scenario():
        factory = _factory(tmp_path / "permissions.sqlite")
        events = []
        async def emit(event):
            events.append(event)
        runtime = ClaudeCodeRuntime()
        with patch.object(agent_permission, "SessionLocal", factory):
            task = asyncio.create_task(runtime.run(
                RuntimeConfig(api_key="local-test-only", api_base_url=f"http://127.0.0.1:{server.server_port}",
                              model="claude-sonnet-4-5", timeout_seconds=25,
                              extra={"permission_mode": mode, "mcp_server_names": ["knowledge"] if mcps else [],
                                     "allowed_mcp_tools": mcp_permissions["allow"] + mcp_permissions["ask"]}),
                WorkspaceContext("directory", str(tmp_path), str(tmp_path), [],
                                 claude_bin=os.environ["AIHUB_TEST_CLAUDE_BIN"], run_cwd=str(tmp_path),
                                 env={"AIHUB_AGENT_WORKSPACE": str(tmp_path), "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "ENABLE_TOOL_SEARCH": "false"}),
                "Create approved.txt using the requested tool.", [], emit, RuntimeRunContext("run-1", 2),
            ))
            try:
                pending = []
                for _ in range(1000):
                    pending = await asyncio.to_thread(claim_pending_permission_events, "run-1")
                    if pending or task.done():
                        break
                    await asyncio.sleep(.01)
                if decision and tool not in {"OutsideWrite", "BlockedMCP"}:
                    assert pending, [e.content for e in events]
                    assert not marker.exists()
                    db = factory()
                    try:
                        result = await user_decide(1, PermissionDecideRequest(
                            run_id="run-1", req_id=pending[0]["req_id"], decision=decision,
                        ), db, CurrentUser(7))
                        assert result["ok"]
                    finally:
                        db.close()
                else:
                    assert not pending
                await asyncio.wait_for(task, 15)
                assert not [e.content for e in events if e.type == "error"]
                assert marker.exists() == (decision != "deny" and tool not in {"OutsideWrite", "BlockedMCP"})
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    try:
        asyncio.run(scenario())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


MCP_SERVER = r'''
import json, pathlib, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion': request['params']['protocolVersion'], 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'local-probe', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'update', 'description': 'write test marker', 'inputSchema': {'type': 'object', 'properties': {'value': {'type': 'string'}}}}]}
    elif method == 'tools/call':
        pathlib.Path('approved.txt').write_text('ok')
        result = {'content': [{'type': 'text', 'text': 'updated'}]}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
'''
