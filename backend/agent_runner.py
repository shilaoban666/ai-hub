"""智能体运行器（兼容层）

已废弃，请直接使用 runtimes/ 下的 runtime 实现。
此文件保留向后兼容，内部委托给 ClaudeCodeRuntime。
"""

import warnings
from typing import AsyncGenerator

from runtimes.base import RuntimeConfig
from runtimes.claude_code import ClaudeCodeRuntime


async def run_agent(
    agent_id: int,
    agent_name: str,
    agent_timeout: int,
    model_api_key: str,
    model_api_proxy_url: str | None,
    user_input: str,
    run_id: str = "",
) -> AsyncGenerator[str, None]:
    """启动 claude code 子进程，流式返回 SSE 字符串（兼容旧接口）

    已废弃：新代码请使用 runtimes.get_runtime() + AgentService
    """
    warnings.warn(
        "agent_runner.run_agent 已废弃，请使用 runtimes + AgentService",
        DeprecationWarning,
        stacklevel=2,
    )

    from agent_workspace import get_workspace_dir
    from runtimes.base import RuntimeEvent
    from sandbox.base import WorkspaceContext

    runtime = ClaudeCodeRuntime()
    config = RuntimeConfig(
        runtime_type="claude_code",
        api_key=model_api_key,
        api_base_url=model_api_proxy_url,
        model="",
        timeout_seconds=agent_timeout,
        extra={"run_id": run_id} if run_id else {},
    )
    ws_dir = get_workspace_dir(agent_id)
    ctx = WorkspaceContext(
        sandbox_type="directory",
        workspace_root=ws_dir,
        host_workspace_path=ws_dir,
        argv_prefix=[],
        claude_bin="claude",
        run_cwd=ws_dir,
    )

    def _sse(data: dict) -> str:
        import json
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def on_event(evt: RuntimeEvent):
        pass  # 兼容层不使用回调，直接 yield SSE

    # 由于旧接口是 AsyncGenerator，我们直接调用 runtime 并在回调中 yield
    # 但 runtime.run 使用回调模式，这里做适配
    queue = []

    async def collect(evt: RuntimeEvent):
        queue.append(evt.to_sse())

    try:
        await runtime.run(config, ctx, user_input, [], collect)
        for sse in queue:
            yield sse
    except Exception as e:
        yield _sse({"type": "error", "content": str(e)})
