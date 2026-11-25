"""Anthropic-compatible proxy for platform models using per-Run credentials."""

import asyncio
import ipaddress
import json
import socket

from agent_execution_lease import _run_sync_atomic
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
import httpx

from credit_billing import (
    CreditBillingError,
    abort_gateway_request,
    begin_gateway_request,
    finish_gateway_request,
    point_value,
    record_metered_usage,
    metered_run_snapshot,
)
from database import settings
from runtime_errors import safe_error_detail


router = APIRouter(prefix="/api/model-gateway", tags=["model-gateway"])


def validate_upstream_url(value: str) -> str:
    raw = (value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("平台模型 API Base URL 必须是无 userinfo 的 HTTPS 地址")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost":
        raise ValueError("平台模型 API Base URL 不允许本机地址")
    return raw


async def _validate_resolved_addresses(url: str) -> None:
    parsed = urlparse(url)
    port = parsed.port or 443
    try:
        infos = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        )
    except socket.gaierror as exc:
        raise CreditBillingError("平台模型域名解析失败", "UPSTREAM_DNS_FAILED") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise CreditBillingError("平台模型地址解析到非公网 IP", "UPSTREAM_ADDRESS_REJECTED")


def _credential_from_request(request: Request) -> str:
    token = request.headers.get("x-api-key", "").strip()
    if not token:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
    if not token.startswith("ahr_"):
        raise CreditBillingError("缺少有效 Run Credential", "INVALID_RUN_CREDENTIAL")
    return token


def _gateway_error(exc: Exception, status_code: int = 400) -> JSONResponse:
    code = getattr(exc, "code", "MODEL_GATEWAY_ERROR")
    return JSONResponse(
        status_code=status_code,
        content={
            "type": "error",
            "error": {"type": str(code).lower(), "message": f"[AIHub 模型网关] {safe_error_detail(str(exc))}"},
        },
    )


def _upstream_messages_url(base_url: str) -> str:
    base = validate_upstream_url(base_url)
    return f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"


def _upstream_auth_headers(base_url: str, api_key: str) -> dict[str, str]:
    """Use Anthropic's API-key header only for the official API endpoint."""
    host = (urlparse(validate_upstream_url(base_url)).hostname or "").lower().rstrip(".")
    if host == "api.anthropic.com":
        return {"x-api-key": api_key}
    return {"authorization": f"Bearer {api_key}"}


def _normalize_usage(value: dict | None) -> dict:
    usage = value or {}
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_read_tokens": int(
            usage.get("cache_read_input_tokens") or usage.get("cache_read_tokens") or 0
        ),
        "cache_creation_tokens": int(
            usage.get("cache_creation_input_tokens") or usage.get("cache_creation_tokens") or 0
        ),
    }


def _merge_usage(total: dict, value: dict | None) -> None:
    normalized = _normalize_usage(value)
    for key, amount in normalized.items():
        total[key] = max(total.get(key, 0), amount)


def _bounded_body(body: dict, context: dict) -> bytes:
    body["model"] = context["model_name"]
    if context.get("billing_mode") == "realtime":
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pricing = context["pricing"]
    output_rate = int(pricing["output_rate"] or 0)
    if output_rate > 0:
        output_budget = max(
            point_value(0),
            point_value(context["remaining_points"]) - point_value(context["input_upper_points"]),
        )
        max_output = int(output_budget * int(pricing["rate_scale"]) // output_rate)
        if max_output < 1:
            raise CreditBillingError("本次运行剩余额度不足", "RUN_BUDGET_EXHAUSTED")
        requested = int(body.get("max_tokens") or max_output)
        body["max_tokens"] = max(1, min(requested, max_output))
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _error_status(exc: CreditBillingError) -> int:
    if "BUDGET" in exc.code or "CREDIT" in exc.code:
        return 402
    if exc.code in {"CONCURRENT_MODEL_REQUEST", "RUN_TERMINATED"}:
        return 409
    if "CREDENTIAL" in exc.code:
        return 401
    return 400


def _connection_error(exc: httpx.HTTPError, request_id: str | None = None):
    timed_out = isinstance(exc, httpx.TimeoutException)
    return CreditBillingError(
        ("模型请求超时" if timed_out else "模型服务连接中断")
        + f": {type(exc).__name__}: {safe_error_detail(str(exc))}"
        + (f"; request_id={request_id}" if request_id else ""),
        "UPSTREAM_TIMEOUT" if timed_out else "UPSTREAM_CONNECTION_FAILED",
    )


def _upstream_error_content(content: bytes, status: int, request_id: str | None) -> bytes:
    detail = content.decode(errors="replace")
    error_type = "upstream_error"
    try:
        payload = json.loads(content)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            error_type = str(error.get("type") or error_type)
            detail = str(error.get("message") or detail)
        if not request_id and isinstance(payload, dict):
            request_id = payload.get("request_id")
    except (ValueError, TypeError):
        pass
    return json.dumps({"type": "error", "error": {
        "type": safe_error_detail(error_type),
        "message": safe_error_detail(detail)
            + f"\n[模型上游 HTTP {status}; request_id={request_id or '无'}]",
    }}, ensure_ascii=False).encode()


async def _while_funded(awaitable, context):
    """Interrupt even a silent upstream when a parallel request drains credit."""
    if context.get("billing_mode") != "realtime":
        return await awaitable
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.25)
            if done:
                return task.result()
            snapshot = await asyncio.to_thread(metered_run_snapshot, context["run_id"])
            if snapshot and snapshot["error_code"]:
                raise CreditBillingError(snapshot["error_message"], snapshot["error_code"])
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@router.post("/v1/messages")
async def anthropic_messages(request: Request):
    try:
        raw_token = _credential_from_request(request)
        raw_body = await request.body()
        if len(raw_body) > 10 * 1024 * 1024:
            raise CreditBillingError("模型请求体过大", "MODEL_REQUEST_TOO_LARGE")
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise CreditBillingError("模型请求不是有效 JSON", "INVALID_MODEL_REQUEST") from exc
        if not isinstance(body, dict):
            raise CreditBillingError("模型请求不是 JSON 对象", "INVALID_MODEL_REQUEST")
        context = await _run_sync_atomic(begin_gateway_request, raw_token, raw_body)
        if context["api_protocol"] != "anthropic-messages":
            raise CreditBillingError("平台模型协议与 Anthropic 网关不兼容", "MODEL_PROTOCOL_MISMATCH")
        bounded_body = _bounded_body(body, context)
        upstream_url = _upstream_messages_url(context["api_base_url"])
        await _validate_resolved_addresses(upstream_url)
    except CreditBillingError as exc:
        if "context" in locals():
            finish_gateway_request(
                context,
                _normalize_usage({}),
                {"gateway_rejected": True, "code": exc.code},
            )
        return _gateway_error(exc, _error_status(exc))
    except ValueError as exc:
        if "context" in locals():
            finish_gateway_request(
                context,
                _normalize_usage({}),
                {"gateway_rejected": True, "code": "INVALID_UPSTREAM_URL"},
            )
        return _gateway_error(exc, 400)

    upstream_headers = {
        "content-type": "application/json",
        "accept": "text/event-stream" if body.get("stream") else "application/json",
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
        **_upstream_auth_headers(context["api_base_url"], context["api_key"]),
    }
    beta = request.headers.get("anthropic-beta")
    if beta:
        upstream_headers["anthropic-beta"] = beta
    timeout = httpx.Timeout(float(settings.model_gateway_request_timeout_seconds))
    # Only retry connection establishment; replaying an accepted generation
    # after a read timeout could create duplicate work and charges.
    client = httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, trust_env=False,
        transport=httpx.AsyncHTTPTransport(retries=2, trust_env=False),
    )
    try:
        upstream_request = client.build_request(
            "POST", upstream_url, headers=upstream_headers, content=bounded_body
        )
        upstream = await _while_funded(
            client.send(upstream_request, stream=bool(body.get("stream"))), context,
        )
    except CreditBillingError as exc:
        await client.aclose()
        await _run_sync_atomic(abort_gateway_request, context, usage_unknown=True)
        return _gateway_error(exc, _error_status(exc))
    except asyncio.CancelledError:
        await client.aclose()
        await _run_sync_atomic(abort_gateway_request, context, usage_unknown=True)
        raise
    except httpx.HTTPError as exc:
        await client.aclose()
        await _run_sync_atomic(abort_gateway_request,
            context,
            usage_unknown=not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)),
        )
        return _gateway_error(_connection_error(exc), 504 if isinstance(exc, httpx.TimeoutException) else 502)

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in {"request-id", "anthropic-request-id"}
    }
    if not body.get("stream") or upstream.status_code >= 400:
        request_id = upstream.headers.get("request-id") or upstream.headers.get("anthropic-request-id")
        try:
            content = await _while_funded(upstream.aread(), context)
        except httpx.HTTPError as exc:
            await _run_sync_atomic(abort_gateway_request, context, usage_unknown=True)
            return _gateway_error(_connection_error(exc, request_id),
                                  504 if isinstance(exc, httpx.TimeoutException) else 502)
        except (CreditBillingError, asyncio.CancelledError) as exc:
            await _run_sync_atomic(abort_gateway_request, context, usage_unknown=True)
            if isinstance(exc, asyncio.CancelledError):
                raise
            return _gateway_error(exc, _error_status(exc))
        finally:
            await upstream.aclose()
            await client.aclose()
        usage = _normalize_usage({})
        raw_usage = {"provider_request_id": upstream.headers.get("request-id")}
        try:
            payload = json.loads(content)
            usage = _normalize_usage(payload.get("usage"))
            raw_usage.update({"response_id": payload.get("id"), "usage": payload.get("usage")})
        except (json.JSONDecodeError, AttributeError):
            raw_usage["parse_error"] = True
        if upstream.status_code >= 400:
            content = _upstream_error_content(content, upstream.status_code, request_id)
        await _run_sync_atomic(finish_gateway_request, context, usage, raw_usage)
        if context.get("billing_mode") == "realtime":
            snapshot = await asyncio.to_thread(metered_run_snapshot, context["run_id"])
            if snapshot and snapshot["error_code"]:
                exc = CreditBillingError(snapshot["error_message"], snapshot["error_code"])
                return _gateway_error(exc, _error_status(exc))
        return Response(
            content=content,
            status_code=upstream.status_code,
            media_type="application/json" if upstream.status_code >= 400 else upstream.headers.get("content-type", "application/json"),
            headers=response_headers,
        )

    async def stream_body():
        usage = _normalize_usage({})
        raw_events = []
        buffer = b""
        complete = False
        provider_request_id = upstream.headers.get("request-id") or upstream.headers.get("anthropic-request-id")
        iterator = upstream.aiter_bytes().__aiter__()

        async def consume_line(line):
            nonlocal provider_request_id, complete
            if not line.startswith(b"data:"):
                return
            data = line[5:].strip()
            if not data or data == b"[DONE]":
                return
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                return
            event_type = event.get("type")
            if event_type == "error":
                error = event.get("error") or {}
                if not isinstance(error, dict):
                    error = {"message": str(error)}
                raise CreditBillingError(
                    safe_error_detail(json.dumps(error, ensure_ascii=False))
                        + f"; request_id={provider_request_id or '无'}",
                    str(error.get("type") or "upstream_error"),
                )
            update = None
            if event_type == "message_start":
                message = event.get("message") or {}
                provider_request_id = message.get("id") or provider_request_id
                update = message.get("usage")
            elif event.get("usage"):
                update = event["usage"]
            if event_type == "message_stop":
                complete = True
            if len(raw_events) < 20 and event_type in {"message_start", "message_delta", "message_stop"}:
                raw_events.append(event)
            if update is not None:
                _merge_usage(usage, update)
                if context.get("billing_mode") == "realtime":
                    result = await _run_sync_atomic(
                        record_metered_usage, context, usage,
                        {"provider_request_id": provider_request_id},
                    )
                    if result["error_code"]:
                        raise CreditBillingError(result["error_message"], result["error_code"])

        try:
            while True:
                try:
                    chunk = await _while_funded(iterator.__anext__(), context)
                except StopAsyncIteration:
                    if buffer:
                        await consume_line(buffer.rstrip(b"\r"))
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    await consume_line(line.rstrip(b"\r"))
                # Persist usage before forwarding it; the CLI may immediately
                # start subagents or cancel its stream after this chunk.
                yield chunk
        except CreditBillingError as exc:
            event = {"type": "error", "error": {"type": exc.code.lower(), "message": str(exc)}}
            yield ("event: error\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
        except httpx.HTTPError as exc:
            error = _connection_error(exc, provider_request_id)
            event = {"type": "error", "error": {"type": error.code.lower(), "message": str(error)}}
            yield ("event: error\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
        finally:
            await upstream.aclose()
            await client.aclose()
            raw = {"provider_request_id": provider_request_id, "events": raw_events}
            if context.get("billing_mode") == "realtime":
                await _run_sync_atomic(record_metered_usage, context, usage, raw,
                                       terminal=True, usage_unknown=not complete)
            else:
                await _run_sync_atomic(finish_gateway_request, context, usage, raw)

    return StreamingResponse(
        stream_body(),
        status_code=upstream.status_code,
        media_type="text/event-stream",
        headers=response_headers,
    )
