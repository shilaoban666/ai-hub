import json
import asyncio
import logging
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from typing import List, Literal
import models
import schemas
from database import engine, get_db, settings, SessionLocal
from agent_stream import cleanup_snapshot_loop
from agent_stream_redis import check_stream_store, close_stream_store, StreamUnavailable
from agent_run_recovery import web_run_recovery_loop
import zipfile
import io
import os
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import git_routes
import skill_metadata
from skill_utils import find_skill_md_content, flatten_file_tree
import dashboard_routes
import credit_dashboard_routes
import feedback_routes
import user_management_routes
from chat_image_storage import ImageStorageError, upload_feedback_image
import agent_routes
import agent_open_calls
from agent_open_worker import open_call_worker_loop
import agent_permission
import enterprise_routes
import knowledge_routes
import asset_routes
import release_downloads
import model_gateway
from asset_security import audit_asset, read_skill_manifest
from skill_release_policy import published_release_filter, restore_scan_rejected_release
from auth import get_current_user, get_current_active_user, CurrentUser, require_permission, ensure_default_admin, router as auth_router
from skill_utils import (
    SKILLS_DIR, get_skill_dir, save_skill_files, load_skill_files,
    delete_skill_files, parse_skill_md, PathTraversalError,
    load_release_file_tree, resolve_release_file_path, build_skill_archive,
)
from skill_access import (
    get_manageable_skill_or_404,
    get_owned_skill_or_404,
    skill_access_filter,
    set_skill_visibility,
)
from exception_handlers import (
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler,
)
from middleware import ResponseWrapperMiddleware
from model_compat import model_identity, model_supports_runtime

logger = logging.getLogger("aihub.main")
BEIJING_TIMEZONE = timezone(timedelta(hours=8))


def _beijing_filename_timestamp() -> str:
    return datetime.now(BEIJING_TIMEZONE).strftime('%Y%m%d%H%M%S')


models.Base.metadata.create_all(bind=engine)
knowledge_routes.ensure_knowledge_schema(engine)

app = FastAPI(title="AI Hub API", version="1.0.0")
agent_open_calls.install_open_call_log_filter()


@app.on_event("startup")
async def start_snapshot_cleanup():
    with SessionLocal() as db:
        ensure_default_admin(db)
    try:
        await check_stream_store()
    except StreamUnavailable as exc:
        logger.warning('%s; new Web chats will return 503', exc)
    app.state.snapshot_cleanup = asyncio.create_task(cleanup_snapshot_loop(SessionLocal))
    app.state.web_run_recovery = asyncio.create_task(web_run_recovery_loop(SessionLocal))
    app.state.open_call_worker = asyncio.create_task(open_call_worker_loop(SessionLocal))


@app.on_event("shutdown")
async def stop_snapshot_cleanup():
    open_worker = getattr(app.state, "open_call_worker", None)
    if open_worker is not None:
        open_worker.cancel()
        await asyncio.gather(open_worker, return_exceptions=True)
    task = getattr(app.state, "snapshot_cleanup", None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    recovery_task = getattr(app.state, "web_run_recovery", None)
    if recovery_task is not None:
        recovery_task.cancel()
        await asyncio.gather(recovery_task, return_exceptions=True)
    await close_stream_store()

# 注册自定义异常处理器（统一错误格式）
async def path_traversal_handler(request, exc: PathTraversalError):
    """路径穿越攻击统一返回 400，避免落入 500 兜底"""
    return JSONResponse(status_code=400, content={"detail": str(exc)})

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(PathTraversalError, path_traversal_handler)
app.add_exception_handler(Exception, general_exception_handler)

# 注册响应包装中间件（统一成功格式）
app.add_middleware(ResponseWrapperMiddleware)

# Old public links must pass current visibility and release-state checks.
RELEASES_DIR = os.path.join(os.path.dirname(__file__), "releases")
os.makedirs(RELEASES_DIR, exist_ok=True)
app.include_router(release_downloads.router)

# 挂载封面图片目录
COVERS_DIR = os.path.join(os.path.dirname(__file__), "uploads", "covers")
os.makedirs(COVERS_DIR, exist_ok=True)
app.mount("/uploads/covers", StaticFiles(directory=COVERS_DIR), name="covers")

# 挂载通用图片上传目录
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "uploads", "images")
os.makedirs(IMAGES_DIR, exist_ok=True)
app.mount("/uploads/images", StaticFiles(directory=IMAGES_DIR), name="images")


_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册本地认证路由
app.include_router(auth_router)

# 注册 Git 同步路由
app.include_router(git_routes.router)

# 注册看板路由
app.include_router(dashboard_routes.router)
app.include_router(dashboard_routes.public_router)
app.include_router(credit_dashboard_routes.personal_router)
app.include_router(credit_dashboard_routes.summary_router)
app.include_router(feedback_routes.router)
app.include_router(user_management_routes.router)

# 注册智能体路由（基于 Claude Code）
app.include_router(agent_routes.router)
app.include_router(agent_routes.public_router)
app.include_router(agent_routes.shared_router)
app.include_router(agent_open_calls.router)
app.include_router(agent_open_calls.open_router)
app.include_router(agent_permission.router)
app.include_router(enterprise_routes.router)
app.include_router(knowledge_routes.router)
app.include_router(knowledge_routes.usage_router)
app.include_router(asset_routes.router)
app.include_router(model_gateway.router)
app.include_router(skill_metadata.router)
app.include_router(skill_metadata.public_router)




@app.get("/")
def read_root():
    return {"message": "AI Hub API"}



@app.get("/api/skills", response_model=schemas.SkillListResponse)
def get_skills(
    skip: int = 0,
    limit: int = 100,
    search: str = None,
    module: str = "",
    role: str = "",
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    query = db.query(models.Skill).filter(
        models.Skill.is_deleted == False,
        skill_access_filter(current_user.user_id),
    )

    # 如果有搜索关键词，添加模糊搜索条件
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (models.Skill.name.like(search_pattern)) |
            (models.Skill.author.like(search_pattern)) |
            (models.Skill.roles.like(search_pattern))
        )

    query = skill_metadata.apply_skill_metadata_filters(query, module, role)
    total = query.count()
    skills = query.order_by(
        models.Skill.created_at.desc(), models.Skill.id.desc(),
    ).offset(skip).limit(limit).all()
    return {"total": total, "items": skills}


@app.get("/api/skills/{skill_id}", response_model=schemas.SkillResponse)
def get_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    skill = get_manageable_skill_or_404(db, skill_id, current_user)

    # 从文件系统加载文件树
    file_tree = load_skill_files(skill_id)
    skill.files = json.dumps({'tree': file_tree}, ensure_ascii=False)

    return skill


@app.post("/api/skills", response_model=schemas.SkillResponse)
def create_skill(
    skill: schemas.SkillCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    skill_data = skill.model_dump()
    files_data = skill_data.pop('files', None)
    if skill_data.get('is_public'):
        raise HTTPException(status_code=409, detail="请先创建技能并发布至少一个版本，再设为公开")

    file_tree = None
    if files_data:
        try:
            file_tree = json.loads(files_data)['tree']
            initial_content = find_skill_md_content(flatten_file_tree(file_tree))
        except (KeyError, AttributeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"文件树格式错误: {exc}")
    else:
        initial_content = skill_data.get('content')
    # Metadata is read only during creation, never in update_skill.
    if initial_content:
        metadata, _ = parse_skill_md(initial_content)
        for field in ('name', 'version', 'description'):
            if metadata[field]:
                skill_data[field] = metadata[field]
        skill_data['content'] = initial_content

    db_skill = models.Skill(**skill_data, user_id=current_user.user_id)
    created_id = None
    try:
        db.add(db_skill)
        db.flush()
        created_id = db_skill.id
        if file_tree is not None:
            save_skill_files(db_skill.id, file_tree)
        db.commit()
    except Exception:
        db.rollback()
        if created_id is not None:
            delete_skill_files(created_id)
        raise
    db.refresh(db_skill)

    return db_skill


@app.put("/api/skills/{skill_id}", response_model=schemas.SkillResponse)
def update_skill(
    skill_id: int,
    skill: schemas.SkillUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_skill = get_manageable_skill_or_404(db, skill_id, current_user)

    update_data = skill.model_dump(exclude_unset=True)
    files_data = update_data.pop('files', None)
    # 作者是技能创建/发布时的来源信息。编辑技能时保留原作者，避免把当前
    # 操作者误显示为作者；前端作者字段也保持只读。
    update_data.pop('author', None)
    if update_data.get('is_public') is not None:
        set_skill_visibility(db, db_skill, update_data.pop('is_public'))

    for key, value in update_data.items():
        setattr(db_skill, key, value)

    db.commit()
    db.refresh(db_skill)

    # 如果有文件数据，保存到文件系统
    if files_data:
        try:
            file_tree_data = json.loads(files_data)
            if 'tree' in file_tree_data:
                save_skill_files(skill_id, file_tree_data['tree'])
        except PathTraversalError:
            raise
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"文件树格式错误: {exc}")

    return db_skill


@app.delete("/api/skills/{skill_id}")
def delete_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_skill = get_owned_skill_or_404(db, skill_id, current_user)

    # 删除封面文件
    if db_skill.cover and db_skill.cover.startswith('/uploads/covers/'):
        filename = db_skill.cover.split('/')[-1]
        file_path = os.path.join(COVERS_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)

    # 删除技能文件目录
    delete_skill_files(skill_id)

    # 软删除：标记为已删除
    db_skill.is_deleted = True
    db.commit()
    return {"message": "Skill deleted successfully"}


@app.get(
    "/api/skills/{skill_id}/collaborators",
    response_model=List[schemas.SkillCollaboratorResponse],
)
def get_skill_collaborators(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    get_manageable_skill_or_404(db, skill_id, current_user)
    return db.query(models.SkillCollaborator).filter(
        models.SkillCollaborator.skill_id == skill_id,
    ).order_by(models.SkillCollaborator.created_at.asc()).all()


@app.post(
    "/api/skills/{skill_id}/collaborators",
    response_model=schemas.SkillCollaboratorResponse,
    status_code=201,
)
def add_skill_collaborator(
    skill_id: int,
    collaborator: schemas.SkillCollaboratorCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    skill = get_owned_skill_or_404(db, skill_id, current_user)
    if collaborator.user_id == skill.user_id:
        raise HTTPException(status_code=400, detail="技能所有者无需添加为协作者")
    username = collaborator.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")

    existing = db.query(models.SkillCollaborator).filter(
        models.SkillCollaborator.skill_id == skill_id,
        models.SkillCollaborator.user_id == collaborator.user_id,
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="该用户已是协作者")

    db_collaborator = models.SkillCollaborator(
        skill_id=skill_id,
        user_id=collaborator.user_id,
        username=username,
        created_by=current_user.user_id,
    )
    db.add(db_collaborator)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该用户已是协作者")
    db.refresh(db_collaborator)
    return db_collaborator


@app.delete("/api/skills/{skill_id}/collaborators/{user_id}")
def remove_skill_collaborator(
    skill_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    get_owned_skill_or_404(db, skill_id, current_user)
    collaborator = db.query(models.SkillCollaborator).filter(
        models.SkillCollaborator.skill_id == skill_id,
        models.SkillCollaborator.user_id == user_id,
    ).first()
    if collaborator is None:
        raise HTTPException(status_code=404, detail="协作者不存在")

    db.delete(collaborator)
    db.commit()
    return {"message": "Collaborator removed successfully"}


@app.post("/api/skills/{skill_id}/cover")
async def upload_cover(
    skill_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    try:
        print(f"收到封面上传请求，skill_id: {skill_id}, 文件名: {file.filename}, 类型: {file.content_type}")

        db_skill = get_manageable_skill_or_404(db, skill_id, current_user)

        # 检查文件大小（1MB = 1048576 bytes）
        contents = await file.read()
        print(f"文件大小: {len(contents)} bytes")

        if len(contents) > 1048576:
            raise HTTPException(status_code=400, detail="文件大小不能超过1MB")

        # 检查文件类型
        if not file.content_type or not file.content_type.startswith('image/'):
            print(f"文件类型不正确: {file.content_type}")
            raise HTTPException(status_code=400, detail="只能上传图片文件")

        # 生成文件名：skill_id + 时间戳 + 原始扩展名
        file_ext = os.path.splitext(file.filename)[1] or '.png'
        filename = f"skill_{skill_id}_{_beijing_filename_timestamp()}{file_ext}"
        file_path = os.path.join(COVERS_DIR, filename)

        # 保存文件
        with open(file_path, 'wb') as f:
            f.write(contents)
        print(f"文件已保存到: {file_path}")

        # 删除旧封面文件（如果存在）
        if db_skill.cover and db_skill.cover.startswith('/uploads/covers/'):
            old_filename = db_skill.cover.split('/')[-1]
            old_file_path = os.path.join(COVERS_DIR, old_filename)
            if os.path.exists(old_file_path):
                os.remove(old_file_path)
                print(f"已删除旧封面: {old_file_path}")

        # 更新数据库中的封面路径
        cover_url = f"/uploads/covers/{filename}"
        db_skill.cover = cover_url
        db.commit()
        db.refresh(db_skill)

        print("封面上传成功")
        return {"message": "封面上传成功", "cover": cover_url}
    except HTTPException:
        raise
    except Exception as e:
        print(f"封面上传失败，错误: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"内部错误: {str(e)}")


@app.delete("/api/skills/{skill_id}/cover")
async def delete_cover(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    try:
        print(f"收到删除封面请求，skill_id: {skill_id}")

        db_skill = get_manageable_skill_or_404(db, skill_id, current_user)

        # 删除文件系统中的封面文件
        if db_skill.cover and db_skill.cover.startswith('/uploads/covers/'):
            filename = db_skill.cover.split('/')[-1]
            file_path = os.path.join(COVERS_DIR, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"已删除封面文件: {file_path}")

        # 清空数据库中的封面字段
        db_skill.cover = None
        db.commit()
        db.refresh(db_skill)

        print("封面删除成功")
        return {"message": "封面删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"封面删除失败，错误: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"内部错误: {str(e)}")




@app.post("/api/skills/import", response_model=schemas.SkillResponse)
async def import_skill(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    """导入技能文件（SKILL.md 或包含 SKILL.md 的 zip）"""

    try:
        file_content = await file.read()
        filename = file.filename.lower()

        skill_md_content = None
        file_tree = []

        # 处理 SKILL.md 文件
        if filename == 'skill.md':
            skill_md_content = file_content.decode('utf-8')
            file_tree = [
                {
                    'id': 1,
                    'label': 'SKILL.md',
                    'type': 'file',
                    'path': 'SKILL.md',
                    'content': skill_md_content,
                    'raw_content': file_content,
                }
            ]

        # 处理 zip 文件
        elif filename.endswith('.zip'):
            try:
                file_tree = load_release_file_tree(io.BytesIO(file_content), include_binary=True)
                skill_md_content = find_skill_md_content(flatten_file_tree(file_tree))
                if skill_md_content is None:
                    raise HTTPException(status_code=400, detail="zip 压缩包中必须包含 SKILL.md 文件")
            except HTTPException:
                raise
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail="无效的 zip 文件")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"解析 zip 文件失败: {str(e)}")

        else:
            raise HTTPException(status_code=400, detail="文件格式不正确，请上传 SKILL.md 文件或包含 SKILL.md 的 zip 压缩包")

        # 检查 SKILL.md 文件是否为空
        if not skill_md_content or not skill_md_content.strip():
            raise HTTPException(status_code=400, detail="SKILL.md 文件不能为空")

        # 解析 SKILL.md 内容
        metadata, content = parse_skill_md(skill_md_content)

        if not metadata['name']:
            metadata['name'] = '未命名技能'

        # 创建技能记录（不存储files内容）
        db_skill = models.Skill(
            name=metadata['name'],
            version=metadata['version'] or '1.0.0',
            author=current_user.first_name,
            module='全局',
            description=metadata['description'],
            roles='通用',
            content=content,
            files=None,  # 不再存储到数据库
            user_id=current_user.user_id
        )

        db.add(db_skill)
        created_id = None
        try:
            db.flush()
            created_id = db_skill.id
            save_skill_files(db_skill.id, file_tree)
            db.commit()
        except Exception:
            db.rollback()
            if created_id is not None:
                delete_skill_files(created_id)
            raise
        db.refresh(db_skill)

        return db_skill

    except HTTPException:
        raise
    except Exception as e:
        print(f"导入失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@app.post("/api/skills/{skill_id}/import", response_model=schemas.SkillResponse)
async def import_skill_into_existing(
    skill_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Replace only the workspace files, preserving all existing skill information."""
    skill = get_manageable_skill_or_404(db, skill_id, current_user)

    try:
        file_content = await file.read()
        filename = str(file.filename or '').lower()
        skill_md_content = None
        file_tree = []

        if filename == 'skill.md':
            skill_md_content = file_content.decode('utf-8')
            file_tree = [{
                'id': 1,
                'label': 'SKILL.md',
                'type': 'file',
                'path': 'SKILL.md',
                'content': skill_md_content,
                'raw_content': file_content,
            }]
        elif filename.endswith('.zip'):
            try:
                file_tree = load_release_file_tree(io.BytesIO(file_content), include_binary=True)
                skill_md_content = find_skill_md_content(flatten_file_tree(file_tree))
                if skill_md_content is None:
                    raise HTTPException(status_code=400, detail="zip 压缩包中必须包含 SKILL.md 文件")
            except HTTPException:
                raise
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail="无效的 zip 文件")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"解析 zip 文件失败: {str(e)}")
        else:
            raise HTTPException(status_code=400, detail="文件格式不正确，请上传 SKILL.md 文件或包含 SKILL.md 的 zip 压缩包")

        if not skill_md_content or not skill_md_content.strip():
            raise HTTPException(status_code=400, detail="SKILL.md 文件不能为空")

        previous_tree = load_skill_files(skill_id, include_binary=True)

        try:
            # Header import always starts from an empty workspace. Remove the
            # entire old directory, including hidden files and empty folders.
            delete_skill_files(skill_id)
            save_skill_files(skill_id, file_tree)
            db.commit()
        except Exception:
            db.rollback()
            try:
                # A failed write may have left part of the imported package.
                delete_skill_files(skill_id)
                save_skill_files(skill_id, previous_tree)
            except Exception:
                logger.exception("Failed to restore skill files after import replacement error")
            raise

        db.refresh(skill)
        return skill
    except HTTPException:
        raise
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="SKILL.md 必须使用 UTF-8 编码")
    except Exception as e:
        logger.exception("覆盖导入技能失败")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@app.get("/api/skills/{skill_id}/export")
def export_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    get_manageable_skill_or_404(db, skill_id, current_user)
    tree = load_skill_files(skill_id, include_binary=True)
    return Response(
        content=build_skill_archive(tree, f"skill-{skill_id}"),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="skill-{skill_id}.zip"', "Cache-Control": "no-store"},
    )


@app.post("/api/skills/{skill_id}/release", response_model=schemas.SkillReleaseResponse)
async def release_skill(
    skill_id: int,
    release: schemas.SkillReleaseCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    """发布技能版本"""
    skill = get_manageable_skill_or_404(db, skill_id, current_user)

    # 检查版本号是否已存在
    existing_release = db.query(models.SkillRelease).filter(
        models.SkillRelease.skill_id == skill_id,
        models.SkillRelease.version == release.version
    ).first()
    if existing_release:
        raise HTTPException(status_code=400, detail="版本号已存在")

    # 从文件系统加载文件树
    file_tree = load_skill_files(skill_id, include_binary=True)

    archive_content = build_skill_archive(file_tree, f"skill-{skill_id}")
    # 保存zip文件到服务器
    filename = f"skill-{skill_id}-{uuid.uuid4().hex}.zip"
    releases_root = os.path.realpath(RELEASES_DIR)
    file_path = os.path.realpath(os.path.join(releases_root, filename))
    if os.path.commonpath([releases_root, file_path]) != releases_root:
        raise PathTraversalError("非法的发布存储路径")

    manifest = read_skill_manifest(file_tree)
    with open(file_path, 'xb') as f:
        f.write(archive_content)

    # 生成访问URL
    file_url = f"/releases/{filename}"

    # 创建发布记录
    db_release = models.SkillRelease(
        skill_id=skill_id,
        version=release.version,
        description=release.description.strip() if release.description else None,
        file_path=file_path,
        file_url=file_url,
        content_sha256=hashlib.sha256(archive_content).hexdigest(),
        manifest_json=json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        status="published",
        scan_status="not_required",
        published_by=current_user.user_id,
    )
    try:
        db.add(db_release)
        db.flush()
        audit_asset(
            db,
            asset_type="skill_release",
            asset_id=db_release.id,
            action="published",
            actor_user_id=current_user.user_id,
            details={"version": release.version},
        )
        skill.version = release.version
        db.commit()
    except Exception:
        db.rollback()
        os.remove(file_path)
        raise
    db.refresh(db_release)

    return db_release


@app.get("/api/skills/{skill_id}/releases", response_model=List[schemas.SkillReleaseResponse])
def get_skill_releases(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """获取当前用户可管理技能的发布历史。"""
    get_manageable_skill_or_404(db, skill_id, current_user)

    releases = db.query(models.SkillRelease).filter(
        models.SkillRelease.skill_id == skill_id
    ).order_by(models.SkillRelease.created_at.desc()).all()

    for release in releases:
        restore_scan_rejected_release(release)
    db.commit()
    return releases


@app.post("/api/skills/{skill_id}/releases/{release_id}/restore")
def restore_skill_release(
    skill_id: int,
    release_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Replace the current skill contents with a previously released version."""
    skill = get_manageable_skill_or_404(db, skill_id, current_user)
    release = db.query(models.SkillRelease).filter(
        models.SkillRelease.id == release_id,
        models.SkillRelease.skill_id == skill_id,
    ).first()
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")

    release_path = resolve_release_file_path(release.file_path, release.file_url)
    releases_root = os.path.realpath(RELEASES_DIR)
    if release_path != releases_root and not release_path.startswith(releases_root + os.sep):
        raise HTTPException(status_code=400, detail="Invalid release file path")
    if not os.path.isfile(release_path):
        raise HTTPException(status_code=404, detail="Release file not found")

    try:
        restored_tree = load_release_file_tree(release_path, include_binary=True)
    except (zipfile.BadZipFile, PathTraversalError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid release archive: {exc}")

    previous_tree = load_skill_files(skill_id, include_binary=True)
    previous_version = skill.version
    previous_content = skill.content
    restored_content = find_skill_md_content(flatten_file_tree(restored_tree))

    try:
        save_skill_files(skill_id, restored_tree)
        skill.version = release.version
        skill.content = restored_content
        db.commit()
    except Exception:
        db.rollback()
        skill.version = previous_version
        skill.content = previous_content
        try:
            save_skill_files(skill_id, previous_tree)
        except Exception:
            logger.exception("Failed to restore skill files after release restore error")
        raise

    return {
        "message": "Release restored successfully",
        "release_id": release.id,
        "version": release.version,
    }


@app.get("/api/public/skills/{skill_id}/releases", response_model=List[schemas.SkillReleaseResponse])
def get_public_skill_releases(skill_id: int, db: Session = Depends(get_db)):
    """公开端点：获取公开技能的发布历史（无需认证）"""
    skill = db.query(models.Skill).filter(
        models.Skill.id == skill_id,
        models.Skill.is_deleted == False,
        models.Skill.is_public == True
    ).first()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    releases = db.query(models.SkillRelease).filter(
        models.SkillRelease.skill_id == skill_id,
        published_release_filter(),
    ).order_by(models.SkillRelease.created_at.desc()).all()

    for release in releases:
        restore_scan_rejected_release(release)
    db.commit()
    return releases


# === 公开 API（无需认证） ===

@app.get("/api/public/skills", response_model=schemas.SkillPublicListResponse)
def get_public_skills(
    skip: int = 0,
    limit: int = 12,
    search: str = None,
    module: str = "",
    role: str = "",
    db: Session = Depends(get_db)
):
    """公开端点：获取已公开的技能列表（无需认证）"""
    query = db.query(models.Skill).filter(
        models.Skill.is_deleted == False,
        models.Skill.is_public == True
    )

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (models.Skill.name.like(search_pattern)) |
            (models.Skill.author.like(search_pattern)) |
            (models.Skill.roles.like(search_pattern))
        )

    query = skill_metadata.apply_skill_metadata_filters(query, module, role)
    total = query.count()
    skills = query.order_by(models.Skill.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": skills}


@app.get("/api/public/skills/{skill_id}", response_model=schemas.SkillPublicResponse)
def get_public_skill(
    skill_id: int,
    db: Session = Depends(get_db)
):
    """公开端点：获取单个公开技能详情（无需认证）"""
    skill = db.query(models.Skill).filter(
        models.Skill.id == skill_id,
        models.Skill.is_deleted == False,
        models.Skill.is_public == True
    ).first()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    file_tree = load_skill_files(skill_id)
    skill.files = json.dumps({'tree': file_tree}, ensure_ascii=False)

    return skill


# === 可见性切换 ===

@app.put("/api/skills/{skill_id}/visibility")
def toggle_skill_visibility(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    """切换技能的公开/私有可见性"""
    db_skill = get_manageable_skill_or_404(db, skill_id, current_user)

    set_skill_visibility(db, db_skill)
    db.commit()
    db.refresh(db_skill)
    return {"is_public": db_skill.is_public}


# === MCP 服务 API（需认证） ===

@app.get("/api/mcps", response_model=schemas.McpServiceListResponse)
def get_mcps(
    skip: int = 0,
    limit: int = 100,
    search: str = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    query = db.query(models.McpService).filter(
        models.McpService.is_deleted == False,
        models.McpService.user_id == current_user.user_id
    )

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (models.McpService.name.like(search_pattern)) |
            (models.McpService.description.like(search_pattern)) |
            (models.McpService.tags.like(search_pattern)) |
            (models.McpService.author.like(search_pattern))
        )

    total = query.count()
    items = query.order_by(
        models.McpService.created_at.desc(), models.McpService.id.desc(),
    ).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@app.get("/api/mcps/{mcp_id}", response_model=schemas.McpServiceResponse)
def get_mcp(
    mcp_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    mcp = db.query(models.McpService).filter(
        models.McpService.id == mcp_id,
        models.McpService.is_deleted == False,
        models.McpService.user_id == current_user.user_id
    ).first()
    if mcp is None:
        raise HTTPException(status_code=404, detail="MCP service not found")
    return mcp


@app.post("/api/mcps", response_model=schemas.McpServiceResponse)
def create_mcp(
    mcp: schemas.McpServiceCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    mcp_data = mcp.model_dump()
    config_value = mcp_data.pop("config", None)
    db_mcp = models.McpService(**mcp_data, user_id=current_user.user_id)
    db.add(db_mcp)
    db.flush()
    db_mcp.store_config(config_value)
    db.commit()
    db.refresh(db_mcp)
    return db_mcp


@app.put("/api/mcps/{mcp_id}", response_model=schemas.McpServiceResponse)
def update_mcp(
    mcp_id: int,
    mcp: schemas.McpServiceUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_mcp = db.query(models.McpService).filter(
        models.McpService.id == mcp_id,
        models.McpService.is_deleted == False,
        models.McpService.user_id == current_user.user_id
    ).first()
    if db_mcp is None:
        raise HTTPException(status_code=404, detail="MCP service not found")

    update_data = mcp.model_dump(exclude_unset=True)
    config_present = "config" in update_data
    config_value = update_data.pop("config", None)
    for key, value in update_data.items():
        setattr(db_mcp, key, value)

    if config_present:
        db_mcp.store_config(config_value)
    elif db_mcp.config_encrypted is None and db_mcp._config_plaintext is not None:
        db_mcp.store_config(db_mcp._config_plaintext)

    if config_present:
        asset_routes.sync_owned_mcp_source(db, db_mcp)

    db.commit()
    db.refresh(db_mcp)
    return db_mcp


@app.delete("/api/mcps/{mcp_id}")
def delete_mcp(
    mcp_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_mcp = db.query(models.McpService).filter(
        models.McpService.id == mcp_id,
        models.McpService.is_deleted == False,
        models.McpService.user_id == current_user.user_id
    ).first()
    if db_mcp is None:
        raise HTTPException(status_code=404, detail="MCP service not found")

    # 删除封面文件
    if db_mcp.cover and db_mcp.cover.startswith('/uploads/covers/'):
        filename = db_mcp.cover.split('/')[-1]
        file_path = os.path.join(COVERS_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)

    db_mcp.is_deleted = True
    db.commit()
    return {"message": "MCP service deleted successfully"}


@app.post("/api/mcps/{mcp_id}/cover")
async def upload_mcp_cover(
    mcp_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_mcp = db.query(models.McpService).filter(
        models.McpService.id == mcp_id,
        models.McpService.user_id == current_user.user_id
    ).first()
    if db_mcp is None:
        raise HTTPException(status_code=404, detail="MCP service not found")

    contents = await file.read()
    if len(contents) > 1048576:
        raise HTTPException(status_code=400, detail="文件大小不能超过1MB")

    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="只能上传图片文件")

    file_ext = os.path.splitext(file.filename)[1] or '.png'
    filename = f"mcp_{mcp_id}_{_beijing_filename_timestamp()}{file_ext}"
    file_path = os.path.join(COVERS_DIR, filename)

    with open(file_path, 'wb') as f:
        f.write(contents)

    # 删除旧封面
    if db_mcp.cover and db_mcp.cover.startswith('/uploads/covers/'):
        old_filename = db_mcp.cover.split('/')[-1]
        old_file_path = os.path.join(COVERS_DIR, old_filename)
        if os.path.exists(old_file_path):
            os.remove(old_file_path)

    cover_url = f"/uploads/covers/{filename}"
    db_mcp.cover = cover_url
    db.commit()
    db.refresh(db_mcp)

    return {"message": "封面上传成功", "cover": cover_url}


@app.delete("/api/mcps/{mcp_id}/cover")
async def delete_mcp_cover(
    mcp_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_mcp = db.query(models.McpService).filter(
        models.McpService.id == mcp_id,
        models.McpService.user_id == current_user.user_id
    ).first()
    if db_mcp is None:
        raise HTTPException(status_code=404, detail="MCP service not found")

    if db_mcp.cover and db_mcp.cover.startswith('/uploads/covers/'):
        filename = db_mcp.cover.split('/')[-1]
        file_path = os.path.join(COVERS_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)

    db_mcp.cover = None
    db.commit()
    db.refresh(db_mcp)

    return {"message": "封面删除成功"}


@app.post("/api/upload/image")
async def upload_image(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_active_user),
    purpose: str = Query(default="content", pattern="^(content|assistant|feedback)$"),
):
    """上传编辑器图片或体积更小的助手头像、悬浮精灵图片。"""
    size_limits = {"assistant": 200 * 1024, "content": 1024 * 1024, "feedback": 3 * 1024 * 1024}
    max_bytes = size_limits[purpose]
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        messages = {"assistant": "图片不能超过 200KB，请压缩后再上传", "content": "文件大小不能超过1MB", "feedback": "反馈截图不能超过3MB"}
        message = messages[purpose]
        raise HTTPException(status_code=400, detail=message)

    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="只能上传图片文件")

    file_ext = os.path.splitext(file.filename)[1] or '.png'
    if purpose == "feedback":
        try:
            url = await asyncio.to_thread(upload_feedback_image, contents, file.content_type, current_user.user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except ImageStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        return {"url": url}

    filename = f"{_beijing_filename_timestamp()}_{hashlib.md5(contents).hexdigest()[:8]}{file_ext}"
    file_path = os.path.join(IMAGES_DIR, filename)

    with open(file_path, 'wb') as f:
        f.write(contents)

    return {"url": f"/uploads/images/{filename}"}


@app.put("/api/mcps/{mcp_id}/visibility")
def toggle_mcp_visibility(
    mcp_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_mcp = db.query(models.McpService).filter(
        models.McpService.id == mcp_id,
        models.McpService.is_deleted == False,
        models.McpService.user_id == current_user.user_id
    ).first()
    if db_mcp is None:
        raise HTTPException(status_code=404, detail="MCP service not found")

    db_mcp.is_public = not db_mcp.is_public
    db.commit()
    db.refresh(db_mcp)
    return {"is_public": db_mcp.is_public}


# === MCP 公开 API（无需认证） ===

def _redact_public_mcp_config(config_value):
    if not config_value:
        return config_value
    try:
        config = json.loads(config_value)
    except (TypeError, json.JSONDecodeError):
        return None

    hidden = "隐藏"

    def redact_url(value):
        if not isinstance(value, str):
            return hidden
        try:
            url = urlsplit(value)
            if url.scheme not in {"http", "https"} or not url.hostname:
                return hidden
            host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
            if url.port is not None:
                host += f":{url.port}"
            # Custom paths can contain opaque credentials as well as query strings.
            path = url.path if url.path in {"", "/", "/mcp", "/sse", "/messages"} else "/REDACTED"
            query = urlencode([(key, hidden) for key, _ in parse_qsl(url.query, keep_blank_values=True)])
            return urlunsplit((url.scheme, host, path, query, ""))
        except (TypeError, ValueError):
            return hidden

    def redact(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                field = str(key).casefold()
                if field in {"headers", "env"} and isinstance(item, dict):
                    result[key] = {item_key: hidden for item_key in item}
                elif field == "url":
                    result[key] = redact_url(item)
                elif field == "command":
                    result[key] = item if isinstance(item, str) and item in {
                        "npx", "node", "uv", "uvx", "python", "python3", "docker",
                    } else hidden
                elif field == "args" and isinstance(item, list):
                    result[key] = [hidden for _ in item]
                elif field == "type" and isinstance(item, str) and item in {
                    "stdio", "sse", "http", "streamable_http", "streamable-http",
                }:
                    result[key] = item
                else:
                    result[key] = redact(item)
            return result
        if isinstance(value, list):
            return [redact(item) for item in value]
        return hidden

    return json.dumps(redact(config), ensure_ascii=False)


def _public_mcp_response(mcp):
    response = schemas.McpServicePublicResponse.model_validate(mcp).model_dump()
    response["config"] = _redact_public_mcp_config(response.get("config"))
    return response


@app.get("/api/public/mcps", response_model=schemas.McpServicePublicListResponse)
def get_public_mcps(
    skip: int = 0,
    limit: int = 12,
    search: str = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.McpService).filter(
        models.McpService.is_deleted == False,
        models.McpService.is_public == True
    )

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (models.McpService.name.like(search_pattern)) |
            (models.McpService.description.like(search_pattern)) |
            (models.McpService.tags.like(search_pattern)) |
            (models.McpService.author.like(search_pattern))
        )

    total = query.count()
    items = query.order_by(models.McpService.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": [_public_mcp_response(item) for item in items]}


@app.get("/api/public/mcps/{mcp_id}", response_model=schemas.McpServicePublicResponse)
def get_public_mcp(
    mcp_id: int,
    db: Session = Depends(get_db)
):
    mcp = db.query(models.McpService).filter(
        models.McpService.id == mcp_id,
        models.McpService.is_deleted == False,
        models.McpService.is_public == True
    ).first()
    if mcp is None:
        raise HTTPException(status_code=404, detail="MCP service not found")
    return _public_mcp_response(mcp)


# === AI 模型 API（需认证） ===

def _agents_using_model(db: Session, user_id: int, model_id: int):
    candidates = db.query(models.Agent).filter(
        models.Agent.user_id == user_id,
        models.Agent.is_deleted == False,
    ).all()
    return [
        agent for agent in candidates
        if agent.default_model_id == model_id
        or any(bound_model.id == model_id for bound_model in agent.models)
    ]


def _prospective_model(db_model, update_data: dict):
    fields = (
        "id", "name", "provider", "api_proxy_url", "api_protocol", "remarks"
    )
    return SimpleNamespace(**{
        field: update_data.get(field, getattr(db_model, field, None))
        for field in fields
    })


def _model_response_item(model):
    """Return model metadata without ever serializing a credential."""
    return {
        "id": model.id,
        "name": model.name,
        "provider": model.provider,
        "api_key": "",
        "has_api_key": bool(
            getattr(model, "api_key_encrypted", None)
            or getattr(model, "_api_key_plaintext", None)
        ),
        "api_proxy_url": model.api_proxy_url,
        "api_protocol": model.api_protocol,
        "reasoning_support": model.reasoning_support,
        "remarks": model.remarks,
        "scope": model.scope,
        "is_enabled": model.is_enabled,
        "health_status": model.health_status,
        "compatible_runtimes": model.compatible_runtimes,
        "is_deleted": model.is_deleted,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


@app.get("/api/models", response_model=schemas.ModelListResponse)
def get_models(
    skip: int = 0,
    limit: int = 100,
    search: str = None,
    scope: Literal["user", "platform"] | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    query = db.query(models.AIModel).filter(
        models.AIModel.is_deleted == False,
        or_(
            models.AIModel.user_id == current_user.user_id,
            and_(
                models.AIModel.scope == "platform",
                models.AIModel.is_enabled == True,
            ),
        ),
    )

    if scope is not None:
        query = query.filter(models.AIModel.scope == scope)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (models.AIModel.name.like(search_pattern)) |
            (models.AIModel.provider.like(search_pattern)) |
            (models.AIModel.remarks.like(search_pattern))
        )

    total = query.count()
    items = query.order_by(
        models.AIModel.created_at.desc(), models.AIModel.id.desc(),
    ).offset(skip).limit(limit).all()
    return {"total": total, "items": [_model_response_item(item) for item in items]}


@app.get("/api/models/{model_id}", response_model=schemas.ModelResponse)
def get_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    model = db.query(models.AIModel).filter(
        models.AIModel.id == model_id,
        models.AIModel.is_deleted == False,
        or_(
            models.AIModel.user_id == current_user.user_id,
            and_(models.AIModel.scope == "platform", models.AIModel.is_enabled == True),
        ),
    ).first()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    return _model_response_item(model)


@app.post("/api/models", response_model=schemas.ModelResponse)
def create_model(
    model: schemas.ModelCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    model_data = model.model_dump()
    api_key = model_data.pop("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    if not settings.agent_credential_encryption_key:
        raise HTTPException(
            status_code=503,
            detail="未配置 AGENT_CREDENTIAL_ENCRYPTION_KEY，禁止保存模型密钥",
        )
    db_model = models.AIModel(**model_data, user_id=current_user.user_id, scope="user")
    db.add(db_model)
    db.flush()
    db_model.store_api_key(api_key, app_settings=settings)
    db.commit()
    db.refresh(db_model)
    return _model_response_item(db_model)


@app.put("/api/models/{model_id}", response_model=schemas.ModelResponse)
def update_model(
    model_id: int,
    model: schemas.ModelUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_model = db.query(models.AIModel).filter(
        models.AIModel.id == model_id,
        models.AIModel.is_deleted == False,
        models.AIModel.scope == "user",
        models.AIModel.user_id == current_user.user_id
    ).first()
    if db_model is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    update_data = model.model_dump(exclude_unset=True)
    api_key_present = "api_key" in update_data
    api_key = update_data.pop("api_key", None)
    prospective_model = _prospective_model(db_model, update_data)
    affected_agents = _agents_using_model(db, current_user.user_id, model_id)
    incompatible_agents = [
        agent for agent in affected_agents
        if not model_supports_runtime(prospective_model, agent.runtime_type or "claude_code")
    ]
    if incompatible_agents:
        agent_names = "、".join(agent.name for agent in incompatible_agents)
        raise HTTPException(
            status_code=409,
            detail=(
                f"修改后的协议与以下智能体 Runtime 不兼容: {agent_names}。"
                "请先调整这些智能体的模型绑定或 Runtime。"
            ),
        )

    for key, value in update_data.items():
        setattr(db_model, key, value)

    if api_key_present:
        # An empty API key means "keep the existing credential".  The UI
        # intentionally does not echo secrets back, so treating a blank edit
        # as a clear operation would make an ordinary metadata save erase a
        # working credential unexpectedly.
        if isinstance(api_key, str) and api_key.strip():
            if not settings.agent_credential_encryption_key:
                raise HTTPException(
                    status_code=503,
                    detail="未配置 AGENT_CREDENTIAL_ENCRYPTION_KEY，禁止保存模型密钥",
                )
            db_model.store_api_key(api_key, app_settings=settings)
    elif db_model.api_key_encrypted is None and db_model._api_key_plaintext:
        if not settings.agent_credential_encryption_key:
            raise HTTPException(
                status_code=503,
                detail="该模型仍包含未加密密钥，请先配置 AGENT_CREDENTIAL_ENCRYPTION_KEY",
            )
        db_model.store_api_key(db_model._api_key_plaintext, app_settings=settings)

    db.commit()
    db.refresh(db_model)
    return _model_response_item(db_model)


@app.delete("/api/models/{model_id}")
def delete_model(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_model = db.query(models.AIModel).filter(
        models.AIModel.id == model_id,
        models.AIModel.is_deleted == False,
        models.AIModel.scope == "user",
        models.AIModel.user_id == current_user.user_id
    ).first()
    if db_model is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    affected_agents = _agents_using_model(db, current_user.user_id, model_id)
    if affected_agents:
        agent_names = "、".join(agent.name for agent in affected_agents)
        raise HTTPException(
            status_code=409,
            detail=(
                f"{model_identity(db_model)} 正被以下智能体使用: {agent_names}。"
                "请先解除模型绑定后再删除。"
            ),
        )

    db_model.is_deleted = True
    db.commit()
    return {"message": "模型删除成功"}


# === 提示词模板 API（需认证） ===

@app.get("/api/prompt-templates", response_model=schemas.PromptTemplateListResponse)
def get_prompt_templates(
    skip: int = 0,
    limit: int = 100,
    search: str = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    query = db.query(models.PromptTemplate).filter(
        models.PromptTemplate.is_deleted == False,
        models.PromptTemplate.is_system == False,
        models.PromptTemplate.user_id == current_user.user_id
    )

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (models.PromptTemplate.name.like(search_pattern)) |
            (models.PromptTemplate.category.like(search_pattern)) |
            (models.PromptTemplate.description.like(search_pattern))
        )

    total = query.count()
    items = query.order_by(
        models.PromptTemplate.created_at.desc(), models.PromptTemplate.id.desc(),
    ).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@app.get("/api/prompt-templates/usable", response_model=schemas.PromptTemplateListResponse)
def get_usable_prompt_templates(
    skip: int = 0,
    limit: int = 100,
    search: str = None,
    include_system: bool = True,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    """返回公开和自己的模板，可选择是否包含系统模板。"""
    query = db.query(models.PromptTemplate).filter(
        models.PromptTemplate.is_deleted == False,
        ~db.query(models.WorkspacePromptRemoval).filter(
            models.WorkspacePromptRemoval.user_id == current_user.user_id,
            models.WorkspacePromptRemoval.template_id == models.PromptTemplate.id,
        ).exists(),
        (models.PromptTemplate.is_system == True) |
        (models.PromptTemplate.is_public == True) |
        (models.PromptTemplate.user_id == current_user.user_id)
    )
    if not include_system:
        query = query.filter(models.PromptTemplate.is_system == False)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (models.PromptTemplate.name.like(search_pattern)) |
            (models.PromptTemplate.category.like(search_pattern)) |
            (models.PromptTemplate.description.like(search_pattern))
        )
    total = query.count()
    items = query.order_by(
        models.PromptTemplate.is_system.desc(),
        models.PromptTemplate.created_at.desc(),
    ).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@app.get("/api/prompt-templates/{template_id}", response_model=schemas.PromptTemplateResponse)
def get_prompt_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    template = db.query(models.PromptTemplate).filter(
        models.PromptTemplate.id == template_id,
        models.PromptTemplate.is_deleted == False,
        models.PromptTemplate.is_system == False,
        models.PromptTemplate.user_id == current_user.user_id
    ).first()
    if template is None:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    return template


@app.post("/api/prompt-templates", response_model=schemas.PromptTemplateResponse)
def create_prompt_template(
    template: schemas.PromptTemplateCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    template_data = template.model_dump()
    template_data.pop("author", None)  # author 由后端按登录用户自动注入，不信任前端传入
    db_template = models.PromptTemplate(
        **template_data,
        user_id=current_user.user_id,
        author=(current_user.first_name or current_user.username or "匿名").strip() or "匿名",
    )
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return db_template


@app.put("/api/prompt-templates/{template_id}", response_model=schemas.PromptTemplateResponse)
def update_prompt_template(
    template_id: int,
    template: schemas.PromptTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_template = db.query(models.PromptTemplate).filter(
        models.PromptTemplate.id == template_id,
        models.PromptTemplate.is_deleted == False,
        models.PromptTemplate.is_system == False,
        models.PromptTemplate.user_id == current_user.user_id
    ).first()
    if db_template is None:
        raise HTTPException(status_code=404, detail="提示词模板不存在")

    update_data = template.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_template, key, value)

    db.commit()
    db.refresh(db_template)
    return db_template


@app.delete("/api/prompt-templates/{template_id}")
def delete_prompt_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_template = db.query(models.PromptTemplate).filter(
        models.PromptTemplate.id == template_id,
        models.PromptTemplate.is_deleted == False,
        models.PromptTemplate.is_system == False,
        models.PromptTemplate.user_id == current_user.user_id
    ).first()
    if db_template is None:
        raise HTTPException(status_code=404, detail="提示词模板不存在")

    db_template.is_deleted = True
    db.commit()
    return {"message": "提示词模板删除成功"}


@app.put("/api/prompt-templates/{template_id}/visibility")
def toggle_prompt_template_visibility(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    db_template = db.query(models.PromptTemplate).filter(
        models.PromptTemplate.id == template_id,
        models.PromptTemplate.is_deleted == False,
        models.PromptTemplate.is_system == False,
        models.PromptTemplate.user_id == current_user.user_id
    ).first()
    if db_template is None:
        raise HTTPException(status_code=404, detail="提示词模板不存在")

    db_template.is_public = not db_template.is_public
    db.commit()
    db.refresh(db_template)
    return {"is_public": db_template.is_public}


# === 提示词模板公开 API（无需认证） ===

@app.get("/api/public/prompt-templates", response_model=schemas.PromptTemplatePublicListResponse)
def get_public_prompt_templates(
    skip: int = 0,
    limit: int = 12,
    search: str = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.PromptTemplate).filter(
        models.PromptTemplate.is_deleted == False,
        models.PromptTemplate.is_public == True
    )
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (models.PromptTemplate.name.like(search_pattern)) |
            (models.PromptTemplate.category.like(search_pattern)) |
            (models.PromptTemplate.description.like(search_pattern)) |
            (models.PromptTemplate.author.like(search_pattern))
        )
    total = query.count()
    items = query.order_by(models.PromptTemplate.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@app.get("/api/public/prompt-templates/{template_id}", response_model=schemas.PromptTemplatePublicResponse)
def get_public_prompt_template(
    template_id: int,
    db: Session = Depends(get_db)
):
    template = db.query(models.PromptTemplate).filter(
        models.PromptTemplate.id == template_id,
        models.PromptTemplate.is_deleted == False,
        models.PromptTemplate.is_public == True
    ).first()
    if template is None:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    return template
