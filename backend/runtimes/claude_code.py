"""Claude Code runtime

通过 subprocess 调用 claude code CLI，将 JSONL 流翻译为 RuntimeEvent。

claude 调用:
  <prompt> | claude -p --input-format text --output-format stream-json
        --include-partial-messages --verbose
        --permission-mode acceptEdits

  含图片时通过 --input-format stream-json 传入文本和 Base64 图片内容块。

  <prompt> 已把 DB 中的对话历史拼入(claude -p 是无状态一次性调用，历史由
  调用方在 prompt 中提供，不依赖 --resume 磁盘会话)。

cwd = 智能体工作区目录
env = 最小系统环境 + 工作区变量 + 模型调用变量
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import posixpath
import signal
import subprocess
import sys
import threading
import time
from typing import AsyncGenerator

from runtimes.base import AbstractRuntime, RuntimeConfig, RuntimeEvent, RuntimeRunContext
from sandbox.base import WorkspaceContext
from runtime_errors import strip_model_diagnostics


JSONL_READ_CHUNK_BYTES = 64 * 1024
JSONL_MAX_RECORD_BYTES = 8 * 1024 * 1024
STDERR_MAX_BYTES = 64 * 1024
OVERSIZED_JSONL_NOTICE = "工具输出过大，已省略本次界面展示，智能体将继续处理后续内容。"
TUNNELED_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CONFIG_DIR",
    "FORCE_COLOR",
    "NO_COLOR",
    "PATH",
    "VIRTUAL_ENV",
    "PIP_REQUIRE_VIRTUALENV",
    "PYTHONNOUSERSITE",
    "LANG",
    "LC_ALL",
    "TZ",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
}

# Claude and the tools it launches need a small amount of host process context,
# but must never inherit backend credentials such as DATABASE_URL or encryption
# keys. Keep this list limited to process startup, locale and certificate lookup.
INHERITED_RUNTIME_ENV_KEYS = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
}

# These configure the trusted host Docker client, never the Agent container.
DOCKER_CLIENT_ENV_KEYS = {
    "HOME", "USERPROFILE", "USER", "LOGNAME", "SSH_AUTH_SOCK",
    "DOCKER_CONFIG", "DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_CERT_PATH",
    "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_API_VERSION",
}


def _build_runtime_env(
    config: RuntimeConfig,
    ctx: WorkspaceContext,
    *,
    color: bool = True,
) -> dict[str, str]:
    """Build a clean environment for the untrusted Agent subprocess."""
    env = {
        key: value
        for key in INHERITED_RUNTIME_ENV_KEYS
        if (value := os.environ.get(key)) is not None
    }
    env.setdefault("PATH", os.defpath)
    env.update({
        str(key): str(value)
        for key, value in (ctx.env or {}).items()
        if value is not None
    })

    # Resolve python/python3 and pip in the workspace even after Bash cd's into
    # a subdirectory. Native/container paths are POSIX, including on Windows hosts.
    paths = posixpath if ctx.is_isolated else os.path
    venv = paths.join(ctx.workspace_root, ".venv")
    bin_dir = paths.join(venv, "Scripts" if os.name == "nt" and not ctx.is_isolated else "bin")
    path_separator = ":" if ctx.is_isolated else os.pathsep
    env["PATH"] = bin_dir + path_separator + env["PATH"]
    env["VIRTUAL_ENV"] = venv
    env["PIP_REQUIRE_VIRTUALENV"] = "true"
    env["PYTHONNOUSERSITE"] = "1"

    # Keep CLI/tool configuration lookup inside the Agent workspace instead of
    # the backend service account's home directory.
    env.setdefault("HOME", ctx.workspace_root)
    env.setdefault("USERPROFILE", ctx.workspace_root)
    env.update({
        "ANTHROPIC_API_KEY": config.api_key,
        "CLAUDE_CONFIG_DIR": f"{ctx.workspace_root}/.claude",
    })
    if color:
        env["FORCE_COLOR"] = "1"
        env["NO_COLOR"] = ""
    if config.api_base_url:
        env["ANTHROPIC_BASE_URL"] = config.api_base_url
    return env


def _encode_tunneled_env(ctx: WorkspaceContext, env: dict) -> bytes:
    """Encode the environment consumed by the native user-switch wrapper."""
    if not ctx.tunnel_env_via_stdin:
        return b""
    keys = set(ctx.env) | TUNNELED_ENV_KEYS
    forwarded = {
        key: str(env[key])
        for key in keys
        if key in env and env[key] is not None
    }
    payload = json.dumps(
        forwarded, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    return base64.b64encode(payload) + b"\n"


def _build_subprocess_env(ctx: WorkspaceContext, runtime_env: dict) -> dict[str, str]:
    """Keep host Docker configuration separate from the tunneled Agent env."""
    if ctx.sandbox_type != "container" or not ctx.tunnel_env_via_stdin:
        return runtime_env
    env = {
        key: value
        for key in INHERITED_RUNTIME_ENV_KEYS | DOCKER_CLIENT_ENV_KEYS
        if (value := os.environ.get(key)) is not None
    }
    env.setdefault("PATH", os.defpath)
    env.setdefault("HOME", os.path.expanduser("~"))
    return env


async def _iter_jsonl_records(reader):
    """Read JSONL without StreamReader.readline's separator-size limit."""
    if not hasattr(reader, "read"):
        async for line in reader:
            yield line
        return

    buffer = bytearray()
    discarding = False
    while True:
        chunk = await reader.read(JSONL_READ_CHUNK_BYTES)
        if not chunk:
            break
        offset = 0
        while offset < len(chunk):
            newline = chunk.find(b"\n", offset)
            end = len(chunk) if newline < 0 else newline
            fragment = chunk[offset:end]
            if not discarding:
                if len(buffer) + len(fragment) <= JSONL_MAX_RECORD_BYTES:
                    buffer.extend(fragment)
                else:
                    buffer.clear()
                    discarding = True
            if newline < 0:
                break
            if discarding:
                yield None
            else:
                yield bytes(buffer)
            buffer.clear()
            discarding = False
            offset = newline + 1

    if discarding:
        yield None
    elif buffer:
        yield bytes(buffer)


class _StreamTranslator:
    """把 claude code JSONL 事件翻译成 RuntimeEvent

    claude code 2.1.x JSONL 事件类型:
      - {"type":"system","subtype":"init"/"status"/"thinking_tokens", ...}
      - {"type":"stream_event","event":{Anthropic 原生 streaming 事件}}
          message_start / content_block_start / content_block_delta / content_block_stop /
          message_delta / message_stop
          delta 子类型: text_delta / thinking_delta / input_json_delta / signature_delta
      - {"type":"assistant","message":{"content":[单个 block 完成快照]}}
      - {"type":"user","message":{"content":[{type:tool_result,...}]},"tool_use_result":{stdout,stderr,...}}
      - {"type":"result","subtype":"success","result":"..."}
      - {"type":"error","message":"..."}
    """

    def __init__(self):
        self._blocks: dict[int, dict] = {}
        self.session_id: str | None = None  # 从 system.init 中捕获
        self.model_used: str | None = None  # 实际使用的模型
        # 本轮累计用量(一次 turn 内可能有多次 API 调用,逐次累加)
        self.usage_total: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        # 当前 message 的输入侧用量(message_start 给出,供 message_delta 发出 usage 时附带)
        self._cur_usage: dict[str, int] = {
            "input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }

    @classmethod
    def _content_to_text(cls, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    elif "content" in item:
                        parts.append(cls._content_to_text(item.get("content")))
                    elif "text" in item:
                        parts.append(str(item.get("text", "")))
                elif item is not None:
                    parts.append(str(item))
            return "\n".join(p for p in parts if p)
        if isinstance(value, dict):
            stdout = value.get("stdout")
            stderr = value.get("stderr")
            if stdout or stderr:
                parts = []
                if stdout:
                    parts.append(str(stdout))
                if stderr:
                    parts.append("[stderr]\n" + str(stderr))
                return "\n".join(parts)
            for key in ("content", "text", "result", "output", "error"):
                if key in value:
                    return cls._content_to_text(value.get(key))
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @classmethod
    def _tool_use_result_to_text(cls, tool_use_result, fallback: str) -> str:
        if not tool_use_result:
            return fallback
        text = cls._content_to_text(tool_use_result)
        return text if text else fallback

    def translate(self, raw: dict) -> list[RuntimeEvent]:
        events: list[RuntimeEvent] = []
        try:
            self._translate(raw, events)
        except Exception as e:
            sys.stderr.write(f"[translator] error: {e}, raw={str(raw)[:300]}\n")
        return events

    def _translate(self, raw: dict, events: list[RuntimeEvent]) -> None:
        raw_type = raw.get("type")

        if raw_type == "system":
            subtype = raw.get("subtype", "")
            if subtype == "init":
                # 捕获 session_id 用于后续 --resume
                self.session_id = raw.get("session_id") or raw.get("sessionId")
                self.model_used = raw.get("model")
                events.append(RuntimeEvent(
                    type="info",
                    content="智能体已启动",
                    tool_use_id=self.session_id or "",  # 借用 tool_use_id 字段传 session_id
                ))
            # status / thinking_tokens 忽略

        elif raw_type == "stream_event":
            events.extend(self._handle_stream_event(raw.get("event", {})))

        elif raw_type == "assistant":
            # 每个 content_block_stop 后的单 block 快照，stream_event 已有更细粒度增量，忽略
            if raw.get("isApiErrorMessage") or raw.get("error"):
                detail = self._content_to_text((raw.get("message") or {}).get("content"))
                events.append(RuntimeEvent(
                    type="error", content=detail or str(raw.get("error") or "模型上游请求失败"),
                    metadata={"error_origin": "upstream"},
                ))

        elif raw_type == "user":
            events.extend(self._handle_user(raw))

        elif raw_type == "result":
            subtype = raw.get("subtype", "success")
            result = str(raw.get("result", "") or "")
            api_error = result.lstrip().lower().startswith("api error:")
            if subtype == "success" and not raw.get("is_error") and not api_error:
                events.append(RuntimeEvent(type="done", content=result))
            else:
                errors = self._content_to_text(raw.get("errors"))
                detail = '\n'.join(dict.fromkeys(part for part in (result, errors) if part))
                events.append(RuntimeEvent(type="error", content=detail or "未知错误"))

        elif raw_type == "error":
            msg = raw.get("message", "未知错误")
            msg_lower = msg.lower()
            # 工具输出过大触发 chunk 限制时降级为 info，
            # 让对话在下一轮继续（该限制无法在 CLI 层调大）
            is_chunk_err = ("chunk" in msg_lower and "limit" in msg_lower) or "separator" in msg_lower
            if is_chunk_err:
                events.append(RuntimeEvent(
                    type="info",
                    content=(
                        "⚠️ 工具输出过大触发 Claude Agent/API 的 chunk 限制"
                        "（该限制无法在 CLI 层调大，-p 模式下 PostToolUse 截断 hook 不执行）。"
                        "请缩小范围后重试：\n"
                        "- Read：用 offset/limit 分页，单次 ≤ 300 行\n"
                        "- Grep：设 head_limit=50，优先 files_with_matches\n"
                        "- Bash：命令末尾加 | head -100\n"
                        "不要用相同参数重试。"
                    ),
                ))
            else:
                events.append(RuntimeEvent(type="error", content=msg))

    def _handle_stream_event(self, event: dict) -> list[RuntimeEvent]:
        events: list[RuntimeEvent] = []
        etype = event.get("type")

        if etype == "message_start":
            self._blocks = {}
            # 输入侧用量(cache_read/creation/input)只在 message_start 给出,
            # 捕获并累加到本轮总量(message_delta 只有 output_tokens)
            msg = event.get("message", {}) or {}
            u = msg.get("usage", {}) or {}
            self._cur_usage = {
                "input_tokens": u.get("input_tokens", 0) or 0,
                "cache_read_input_tokens": u.get("cache_read_input_tokens", 0) or 0,
                "cache_creation_input_tokens": u.get("cache_creation_input_tokens", 0) or 0,
            }
            for k, v in self._cur_usage.items():
                self.usage_total[k] = self.usage_total.get(k, 0) + v

        elif etype == "content_block_start":
            idx = event.get("index")
            block = event.get("content_block", {})
            self._blocks[idx] = {
                "type": block.get("type"),
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "input_buf": "",
            }

        elif etype == "content_block_delta":
            idx = event.get("index")
            delta = event.get("delta", {})
            dtype = delta.get("type")
            if dtype == "text_delta":
                text = delta.get("text", "")
                if text:
                    events.append(RuntimeEvent(type="text", content=text))
            elif dtype == "thinking_delta":
                thinking = delta.get("thinking", "")
                if thinking:
                    events.append(RuntimeEvent(type="thinking", content=thinking))
            elif dtype == "input_json_delta":
                block = self._blocks.get(idx)
                if block is not None:
                    block["input_buf"] += delta.get("partial_json", "")

        elif etype == "content_block_stop":
            idx = event.get("index")
            block = self._blocks.get(idx)
            if block and block.get("type") == "tool_use":
                try:
                    inp = json.loads(block["input_buf"]) if block["input_buf"] else {}
                except json.JSONDecodeError:
                    inp = {}
                events.append(RuntimeEvent(
                    type="tool_use",
                    tool_name=block.get("name", ""),
                    tool_input=inp,
                    tool_use_id=block.get("id", ""),
                ))

        elif etype == "message_delta":
            u = event.get("usage") or {}
            out = u.get("output_tokens", 0) or 0
            if u:
                self.usage_total["output_tokens"] = self.usage_total.get("output_tokens", 0) + out
                # 附带本 message 的输入侧 cache 用量,让 DB/前端能看到 cache 命中情况
                events.append(RuntimeEvent(
                    type="usage",
                    usage={
                        "input_tokens": self._cur_usage["input_tokens"],
                        "output_tokens": out,
                        "cache_read_input_tokens": self._cur_usage["cache_read_input_tokens"],
                        "cache_creation_input_tokens": self._cur_usage["cache_creation_input_tokens"],
                    },
                ))

        return events

    def _handle_user(self, raw: dict) -> list[RuntimeEvent]:
        """提取工具结果，超大结果做截断"""
        events: list[RuntimeEvent] = []
        message = raw.get("message", {})
        if not isinstance(message, dict):
            message = {}
        content = message.get("content", [])
        if isinstance(content, dict):
            content = [content]
        elif not isinstance(content, list):
            content = []
        tur = raw.get("tool_use_result") or {}

        MAX_RESULT_LEN = 200_000  # 单条工具结果最大 200K 字符（与 hook 阈值保持一致）

        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "tool_result":
                continue
            fallback = self._content_to_text(item.get("content", ""))
            content_str = self._tool_use_result_to_text(tur, fallback)

            if len(content_str) > MAX_RESULT_LEN:
                content_str = (
                    content_str[:MAX_RESULT_LEN]
                    + f"\n\n[... 结果过长已截断，原长度 {len(content_str)} 字符，"
                    f"仅显示前 {MAX_RESULT_LEN} 字符 ...]"
                )

            events.append(RuntimeEvent(
                type="tool_result",
                tool_use_id=item.get("tool_use_id", ""),
                content=content_str,
                is_error=bool(item.get("is_error", False)),
            ))
        return events


def _assistant_text_for_history(content: str) -> str:
    """从助手消息提取可读文本(blocks JSON 或纯文本)，工具调用/结果做简短标注。

    assistant 消息在 DB 中存为 {"blocks":[{"type":"text"|"thinking"|"tool_use"|
    "tool_result",...}]}；这里只保留 text，工具调用/结果以简短标记带出，让模型
    知道之前用过哪些工具，而 thinking/usage 不进入历史文本。
    """
    if not content:
        return ""
    # 兼容旧的纯文本格式
    if not content.lstrip().startswith("{"):
        return content
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    blocks = data.get("blocks") if isinstance(data, dict) else None
    if not isinstance(blocks, list):
        return content
    parts: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "text":
            t = b.get("content", "")
            if t:
                parts.append(t)
        elif btype == "tool_use":
            name = b.get('name', '')
            inp = b.get('input', {})
            if isinstance(inp, dict) and inp:
                if name == 'Bash' and 'command' in inp:
                    parts.append(f"[调用工具 Bash: {inp['command'][:200]}]")
                elif 'file_path' in inp:
                    parts.append(f"[调用工具 {name}: {inp['file_path']}]")
                elif 'pattern' in inp:
                    parts.append(f"[调用工具 {name}: {inp['pattern']}]")
                elif 'url' in inp:
                    parts.append(f"[调用工具 {name}: {inp['url']}]")
                else:
                    parts.append(f"[调用工具 {name}: {str(inp)[:200]}]")
            else:
                parts.append(f"[调用工具 {name}]")
        elif btype == "tool_result":
            c = b.get("content", "")
            if len(c) <= 2000:
                parts.append(f"[工具结果: {c}]")
            else:
                parts.append(f"[工具结果(截取): {c[:1500]}…（共{len(c)}字符）]")
    return "\n".join(p for p in parts if p)


MAX_HISTORY_PROMPT_CHARS = 72_000
MAX_HISTORY_SUMMARY_CHARS = 12_000


def _build_prompt_with_history(user_input: str, history: list[dict]) -> str:
    """把对话历史拼入 prompt，使 claude -p 无状态调用具备多轮上下文。

    claude -p 每次都是独立一次性调用、不携带历史。这里从 DB 历史中提取最近可
    容纳的消息(受字符预算限制，避免超出模型上下文)前置到 prompt。

    替代原先依赖 --resume 读磁盘 transcript 的方案：transcript 在跨沙箱(cwd
    变化)、异常退出等情况下不会落盘，导致 resume 失败、每轮上下文丢失。
    """
    if not history:
        return user_input

    # AgentService 会在保存本轮用户消息之前读取历史，因此这里不能删除末尾 user；
    # 上一轮失败时历史可能正好以 user 结尾，删除会造成恢复上下文丢失。
    trimmed = list(history)

    # AgentMemory 会先把过长的早期历史压成一个 system 摘要。这里始终为摘要
    # 保留空间，再用剩余预算装入最近原文，避免恢复失败后静默丢掉长期上下文。
    summaries: list[str] = []
    conversation: list[str] = []
    for message in trimmed:
        role = message.get("role", "")
        content = message.get("content") or ""
        if not content:
            continue
        if role == "user":
            conversation.append(f"用户：{content}")
        elif role == "assistant":
            text = _assistant_text_for_history(content)
            if text:
                conversation.append(f"助手：{text}")
        elif role == "system":
            summaries.append(content)

    summary_text = "\n".join(summaries)[:MAX_HISTORY_SUMMARY_CHARS]
    recent_budget = max(8_000, MAX_HISTORY_PROMPT_CHARS - len(summary_text))
    picked: list[str] = []
    total = 0
    for line in reversed(conversation):
        remaining = recent_budget - total
        if remaining <= 0:
            break
        if len(line) > remaining:
            if picked:
                break
            suffix = "\n[以上历史已截断]"
            line = line[:max(0, remaining - len(suffix))] + suffix
        if total + len(line) > recent_budget and picked:
            break
        picked.insert(0, line)
        total += len(line)
        if total >= recent_budget:
            break

    history_parts: list[str] = []
    if summary_text:
        history_parts.append(summary_text)
    omitted_recent = max(0, len(conversation) - len(picked))
    if omitted_recent:
        history_parts.append(
            f"[另有 {omitted_recent} 条较早对话未直接载入，已优先保留最近内容。]"
        )
    history_parts.extend(picked)

    if not history_parts:
        return user_input
    return (
        "以下是之前的对话历史，请基于该上下文回应用户的最新消息：\n\n"
        + "\n\n".join(history_parts)
        + f"\n\n--- 最新用户消息 ---\n{user_input}"
    )


async def _await_process_cleanup(task):
    """Finish reaping even when stop or shutdown cancels the caller repeatedly."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


def _capture_stderr(buffer, chunk):
    if isinstance(chunk, str):
        chunk = chunk.encode("utf-8", errors="replace")
    buffer.extend(chunk[:max(0, STDERR_MAX_BYTES - len(buffer))])


class ClaudeCodeRuntime(AbstractRuntime):
    """通过 subprocess 调用 claude CLI"""

    def __init__(self):
        self._proc: asyncio.subprocess.Process | subprocess.Popen | None = None
        self._process_group_id: int | None = None
        self._translator: _StreamTranslator | None = None

    def _terminate_process(self, proc) -> None:
        if proc is None:
            return
        group_id = self._process_group_id if proc is self._proc else None
        if group_id is not None:
            # The user-switch parent may exit before its CLI and tools do.
            try:
                if os.geteuid() == 0:
                    os.killpg(group_id, signal.SIGKILL)
                else:
                    # sudo's monitor and the CLI have different UIDs. Killing
                    # only permitted members can strand the isolated tools.
                    result = subprocess.run(
                        ["sudo", "-n", "kill", "-KILL", "--", f"-{group_id}"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        check=False, timeout=5,
                    )
                    if result.returncode != 0:
                        os.killpg(group_id, 0)
                        raise RuntimeError("Native process group termination failed")
            except ProcessLookupError:
                pass
            self._process_group_id = None
            return
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    @property
    def last_session_id(self) -> str | None:
        """上一次运行捕获的 claude code session_id"""
        if self._translator:
            return self._translator.session_id
        return None

    def _log_turn_metrics(
        self,
        total: float,
        ttft: float | None,
        *,
        prompt_mode: str = "",
        prompt_chars: int = 0,
        history_messages: int = 0,
        history_chars: int = 0,
    ) -> None:
        """把本轮耗时与 token 用量(含 prompt cache 命中)写到 stderr。

        用于度量当前 -p 无状态方案的 cache 命中率与每轮启动延迟,判断是否
        需要切 --resume/常驻进程。零副作用,不影响对话流。
        """
        tr = self._translator
        if tr is None:
            return
        u = tr.usage_total
        cr = u.get("cache_read_input_tokens", 0)
        cc = u.get("cache_creation_input_tokens", 0)
        inp = u.get("input_tokens", 0)
        out = u.get("output_tokens", 0)
        hit = "HIT" if cr > 0 else "MISS"
        ttft_s = f"{ttft:.2f}s" if ttft is not None else "n/a"
        sys.stderr.write(
            f"[metrics] sid={tr.session_id or '-'} model={tr.model_used or '-'} "
            f"total={total:.2f}s ttft={ttft_s} cache={hit} "
            f"in={inp} out={out} cache_read={cr} cache_create={cc} "
            f"mode={prompt_mode or '-'} prompt_chars={prompt_chars} "
            f"history_messages={history_messages} history_chars={history_chars}\n"
        )
        sys.stderr.flush()

    async def run(
        self,
        config: RuntimeConfig,
        ctx: WorkspaceContext,
        user_input: str,
        history: list[dict],
        on_event,
        run_context: RuntimeRunContext | None = None,
    ) -> None:
        """启动 claude code 子进程，流式读取 JSONL 并回调 on_event

        claude -p 是无状态一次性调用、本身不携带历史；本方法把 DB 中的对话历史
        以文本形式拼入 prompt，使模型具备多轮上下文（替代脆弱的 --resume 磁盘
        会话：跨沙箱 cwd 变化或异常退出时 transcript 不落盘，会导致 resume 失
        敗、每轮上下文丢失）。

        隔离沙箱下 host_workspace_path 不应以当前进程权限直接验证；
        prepare 调用本身已保证工作区就绪。
        """
        if not ctx.is_isolated and not os.path.exists(ctx.host_workspace_path):
            await on_event(RuntimeEvent(
                type="error", content="智能体工作区不存在，请先保存配置"
            ))
            return

        timeout = config.timeout_seconds
        resume_id = config.extra.get("resume_id")
        prompt = user_input if resume_id else _build_prompt_with_history(user_input, history)
        prompt_mode = "resume" if resume_id else ("history" if prompt != user_input else "fresh")
        history_messages = len(history)
        history_chars = sum(len(m.get("content") or "") for m in history if isinstance(m, dict))

        # 本轮计时埋点(度量 cache 命中与启动延迟,见 _log_turn_metrics)
        t0 = time.monotonic()
        deadline = t0 + timeout
        ttft: float | None = None  # 首个 text/thinking 事件距开始的秒数

        # 构建最小运行环境，禁止继承后端数据库和平台凭据。
        env = _build_runtime_env(config, ctx)
        stdin_env = _encode_tunneled_env(ctx, env)
        subprocess_env = _build_subprocess_env(ctx, env)

        extra = config.extra
        permission_mode = extra.get("permission_mode") or "acceptEdits"
        if permission_mode not in {"acceptEdits", "default"}:
            permission_mode = "acceptEdits"

        # Managed turns use the official SDK for bidirectional tool approval.
        # Bare runtime invocations (diagnostics/resume utilities) remain one-shot.
        sdk_permissions = run_context is not None
        if sdk_permissions:
            from runtimes.sdk_permissions import PermissionTransport, PermissionTransportClosed, serve_permissions

        image_blocks = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": attachment.media_type,
                    "data": base64.b64encode(attachment.image_data).decode("ascii"),
                },
            }
            for attachment in (run_context.attached_files if run_context else ())
            if attachment.image_data is not None
        ]

        def _stdin_message():
            return {
                "type": "user",
                "parent_tool_use_id": None,
                "message": {
                    "role": "user",
                    "content": [*image_blocks, {"type": "text", "text": prompt}],
                },
            }

        def _stdin_prompt():
            if not image_blocks:
                return prompt
            return json.dumps(_stdin_message(), ensure_ascii=False) + "\n"

        def _build_cmd(use_resume: bool):
            cmd = [
                *ctx.argv_prefix, ctx.claude_bin, "-p",
                "--input-format", "stream-json" if image_blocks or sdk_permissions else "text",
                "--output-format", "stream-json",
                "--include-partial-messages",
                "--verbose",
                "--permission-mode", permission_mode,
            ]
            if sdk_permissions:
                cmd += ["--permission-prompt-tool", "stdio"]
                if permission_mode == "default" and run_context.source == "web":
                    # ask rules outrank existing allow rules. Do not rely on
                    # default mode alone: workspace tools are already allowed.
                    ask = ["Bash", "Write", "Edit", "NotebookEdit"]
                    ask += [f"mcp__{name}__*" for name in extra.get("mcp_server_names", [])]
                    cmd += ["--settings", json.dumps({"permissions": {"ask": ask}})]
            if use_resume and resume_id:
                cmd += ["--resume", resume_id]
            if config.model:
                cmd += ["--model", config.model]
            if run_context is not None and run_context.source == "api":
                # Keep connectors scoped to this run, with the same tools and
                # permission policies as the custom agent.
                cmd += ["--strict-mcp-config", "--mcp-config", ".mcp.json"]
            effort = str(extra.get("thinking_level") or "inherit")
            if effort in {"low", "medium", "high", "xhigh", "max"}:
                cmd += ["--effort", effort]
            return cmd

        async def _exec(cmd, event_callback=on_event):
            """启动子进程 + 流式读取 JSONL + 翻译回调。返回 (exit_code, stderr)。"""
            nonlocal ttft
            self._translator = _StreamTranslator()
            native_group = os.name == "posix" and ctx.sandbox_type == "native"
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=ctx.run_cwd or None,
                    env=subprocess_env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **({"start_new_session": True} if native_group else {}),
                )
                self._process_group_id = self._proc.pid if native_group else None
            except FileNotFoundError:
                await event_callback(RuntimeEvent(
                    type="error", content=f"服务器未安装沙箱命令（未找到 '{cmd[0] if cmd else '?'}'）"
                ))
                return -2, ""
            except NotImplementedError:
                return await _exec_threaded(cmd, event_callback)
            except Exception as e:
                detail = str(e) or repr(e) or e.__class__.__name__
                await event_callback(RuntimeEvent(
                    type="error", content=f"启动智能体失败: {detail}"
                ))
                return -2, ""

            proc = self._proc
            stderr_buffer = bytearray()

            async def read_stderr():
                if proc.stderr is None:
                    return
                if not hasattr(proc.stderr, "read"):
                    async for chunk in proc.stderr:
                        _capture_stderr(stderr_buffer, chunk)
                    return
                while chunk := await proc.stderr.read(JSONL_READ_CHUNK_BYTES):
                    _capture_stderr(stderr_buffer, chunk)

            stderr_task = asyncio.create_task(read_stderr())

            finished = asyncio.Event()

            async def write_control(data):
                proc.stdin.write(data.encode("utf-8"))
                await proc.stdin.drain()

            permission_transport = PermissionTransport(write_control) if sdk_permissions else None

            async def send_input():
                if sdk_permissions:
                    if stdin_env:
                        proc.stdin.write(stdin_env)
                        await proc.stdin.drain()
                    await serve_permissions(permission_transport, run_context, _stdin_message(), finished,
                                            allowed_mcp_tools=extra.get("allowed_mcp_tools", []))
                elif proc.stdin is not None:
                    try:
                        proc.stdin.write(stdin_env + _stdin_prompt().encode("utf-8"))
                        await proc.stdin.drain()
                    except OSError:
                        pass
                    finally:
                        proc.stdin.close()

            async def receive_output():
                nonlocal ttft
                oversized_notice_emitted = False
                await event_callback(RuntimeEvent(type="info", content="已启动智能体"))
                async for line in _iter_jsonl_records(self._proc.stdout):
                    if line is None:
                        if not oversized_notice_emitted:
                            oversized_notice_emitted = True
                            await event_callback(RuntimeEvent(
                                type="info", content=OVERSIZED_JSONL_NOTICE
                            ))
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw_event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(raw_event, dict):
                        continue
                    if permission_transport is not None:
                        permission_transport.feed(raw_event)
                        if raw_event.get("type") == "result":
                            proc.stdin.close()
                    for sse_event in self._translator.translate(raw_event):
                        if ttft is None and sse_event.type in ("text", "thinking"):
                            ttft = time.monotonic() - t0
                        await event_callback(sse_event)
                await proc.wait()

            async def read_output():
                sender = asyncio.create_task(send_input())
                receiver = asyncio.create_task(receive_output())
                try:
                    # When stdout ends before initialize/result, wake the SDK
                    # as well so failed CLI startup does not wait for timeout.
                    def finish(_):
                        finished.set()
                        if permission_transport is not None:
                            permission_transport.finish()
                    receiver.add_done_callback(finish)
                    await asyncio.gather(sender, receiver)
                finally:
                    finished.set()
                    sender.cancel()
                    receiver.cancel()
                    await asyncio.gather(sender, receiver, return_exceptions=True)

            async def reap_process():
                # A killed process can still have buffered stdout. Drain it so
                # Process.wait() is not held by a paused pipe transport.
                async for _ in _iter_jsonl_records(proc.stdout):
                    pass
                await asyncio.gather(proc.wait(), stderr_task)

            timed_out = False
            sdk_error = ""
            try:
                await asyncio.wait_for(read_output(), timeout=max(0, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                timed_out = True
            except Exception as exc:
                if not sdk_permissions or not isinstance(exc, PermissionTransportClosed):
                    raise
                sdk_error = str(exc)
            finally:
                self._terminate_process(proc)
                await _await_process_cleanup(asyncio.create_task(reap_process()))

            if timed_out:
                await event_callback(RuntimeEvent(
                    type="error", content=f"智能体执行超时({timeout}秒)，已强制终止",
                    error_code="runtime_timeout",
                ))
                return -2, ""

            stderr_text = strip_model_diagnostics(stderr_buffer.decode("utf-8", errors="replace"))
            if sdk_error and (not stderr_text or proc.returncode == 0):
                await event_callback(RuntimeEvent(type="error", content=stderr_text or sdk_error))
                return -2, ""
            return proc.returncode, stderr_text if proc.returncode != 0 else ""

        async def _exec_threaded(cmd, event_callback=on_event):
            """Windows SelectorEventLoop 不支持 asyncio 子进程时的降级实现。"""
            self._translator = _StreamTranslator()
            loop = asyncio.get_running_loop()
            event_queue: asyncio.Queue = asyncio.Queue()

            def put(kind: str, payload):
                loop.call_soon_threadsafe(event_queue.put_nowait, (kind, payload))

            stop_requested = threading.Event()

            def worker():
                nonlocal ttft
                proc = None
                stderr_buffer = bytearray()
                stderr_thread = None
                try:
                    proc = subprocess.Popen(
                        cmd,
                        cwd=ctx.run_cwd or None,
                        env=subprocess_env,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        **({"start_new_session": True}
                           if os.name == "posix" and ctx.sandbox_type == "native" else {}),
                    )
                    self._proc = proc
                    self._process_group_id = (
                        proc.pid if os.name == "posix" and ctx.sandbox_type == "native" else None
                    )
                except FileNotFoundError:
                    put("event", RuntimeEvent(
                        type="error",
                        content=f"服务器未安装沙箱命令（未找到 '{cmd[0] if cmd else '?'}'）",
                    ))
                    put("result", (-2, ""))
                    return
                except Exception as e:
                    detail = str(e) or repr(e) or e.__class__.__name__
                    put("event", RuntimeEvent(type="error", content=f"启动智能体失败: {detail}"))
                    put("result", (-2, ""))
                    return

                def read_stderr():
                    if proc.stderr is not None:
                        while chunk := proc.stderr.read(JSONL_READ_CHUNK_BYTES):
                            _capture_stderr(stderr_buffer, chunk)

                try:
                    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
                    stderr_thread.start()
                    if stop_requested.is_set():
                        return
                    if proc.stdin is not None:
                        try:
                            proc.stdin.write(stdin_env.decode("ascii") + ("" if sdk_permissions else _stdin_prompt()))
                            proc.stdin.flush()
                        except (BrokenPipeError, OSError):
                            pass
                        finally:
                            if not sdk_permissions:
                                try:
                                    proc.stdin.close()
                                except OSError:
                                    pass

                    if sdk_permissions:
                        put("sdk_ready", None)

                    put("event", RuntimeEvent(type="info", content="已启动智能体"))
                    oversized_notice_emitted = False
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        if len(line.encode("utf-8", errors="replace")) > JSONL_MAX_RECORD_BYTES:
                            if not oversized_notice_emitted:
                                oversized_notice_emitted = True
                                put("event", RuntimeEvent(
                                    type="info", content=OVERSIZED_JSONL_NOTICE
                                ))
                            continue
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            raw_event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(raw_event, dict):
                            continue
                        if sdk_permissions:
                            put("sdk_control", raw_event)
                            if raw_event.get("type") == "result":
                                proc.stdin.close()
                        for sse_event in self._translator.translate(raw_event):
                            if ttft is None and sse_event.type in ("text", "thinking"):
                                ttft = time.monotonic() - t0
                            put("event", sse_event)
                    proc.wait()
                except Exception as exc:
                    put("failure", exc)
                finally:
                    self._terminate_process(proc)
                    proc.wait()
                    if stderr_thread is not None:
                        stderr_thread.join()
                    for stream in (proc.stdin, proc.stdout, proc.stderr):
                        if stream is not None and hasattr(stream, "close"):
                            stream.close()
                stderr_text = stderr_buffer.decode("utf-8", errors="replace").strip() if proc.returncode != 0 else ""
                put("result", (proc.returncode, stderr_text))

            async def receive_events():
                sdk_task = None
                permission_transport = None
                finished = asyncio.Event()

                async def write_control(data):
                    def write():
                        self._proc.stdin.write(data)
                        self._proc.stdin.flush()
                    await asyncio.to_thread(write)

                def sdk_done(task):
                    if not task.cancelled() and task.exception() is not None:
                        event_queue.put_nowait(("failure", task.exception()))

                try:
                    while True:
                        kind, payload = await event_queue.get()
                        if kind == "sdk_ready":
                            permission_transport = PermissionTransport(write_control)
                            sdk_task = asyncio.create_task(serve_permissions(
                                permission_transport, run_context, _stdin_message(), finished,
                                allowed_mcp_tools=extra.get("allowed_mcp_tools", []),
                            ))
                            sdk_task.add_done_callback(sdk_done)
                        elif kind == "sdk_control":
                            permission_transport.feed(payload)
                        elif kind == "event":
                            await event_callback(payload)
                        elif kind == "failure":
                            raise payload
                        elif kind == "result":
                            return payload
                finally:
                    finished.set()
                    if permission_transport is not None:
                        permission_transport.finish()
                    if sdk_task is not None:
                        sdk_task.cancel()
                        await asyncio.gather(sdk_task, return_exceptions=True)

            worker_done = loop.create_future()
            def run_worker():
                try:
                    worker()
                except Exception as exc:
                    put("failure", exc)
                finally:
                    loop.call_soon_threadsafe(worker_done.set_result, None)
            threading.Thread(target=run_worker, daemon=True).start()
            timed_out = False
            try:
                result = await asyncio.wait_for(receive_events(), timeout=max(0, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                timed_out = True
            finally:
                stop_requested.set()
                self._terminate_process(self._proc)
                await _await_process_cleanup(worker_done)
            if timed_out:
                await event_callback(RuntimeEvent(
                    type="error", content=f"智能体执行超时({timeout}秒)，已强制终止",
                    error_code="runtime_timeout",
                ))
                return -2, ""
            return result

        deferred_resume_events: list[RuntimeEvent] = []

        async def _defer_resume_terminal_event(evt: RuntimeEvent) -> None:
            if evt.type in {"error", "done"}:
                deferred_resume_events.append(evt)
                return
            await on_event(evt)

        if resume_id:
            exit_code, stderr = await _exec(
                _build_cmd(use_resume=True),
                _defer_resume_terminal_event,
            )
        else:
            exit_code, stderr = await _exec(_build_cmd(use_resume=False))

        resume_failure_text = "\n".join([
            stderr,
            *(evt.content for evt in deferred_resume_events if evt.content),
        ]).lower()
        resume_unavailable = (
            exit_code != 0
            and bool(resume_id)
            and (
                "no conversation found" in resume_failure_text
                or "--resume requires a valid session id" in resume_failure_text
            )
        )
        if resume_unavailable:
            await on_event(RuntimeEvent(
                type="info",
                content="会话已过期或不可用，已回退到 DB 历史上下文",
            ))
            prompt = _build_prompt_with_history(user_input, history)
            prompt_mode = "fallback_history"
            exit_code, stderr = await _exec(_build_cmd(use_resume=False))
        else:
            for evt in deferred_resume_events:
                await on_event(evt)

        self._log_turn_metrics(
            time.monotonic() - t0,
            ttft,
            prompt_mode=prompt_mode,
            prompt_chars=len(prompt),
            history_messages=history_messages,
            history_chars=history_chars,
        )

        if exit_code not in {0, -2}:
            stderr = strip_model_diagnostics(stderr)
            await on_event(RuntimeEvent(
                type="error",
                content=f"智能体退出码 {exit_code}: {stderr or '运行环境异常退出，请重试'}",
            ))
        # 兜底 done
        await on_event(RuntimeEvent(type="done", content=""))

    async def resume(
        self,
        config: RuntimeConfig,
        ctx: WorkspaceContext,
        session_id: str,
    ) -> AsyncGenerator[RuntimeEvent, None]:
        """恢复已有会话（需要使用 --resume + --continue）"""
        cmd = [
            *ctx.argv_prefix, ctx.claude_bin, "--resume", session_id, "--continue",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode", "acceptEdits",
        ]
        env = _build_runtime_env(config, ctx, color=False)
        stdin_env = _encode_tunneled_env(ctx, env)
        subprocess_env = _build_subprocess_env(ctx, env)

        self._translator = _StreamTranslator()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=ctx.run_cwd or None,
                env=subprocess_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            yield RuntimeEvent(type="error", content="claude 命令未找到")
            return

        if proc.stdin is not None:
            proc.stdin.write(stdin_env)
            await proc.stdin.drain()
            proc.stdin.close()
            try:
                await proc.stdin.wait_closed()
            except (AttributeError, OSError):
                pass

        oversized_notice_emitted = False
        async for line in _iter_jsonl_records(proc.stdout):
            if line is None:
                if not oversized_notice_emitted:
                    oversized_notice_emitted = True
                    yield RuntimeEvent(type="info", content=OVERSIZED_JSONL_NOTICE)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            for evt in self._translator.translate(raw):
                yield evt

        await proc.wait()
        yield RuntimeEvent(type="done", content="")

    async def cancel(self) -> None:
        """取消正在运行的任务"""
        self._terminate_process(self._proc)
