"""Runtime 抽象基类

所有 runtime 实现的统一接口。新 runtime 只需继承 AbstractRuntime 并实现 run/resume/cancel 三个方法。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Awaitable

from pydantic import BaseModel

from sandbox.base import WorkspaceContext


class RuntimeConfig(BaseModel):
    """Runtime 配置

    所有 runtime 通用的配置项。特定 runtime 的扩展配置通过 extra 字段传入。
    """
    runtime_type: str = "claude_code"   # Registered runtime identifier
    api_key: str = ""
    api_base_url: str | None = None
    model: str = ""                     # 模型名（如 claude-sonnet-4-20250514）
    max_turns: int = 50
    timeout_seconds: int = 600

    # 特定 runtime 的扩展配置
    extra: dict = {}


@dataclass(frozen=True)
class RuntimeAttachment:
    path: str
    filename: str = ""
    media_type: str = ""
    image_data: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class RuntimeRunContext:
    run_id: str
    session_id: int
    runtime_session_id: str | None = None
    source: str = "web"
    source_binding_id: int | None = None
    attached_files: tuple[RuntimeAttachment, ...] = ()
    permission_mode: str | None = None
    include_history: bool = True


@dataclass
class RuntimeEvent:
    """统一的 Runtime 事件

    屏蔽不同 runtime 的差异，前端只接收这种标准化事件。
    对应 SSE 中的 data 字段。

    事件类型:
      - text:          助手文本增量
      - thinking:      思考过程增量
      - tool_use:      工具调用开始（含 name + input）
      - tool_result:   工具调用结果
      - usage:         token 用量
      - artifacts:     已保存的本轮文件列表（metadata.files）
      - done:          流结束
      - cancelled:     用户取消，可能携带已完成的部分结果
      - error:         错误
      - info:          系统提示
      - permission_request: 需要用户授权
    """
    type: str
    content: str = ""
    tool_name: str = ""
    tool_input: dict | None = None
    tool_use_id: str = ""
    is_error: bool = False
    usage: dict | None = None

    # permission_request 专用字段
    req_id: str = ""
    run_id: str = ""
    tool_key: str = ""
    runtime_run_id: str = ""
    runtime_session_id: str = ""
    error_code: str = ""
    metadata: dict | None = None

    def to_sse(self) -> str:
        """转为 SSE 字符串"""
        d = {"type": self.type}
        if self.content:
            d["content"] = self.content
        if self.tool_name:
            d["name"] = self.tool_name
        if self.tool_input is not None:
            d["input"] = self.tool_input
        if self.tool_use_id:
            d["tool_use_id"] = self.tool_use_id
        if self.is_error:
            d["is_error"] = True
        if self.usage:
            d["usage"] = self.usage
        if self.req_id:
            d["req_id"] = self.req_id
        if self.run_id:
            d["run_id"] = self.run_id
        if self.tool_key:
            d["tool_key"] = self.tool_key
        if self.runtime_run_id:
            d["runtime_run_id"] = self.runtime_run_id
        if self.runtime_session_id:
            d["runtime_session_id"] = self.runtime_session_id
        if self.error_code:
            d["error_code"] = self.error_code
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"


# 事件回调类型: async callable 接收 RuntimeEvent
EventCallback = Callable[[RuntimeEvent], Awaitable[None]]


class AbstractRuntime(ABC):
    """Runtime 抽象基类

    每个 runtime 实例管理自己的子进程 / 连接。
    """

    @abstractmethod
    async def run(
        self,
        config: RuntimeConfig,
        ctx: WorkspaceContext,
        user_input: str,
        history: list[dict],
        on_event: EventCallback,
        run_context: RuntimeRunContext | None = None,
    ) -> None:
        """执行一次对话

        Args:
            config: Runtime 配置
            ctx: 沙箱工作区上下文(workspace_root/argv_prefix/run_cwd/env 等)
            user_input: 用户输入文本
            history: 历史消息列表 [{"role":"user"|"assistant","content":"..."}, ...]
            on_event: 事件回调（会多次调用，每次一个 RuntimeEvent）

        实现要求:
          - 内部处理 runtime 启动、流式读取、事件翻译
          - 翻译后的事件通过 on_event 回调传出
          - 完成后正常返回；错误通过 RuntimeEvent(type="error") 报告
        """
        ...

    @abstractmethod
    async def resume(
        self,
        config: RuntimeConfig,
        ctx: WorkspaceContext,
        session_id: str,
    ) -> AsyncGenerator[RuntimeEvent, None]:
        """恢复已有会话（用于支持 --resume 等机制）

        Args:
            config: Runtime 配置
            ctx: 沙箱工作区上下文
            session_id: 之前保存的会话 ID

        Yields:
            RuntimeEvent 流
        """
        ...

    @abstractmethod
    async def cancel(self) -> None:
        """取消当前正在执行的任务"""
        ...
