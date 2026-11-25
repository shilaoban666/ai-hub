from fastapi import HTTPException
from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session

import models
from skill_release_policy import published_release_filter
from auth import CurrentUser


def set_skill_visibility(db: Session, skill: models.Skill, is_public=None) -> None:
    """Validate publication and serialize visibility changes with global installs."""
    db.refresh(skill, with_for_update=True)
    target = not skill.is_public if is_public is None else is_public
    if target:
        published = db.query(models.SkillRelease.id).filter(
            models.SkillRelease.skill_id == skill.id,
            published_release_filter(),
        ).first()
        if published is None:
            raise HTTPException(status_code=409, detail="请先发布至少一个技能版本，再设为公开")
    else:
        installed = db.query(models.SystemSkillInstallation.id).filter(
            models.SystemSkillInstallation.skill_id == skill.id,
            models.SystemSkillInstallation.status == "active",
        ).with_for_update().first()
        if installed is not None:
            raise HTTPException(status_code=409, detail="该技能已全局安装，请先全局卸载，再设为私有")
    skill.is_public = target


def skill_access_filter(user_id: int):
    """SQL expression for skills owned by or shared with a user."""
    collaborator_exists = exists().where(
        and_(
            models.SkillCollaborator.skill_id == models.Skill.id,
            models.SkillCollaborator.user_id == user_id,
        )
    )
    return or_(models.Skill.user_id == user_id, collaborator_exists)


def visible_skill_filter(user_id):
    """Catalog visibility shared by installed skills, chat and execution."""
    return or_(models.Skill.is_public == True, skill_access_filter(user_id))


def get_manageable_skill_or_404(
    db: Session,
    skill_id: int,
    current_user: CurrentUser,
) -> models.Skill:
    skill = db.query(models.Skill).filter(
        models.Skill.id == skill_id,
        models.Skill.is_deleted == False,
        skill_access_filter(current_user.user_id),
    ).first()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


def get_owned_skill_or_404(
    db: Session,
    skill_id: int,
    current_user: CurrentUser,
) -> models.Skill:
    skill = db.query(models.Skill).filter(
        models.Skill.id == skill_id,
        models.Skill.is_deleted == False,
        models.Skill.user_id == current_user.user_id,
    ).first()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill
