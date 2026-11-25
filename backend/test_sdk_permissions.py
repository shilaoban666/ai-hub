"""Real SDK + sandbox pipes + SQLite decisions; no external model or business DB."""

import asyncio
from contextlib import nullcontext
import json
import sys
from unittest.mock import patch

import pytest

import agent_permission
from agent_permission import claim_pending_permission_events, user_decide
from auth import CurrentUser
from models import AgentRun
from runtimes.base import RuntimeConfig, RuntimeRunContext
from runtimes.base import RuntimeAttachment
from runtimes.claude_code import ClaudeCodeRuntime
from runtimes.sdk_permissions import request_tool_permission
from sandbox.base import WorkspaceContext
from schemas import PermissionDecideRequest
from test_agent_permission import _factory


# Behaves like the CLI on the wire, including SDK initialize and bidirectional
# can_use_tool. The marker represents a side effect after the allow response.
CLI = r'''
import json, pathlib, sys, time
def send(data):
    print(json.dumps(data), flush=True)
initialize = json.loads(sys.stdin.readline())
assert initialize['request']['subtype'] == 'initialize', initialize
send({'type': 'control_response', 'response': {
    'subtype': 'success', 'request_id': initialize['request_id'], 'response': {}}})
prompt = json.loads(sys.stdin.readline())
assert prompt['type'] == 'user'
assert '--permission-prompt-tool' in sys.argv
send({'type': 'control_request', 'request_id': 'cli-approval', 'request': {
    'subtype': 'can_use_tool', 'tool_name': 'Write',
    'tool_use_id': 'tool-1', 'input': {'file_path': 'approved.txt', 'content': 'ok'}}})
decision = json.loads(sys.stdin.readline())
assert decision['response']['request_id'] == 'cli-approval', decision
behavior = decision['response']['response']['behavior']
if behavior == 'allow':
    pathlib.Path('approved.txt').write_text('ok')
send({'type': 'result', 'subtype': 'success', 'result': behavior})
sys.stdin.read()
'''


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize("decision", ["allow", "deny"])
@pytest.mark.parametrize("tunnel", [False, True])
def test_sdk_waits_for_owner_and_only_executes_after_allow(tmp_path, threaded, decision, tunnel):
    async def scenario():
        factory = _factory(tmp_path / "permissions.sqlite")
        runtime = ClaudeCodeRuntime()
        source = ("import base64,json,sys; assert json.loads(base64.b64decode(sys.stdin.readline()))['AIHUB_AGENT_WORKSPACE']\n" if tunnel else "") + CLI
        ctx = WorkspaceContext("directory", str(tmp_path), str(tmp_path),
                               [sys.executable, "-c", source], claude_bin="unused", run_cwd=str(tmp_path),
                               env={"AIHUB_AGENT_WORKSPACE": str(tmp_path)}, tunnel_env_via_stdin=tunnel)
        events = []
        async def emit(event):
            events.append(event)
        fallback = patch("runtimes.claude_code.asyncio.create_subprocess_exec", side_effect=NotImplementedError) if threaded else nullcontext()
        with patch.object(agent_permission, "SessionLocal", factory), fallback:
            task = asyncio.create_task(runtime.run(
                RuntimeConfig(timeout_seconds=10, extra={"permission_mode": "default", "mcp_server_names": ["knowledge"]}),
                ctx, "create file", [], emit, RuntimeRunContext("run-1", 2),
            ))
            try:
                pending = []
                for _ in range(300):
                    if task.done():
                        await task
                        pytest.fail("runtime completed without waiting for a decision")
                    pending = await asyncio.to_thread(claim_pending_permission_events, "run-1")
                    if pending:
                        break
                    await asyncio.sleep(.01)
                assert len(pending) == 1
                assert not task.done()
                assert not (tmp_path / "approved.txt").exists()
                db = factory()
                try:
                    result = await user_decide(1, PermissionDecideRequest(
                        run_id="run-1", req_id=pending[0]["req_id"], decision=decision,
                    ), db, CurrentUser(7))
                finally:
                    db.close()
                assert result["ok"]
                await asyncio.wait_for(task, 5)
                assert not [e.content for e in events if e.type == "error"]
                assert (tmp_path / "approved.txt").exists() == (decision == "allow")
                assert any(e.type == "done" and e.content == decision for e in events)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize("action", ["cancel", "timeout"])
def test_waiting_sdk_permission_is_cancelled_and_reaped(tmp_path, threaded, action):
    async def scenario():
        factory = _factory(tmp_path / "permissions.sqlite")
        runtime = ClaudeCodeRuntime()
        events = []
        async def emit(event):
            events.append(event)
        ctx = WorkspaceContext("directory", str(tmp_path), str(tmp_path),
                               [sys.executable, "-c", CLI], claude_bin="unused", run_cwd=str(tmp_path))
        fallback = patch("runtimes.claude_code.asyncio.create_subprocess_exec", side_effect=NotImplementedError) if threaded else nullcontext()
        with patch.object(agent_permission, "SessionLocal", factory), fallback:
            task = asyncio.create_task(runtime.run(
                RuntimeConfig(timeout_seconds=1 if action == "timeout" else 5),
                ctx, "create file", [], emit, RuntimeRunContext("run-1", 2),
            ))
            try:
                for _ in range(100):
                    if await asyncio.to_thread(claim_pending_permission_events, "run-1"):
                        break
                    await asyncio.sleep(.01)
                else:
                    pytest.fail("no SDK permission request")
                if action == "cancel":
                    task.cancel()
                    await asyncio.sleep(0)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 3)
                else:
                    await asyncio.wait_for(task, 3)
                    assert any(e.type == "error" and "超时" in e.content for e in events)
                assert not (tmp_path / "approved.txt").exists()
                assert runtime._proc.returncode is not None
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("threaded", [False, True])
def test_sdk_startup_failure_keeps_stderr_without_waiting_for_initialize(tmp_path, threaded):
    async def scenario():
        events = []
        async def emit(event):
            events.append(event)
        ctx = WorkspaceContext("directory", str(tmp_path), str(tmp_path),
                               [sys.executable, "-c", "import sys; sys.stderr.write('CLI startup failed'); sys.exit(7)"],
                               claude_bin="unused", run_cwd=str(tmp_path))
        fallback = patch("runtimes.claude_code.asyncio.create_subprocess_exec", side_effect=NotImplementedError) if threaded else nullcontext()
        with fallback:
            await asyncio.wait_for(ClaudeCodeRuntime().run(
                RuntimeConfig(timeout_seconds=10), ctx, "test", [], emit, RuntimeRunContext("run-1", 2),
            ), 2)
        assert any(e.type == "error" and "CLI startup failed" in e.content for e in events)
        assert not any("超时" in e.content for e in events)
    asyncio.run(scenario())


def test_sdk_callback_denies_for_channels_without_creating_requests():
    async def scenario():
        with patch.object(agent_permission, "permission_request") as create:
            result = await request_tool_permission(RuntimeRunContext("run-1", 2, source="dingtalk"), "Write", {}, None)
            assert result.behavior == "deny"
            create.assert_not_called()
    asyncio.run(scenario())


def test_sdk_callback_denies_on_service_failure():
    async def scenario():
        with patch.object(agent_permission, "permission_request", side_effect=RuntimeError("unavailable")):
            result = await request_tool_permission(RuntimeRunContext("run-1", 2), "Bash", {"command": "ls"}, None)
            assert result.behavior == "deny"
    asyncio.run(scenario())


@pytest.mark.parametrize("rules,allowed", [([], False), (["mcp__other__*"], False),
                                        (["mcp__knowledge__read"], False), (["mcp__knowledge__update"], True)])
def test_sdk_callback_enforces_bound_mcp_tool_policy(rules, allowed):
    async def scenario():
        with patch.object(agent_permission, "permission_request", return_value={"ok": True}) as create, \
             patch.object(agent_permission, "permission_decide", return_value={"decision": "allow"}):
            result = await request_tool_permission(RuntimeRunContext("run-1", 2), "mcp__knowledge__update", {}, None,
                                                   allowed_mcp_tools=rules)
            assert result.behavior == ("allow" if allowed else "deny")
            assert create.called == allowed
    asyncio.run(scenario())


def test_sdk_callback_timeout_and_cancelled_run_deny(tmp_path):
    async def scenario():
        factory = _factory(tmp_path / "permissions.sqlite")
        with patch.object(agent_permission, "SessionLocal", factory), patch.object(agent_permission, "PERMISSION_TIMEOUT_SECONDS", 0):
            result = await request_tool_permission(RuntimeRunContext("run-1", 2), "Write", {}, None)
            assert result.behavior == "deny"
        db = factory()
        db.query(AgentRun).filter_by(id="run-1").one().cancel_requested = True
        db.commit()
        db.close()
        with patch.object(agent_permission, "SessionLocal", factory):
            result = await request_tool_permission(RuntimeRunContext("run-1", 2), "Write", {}, None)
            assert result.behavior == "deny"
    asyncio.run(scenario())


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize("resume", [False, True])
def test_images_and_resume_fallback_with_real_sdk(tmp_path, threaded, resume):
    async def scenario():
        ctx = WorkspaceContext("directory", str(tmp_path), str(tmp_path),
                               [sys.executable, "-c", IMAGE_CLI], claude_bin="unused", run_cwd=str(tmp_path))
        events = []
        async def emit(event):
            events.append(event)
        fallback = patch("runtimes.claude_code.asyncio.create_subprocess_exec", side_effect=NotImplementedError) if threaded else nullcontext()
        with fallback:
            await ClaudeCodeRuntime().run(
                RuntimeConfig(timeout_seconds=5, extra={"resume_id": "missing"} if resume else {}),
                ctx, "多行\n问题", [{"role": "user", "content": "历史问题"}], emit,
                RuntimeRunContext("run-1", 2, attached_files=(RuntimeAttachment(
                    "screen.png", media_type="image/png", image_data=b"test-image",
                ),)),
            )
        assert not [e.content for e in events if e.type == "error"]
        message = json.loads((tmp_path / "prompt.json").read_text())
        blocks = message["message"]["content"]
        assert blocks[0]["source"]["data"] == "dGVzdC1pbWFnZQ=="
        assert "多行\n问题" in blocks[1]["text"]
        assert "历史问题" in blocks[1]["text"]
        assert any(e.type == "info" and "回退" in e.content for e in events) == resume
    asyncio.run(scenario())


IMAGE_CLI = r'''
import json, pathlib, sys
initialize = json.loads(sys.stdin.readline())
print(json.dumps({'type': 'control_response', 'response': {
    'subtype': 'success', 'request_id': initialize['request_id'], 'response': {}}}), flush=True)
prompt = sys.stdin.readline()
if '--resume' in sys.argv:
    print(json.dumps({'type': 'result', 'subtype': 'error_during_execution', 'result': 'No conversation found'}), flush=True)
    sys.stdin.read()
    sys.stderr.write('No conversation found')
    sys.exit(1)
pathlib.Path('prompt.json').write_text(prompt)
print(json.dumps({'type': 'result', 'subtype': 'success', 'result': 'ok'}), flush=True)
sys.stdin.read()
'''
