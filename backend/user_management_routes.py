"""Local user management endpoints backed by the local users table."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import CurrentUser, get_current_active_user, hash_password, user_profile_dict
from database import get_db
import models

router = APIRouter(prefix="/api/admin/user-management", tags=["user-management"])


class LocalUserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=4, max_length=255)
    first_name: str = Field(default="", max_length=150)
    email: str = Field(default="", max_length=255)
    is_superuser: bool = False
    is_active: bool = True


class LocalUserUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, max_length=150)
    email: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, min_length=4, max_length=255)
    is_superuser: Optional[bool] = None
    is_active: Optional[bool] = None


def _require_superuser(user: CurrentUser) -> None:
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="仅超级用户可管理用户")


@router.get("/")
def list_management_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    search: Optional[str] = Query(None, max_length=150),
    is_superuser: Optional[bool] = Query(None),
    user_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_superuser(current_user)
    query = db.query(models.User)
    if user_id is not None:
        query = query.filter(models.User.id == user_id)
    if is_superuser is not None:
        query = query.filter(models.User.is_superuser == is_superuser)
    search_text = (search or "").strip()
    if search_text:
        pattern = f"%{search_text}%"
        query = query.filter(
            or_(
                models.User.username.like(pattern),
                models.User.first_name.like(pattern),
                models.User.email.like(pattern),
            )
        )
    total = query.count()
    users = query.order_by(models.User.id.asc()).offset(skip).limit(limit).all()
    all_users = db.query(models.User).order_by(models.User.id.asc()).all()
    return {
        "total": total,
        "items": [{**user_profile_dict(u), "departments": []} for u in users],
        "department_options": [],
        "user_options": [
            {"id": u.id, "username": u.username, "first_name": u.first_name or ""}
            for u in all_users
        ],
    }


@router.post("/")
def create_management_user(
    body: LocalUserCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_superuser(current_user)
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if db.query(models.User.id).filter(models.User.username == username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = models.User(
        username=username,
        password_hash=hash_password(body.password),
        first_name=body.first_name.strip(),
        email=body.email.strip(),
        is_superuser=body.is_superuser,
        is_staff=body.is_superuser,
        is_active=body.is_active,
        roles=["admin"] if body.is_superuser else ["user"],
        permissions=["*"] if body.is_superuser else [],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_profile_dict(user)


@router.put("/{target_user_id}")
def update_management_user(
    target_user_id: int,
    body: LocalUserUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    _require_superuser(current_user)
    user = db.query(models.User).filter(models.User.id == target_user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.first_name is not None:
        user.first_name = body.first_name.strip()
    if body.email is not None:
        user.email = body.email.strip()
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.is_superuser is not None:
        if user.id == current_user.user_id and not body.is_superuser:
            raise HTTPException(status_code=400, detail="不能取消当前登录管理员的超级用户权限")
        user.is_superuser = body.is_superuser
        user.is_staff = body.is_superuser
        user.roles = ["admin"] if body.is_superuser else ["user"]
        user.permissions = ["*"] if body.is_superuser else []
    if body.is_active is not None:
        if user.id == current_user.user_id and not body.is_active:
            raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return user_profile_dict(user)
