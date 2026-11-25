import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from fnmatch import fnmatch
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db, settings
import models

logger = logging.getLogger("aihub.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

PBKDF2_ITERATIONS = 120_000


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${_b64url_encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iter_str, salt, expected = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    )
    return hmac.compare_digest(_b64url_encode(digest), expected)


def _encode_jwt(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def _decode_jwt(token: str, expected_type: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(
            settings.jwt_secret_key.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(_b64url_encode(expected_sig), sig_b64):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        if payload.get("type") != expected_type:
            return None
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)) or exp < time.time():
            return None
        return payload
    except Exception:
        return None


def create_access_token(user: models.User) -> str:
    now = int(time.time())
    return _encode_jwt({
        "sub": str(user.id),
        "username": user.username,
        "type": "access",
        "iat": now,
        "exp": now + max(1, settings.jwt_access_token_expire_minutes) * 60,
    })


def create_refresh_token(user: models.User) -> str:
    now = int(time.time())
    return _encode_jwt({
        "sub": str(user.id),
        "type": "refresh",
        "iat": now,
        "exp": now + max(1, settings.jwt_refresh_token_expire_days) * 86400,
    })


class CurrentUser:
    def __init__(self, user_id: int, is_superuser: bool = False, permissions: list = None):
        self.user_id = user_id
        self.username = ""
        self.first_name = ""
        self.email = ""
        self.is_staff = False
        self.is_superuser = is_superuser
        self.roles = []
        self.permissions = permissions or []

    def has_permission(self, permission: str) -> bool:
        if self.is_superuser:
            return True
        return any(fnmatch(permission, value) for value in self.permissions)

    def has_role(self, role: str) -> bool:
        return self.is_superuser or role in self.roles


def _user_to_current_user(user: models.User) -> CurrentUser:
    current = CurrentUser(
        user_id=user.id,
        is_superuser=bool(user.is_superuser),
        permissions=list(user.permissions or []),
    )
    current.username = user.username or ""
    current.first_name = user.first_name or ""
    current.email = user.email or ""
    current.is_staff = bool(user.is_staff)
    current.roles = list(user.roles or [])
    return current


def user_profile_dict(user: models.User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name or "",
        "email": user.email or "",
        "is_active": bool(user.is_active),
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
        "roles": list(user.roles or []),
        "permissions": list(user.permissions or []),
    }


def ensure_default_admin(db: Session) -> None:
    """Create the default local admin user when the users table is empty."""
    if db.query(models.User.id).first() is not None:
        return
    username = (settings.default_admin_username or "admin").strip() or "admin"
    password = settings.default_admin_password or "admin123"
    admin = models.User(
        username=username,
        password_hash=hash_password(password),
        first_name="管理员",
        email="admin@localhost",
        is_active=True,
        is_staff=True,
        is_superuser=True,
        roles=["admin"],
        permissions=["*"],
    )
    db.add(admin)
    db.commit()
    logger.info("Initialized default local admin user: %s", username)


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> CurrentUser:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = _decode_jwt(token, "access")
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return _user_to_current_user(user)


async def get_current_active_user(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    return current_user


def require_permission(permission: str):
    async def checker(current_user: CurrentUser = Depends(get_current_user)):
        if not current_user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission} required",
            )
        return current_user
    return checker


def require_role(role: str):
    async def checker(current_user: CurrentUser = Depends(get_current_user)):
        if not current_user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {role}",
            )
        return current_user
    return checker


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1, max_length=255)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    username = body.username.strip()
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
        "user": user_profile_dict(user),
    }


@router.post("/refresh")
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    payload = _decode_jwt(body.refresh_token, "refresh")
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的刷新凭证")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
    }


@router.post("/logout")
def logout():
    return {"ok": True}


@router.get("/me")
def get_me(
    current_user: CurrentUser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == current_user.user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user_profile_dict(user)
