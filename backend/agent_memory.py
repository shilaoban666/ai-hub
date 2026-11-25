"""智能体会话记忆管理

负责:
  - 加载/保存历史消息
  - 智能压缩（保留最近 N 条 + 摘要旧消息）
  - Claude Code session ID 管理
  - Token 估算
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from models import AgentMessage, AgentSession
from message_content import unpack_user_content


logger = logging.getLogger(__name__)

MAX_THINKING_CHARS = 2_000
MAX_TEXT_CHARS = 40_000
MAX_TOOL_RESULT_CHARS = 12_000
MAX_TOOL_INPUT_CHARS = 4_000
MAX_ASSISTANT_MESSAGE_BYTES = 500_000
FALLBACK_ASSISTANT_MESSAGE_BYTES = 60_000
DEFAULT_HISTORY_MESSAGES = 200
DEFAULT_HISTORY_TOKENS = 120_000
HISTORY_RECENT_RATIO = 0.78
HISTORY_EXCERPT_CHARS = 600


def _extract_tool_result_html(value) -> str:
    """Keep the displayed HTML independently of truncated diagnostic output."""
    if isinstance(value, str):
        source = value.strip()
        if not source.startswith(("{", "[")):
            return ""
        try:
            value = json.loads(source)
        except (ValueError, TypeError):
            return ""
    if isinstance(value, dict):
        for field in ("s_html", "html"):
            html = value.get(field)
            if isinstance(html, str) and html.strip():
                return html
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return ""
    for child in children:
        html = _extract_tool_result_html(child)
        if html:
            return html
    return ""


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文 ~1.5 字符/token，英文 ~4 字符/token）"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    other_chars = len(text) - chinese_chars
    return max(1, int(chinese_chars / 1.5 + other_chars / 4))


class AgentMemory:
    """智能体会话记忆管理"""

    def __init__(self, db: Session, session_id: int):
        self.db = db
        self.session_id = session_id
        self.history_info = {
            "compacted": False,
            "loaded_messages": 0,
            "included_messages": 0,
            "compacted_messages": 0,
            "older_history_omitted": False,
            "estimated_tokens": 0,
        }
        self._session = db.query(AgentSession).filter(
            AgentSession.id == session_id,
            AgentSession.is_deleted == False,
        ).first()

    @property
    def is_valid(self) -> bool:
        return self._session is not None

    def load_history(
        self,
        max_messages: int = DEFAULT_HISTORY_MESSAGES,
        max_context_tokens: int = DEFAULT_HISTORY_TOKENS,
    ) -> list[dict]:
        """加载历史消息，并在超出预算时生成一个可读的早期历史摘要。"""
        if not self._session:
            return []

        newest_first = (
            self.db.query(AgentMessage)
            .filter(AgentMessage.session_id == self.session_id)
            .order_by(AgentMessage.id.desc())
            .limit(max_messages + 1)
            .all()
        )
        omitted_by_limit = len(newest_first) > max_messages
        messages = list(reversed(newest_first[:max_messages]))

        result = []
        total_tokens = 0

        for msg in messages:
            content = msg.content or ""
            if msg.role == "user":
                user_content = unpack_user_content(content)
                content = user_content["content"] or ""
                links = [path for path in user_content["attached_files"] if path.startswith("https://")]
                if links:
                    content += "\n\n图片公网链接：\n" + "\n".join(links)
            result.append({"role": msg.role, "content": content})
            total_tokens += estimate_tokens(content)

        compacted_count = 0
        if total_tokens > max_context_tokens:
            result, compacted_count = self._compress_history_with_stats(
                result,
                max_context_tokens,
                older_messages_omitted=omitted_by_limit,
            )
        elif omitted_by_limit:
            result.insert(0, {
                "role": "system",
                "content": "[上下文说明] 当前仅载入最近的对话消息，更早内容未进入本轮上下文。",
            })

        self.history_info = {
            "compacted": bool(compacted_count or omitted_by_limit),
            "loaded_messages": len(messages),
            "included_messages": sum(1 for item in result if item.get("role") != "system"),
            "compacted_messages": compacted_count,
            "older_history_omitted": omitted_by_limit,
            "estimated_tokens": sum(estimate_tokens(item.get("content", "")) for item in result),
        }

        return result

    def _compress_history(
        self,
        messages: list[dict],
        total_tokens: int,
        max_tokens: int,
    ) -> list[dict]:
        """兼容旧调用点；压缩统计由 ``load_history`` 记录。"""
        del total_tokens
        result, _ = self._compress_history_with_stats(messages, max_tokens)
        return result

    def _compress_history_with_stats(
        self,
        messages: list[dict],
        max_tokens: int,
        *,
        older_messages_omitted: bool = False,
    ) -> tuple[list[dict], int]:
        """保留最近消息，并将更早内容压成一个有边界说明的可读摘要。"""
        if not messages:
            return [], 0

        token_budget = max(1_000, int(max_tokens or DEFAULT_HISTORY_TOKENS))
        recent_budget = max(750, int(token_budget * HISTORY_RECENT_RATIO))
        recent_reversed: list[dict] = []
        recent_tokens = 0

        for message in reversed(messages):
            content = message.get("content", "") or ""
            cost = estimate_tokens(content)
            if recent_reversed and recent_tokens + cost > recent_budget:
                break
            if cost > recent_budget:
                message = {
                    **message,
                    "content": self._truncate_history_text(content, recent_budget),
                }
                cost = estimate_tokens(message["content"])
            recent_reversed.append(message)
            recent_tokens += cost
            if recent_tokens >= recent_budget:
                break

        recent = list(reversed(recent_reversed))
        early_count = max(0, len(messages) - len(recent))
        early = messages[:early_count]
        result: list[dict] = []
        if early or older_messages_omitted:
            summary_budget = max(250, token_budget - recent_tokens)
            result.append({
                "role": "system",
                "content": self._build_history_summary(
                    early,
                    summary_budget,
                    older_messages_omitted=older_messages_omitted,
                ),
            })
        result.extend(recent)
        return result, early_count

    def _build_history_summary(
        self,
        messages: list[dict],
        max_tokens: int,
        *,
        older_messages_omitted: bool,
    ) -> str:
        excerpts = [self._history_excerpt(message) for message in messages]
        excerpts = [excerpt for excerpt in excerpts if excerpt]
        max_chars = max(500, max_tokens * 2)
        header = (
            f"[较早对话摘要，共 {len(messages)} 条消息。以下内容是压缩记录，"
            "最近对话保留原文。]\n"
        )
        if older_messages_omitted:
            header += "[存储中还有更早消息未载入本轮上下文。]\n"

        selected: list[str] = []
        used = len(header)
        for excerpt in excerpts:
            if used + len(excerpt) + 1 > max_chars:
                break
            selected.append(excerpt)
            used += len(excerpt) + 1

        omitted_excerpts = len(excerpts) - len(selected)
        footer = (
            f"\n[摘要中另有 {omitted_excerpts} 条较早消息因预算省略。]"
            if omitted_excerpts > 0
            else ""
        )
        return (header + "\n".join(selected) + footer)[:max_chars]

    def _history_excerpt(self, message: dict) -> str:
        role = message.get("role", "")
        content = message.get("content", "") or ""
        label = {"user": "用户", "assistant": "助手", "system": "系统"}.get(role, role or "消息")
        if role == "assistant" and content.lstrip().startswith("{"):
            try:
                payload = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                payload = None
            blocks = payload.get("blocks") if isinstance(payload, dict) else None
            if isinstance(blocks, list):
                parts = []
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    if block_type == "text" and block.get("content"):
                        parts.append(str(block["content"]))
                    elif block_type == "tool_use":
                        parts.append(f"[调用 {block.get('name') or '工具'}]")
                    elif block_type == "tool_result" and block.get("is_error"):
                        parts.append(f"[工具失败: {block.get('content', '')}]")
                content = "\n".join(parts)
        content = " ".join(str(content).split())
        if not content:
            return ""
        if len(content) > HISTORY_EXCERPT_CHARS:
            head = int(HISTORY_EXCERPT_CHARS * 0.72)
            tail = HISTORY_EXCERPT_CHARS - head
            content = f"{content[:head]} … {content[-tail:]}"
        return f"{label}: {content}"

    @staticmethod
    def _truncate_history_text(text: str, max_tokens: int) -> str:
        max_chars = max(200, max_tokens * 2)
        if len(text) <= max_chars:
            return text
        marker = "\n[消息中段因上下文预算省略]\n"
        available = max(2, max_chars - len(marker))
        head = int(available * 0.7)
        return text[:head] + marker + text[-(available - head):]

    def save_user_message(self, content: str) -> AgentMessage:
        """保存用户消息"""
        msg = AgentMessage(
            session_id=self.session_id,
            role="user",
            content=content,
        )
        self.db.add(msg)
        self.db.commit()
        self._update_session_stats()
        return msg

    def save_assistant_message(
        self,
        blocks: list[dict],
        usage: dict | None = None,
        duration_ms: int | None = None,
    ) -> AgentMessage | None:
        """保存助手消息（blocks 格式）"""
        payload = {"blocks": self._compact_blocks(blocks)}
        if usage:
            payload["usage"] = usage
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        content = self._dump_payload_with_limit(payload, MAX_ASSISTANT_MESSAGE_BYTES)
        msg = self._create_message("assistant", content)
        try:
            self.db.add(msg)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            logger.warning(
                "Assistant message save failed, retrying with compact payload: session_id=%s",
                self.session_id,
                exc_info=True,
            )
        else:
            self._safe_update_session_stats("assistant")
            return msg

        fallback_payload = {
            "blocks": self._compact_blocks(blocks, aggressive=True),
            "truncated": True,
        }
        if usage:
            fallback_payload["usage"] = usage
        if duration_ms is not None:
            fallback_payload["duration_ms"] = duration_ms
        msg = AgentMessage(
            session_id=self.session_id,
            role="assistant",
            content=self._dump_payload_with_limit(
                fallback_payload,
                FALLBACK_ASSISTANT_MESSAGE_BYTES,
            ),
        )
        try:
            self.db.add(msg)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            logger.error(
                "Assistant message fallback save failed: session_id=%s",
                self.session_id,
                exc_info=True,
            )
            return None
        self._safe_update_session_stats("assistant_fallback")
        return msg

    def save_system_message(self, content: str) -> AgentMessage:
        """保存系统消息"""
        msg = AgentMessage(
            session_id=self.session_id,
            role="system",
            content=content,
        )
        self.db.add(msg)
        self.db.commit()
        return msg

    def _create_message(self, role: str, content: str) -> AgentMessage:
        """创建消息 ORM 对象，调用方负责提交事务。"""
        return AgentMessage(
            session_id=self.session_id,
            role=role,
            content=content,
        )

    def _compact_blocks(self, blocks: list[dict], aggressive: bool = False) -> list[dict]:
        """压缩助手 blocks，避免 thinking/tool_result 无限写入数据库。"""
        compacted = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "thinking":
                content = block.get("content", "")
                limit = 400 if aggressive else MAX_THINKING_CHARS
                compacted_block = {
                    "type": "thinking",
                    "content": self._truncate_text(content, limit),
                }
                self._copy_duration(block, compacted_block)
                compacted.append(compacted_block)
            elif block_type == "text":
                content = block.get("content", "")
                limit = 4_000 if aggressive else MAX_TEXT_CHARS
                compacted.append({
                    "type": "text",
                    "content": self._truncate_text(content, limit),
                })
            elif block_type == "tool_result":
                content = block.get("content", "")
                limit = 2_000 if aggressive else MAX_TOOL_RESULT_CHARS
                compacted_block = {
                    "type": "tool_result",
                    "tool_use_id": block.get("tool_use_id", ""),
                    "content": self._truncate_text(content, limit),
                    "is_error": bool(block.get("is_error", False)),
                }
                html = block.get("resultHtml")
                if not isinstance(html, str) or not html.strip():
                    html = _extract_tool_result_html(content) if compacted_block["content"] != content else ""
                if html:
                    # Never cut markup or its containing JSON. The overall
                    # message byte budget still applies in _dump_payload_with_limit.
                    compacted_block["resultHtml"] = html
                compacted.append(compacted_block)
            elif block_type == "tool_use":
                compacted_block = {
                    "type": "tool_use",
                    "name": block.get("name", ""),
                    "input": self._compact_value(block.get("input", {}), aggressive=aggressive),
                    "tool_use_id": block.get("tool_use_id", ""),
                }
                self._copy_duration(block, compacted_block)
                compacted.append(compacted_block)
            elif block_type == "usage":
                compacted.append(block)
            elif block_type == "artifacts":
                compacted.append({"type": "artifacts", "files": block.get("files", [])})
            elif block_type == "error":
                from runtime_errors import safe_error_detail

                metadata = block.get("metadata") or {}
                compacted.append({
                    "type": "error",
                    "content": safe_error_detail(str(block.get("content") or "")),
                    "error_code": block.get("error_code") or "runtime_error",
                    "metadata": {
                        "error_origin": metadata.get("error_origin") or "unknown",
                        "error_detail": safe_error_detail(str(metadata.get("error_detail") or block.get("content") or "")),
                    },
                })
        return compacted

    @staticmethod
    def _copy_duration(source: dict, target: dict) -> None:
        duration_ms = source.get("duration_ms")
        if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool):
            target["duration_ms"] = max(0, round(duration_ms))

    def _compact_value(self, value, aggressive: bool = False):
        """递归压缩工具输入，保留结构但限制长字符串。"""
        limit = 800 if aggressive else MAX_TOOL_INPUT_CHARS
        if isinstance(value, str):
            return self._truncate_text(value, limit)
        if isinstance(value, list):
            return [self._compact_value(item, aggressive=aggressive) for item in value[:50]]
        if isinstance(value, dict):
            return {
                str(key): self._compact_value(item, aggressive=aggressive)
                for key, item in list(value.items())[:50]
            }
        return value

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        """按字符数截断文本并保留原长度提示。"""
        if not isinstance(text, str):
            text = str(text)
        if len(text) <= max_chars:
            return text
        return (
            text[:max_chars]
            + f"\n\n[... 已截断，原长度 {len(text)} 字符 ...]"
        )

    @staticmethod
    def _dump_payload_with_limit(payload: dict, max_bytes: int) -> str:
        """序列化 payload；超过字节上限时降级成摘要，避免数据库写入失败。"""
        content = json.dumps(payload, ensure_ascii=False)
        content_bytes = content.encode("utf-8")
        if len(content_bytes) <= max_bytes:
            return content
        summary: dict = {
            "blocks": [
                {
                    "type": "text",
                    "content": (
                        "[助手消息过长，已压缩保存。"
                        f"原始大小约 {len(content_bytes)} bytes。]"
                    ),
                }
            ],
            "truncated": True,
        }
        # 保留 usage 和 duration_ms，避免截断后 Token 用量和耗时丢失
        for key in ("usage", "duration_ms"):
            if key in payload:
                summary[key] = payload[key]
        # Keep file links even when text is summarized, while respecting the
        # existing message size budget for unusually large file lists.
        artifact_block = {"type": "artifacts", "files": []}
        summary["blocks"].append(artifact_block)
        remaining = max_bytes - len(json.dumps(summary, ensure_ascii=False).encode("utf-8"))
        for block in payload.get("blocks", []):
            if block.get("type") != "artifacts":
                continue
            for file in block.get("files", []):
                cost = len(json.dumps(file, ensure_ascii=False).encode("utf-8")) + 2
                if cost <= remaining:
                    artifact_block["files"].append(file)
                    remaining -= cost
        if not artifact_block["files"]:
            summary["blocks"].pop()
        return json.dumps(summary, ensure_ascii=False)

    def _update_session_stats(self) -> None:
        """更新会话统计信息"""
        if not self._session:
            return
        count = (
            self.db.query(AgentMessage)
            .filter(AgentMessage.session_id == self.session_id)
            .count()
        )
        now = datetime.now(timezone.utc)
        self._session.message_count = count
        self._session.last_message_at = now
        self._session.updated_at = now
        self.db.commit()

    def _safe_update_session_stats(self, source: str) -> None:
        """更新会话统计；失败时只记录日志，不影响消息保存结果。"""
        try:
            self._update_session_stats()
        except SQLAlchemyError:
            self.db.rollback()
            logger.warning(
                "Agent session stats update failed: session_id=%s source=%s",
                self.session_id,
                source,
                exc_info=True,
            )

    def get_runtime_session_id(self) -> str | None:
        """获取 runtime 内部会话 ID（用于 --resume 等）"""
        if not self._session:
            return None
        return self._session.runtime_session_id or self._session.claude_session_id

    def set_runtime_session_id(self, session_id: str) -> None:
        """保存 runtime 内部会话 ID"""
        if not self._session:
            return
        self._session.runtime_session_id = session_id
        self.db.commit()

    def get_first_message(self) -> str:
        """获取首条消息（用作会话标题）"""
        first = (
            self.db.query(AgentMessage)
            .filter(AgentMessage.session_id == self.session_id)
            .order_by(AgentMessage.id)
            .first()
        )
        if first and first.content:
            content = unpack_user_content(first.content)["content"] if first.role == "user" else first.content
            return content[:50] + ("..." if len(content) > 50 else "")
        return "新对话"
