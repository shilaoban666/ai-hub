"""Short, intent-aware titles for new conversations."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from model_compat import ANTHROPIC_MESSAGES, OPENAI_COMPLETIONS, configured_model_protocol


logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 30
TITLE_REQUEST_TIMEOUT_SECONDS = 6.0

_GREETING_PATTERN = re.compile(
    r"^(?:hi+|hello+|hey+|你好|您好|哈喽|嗨|早上好|上午好|中午好|下午好|晚上好|在吗)[!！,.，。?？~～\s]*$",
    re.IGNORECASE,
)
_THANKS_PATTERN = re.compile(
    r"^(?:thanks?|thank\s+you|谢谢|感谢|多谢)[!！,.，。\s]*$",
    re.IGNORECASE,
)

_TITLE_SYSTEM_PROMPT = """你是会话标题生成器。根据用户的首条消息概括其真实意图。
只输出标题，不解释，不使用引号、句号或 Markdown。
中文标题控制在 4-12 个汉字，英文标题控制在 3-8 个单词。
不要机械复制原句；例如 hi、hello、你好统一概括为“简单问候”。"""


def _clean_input(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _known_intent_title(user_input: str) -> str | None:
    value = _clean_input(user_input)
    if _GREETING_PATTERN.fullmatch(value):
        return "简单问候"
    if _THANKS_PATTERN.fullmatch(value):
        return "表达感谢"
    return None


def normalize_session_title(value: str, fallback: str) -> str:
    title = _clean_input(value)
    title = re.sub(r"^<title>|</title>$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"^(?:标题|会话标题)\s*[:：]\s*", "", title).strip()
    title = title.strip("`#*'\"“”‘’《》 ")
    title = re.sub(r"[。.!！]+$", "", title).strip()
    if not title:
        return fallback
    if len(title) > TITLE_MAX_LENGTH:
        return title[: TITLE_MAX_LENGTH - 3].rstrip() + "..."
    return title


def fallback_session_title(user_input: str) -> str:
    known_title = _known_intent_title(user_input)
    if known_title:
        return known_title
    value = _clean_input(user_input) or "新对话"
    if len(value) > TITLE_MAX_LENGTH:
        return value[: TITLE_MAX_LENGTH - 3].rstrip() + "..."
    return value


def _completion_url(base_url: str | None, protocol: str) -> str:
    if protocol == ANTHROPIC_MESSAGES:
        base = (base_url or "https://api.anthropic.com").strip().rstrip("/")
        return f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"
    base = (base_url or "https://api.openai.com").strip().rstrip("/")
    return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"


def _response_text(payload: dict[str, Any], protocol: str) -> str:
    if protocol == ANTHROPIC_MESSAGES:
        content = payload.get("content")
        if isinstance(content, list):
            return "".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
        return str(content or "")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict)
        )
    return ""


async def generate_session_title(
    model,
    user_input: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Generate a title without adding a message to the agent conversation."""
    fallback = fallback_session_title(user_input)
    known_title = _known_intent_title(user_input)
    if known_title:
        return known_title

    protocol = configured_model_protocol(model)
    api_key = str(getattr(model, "api_key", "") or "").strip()
    model_name = str(getattr(model, "name", "") or "").strip()
    if not protocol or not api_key or not model_name:
        return fallback

    url = _completion_url(getattr(model, "api_proxy_url", None), protocol)
    prompt = f"用户首条消息：\n{_clean_input(user_input)[:2000]}"
    if protocol == ANTHROPIC_MESSAGES:
        headers = {
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": model_name,
            "max_tokens": 48,
            "system": _TITLE_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
    elif protocol == OPENAI_COMPLETIONS:
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {api_key}",
        }
        body = {
            "model": model_name,
            "max_tokens": 48,
            "messages": [
                {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
    else:
        return fallback

    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=TITLE_REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
    )
    try:
        if getattr(model, "scope", "user") == "platform":
            from model_gateway import _validate_resolved_addresses, validate_upstream_url

            url = validate_upstream_url(url)
            await _validate_resolved_addresses(url)
        response = await http.post(url, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return fallback
        return normalize_session_title(_response_text(payload, protocol), fallback)
    except Exception as exc:
        logger.info(
            "Conversation title generation fell back: model_id=%s error=%s",
            getattr(model, "id", None),
            type(exc).__name__,
        )
        return fallback
    finally:
        if owns_client:
            await http.aclose()
