"""Reply feedback and the enterprise feedback inbox."""

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from auth import CurrentUser, get_current_active_user
from database import get_db
from feedback_notifications import FeedbackNotificationError, sync_assignment_notification, sync_resolution_notification
from message_content import unpack_user_content
from models import Agent, AgentMessage, AgentMessageFeedback, AgentSession

ASSISTANT_KIND = "personal_default"


def _feedback_counts():
    return (
        func.count(AgentMessageFeedback.id).label("feedback_count"),
        func.coalesce(func.sum(case((AgentMessageFeedback.rating == "like", 1), else_=0)), 0).label("likes"),
        func.coalesce(func.sum(case((AgentMessageFeedback.rating == "dislike", 1), else_=0)), 0).label("dislikes"),
        func.coalesce(func.sum(case((
            (AgentMessageFeedback.rating == "dislike") & (AgentMessageFeedback.processing_status == "resolved"),
            1,
        ), else_=0)), 0).label("resolved"),
    )


router = APIRouter(prefix="/api/feedback", tags=["feedback"])
FEEDBACK_TIME_ZONE = timezone(timedelta(hours=8))

Reason = Literal["误解了我的问题", "上下文理解错误", "回答模糊/不具体", "代码有错误", "回答不专业", "代码格式问题", "其他原因"]


class FeedbackInput(BaseModel):
    rating: Literal["like", "dislike"]
    reasons: list[Reason] = Field(default_factory=list, max_length=7)
    comment: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_details(self):
        self.comment = self.comment.strip()
        self.reasons = list(dict.fromkeys(self.reasons))
        if self.rating == "like":
            self.reasons = []
            self.comment = ""
        return self


class FeedbackProcessingInput(BaseModel):
    action: Literal["assignment", "processing"] = "processing"
    processing_status: Optional[Literal["pending", "resolved"]] = None
    processing_remark: str = Field(default="", max_length=2000)
    processing_images: list[str] = Field(default_factory=list, max_length=10)
    assignee_user_id: Optional[int] = Field(default=None, ge=1)
    assignee_username: str = Field(default="", max_length=200)
    assignee_name: str = Field(default="", max_length=200)
    detail_url: str = Field(default="", max_length=255)

    @model_validator(mode="after")
    def validate_detail_url(self):
        self.processing_remark = self.processing_remark.strip()
        for image in self.processing_images:
            parsed_image = urlsplit(image)
            if not image.startswith('/uploads/images/') and (parsed_image.scheme != 'https' or not parsed_image.netloc):
                raise ValueError("处理截图地址无效")
        self.detail_url = self.detail_url.strip()
        if self.detail_url:
            parsed = urlsplit(self.detail_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError("详情链接必须是有效的 HTTP(S) 地址")
        return self


def feedback_value(row):
    return {"rating": row.rating, "reasons": json.loads(row.reasons), "comment": row.comment} if row else None


def _owned_message(db, message_id, user):
    # Lock the existing session even on the first vote, serializing insert/update/delete.
    session = db.query(AgentSession).join(AgentMessage, AgentMessage.session_id == AgentSession.id).filter(
        AgentMessage.id == message_id, AgentMessage.role == "assistant",
        AgentSession.user_id == user.user_id, AgentSession.is_deleted == False,
        AgentSession.source == "web",
    ).with_for_update().first()
    if session is None:
        raise HTTPException(404, "回复不存在或无权反馈")
    return session


@router.put("/messages/{message_id}")
def save_feedback(message_id: int, body: FeedbackInput, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(get_current_active_user)):
    session = _owned_message(db, message_id, user)
    row = db.query(AgentMessageFeedback).filter_by(user_id=user.user_id, message_id=message_id).with_for_update().first()
    if row is None:
        row = AgentMessageFeedback(user_id=user.user_id, message_id=message_id, session_id=session.id)
        db.add(row)
    changed = (row.rating != body.rating or row.reasons != json.dumps(body.reasons, ensure_ascii=False)
               or row.comment != body.comment)
    if body.rating == "like":
        row.processing_status = None
        row.assignee_user_id = None
        row.assignee_username = None
        row.assignee_name = None
    elif changed or not row.processing_status:
        # A changed complaint needs review again; an identical retry preserves work.
        row.processing_status = "pending"
    row.username = (user.username or "")[:200]
    row.display_name = (user.first_name or user.username or f"用户 {user.user_id}")[:200]
    row.session_title = session.title or "未命名对话"
    row.rating = body.rating
    row.reasons = json.dumps(body.reasons, ensure_ascii=False)
    row.comment = body.comment
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return feedback_value(row)


@router.delete("/messages/{message_id}")
def remove_feedback(message_id: int, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(get_current_active_user)):
    _owned_message(db, message_id, user)
    db.query(AgentMessageFeedback).filter_by(user_id=user.user_id, message_id=message_id).delete()
    db.commit()
    return {"message": "已撤回反馈"}


def _admin(user: CurrentUser = Depends(get_current_active_user)):
    if not user.is_superuser:
        raise HTTPException(403, "仅超级管理员可查看用户反馈")
    return user


def _iso(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None


def _record(row):
    return {
        "id": row.id, "session_id": row.session_id, "message_id": row.message_id,
        "user_id": row.user_id, "username": row.username, "display_name": row.display_name,
        "session_title": row.session_title, **feedback_value(row),
        "processing_status": ("resolved" if row.processing_status == "resolved" else "pending") if row.rating == "dislike" else None,
        "processing_remark": row.processing_remark or "",
        "processing_images": json.loads(row.processing_images or "[]"),
        "assignee_user_id": row.assignee_user_id,
        "assignee_username": row.assignee_username, "assignee_name": row.assignee_name,
        "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
    }


def _filter_feedback_dates(query, start_date, end_date):
    """Filter UTC timestamps by inclusive Beijing calendar dates."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "开始日期不能晚于结束日期")
    if start_date:
        start_at = datetime.combine(start_date, time.min, FEEDBACK_TIME_ZONE)
        query = query.filter(AgentMessageFeedback.created_at >= start_at.astimezone(timezone.utc).replace(tzinfo=None))
    if end_date:
        # Include the entire end date, including fractional seconds.
        end_at = datetime.combine(end_date, time.max, FEEDBACK_TIME_ZONE)
        query = query.filter(AgentMessageFeedback.created_at <= end_at.astimezone(timezone.utc).replace(tzinfo=None))
    return query


def _filter_processing_status(query, processing_status):
    if not processing_status:
        return query
    query = query.filter(AgentMessageFeedback.rating == "dislike")
    if processing_status == "resolved":
        return query.filter(AgentMessageFeedback.processing_status == "resolved")
    # Historical in-progress and missing statuses are outstanding complaints.
    return query.filter(func.coalesce(AgentMessageFeedback.processing_status, "pending") != "resolved")


def _feedback_page(query, skip, limit):
    counts = query.with_entities(*_feedback_counts()).one()
    summary = {key: int(value or 0) for key, value in counts._mapping.items()}
    summary["resolution_rate"] = summary["resolved"] / summary["dislikes"] if summary["dislikes"] else None
    rows = query.order_by(AgentMessageFeedback.created_at.desc(), AgentMessageFeedback.id.desc()).offset(skip).limit(limit).all()
    return {"total": summary["feedback_count"], "summary": summary, "items": [_record(row) for row in rows]}


@router.get("")
def list_feedback(start_date: Optional[date] = Query(None), end_date: Optional[date] = Query(None),
                  xiaoqu_only: bool = False, department: Optional[str] = Query(None, max_length=2000),
                  authorization: Optional[str] = Header(None),
                  rating: Optional[Literal["like", "dislike"]] = None,
                  processing_status: Optional[Literal["pending", "resolved"]] = None,
                  assigned: Optional[bool] = None,
                  creator_user_id: Optional[int] = Query(None, ge=1),
                  assignee_user_id: Optional[int] = Query(None, ge=1),
                  creator: str = Query("", max_length=200), assignee: str = Query("", max_length=200),
                  search: str = Query("", max_length=200), skip: int = Query(0, ge=0),
                  limit: int = Query(16, ge=1, le=100), db: Session = Depends(get_db),
                  user: CurrentUser = Depends(_admin)):
    query = db.query(AgentMessageFeedback)
    if creator_user_id is not None:
        query = query.filter(AgentMessageFeedback.user_id == creator_user_id)
    if assignee_user_id is not None:
        query = query.filter(AgentMessageFeedback.assignee_user_id == assignee_user_id)
    if xiaoqu_only:
        assistant_ids = db.query(AgentSession.id).join(Agent, Agent.id == AgentSession.agent_id).filter(Agent.kind == ASSISTANT_KIND)
        query = query.filter(AgentMessageFeedback.session_id.in_(assistant_ids))
    if assigned is not None:
        query = query.filter(AgentMessageFeedback.assignee_user_id.isnot(None) if assigned
                             else AgentMessageFeedback.assignee_user_id.is_(None))
    if rating:
        query = query.filter(AgentMessageFeedback.rating == rating)
    query = _filter_processing_status(query, processing_status)
    for term, name, username, identity in (
        (creator, AgentMessageFeedback.display_name, AgentMessageFeedback.username, AgentMessageFeedback.user_id),
        (assignee, AgentMessageFeedback.assignee_name, AgentMessageFeedback.assignee_username, AgentMessageFeedback.assignee_user_id),
    ):
        if term.strip():
            pattern = f"%{term.strip()}%"
            conditions = [name.like(pattern), username.like(pattern)]
            if term.strip().isdigit():
                conditions.append(identity == int(term.strip()))
            query = query.filter(or_(*conditions))
    if search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(
            AgentMessageFeedback.session_title.like(pattern), AgentMessageFeedback.reasons.like(pattern),
            AgentMessageFeedback.comment.like(pattern),
        ))
    query = _filter_feedback_dates(query, start_date, end_date)
    return _feedback_page(query, skip, limit)


@router.get("/mine")
def list_my_feedback(start_date: Optional[date] = Query(None), end_date: Optional[date] = Query(None),
                     rating: Optional[Literal["like", "dislike"]] = None,
                     processing_status: Optional[Literal["pending", "resolved"]] = None,
                     search: str = Query("", max_length=200), skip: int = Query(0, ge=0),
                     limit: int = Query(16, ge=1, le=100), db: Session = Depends(get_db),
                     user: CurrentUser = Depends(get_current_active_user)):
    """List the current user's own reply ratings."""
    query = db.query(AgentMessageFeedback).filter(AgentMessageFeedback.user_id == user.user_id)
    if rating:
        query = query.filter(AgentMessageFeedback.rating == rating)
    query = _filter_processing_status(query, processing_status)
    if search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(
            AgentMessageFeedback.session_title.like(pattern), AgentMessageFeedback.reasons.like(pattern),
            AgentMessageFeedback.comment.like(pattern),
        ))
    query = _filter_feedback_dates(query, start_date, end_date)
    return _feedback_page(query, skip, limit)


@router.patch("/{feedback_id}/processing")
def update_processing(feedback_id: int, body: FeedbackProcessingInput,
                      db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user),
                      authorization: Optional[str] = Header(default=None)):
    row = db.query(AgentMessageFeedback).filter_by(id=feedback_id).populate_existing().with_for_update().first()
    if row is None:
        raise HTTPException(404, "反馈不存在或已撤回")
    if row.rating != "dislike":
        raise HTTPException(409, "点赞无需处理")
    if not user.is_superuser and row.assignee_user_id != user.user_id:
        raise HTTPException(403, "仅超级管理员或指定处理人可处理反馈")
    if not user.is_superuser and any(field in body.model_fields_set for field in (
            "assignee_user_id", "assignee_username", "assignee_name")):
        raise HTTPException(403, "仅超级管理员可分配处理人")
    if body.action == "assignment" and ("assignee_user_id" not in body.model_fields_set or body.processing_status is not None):
        raise HTTPException(422, "分配操作仅支持指定处理人")
    if body.action == "processing" and body.processing_status is None:
        raise HTTPException(422, "请选择处理状态")
    previous_assignee_user_id = row.assignee_user_id
    previous_status = row.processing_status
    if row.processing_status != "resolved":
        row.processing_status = "pending"
    if body.processing_status is not None:
        row.processing_status = body.processing_status
        if "processing_remark" in body.model_fields_set:
            row.processing_remark = body.processing_remark
        if "processing_images" in body.model_fields_set:
            row.processing_images = json.dumps(body.processing_images, ensure_ascii=False)
    # Assignment is changed only when explicitly supplied by the assignment UI.
    assignment_supplied = "assignee_user_id" in body.model_fields_set
    if not assignment_supplied:
        body.assignee_user_id = row.assignee_user_id
        body.assignee_username = row.assignee_username or ""
        body.assignee_name = row.assignee_name or ""
    row.assignee_user_id = body.assignee_user_id
    row.assignee_username = body.assignee_username.strip() if body.assignee_user_id else None
    row.assignee_name = (body.assignee_name.strip() or body.assignee_username.strip()
                         or f"用户 {body.assignee_user_id}") if body.assignee_user_id else None
    notification_sent = False
    if body.assignee_user_id != previous_assignee_user_id:
        try:
            notification_sent = sync_assignment_notification(
                authorization=authorization,
                feedback_id=row.id,
                processing_status=row.processing_status or "pending",
                previous_assignee_user_id=previous_assignee_user_id,
                assignee_user_id=row.assignee_user_id,
                feedback_user=row.display_name or row.username,
                session_title=row.session_title,
                comment=row.comment,
                detail_url=body.detail_url or f"/admin/feedback/{row.id}",
            )
        except FeedbackNotificationError as exc:
            db.rollback()
            raise HTTPException(503, f"{exc}，处理信息未保存") from exc
    resolution_notification_sent = False
    if row.processing_status == "resolved" and previous_status != "resolved":
        try:
            resolution_notification_sent = sync_resolution_notification(
                authorization=authorization, feedback_id=row.id, feedback_user_id=row.user_id,
                session_title=row.session_title, processing_remark=row.processing_remark or "",
                detail_url=body.detail_url or f"/admin/feedback/{row.id}",
                resolution_key=row.updated_at.isoformat() if row.updated_at else "initial",
            )
        except FeedbackNotificationError as exc:
            db.rollback()
            raise HTTPException(503, f"{exc}，处理信息未保存") from exc
    db.commit()
    return {**_record(row), "notification_sent": notification_sent,
            "resolution_notification_sent": resolution_notification_sent}


@router.patch("/{feedback_id}/assignment")
def assign_feedback(feedback_id: int, body: FeedbackProcessingInput,
                    db: Session = Depends(get_db), user: CurrentUser = Depends(_admin),
                    authorization: Optional[str] = Header(default=None)):
    if "assignee_user_id" not in body.model_fields_set or body.processing_status is not None:
        raise HTTPException(422, "分配接口仅支持指定处理人")
    body.action = "assignment"
    return update_processing(feedback_id, body, db, user, authorization)


@router.get("/{feedback_id}")
def feedback_detail(feedback_id: int, before_id: Optional[int] = Query(None, ge=1),
                    limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db),
                    user: CurrentUser = Depends(get_current_active_user),
                    scope: Literal["context", "conversation"] = Query("context")):
    row = db.query(AgentMessageFeedback).filter_by(id=feedback_id).first()
    if row is None:
        raise HTTPException(404, "反馈不存在或已撤回")
    if not user.is_superuser and row.user_id != user.user_id and row.assignee_user_id != user.user_id:
        raise HTTPException(403, "无权查看该反馈")
    # Retain access to feedback context after the owner soft-deletes a session.
    session = db.query(AgentSession).filter_by(id=row.session_id, user_id=row.user_id).first()
    if session is None:
        raise HTTPException(404, "关联对话不存在")
    query = db.query(AgentMessage).filter(
        AgentMessage.session_id == row.session_id,
    )
    if scope == "context":
        query = query.filter(AgentMessage.id <= row.message_id)
    if before_id is not None:
        query = query.filter(AgentMessage.id < before_id)
    rows = query.order_by(AgentMessage.id.desc()).limit(limit + 1).all()
    agent = db.query(Agent).filter_by(id=session.agent_id).first()
    return {
        "feedback": _record(row), "session_deleted": session.is_deleted,
        "can_process": user.is_superuser or row.assignee_user_id == user.user_id,
        "can_assign": user.is_superuser,
        "session": {"title": session.title, "agent_name": agent.name if agent else None,
                    "agent_icon": agent.icon if agent else None},
        "has_more": len(rows) > limit,
        "items": [{"id": message.id, "role": message.role, "created_at": _iso(message.created_at),
                   **(unpack_user_content(message.content) if message.role == "user" else {"content": message.content})}
                  for message in reversed(rows[:limit])],
    }


@router.get("/mine/{feedback_id}")
def my_feedback_detail(feedback_id: int, before_id: Optional[int] = Query(None, ge=1),
                       limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db),
                       user: CurrentUser = Depends(get_current_active_user),
                       scope: Literal["context", "conversation"] = Query("context")):
    """Return context for one of the current user's own ratings."""
    row = db.query(AgentMessageFeedback).filter_by(id=feedback_id, user_id=user.user_id).first()
    if row is None:
        raise HTTPException(404, "反馈不存在或已撤回")
    session = db.query(AgentSession).filter_by(id=row.session_id, user_id=user.user_id).first()
    if session is None:
        raise HTTPException(404, "关联对话不存在")
    query = db.query(AgentMessage).filter(AgentMessage.session_id == row.session_id)
    if scope == "context":
        query = query.filter(AgentMessage.id <= row.message_id)
    if before_id is not None:
        query = query.filter(AgentMessage.id < before_id)
    rows = query.order_by(AgentMessage.id.desc()).limit(limit + 1).all()
    agent = db.query(Agent).filter_by(id=session.agent_id).first()
    return {
        "feedback": _record(row), "session_deleted": session.is_deleted,
        "session": {"title": session.title, "agent_name": agent.name if agent else None,
                    "agent_icon": agent.icon if agent else None},
        "has_more": len(rows) > limit,
        "items": [{"id": message.id, "role": message.role, "created_at": _iso(message.created_at),
                   **(unpack_user_content(message.content) if message.role == "user" else {"content": message.content})}
                  for message in reversed(rows[:limit])],
    }
