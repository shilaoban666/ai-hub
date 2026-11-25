import asyncio
import json
import threading
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import agent_service
from agent_memory import AgentMemory as PersistedAgentMemory
from models import Agent, AgentMessage, AgentRun, AgentSession, AIModel, PlatformAgentSettings
from runtimes.base import RuntimeEvent


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self.value

    def order_by(self, *_args):
        return self

    def all(self):
        return [self.value] if self.value is not None else []

    def one(self):
        assert self.value is not None
        return self.value

    def populate_existing(self):
        return self

    def with_for_update(self):
        return self


class _DB:
    @property
    def no_autoflush(self):
        return nullcontext()

    def __init__(self, session, model):
        self.session = session
        self.model = model
        self.run = None
        self.commits = 0

    def query(self, model_type):
        if model_type is PlatformAgentSettings:
            return _Query(None)
        if model_type is AgentSession:
            return _Query(self.session)
        if model_type is AIModel:
            return _Query(self.model)
        if model_type is AgentRun:
            return _Query(self.run)
        raise AssertionError(f"unexpected query: {model_type}")

    def add(self, value):
        if isinstance(value, AgentRun):
            self.run = value
            return
        raise AssertionError(f"unexpected add: {value}")

    def commit(self):
        self.commits += 1


class _Memory:
    order = []
    saved_blocks = None
    saved_duration_ms = None

    def __init__(self, db, session_id):
        self.session = db.session

    def load_history(self):
        self.order.append("load_history")
        return [{"role": "user", "content": "previous"}]

    def save_user_message(self, content):
        self.order.append("save_user")
        self.session.message_count = 1
        return SimpleNamespace(id=101)

    def get_runtime_session_id(self):
        return None

    def save_assistant_message(self, blocks, usage=None, duration_ms=None):
        type(self).saved_blocks = blocks
        type(self).saved_duration_ms = duration_ms
        return SimpleNamespace(id=102)

    def set_runtime_session_id(self, session_id):
        pass


class _Sandbox:
    is_isolated = True

    def prepare(self, agent, model, filter_skills=None):
        return SimpleNamespace()

    def cleanup(self, ctx):
        pass

    def discard_execution(self, ctx):
        pass

    def prepare_execution(self, agent, model, *, run_id, workspace, filter_skills=None):
        return SimpleNamespace(
            sandbox_type="native",
            host_workspace_path="/tmp/workspace",
            execution_view_path="/tmp/workspace",
            handle={},
        )


class _FailingDirectorySandbox:
    is_isolated = False

    def prepare(self, agent, model, filter_skills=None):
        raise RuntimeError("workspace unavailable")

    def prepare_execution(self, agent, model, *, run_id, workspace, filter_skills=None):
        return self.prepare(agent, model, filter_skills=filter_skills)

    def cleanup(self, ctx):
        raise AssertionError("cleanup must not run without a workspace context")


class _Runtime:
    def __init__(self, include_permission=False, thinking=""):
        self.include_permission = include_permission
        self.thinking = thinking

    async def run(self, config, ctx, user_input, history, on_event, run_context=None):
        assert history == [{"role": "user", "content": "previous"}]
        assert run_context is not None
        assert run_context.include_history is True
        if self.include_permission:
            await on_event(RuntimeEvent(
                type="permission_request",
                tool_name="Bash",
                tool_input={"command": "echo test"},
            ))
        if self.thinking:
            await on_event(RuntimeEvent(type="thinking", content=self.thinking[:4]))
            await on_event(RuntimeEvent(type="thinking", content=self.thinking[4:]))
        await on_event(RuntimeEvent(type="text", content="result"))
        await on_event(RuntimeEvent(
            type="usage",
            usage={"input_tokens": 1, "output_tokens": 2},
        ))
        await on_event(RuntimeEvent(type="done", content=""))

    async def cancel(self):
        pass


class _CancelledRuntime(_Runtime):
    async def run(self, config, ctx, user_input, history, on_event, run_context=None):
        raise asyncio.CancelledError


class _PartialCancelledRuntime(_Runtime):
    async def run(self, config, ctx, user_input, history, on_event, run_context=None):
        await on_event(RuntimeEvent(type="text", content="partial result"))
        raise asyncio.CancelledError


def _agent():
    return SimpleNamespace(
        id=1,
        user_id=7,
        default_model_id=1,
        runtime_type="claude_code",
        thinking_level="inherit",
        reasoning_visibility="off",
        max_turns=10,
        timeout_seconds=60,
        skills=[],
        mcps=[],
        models=[SimpleNamespace(id=1), SimpleNamespace(id=2)],
    )


def _model():
    return SimpleNamespace(
        id=1,
        user_id=7,
        is_deleted=False,
        api_key="test-key",
        api_proxy_url=None,
        api_protocol="anthropic-messages",
        name="test-model",
        provider="test-provider",
        remarks="test-account",
    )


def _session():
    return SimpleNamespace(
        id=11,
        agent_id=1,
        user_id=7,
        is_deleted=False,
        workspace_id=5,
        model_id=1,
        config_version=None,
        runtime_type="claude_code",
        runtime_session_id=None,
        runtime_instance_id=None,
        source="web",
        source_binding_id=None,
        message_count=0,
        title="",
    )


@contextmanager
def _execution_dependencies():
    runtime_assets = {
        "skills": [],
        "mcps": [],
        "secret_env": {},
        "effective_capabilities": [],
        "requires_confirmation": False,
        "skill_snapshot": [],
        "mcp_snapshot": [],
    }
    with (
        patch.object(
            agent_service,
            "bind_agent_workspace",
            return_value=(SimpleNamespace(id=5), SimpleNamespace(desired_config_hash="hash")),
        ),
        patch.object(agent_service, "record_run_view"),
        patch.object(agent_service, "finish_run_view"),
        patch.object(agent_service, "load_runtime_assets", return_value=runtime_assets),
        patch.object(agent_service, "load_global_runtime_environment", return_value={}),
        patch.object(
            agent_service,
            "generate_session_title",
            new=AsyncMock(return_value="Current request"),
        ),
    ):
        yield


def test_execute_agent_turn_loads_history_before_current_message():
    _Memory.order = []
    _Memory.saved_blocks = None
    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(agent_service, "get_runtime", return_value=_Runtime()),
    ):
        db = _DB(_session(), _model())
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=_agent(),
            user_input="current",
            session_id=11,
            user_id=7,
            db=db,
            interactive_permissions=False,
        ))

    assert _Memory.order == ["load_history", "save_user"]
    assert result.status == "succeeded"
    assert result.final_text == "result"
    assert result.usage == {"input_tokens": 1, "output_tokens": 2}
    assert result.user_message_id == 101
    assert result.assistant_message_id == 102
    assert db.session.title == "Current request"
    assert result.duration_ms is not None
    assert result.duration_ms >= 0
    assert _Memory.saved_duration_ms == result.duration_ms
    assert _Memory.saved_blocks[0] == {"type": "text", "content": "result"}
    assert db.run.status == "succeeded"
    assert db.run.finished_at is not None
    assert db.run.duration_ms == result.duration_ms
    assert db.run.input_tokens == 1
    assert db.run.output_tokens == 2
    assert db.run.total_tokens == 3
    assert json.loads(db.run.usage_detail) == result.usage


def test_workbench_executes_unbound_custom_model_with_saved_credentials(kind="personal_default"):
    agent = _agent()
    agent.kind = kind
    agent.models = []
    model = _model()
    model.scope = "user"
    model.is_enabled = True
    model.api_proxy_url = "https://custom.example/v1"
    runtime = _Runtime()
    runtime.run = AsyncMock(wraps=runtime.run)
    db = _DB(_session(), model)
    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(agent_service, "get_runtime", return_value=runtime),
        patch.object(agent_service, "prepare_platform_run") as platform_billing,
    ):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=agent, user_input="current", session_id=11, user_id=7, db=db,
        ))
    assert result.status == "succeeded"
    config = runtime.run.call_args.kwargs["config"]
    assert config.model == model.name
    assert config.api_key == model.api_key
    assert config.api_base_url == model.api_proxy_url
    platform_billing.assert_not_called()


def test_expert_executes_unbound_custom_model_with_saved_credentials():
    test_workbench_executes_unbound_custom_model_with_saved_credentials("expert")


def test_execution_rejects_foreign_or_disabled_models():
    for kind, owner, enabled in [
        ("personal_default", 8, True),
        ("personal_default", 7, False),
        ("expert", 8, True),
        ("expert", 7, False),
    ]:
        agent = _agent()
        agent.kind = kind
        agent.models = []
        model = _model()
        model.scope = "user"
        model.user_id = owner
        model.is_enabled = enabled
        db = _DB(_session(), model)
        with (
            _execution_dependencies(),
            patch.object(agent_service, "get_runtime") as runtime,
            patch.object(agent_service, "AgentMemory") as memory,
        ):
            result = asyncio.run(agent_service.execute_agent_turn(
                agent=agent, user_input="current", session_id=11, user_id=7, db=db,
            ))
        assert result.status == "failed"
        runtime.assert_not_called()
        memory.assert_not_called()


def test_merge_usage_accumulates_complete_turn():
    usage = agent_service._merge_usage(None, {
        "input_tokens": 10,
        "output_tokens": 3,
        "cache_read_input_tokens": 5,
    })
    usage = agent_service._merge_usage(usage, {
        "input_tokens": 2,
        "output_tokens": 4,
        "cache_read_input_tokens": 7,
    })

    assert usage == {
        "input_tokens": 12,
        "output_tokens": 7,
        "cache_read_input_tokens": 12,
    }


def test_usage_metrics_normalizes_openai_aliases_and_preserves_reported_total():
    metrics = agent_service._usage_metrics({
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "cache_read_tokens": 3,
        "total_tokens": 14,
    })

    assert metrics["input_tokens"] == 10
    assert metrics["output_tokens"] == 4
    assert metrics["cache_read_tokens"] == 3
    assert metrics["total_tokens"] == 14


def test_block_timing_tracks_thinking_and_tool_duration():
    blocks = []
    timing = agent_service._BlockTimingState()

    agent_service._append_event_block(
        blocks,
        RuntimeEvent(type="thinking", content="first"),
        timing=timing,
        now=10.0,
    )
    agent_service._append_event_block(
        blocks,
        RuntimeEvent(type="thinking", content=" second"),
        timing=timing,
        now=10.4,
    )
    agent_service._append_event_block(
        blocks,
        RuntimeEvent(
            type="tool_use",
            tool_name="Read",
            tool_input={"path": "a.txt"},
            tool_use_id="call-1",
        ),
        timing=timing,
        now=11.25,
    )
    agent_service._append_event_block(
        blocks,
        RuntimeEvent(type="tool_result", tool_use_id="call-1", content="ok"),
        timing=timing,
        now=13.5,
    )

    assert blocks[0] == {
        "type": "thinking",
        "content": "first second",
        "duration_ms": 1250,
    }
    assert blocks[1]["type"] == "tool_use"
    assert blocks[1]["duration_ms"] == 2250


def test_block_timing_finishes_tool_without_result_at_run_end():
    blocks = []
    timing = agent_service._BlockTimingState()
    agent_service._append_event_block(
        blocks,
        RuntimeEvent(type="tool_use", tool_name="Bash", tool_use_id="call-2"),
        timing=timing,
        now=20.0,
    )

    timing.finish_all(blocks, now=21.5)

    assert blocks[0]["duration_ms"] == 1500


def test_block_timing_skips_clock_reads_for_plain_text_deltas():
    blocks = []
    timing = agent_service._BlockTimingState()

    with patch("agent_service.time.monotonic") as monotonic:
        agent_service._append_event_block(
            blocks,
            RuntimeEvent(type="text", content="first"),
            timing=timing,
        )
        agent_service._append_event_block(
            blocks,
            RuntimeEvent(type="text", content=" second"),
            timing=timing,
        )

    monotonic.assert_not_called()
    assert blocks == [{"type": "text", "content": "first second"}]


def test_assistant_message_compaction_preserves_block_duration():
    memory = object.__new__(PersistedAgentMemory)

    compacted = memory._compact_blocks([
        {"type": "thinking", "content": "reason", "duration_ms": 1250},
        {
            "type": "tool_use",
            "name": "Read",
            "input": {"path": "a.txt"},
            "tool_use_id": "call-1",
            "duration_ms": 2250,
        },
    ])

    assert [block["duration_ms"] for block in compacted] == [1250, 2250]


def test_reasoning_visibility_buffers_web_reasoning_until_complete():
    agent = _agent()
    agent.reasoning_visibility = "on"
    emitted = []

    async def on_event(event):
        emitted.append(event)

    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(agent_service, "get_runtime", return_value=_Runtime(thinking="reasoning")),
    ):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=agent,
            user_input="current",
            session_id=11,
            user_id=7,
            db=_DB(_session(), _model()),
            on_event=on_event,
            interactive_permissions=False,
        ))

    reasoning_events = [event for event in emitted if event.type == "thinking"]
    assert [event.content for event in reasoning_events] == ["reasoning"]
    assert [block["type"] for block in result.blocks[:2]] == ["thinking", "text"]


def test_external_channel_never_emits_or_persists_reasoning():
    agent = _agent()
    agent.reasoning_visibility = "stream"
    emitted = []

    async def on_event(event):
        emitted.append(event)

    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(agent_service, "get_runtime", return_value=_Runtime(thinking="private")),
    ):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=agent,
            user_input="current",
            session_id=11,
            user_id=7,
            db=_DB(_session(), _model()),
            on_event=on_event,
            interactive_permissions=False,
            source="dingtalk_clawbot",
        ))

    assert all(event.type != "thinking" for event in emitted)
    assert all(block["type"] != "thinking" for block in result.blocks)
    assert result.final_text == "result"


def test_execute_agent_turn_rejects_interactive_permission_for_channel():
    emitted = []

    async def on_event(event):
        emitted.append(event)

    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(
            agent_service,
            "get_runtime",
            return_value=_Runtime(include_permission=True),
        ),
    ):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=_agent(),
            user_input="current",
            session_id=11,
            user_id=7,
            db=_DB(_session(), _model()),
            on_event=on_event,
            permission_mode="default",
            interactive_permissions=False,
            source="weixin_clawbot",
        ))

    assert result.status == "failed"
    assert result.final_text == "result"
    assert any(
        event.type == "error" and "不支持交互授权" in event.content
        for event in emitted
    )


def test_execute_agent_turn_guard_blocks_before_user_message():
    _Memory.order = []

    async def run_guard():
        return False

    with _execution_dependencies(), patch.object(agent_service, "AgentMemory", _Memory):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=_agent(),
            user_input="current",
            session_id=11,
            user_id=7,
            db=_DB(_session(), _model()),
            manage_run_record=False,
            run_guard=run_guard,
        ))

    assert result.status == "unknown"
    assert result.user_message_id is None
    assert _Memory.order == []


def test_directory_workspace_failure_stops_run_without_stale_fallback():
    emitted = []

    async def on_event(event):
        emitted.append(event)

    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(
            agent_service,
            "get_workspace_provider",
            return_value=_FailingDirectorySandbox(),
        ),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(agent_service, "get_runtime") as get_runtime_mock,
    ):
        db = _DB(_session(), _model())
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=_agent(),
            user_input="current",
            session_id=11,
            user_id=7,
            db=db,
            on_event=on_event,
            interactive_permissions=False,
        ))

    assert result.status == "failed"
    assert result.error == f"工作区准备失败（运行编号：{result.run_id}）"
    assert db.run.status == "failed"
    assert db.run.error_code == "workspace_preparation_failed"
    assert get_runtime_mock.call_count == 0
    assert any(
        event.type == "error" and event.content == result.error
        for event in emitted
    )


def test_execute_agent_turn_guard_blocks_assistant_persist_after_runtime():
    _Memory.order = []
    _Memory.saved_blocks = None
    checks = 0

    async def run_guard():
        nonlocal checks
        checks += 1
        return checks == 1

    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(agent_service, "get_runtime", return_value=_Runtime()),
    ):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=_agent(),
            user_input="current",
            session_id=11,
            user_id=7,
            db=_DB(_session(), _model()),
            manage_run_record=False,
            run_guard=run_guard,
        ))

    assert checks == 3
    assert result.status == "unknown"
    assert result.user_message_id == 101
    assert result.assistant_message_id is None
    assert _Memory.saved_blocks is None


def test_lease_loss_marks_cancelled_execution_unknown():
    checks = 0

    async def run_guard():
        nonlocal checks
        checks += 1
        return checks == 1

    db = _DB(_session(), _model())
    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(agent_service, "get_runtime", return_value=_CancelledRuntime()),
    ):
        try:
            asyncio.run(agent_service.execute_agent_turn(
                agent=_agent(),
                user_input="current",
                session_id=11,
                user_id=7,
                db=db,
                run_guard=run_guard,
            ))
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("runtime cancellation must propagate")

    assert checks == 3
    assert db.run.status == "unknown"
    assert "租约" in db.run.error_message


def test_user_cancellation_persists_partial_result_and_emits_terminal_event():
    emitted = []

    async def on_event(event):
        emitted.append(event)

    _Memory.saved_blocks = None
    db = _DB(_session(), _model())
    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(agent_service, "get_runtime", return_value=_PartialCancelledRuntime()),
    ):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=_agent(),
            user_input="current",
            session_id=11,
            user_id=7,
            db=db,
            on_event=on_event,
        ))

    assert result.status == "cancelled"
    assert result.final_text == "partial result"
    assert _Memory.saved_blocks == [{"type": "text", "content": "partial result"}]
    assert [event.type for event in emitted][-1] == "cancelled"
    assert db.run.status == "cancelled"
    assert db.run.error_code == "cancelled"


@pytest.mark.parametrize("stage", [
    "cancel_guard", "runtime_stop", "artifact_snapshot", "cleanup_guard", "workspace_cleanup", "persist_guard",
])
@pytest.mark.parametrize("lease_lost", [False, True])
def test_repeated_cancellation_keeps_partial_history_unless_lease_is_lost(stage, lease_lost):
    from agent_routes import get_messages
    from agent_stream import _completed_snapshot
    from auth import CurrentUser
    from test_agent_routes import _create_db

    db = _create_db()
    model = AIModel(id=1, user_id=7, name="test-model", provider="test",
                    api_key="test-key", api_protocol="anthropic-messages")
    db.add_all([
        Agent(id=1, user_id=7, name="agent", runtime_type="claude_code"),
        AgentSession(id=11, agent_id=1, user_id=7, model_id=1,
                     runtime_type="claude_code", is_deleted=False),
        model,
    ])
    db.commit()

    async def scenario():
        runtime_ready = asyncio.Event()
        finalization_ready = asyncio.Event()
        release_finalization = asyncio.Event()
        release_thread = threading.Event()
        loop = asyncio.get_running_loop()
        guard_calls = 0

        async def pause():
            finalization_ready.set()
            await release_finalization.wait()

        def pause_thread():
            loop.call_soon_threadsafe(finalization_ready.set)
            assert release_thread.wait(3), "finalization was not released"

        class Runtime(_Runtime):
            async def run(self, **kwargs):
                await kwargs["on_event"](RuntimeEvent(type="info", runtime_session_id="saved-runtime"))
                await kwargs["on_event"](RuntimeEvent(type="text", content="已生成的部分回复"))
                await kwargs["on_event"](RuntimeEvent(type="usage", usage={"input_tokens": 10, "output_tokens": 5}))
                runtime_ready.set()
                await asyncio.Event().wait()

            async def cancel(self):
                if stage == "runtime_stop":
                    await pause()

        class Workspace(_Sandbox):
            snapshots = 0

            def snapshot_execution_files(self, *_args):
                self.snapshots += 1
                if self.snapshots == 2 and stage == "artifact_snapshot":
                    pause_thread()
                return {}

            def cleanup(self, _ctx):
                if stage == "workspace_cleanup":
                    pause_thread()

        async def guard():
            nonlocal guard_calls
            guard_calls += 1
            if (guard_calls == 2 and stage == "cancel_guard") or (guard_calls == 3 and stage == "cleanup_guard"):
                await pause()
            if guard_calls == 4:
                if stage == "persist_guard":
                    await pause()
                return not lease_lost
            return True

        with (
            _execution_dependencies(),
            patch.object(agent_service, "_agent_available_models", return_value=[model]),
            patch.object(agent_service, "get_workspace_provider", return_value=Workspace()),
            patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
            patch.object(agent_service, "get_runtime", return_value=Runtime()),
        ):
            task = asyncio.create_task(agent_service.execute_agent_turn(
                agent=_agent(), user_input="current", session_id=11, user_id=7,
                db=db, run_guard=guard,
            ))
            try:
                await asyncio.wait_for(runtime_ready.wait(), 2)
                task.cancel()
                await asyncio.wait_for(finalization_ready.wait(), 2)
                # Match the stop endpoint and background monitor both cancelling
                # an execution; also exercise cancellation while draining it.
                for _ in range(3):
                    task.cancel()
                    await asyncio.sleep(0)
                release_finalization.set()
                release_thread.set()
                result = await asyncio.wait_for(asyncio.shield(task), 3)
            finally:
                release_finalization.set()
                release_thread.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        assert guard_calls == 4
        assert result.final_text == "已生成的部分回复"
        if lease_lost:
            assert result.status == "unknown"
            assert result.assistant_message_id is None
            assert db.query(AgentMessage).filter_by(role="assistant").count() == 0
            return

        assert result.status == "cancelled"
        assert result.assistant_message_id is not None
        # Reopen history with a fresh session, as the browser does on reload.
        from sqlalchemy.orm import sessionmaker
        with sessionmaker(bind=db.get_bind())() as reopened:
            history = get_messages(1, 11, None, 100, reopened, CurrentUser(7))
            assert [m["role"] for m in history["items"]] == ["user", "assistant"]
            saved = json.loads(history["items"][-1]["content"])
            assert saved["blocks"][0]["content"] == "已生成的部分回复"
            assert saved["usage"] == {"input_tokens": 10, "output_tokens": 5}
            assert saved["duration_ms"] >= 0
            run = reopened.get(AgentRun, result.run_id)
            assert run.status == "cancelled"
            assert run.assistant_message_id == result.assistant_message_id
            assert run.total_tokens == 15
            assert reopened.get(AgentSession, 11).runtime_session_id == "saved-runtime"
            assert reopened.get(AgentSession, 11).message_count == 2
            replay = _completed_snapshot(reopened, run, 0)
            assert any(e.get("content") == "已生成的部分回复" for e in replay["events"])

    try:
        asyncio.run(scenario())
    finally:
        db.close()
        db.get_bind().dispose()


@pytest.mark.parametrize("cancelled", [False, True])
def test_assistant_save_failure_is_reported_instead_of_silent_success(cancelled):
    emitted = []

    async def on_event(event):
        emitted.append(event)

    db = _DB(_session(), _model())
    with (
        _execution_dependencies(),
        patch.object(agent_service, "AgentMemory", _Memory),
        patch.object(_Memory, "save_assistant_message", return_value=None),
        patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
        patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
        patch.object(agent_service, "get_runtime", return_value=_PartialCancelledRuntime() if cancelled else _Runtime()),
    ):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=_agent(), user_input="current", session_id=11,
            user_id=7, db=db, on_event=on_event,
        ))

    assert result.status == db.run.status == "failed"
    assert result.assistant_message_id is None
    assert result.final_text == ("partial result" if cancelled else "result")
    assert db.run.error_code == "assistant_message_save_failed"
    assert emitted[-1].type == "error"
    assert emitted[-1].error_code == db.run.error_code
    assert "回复保存失败" in result.error


@pytest.mark.parametrize("failures", [1, 2])
def test_database_save_retry_keeps_run_link_or_records_save_failure(failures):
    from sqlalchemy.exc import SQLAlchemyError
    from test_agent_routes import _create_db

    db = _create_db()
    model = AIModel(id=1, user_id=7, name="test-model", provider="test",
                    api_key="test-key", api_protocol="anthropic-messages")
    db.add_all([
        Agent(id=1, user_id=7, name="agent", runtime_type="claude_code"),
        AgentSession(id=11, agent_id=1, user_id=7, model_id=1, runtime_type="claude_code"),
        model,
    ])
    db.commit()
    commit = db.commit
    attempts = 0
    emitted = []

    def commit_with_failure():
        nonlocal attempts
        if any(isinstance(row, AgentMessage) and row.role == "assistant" for row in db.new):
            attempts += 1
            if attempts <= failures:
                raise SQLAlchemyError("simulated message write failure")
        commit()

    class Runtime(_Runtime):
        async def run(self, **kwargs):
            await kwargs["on_event"](RuntimeEvent(type="text", content="partial result"))
            raise asyncio.CancelledError

    async def on_event(event):
        emitted.append(event)

    try:
        with (
            _execution_dependencies(),
            patch.object(agent_service, "_agent_available_models", return_value=[model]),
            patch.object(agent_service, "get_workspace_provider", return_value=_Sandbox()),
            patch.object(agent_service, "build_mcp_json", return_value=({}, [])),
            patch.object(agent_service, "get_runtime", return_value=Runtime()),
            patch.object(db, "commit", side_effect=commit_with_failure),
        ):
            result = asyncio.run(agent_service.execute_agent_turn(
                agent=_agent(), user_input="current", session_id=11,
                user_id=7, db=db, on_event=on_event,
            ))
        assert attempts == 2
        db.expire_all()
        run = db.get(AgentRun, result.run_id)
        if failures == 1:
            assert run.status == result.status == "cancelled"
            assert run.assistant_message_id == result.assistant_message_id
            message = db.get(AgentMessage, run.assistant_message_id)
            assert json.loads(message.content)["blocks"][0]["content"] == "partial result"
        else:
            assert run.status == result.status == "failed"
            assert run.error_code == "assistant_message_save_failed"
            assert run.assistant_message_id is None
            assert emitted[-1].error_code == "assistant_message_save_failed"
    finally:
        db.close()
        db.get_bind().dispose()


def test_runtime_errors_are_normalized_and_prioritized_for_users():
    balance, balance_priority = agent_service._normalize_runtime_error_event(RuntimeEvent(
        type="error",
        content="Failed to authenticate. API Error: 403 Insufficient account balance",
    ))
    model, model_priority = agent_service._normalize_runtime_error_event(RuntimeEvent(
        type="error",
        content='[claude-code:unrecognized_model] {"model":"deepseek-flash"}',
    ))

    assert balance.error_code == "model_balance_insufficient"
    assert balance.content == "模型服务余额不足，请联系管理员充值或切换其他模型后重试。"
    assert model.error_code == "runtime_error"
    assert 'unrecognized_model' not in model.content
    assert balance.metadata['error_origin'] == 'upstream'
    assert '403 Insufficient account balance' in balance.metadata['error_detail']
    assert balance_priority > model_priority


@pytest.mark.parametrize('raw,code,origin', [
    ('[claude-code:unrecognized_model] {"model":"claude-sonnet-5-5"}\nAPI Error: 504 upstream_timeout',
     'model_request_timeout', 'model_connection'),
    ('[claude-code:unrecognized_model] {"model":"claude-sonnet-5-5"}\nAPI Error: 429 rate_limit_error',
     'model_rate_limited', 'upstream'),
    ('API Error: 404 model_not_found: unknown model', 'model_not_supported', 'upstream'),
    ('API Error: 503 overloaded_error: upstream capacity exhausted; request_id=req-test',
     'runtime_error', 'upstream'),
    ('API Error: 502 upstream_connection_failed: Connection reset by peer',
     'model_connection_failed', 'model_connection'),
])
def test_upstream_error_details_survive_normalization_and_history(raw, code, origin):
    event, _ = agent_service._normalize_runtime_error_event(RuntimeEvent(type='error', content=raw))
    assert event.error_code == code
    assert event.metadata['error_origin'] == origin
    assert 'API Error:' in event.metadata['error_detail']
    assert 'unrecognized_model' not in event.metadata['error_detail']
    blocks = []
    agent_service._append_event_block(blocks, event)
    assert blocks[0]['metadata'] == event.metadata
    assert blocks[0]['error_code'] == code


def test_gateway_rejections_are_not_misattributed_to_the_model_provider():
    event, _ = agent_service._normalize_runtime_error_event(RuntimeEvent(
        type='error', content='API Error: 401 [AIHub 模型网关] invalid_run_credential',
        metadata={'error_origin': 'upstream'},
    ))
    assert event.metadata['error_origin'] == 'aihub'


if __name__ == "__main__":
    test_execute_agent_turn_loads_history_before_current_message()
    test_workbench_executes_unbound_custom_model_with_saved_credentials()
    test_expert_executes_unbound_custom_model_with_saved_credentials()
    test_execution_rejects_foreign_or_disabled_models()
    test_merge_usage_accumulates_complete_turn()
    test_usage_metrics_normalizes_openai_aliases_and_preserves_reported_total()
    test_block_timing_tracks_thinking_and_tool_duration()
    test_block_timing_finishes_tool_without_result_at_run_end()
    test_block_timing_skips_clock_reads_for_plain_text_deltas()
    test_assistant_message_compaction_preserves_block_duration()
    test_reasoning_visibility_buffers_web_reasoning_until_complete()
    test_external_channel_never_emits_or_persists_reasoning()
    test_execute_agent_turn_rejects_interactive_permission_for_channel()
    test_execute_agent_turn_guard_blocks_before_user_message()
    test_directory_workspace_failure_stops_run_without_stale_fallback()
    test_execute_agent_turn_guard_blocks_assistant_persist_after_runtime()
    test_lease_loss_marks_cancelled_execution_unknown()
    test_user_cancellation_persists_partial_result_and_emits_terminal_event()
    test_runtime_errors_are_normalized_and_prioritized_for_users()
    print("agent_service tests passed")
