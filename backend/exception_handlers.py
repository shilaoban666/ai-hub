from datetime import datetime, timezone
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger("aihub.exception")


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    headers = dict(exc.headers or {})
    if exc.status_code == 503:
        # Distinguish business dependency failures from a gateway outage.
        headers['X-AIHub-Error'] = 'business'
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("message", str(detail))
        data = detail.get("data")
    else:
        message = str(detail)
        data = None
    if request is not None and request.url.path.startswith("/api/open/agents/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.status_code, "message": message}},
            headers=headers or None,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        },
        headers=headers or None,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/open/agents/"):
        return JSONResponse(status_code=422, content={"error": {"code": 422, "message": "请求参数验证失败"}})
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "请求参数验证失败",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": exc.errors(),
        },
    )


async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API exception: %s %s", request.method, request.url.path)
    if request.url.path.startswith("/api/open/agents/"):
        return JSONResponse(status_code=500, content={"error": {"code": 500, "message": "服务器内部错误"}})
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "服务器内部错误",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": None,
        },
    )
