import asyncio
import base64
import json
import os
from unittest.mock import patch

import runtimes.claude_code as claude_code_module
from runtimes.base import RuntimeConfig
from runtimes.claude_code import (
    ClaudeCodeRuntime,
    _StreamTranslator,
    _build_prompt_with_history,
    _build_runtime_env,
    _encode_tunneled_env,
)
from sandbox.base import WorkspaceContext


def test_assistant_api_error_snapshot_preserves_upstream_detail():
    events = _StreamTranslator().translate({
        'type': 'assistant', 'isApiErrorMessage': True, 'error': 'server_error',
        'message': {'content': [{'type': 'text', 'text': 'API Error: 503 provider overloaded; request_id=req-cli'}]},
    })
    assert len(events) == 1
    assert events[0].type == 'error'
    assert events[0].metadata['error_origin'] == 'upstream'
    assert events[0].content == 'API Error: 503 provider overloaded; request_id=req-cli'


def test_user_tool_result_accepts_string_tool_use_result() -> None:
    raw = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": "fallback content",
                    "is_error": True,
                    "tool_use_id": "call_0",
                }
            ],
        },
        "tool_use_result": "This command requires approval",
    }

    events = _StreamTranslator().translate(raw)

    assert len(events) == 1
    assert events[0].type == "tool_result"
    assert events[0].tool_use_id == "call_0"
    assert events[0].content == "This command requires approval"
    assert events[0].is_error is True


def test_user_tool_result_accepts_mixed_content_list() -> None:
    raw = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": [
                        {"type": "text", "text": "line 1"},
                        "line 2",
                    ],
                    "tool_use_id": "call_1",
                }
            ],
        },
    }

    events = _StreamTranslator().translate(raw)

    assert len(events) == 1
    assert events[0].type == "tool_result"
    assert events[0].tool_use_id == "call_1"
    assert events[0].content == "line 1\nline 2"


def test_jsonl_reader_handles_long_records_and_recovers_after_oversize() -> None:
    class ChunkStream:
        def __init__(self, content, chunk_size=17):
            self.content = content
            self.chunk_size = chunk_size

        async def read(self, _limit):
            if not self.content:
                return b""
            chunk = self.content[:self.chunk_size]
            self.content = self.content[self.chunk_size:]
            return chunk

    async def scenario():
        long_record = b'{"type":"result","result":"' + (b"x" * 100_000) + b'"}\n'
        reader = asyncio.StreamReader(limit=64 * 1024)
        reader.feed_data(long_record)
        reader.feed_eof()
        records = []
        async for record in claude_code_module._iter_jsonl_records(reader):
            records.append(record)
        assert len(records) == 1
        assert len(records[0]) > 64 * 1024

        content = (b"x" * 65) + b'\n{"type":"result","result":"ok"}\n'
        original_max = claude_code_module.JSONL_MAX_RECORD_BYTES
        claude_code_module.JSONL_MAX_RECORD_BYTES = 64
        try:
            recovered = []
            async for record in claude_code_module._iter_jsonl_records(ChunkStream(content)):
                recovered.append(record)
        finally:
            claude_code_module.JSONL_MAX_RECORD_BYTES = original_max
        assert recovered[0] is None
        assert recovered[1] == b'{"type":"result","result":"ok"}'

    asyncio.run(scenario())


# Managed image input/resume coverage uses the real SDK handshake in
# test_sdk_permissions.py; these unit tests retain the bare diagnostic path.
def test_runtime_sends_multiline_prompt_via_stdin() -> None:
    prompt = "[微信语音转写]\n看一下我的代办; echo should-not-run"
    captured = {}

    class FakeStdin:
        def __init__(self):
            self.data = bytearray()
            self.closed = False

        def write(self, data):
            self.data.extend(data)

        async def drain(self):
            return None

        def close(self):
            self.closed = True

        async def wait_closed(self):
            return None

    class EmptyAsyncStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeProcess:
        pid = None

        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = EmptyAsyncStream()
            self.stderr = EmptyAsyncStream()
            self.returncode = 0

        async def wait(self):
            return self.returncode

    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return process

    async def scenario():
        emitted = []

        async def on_event(event):
            emitted.append(event)

        runtime = ClaudeCodeRuntime()
        await runtime.run(
            config=RuntimeConfig(
                api_key="test-key",
                timeout_seconds=5,
                extra={"thinking_level": "high"},
            ),
            ctx=WorkspaceContext(
                sandbox_type="native",
                workspace_root="/tmp/agent",
                host_workspace_path="",
                argv_prefix=["sudo", "--"],
                env={"AIHUB_AGENT_WORKSPACE": "/tmp/agent"},
                tunnel_env_via_stdin=True,
                is_isolated=True,
            ),
            user_input=prompt,
            history=[],
            on_event=on_event,
        )
        assert emitted[-1].type == "done"

    original_create_subprocess_exec = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = fake_create_subprocess_exec
    try:
        asyncio.run(scenario())
    finally:
        asyncio.create_subprocess_exec = original_create_subprocess_exec

    assert prompt not in captured["args"]
    assert captured["kwargs"]["stdin"] == asyncio.subprocess.PIPE
    assert "--input-format" in captured["args"]
    assert captured["args"][captured["args"].index("--effort") + 1] == "high"
    header, sent_prompt = bytes(process.stdin.data).split(b"\n", 1)
    tunneled_env = json.loads(base64.b64decode(header).decode("utf-8"))
    assert tunneled_env["AIHUB_AGENT_WORKSPACE"] == "/tmp/agent"
    assert tunneled_env["ANTHROPIC_API_KEY"] == "test-key"
    assert captured["args"][captured["args"].index("--input-format") + 1] == "text"
    assert sent_prompt.decode("utf-8") == prompt
    assert process.stdin.closed is True


def test_environment_tunnel_is_opt_in_and_uses_an_allowlist() -> None:
    env = {
        "ANTHROPIC_API_KEY": "secret",
        "HTTPS_PROXY": "http://proxy.example",
        "UNRELATED_SECRET": "do-not-forward",
    }
    plain_ctx = WorkspaceContext("directory", "/tmp/a", "/tmp/a", [])
    assert _encode_tunneled_env(plain_ctx, env) == b""

    native_ctx = WorkspaceContext(
        "native",
        "/tmp/a",
        "",
        [],
        env={"HOME": "/tmp/a"},
        tunnel_env_via_stdin=True,
    )
    header = _encode_tunneled_env(native_ctx, env).rstrip(b"\n")
    forwarded = json.loads(base64.b64decode(header).decode("utf-8"))
    assert forwarded == {
        "ANTHROPIC_API_KEY": "secret",
        "HTTPS_PROXY": "http://proxy.example",
    }


def test_runtime_environment_does_not_inherit_backend_secrets() -> None:
    ctx = WorkspaceContext(
        "directory",
        "/tmp/agent",
        "/tmp/agent",
        [],
        env={"AIHUB_AGENT_WORKSPACE": "/tmp/agent"},
    )
    config = RuntimeConfig(
        api_key="model-secret",
        api_base_url="https://models.example.test",
    )
    with patch.dict(os.environ, {
        "PATH": "/usr/bin",
        "DATABASE_URL": "mysql://platform-secret",
        "AGENT_CREDENTIAL_ENCRYPTION_KEY": "platform-encryption-secret",
        "CHANNEL_TOKEN": "channel-secret",
    }, clear=False):
        env = _build_runtime_env(config, ctx)

    assert env["PATH"] == "/tmp/agent/.venv/bin:/usr/bin"
    assert env["VIRTUAL_ENV"] == "/tmp/agent/.venv"
    assert env["PIP_REQUIRE_VIRTUALENV"] == "true"
    assert env["HOME"] == "/tmp/agent"
    assert env["USERPROFILE"] == "/tmp/agent"
    assert env["ANTHROPIC_API_KEY"] == "model-secret"
    assert env["ANTHROPIC_BASE_URL"] == "https://models.example.test"
    assert env["AIHUB_AGENT_WORKSPACE"] == "/tmp/agent"
    assert "DATABASE_URL" not in env
    assert "AGENT_CREDENTIAL_ENCRYPTION_KEY" not in env
    assert "CHANNEL_TOKEN" not in env


def test_threaded_runtime_sends_multiline_prompt_via_stdin() -> None:
    prompt = "第一行\n第二行 && echo should-not-run"
    captured = {}

    class FakeTextStdin:
        def __init__(self):
            self.data = ""
            self.closed = False

        def write(self, data):
            self.data += data

        def flush(self):
            return None

        def close(self):
            self.closed = True

    class FakeProcess:
        pid = None

        def __init__(self):
            self.stdin = FakeTextStdin()
            self.stdout = []
            self.stderr = None
            self.returncode = 0

        def wait(self):
            return self.returncode

    process = FakeProcess()

    async def unsupported_async_subprocess(*args, **kwargs):
        raise NotImplementedError

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return process

    async def scenario():
        async def on_event(_event):
            return None

        await ClaudeCodeRuntime().run(
            config=RuntimeConfig(api_key="test-key", timeout_seconds=5),
            ctx=WorkspaceContext(
                sandbox_type="native",
                workspace_root="/tmp/agent",
                host_workspace_path="",
                argv_prefix=["sudo", "--"],
                is_isolated=True,
            ),
            user_input=prompt,
            history=[],
            on_event=on_event,
        )

    original_create_subprocess_exec = asyncio.create_subprocess_exec
    original_popen = claude_code_module.subprocess.Popen
    asyncio.create_subprocess_exec = unsupported_async_subprocess
    claude_code_module.subprocess.Popen = fake_popen
    try:
        asyncio.run(scenario())
    finally:
        claude_code_module.subprocess.Popen = original_popen
        asyncio.create_subprocess_exec = original_create_subprocess_exec

    assert prompt not in captured["cmd"]
    assert captured["kwargs"]["stdin"] == claude_code_module.subprocess.PIPE
    assert process.stdin.data == prompt
    assert process.stdin.closed is True


def test_resume_fallback_sends_rebuilt_history_prompt_via_stdin() -> None:
    prompt = "本轮语音\n查看我的待办"
    captured_args = []

    class FakeStdin:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data)

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    class AsyncStream:
        def __init__(self, *lines):
            self.lines = iter(lines)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.lines)
            except StopIteration:
                raise StopAsyncIteration

    class FakeStderr:
        def __init__(self, data):
            self.data = data

        async def read(self, limit=-1):
            data, self.data = self.data, b""
            return data

    class FakeProcess:
        pid = None

        def __init__(self, returncode, stderr, *stdout_lines):
            self.stdin = FakeStdin()
            self.stdout = AsyncStream(*stdout_lines)
            self.stderr = FakeStderr(stderr)
            self.returncode = returncode

        async def wait(self):
            return self.returncode

    processes = [
        FakeProcess(
            1,
            b"No conversation found",
            json.dumps({
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "errors": ["No conversation found with session ID: missing-session"],
            }).encode("utf-8") + b"\n",
        ),
        FakeProcess(0, b""),
    ]

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_args.append(args)
        return processes[len(captured_args) - 1]

    events = []

    async def scenario():
        async def on_event(event):
            events.append(event)

        await ClaudeCodeRuntime().run(
            config=RuntimeConfig(
                api_key="test-key",
                timeout_seconds=5,
                extra={"resume_id": "missing-session"},
            ),
            ctx=WorkspaceContext(
                sandbox_type="native",
                workspace_root="/tmp/agent",
                host_workspace_path="",
                argv_prefix=["sudo", "--"],
                is_isolated=True,
            ),
            user_input=prompt,
            history=[
                {"role": "user", "content": "之前的问题"},
                {"role": "assistant", "content": "之前的答复"},
            ],
            on_event=on_event,
        )

    original_create_subprocess_exec = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = fake_create_subprocess_exec
    try:
        asyncio.run(scenario())
    finally:
        asyncio.create_subprocess_exec = original_create_subprocess_exec

    assert len(captured_args) == 2
    assert "--resume" in captured_args[0]
    assert "--resume" not in captured_args[1]
    first_prompt = bytes(processes[0].stdin.data).decode("utf-8")
    assert first_prompt == prompt
    fallback_prompt = bytes(processes[1].stdin.data).decode("utf-8")
    assert "之前的问题" in fallback_prompt
    assert "之前的答复" in fallback_prompt
    assert fallback_prompt.endswith(prompt)
    assert not [event for event in events if event.type == "error"]


def test_history_fallback_preserves_previous_unanswered_user_message() -> None:
    prompt = _build_prompt_with_history(
        "继续处理",
        [{"role": "user", "content": "上一轮失败但仍需保留的问题"}],
    )
    assert "上一轮失败但仍需保留的问题" in prompt
    assert prompt.endswith("继续处理")


def test_history_fallback_keeps_compaction_summary_when_recent_history_is_large() -> None:
    prompt = _build_prompt_with_history(
        "继续处理",
        [
            {"role": "system", "content": "[较早对话摘要] 最初目标是完成库存分析"},
            {"role": "user", "content": "old-message " + ("x" * 80_000)},
            {"role": "assistant", "content": "最近确认的结论"},
        ],
    )

    assert "最初目标是完成库存分析" in prompt
    assert "最近确认的结论" in prompt
    assert "另有 1 条较早对话未直接载入" in prompt
    assert prompt.endswith("继续处理")


if __name__ == "__main__":
    test_images_reach_async_threaded_and_resume_fallback_input()
    test_user_tool_result_accepts_string_tool_use_result()
    test_user_tool_result_accepts_mixed_content_list()
    test_jsonl_reader_handles_long_records_and_recovers_after_oversize()
    test_runtime_sends_multiline_prompt_via_stdin()
    test_environment_tunnel_is_opt_in_and_uses_an_allowlist()
    test_runtime_environment_does_not_inherit_backend_secrets()
    test_threaded_runtime_sends_multiline_prompt_via_stdin()
    test_resume_fallback_sends_rebuilt_history_prompt_via_stdin()
    test_history_fallback_preserves_previous_unanswered_user_message()
    test_history_fallback_keeps_compaction_summary_when_recent_history_is_large()
