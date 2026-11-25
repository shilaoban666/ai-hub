from datetime import datetime, timezone
from typing import Any, Optional, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "ok"
    timestamp: str = ""
    data: Optional[T] = None


def success(data: Any = None, message: str = "ok", code: int = 200) -> dict:
    return {
        "code": code,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def error(code: int, message: str, data: Any = None) -> dict:
    return {
        "code": code,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
