import json
from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

HTTP_MESSAGES = {
    200: "ok",
    201: "created",
    204: "no content",
}

STANDARD_KEYS = {"code", "message", "timestamp", "data"}


class ResponseWrapperMiddleware(BaseHTTPMiddleware):
    """Wrap all JSON success responses into {code, message, timestamp, data} format."""

    # Paths whose responses must not be wrapped (used by Swagger UI / ReDoc)
    _SKIP_PATHS = {"/openapi.json", "/docs", "/redoc"}

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        if request.url.path.startswith("/api/open/agents/"):
            response.headers["cache-control"] = "no-store, max-age=0"
            response.headers["referrer-policy"] = "no-referrer"
            return response

        # Model gateway responses must remain byte-for-byte provider compatible.
        if request.url.path.startswith("/api/model-gateway/"):
            return response

        if request.url.path.startswith("/api/public/conversation-shares/"):
            response.headers["cache-control"] = "no-store, max-age=0"
            response.headers["pragma"] = "no-cache"
        if request.url.path.startswith("/api/public/hierarchy-boards/"):
            response.headers["cache-control"] = "no-store, max-age=0"
            response.headers["pragma"] = "no-cache"
        if request.url.path.startswith("/api/public/data-tables/"):
            response.headers["cache-control"] = "no-store, max-age=0"
            response.headers["pragma"] = "no-cache"
        if request.url.path.startswith("/api/assets/mcp/") and request.url.path.endswith("/headers"):
            response.headers["cache-control"] = "no-store, max-age=0"
            response.headers["pragma"] = "no-cache"

        # Don't wrap OpenAPI schema or docs pages
        if request.url.path in self._SKIP_PATHS:
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        if response.status_code >= 400:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="application/json",
            )

        if isinstance(data, dict) and STANDARD_KEYS.issubset(data.keys()):
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="application/json",
            )

        wrapped = {
            "code": response.status_code,
            "message": HTTP_MESSAGES.get(response.status_code, "ok"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }

        headers = dict(response.headers)
        headers["content-length"] = str(len(json.dumps(wrapped, ensure_ascii=False).encode("utf-8")))
        return Response(
            content=json.dumps(wrapped, ensure_ascii=False).encode("utf-8"),
            status_code=response.status_code,
            headers=headers,
            media_type="application/json",
        )
