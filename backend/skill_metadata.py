"""Reusable module/role suggestions from skills visible to the current user."""
import re

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import CurrentUser, get_current_active_user
from database import get_db
from models import Skill
from skill_access import skill_access_filter

router = APIRouter(prefix="/api/skills", tags=["skills"])
public_router = APIRouter(prefix="/api/public/skills", tags=["skills"])


def parse_metadata_tags(value):
    return list(dict.fromkeys(
        tag.strip() for tag in re.split(r"[,，;；\r\n]+", value or "") if tag.strip()
    ))


def apply_skill_metadata_filters(query, module="", role=""):
    """Match complete tags, including legacy separators, before pagination."""
    for column, value in ((Skill.module, module), (Skill.roles, role)):
        tag = (value or "").strip()
        if tag:
            pattern = r"(^|[,，;；\r\n])\s*" + re.escape(tag) + r"\s*([,，;；\r\n]|$)"
            query = query.filter(column.regexp_match(pattern))
    return query


def metadata_options(rows):
    modules, roles = {"全局"}, {"通用"}
    for module, role in rows:
        modules.update(parse_metadata_tags(module))
        roles.update(parse_metadata_tags(role))
    return {"modules": sorted(modules), "roles": sorted(roles)}


@public_router.get("/metadata-options")
def get_public_skill_metadata_options(db: Session = Depends(get_db)):
    rows = db.query(Skill.module, Skill.roles).filter(
        Skill.is_deleted == False, Skill.is_public == True,
    ).distinct().all()
    return metadata_options(rows)


@router.get("/metadata-options")
def get_skill_metadata_options(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    rows = db.query(Skill.module, Skill.roles).filter(
        Skill.is_deleted == False,
        or_(skill_access_filter(current_user.user_id), Skill.is_public == True),
    ).distinct().all()
    return metadata_options(rows)
