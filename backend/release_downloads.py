"""Compatibility downloads for old links, including after visibility changes.

This path may be proxied directly, without the identity gateway. Only public
archives are served here; private downloads use the authenticated assets API.
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Skill, SkillRelease
from skill_release_policy import published_release_filter
from skill_utils import resolve_release_file_path

router = APIRouter()


@router.get('/releases/{filename:path}', response_class=FileResponse)
def download_public_archive(filename: str, db: Session = Depends(get_db)):
    headers = {'Cache-Control': 'no-store'}
    if not filename or '/' in filename or '\\' in filename or filename in {'.', '..'}:
        raise HTTPException(404, 'Skill release not found', headers=headers)
    release = db.query(SkillRelease).join(Skill, Skill.id == SkillRelease.skill_id).filter(
        SkillRelease.file_url == f'/releases/{filename}',
        Skill.is_public == True,
        Skill.is_deleted == False,
        published_release_filter(),
    ).first()
    if release is None:
        raise HTTPException(404, 'Skill release not found', headers=headers)
    archive_path = resolve_release_file_path(release.file_path, release.file_url)
    if not os.path.isfile(archive_path):
        raise HTTPException(404, 'Skill release archive is missing', headers=headers)
    return FileResponse(archive_path, filename=filename, media_type='application/zip', headers=headers)
