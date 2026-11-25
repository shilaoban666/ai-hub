from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from database import get_db
import models
import schemas
from auth import get_current_active_user, CurrentUser
from git_client import GitClient, GitAPIError, create_git_client
from skill_utils import (
    load_skill_files, save_skill_files, parse_skill_md,
    flatten_file_tree, build_file_tree_from_flat, find_skill_md_content, delete_skill_files
)
from skill_access import get_manageable_skill_or_404

router = APIRouter(prefix="/api/git", tags=["git"])


def _create_client(provider: str, repo_url: str, access_token: str = None, branch: str = "main") -> GitClient:
    """创建 Git 客户端，access_token 可选（公开仓库不需要）"""
    token = access_token or None
    return create_git_client(provider, repo_url, token, branch)


def _get_skill_or_404(skill_id: int, db: Session, current_user: CurrentUser) -> models.Skill:
    return get_manageable_skill_or_404(db, skill_id, current_user)


@router.post("/skills/import", response_model=schemas.SkillResponse)
async def import_from_remote(
    req: schemas.GitBindRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """Initialize metadata once when creating a skill from a repository."""
    created_id = None
    try:
        client = _create_client(req.provider, req.repo_url, req.access_token, req.branch or "main")
        remote_files = await client.get_tree_files()
        content = find_skill_md_content(remote_files)
        if not content or not content.strip():
            raise HTTPException(status_code=400, detail="仓库必须包含非空的 SKILL.md 文件")
        metadata, _ = parse_skill_md(content)
        latest = await client.get_latest_commit()
        skill = models.Skill(
            user_id=current_user.user_id,
            name=metadata['name'] or '未命名技能',
            version=metadata['version'] or '1.0.0',
            description=metadata['description'],
            author=current_user.first_name,
            module='全局', roles='通用', content=content,
            git_provider=req.provider, git_repo_url=req.repo_url,
            git_branch=req.branch or 'main', git_access_token=req.access_token,
            git_sync_status='synced', git_sync_direction=1,
            git_last_synced_at=datetime.now(timezone.utc),
            git_last_commit_sha=(latest.get('sha') or latest.get('id', '')) if latest else None,
        )
        db.add(skill)
        db.flush()
        created_id = skill.id
        save_skill_files(skill.id, build_file_tree_from_flat(remote_files))
        db.commit()
    except Exception as exc:
        db.rollback()
        if created_id is not None:
            delete_skill_files(created_id)
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, GitAPIError):
            raise HTTPException(status_code=exc.status_code, detail=f"导入失败: {exc.message}")
        raise HTTPException(status_code=500, detail="从仓库创建技能失败") from exc
    db.refresh(skill)
    return skill


@router.post("/test-connection")
async def test_connection(
    req: schemas.GitTestConnectionRequest,
    current_user: CurrentUser = Depends(get_current_active_user),
):
    """测试 Git 仓库连接"""
    try:
        client = _create_client(req.provider, req.repo_url, req.access_token, req.branch or "main")
        result = await client.test_connection()
        return result
    except GitAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=f"连接失败: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败: {str(e)}")


@router.post("/skills/{skill_id}/bind")
async def bind_repo(
    skill_id: int,
    req: schemas.GitBindRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    """绑定 Git 仓库，仅保存配置，不自动同步文件"""
    skill = _get_skill_or_404(skill_id, db, current_user)
    print(f"[Routes:bind] skill_id={skill_id}, provider={req.provider}, repo_url={req.repo_url}, branch={req.branch}")

    skill.git_provider = req.provider
    skill.git_repo_url = req.repo_url
    skill.git_branch = req.branch or "main"
    skill.git_access_token = req.access_token
    db.commit()
    db.refresh(skill)

    return {
        "success": True,
        "message": "仓库配置已保存",
        "sync_status": skill.git_sync_status,
        "provider": skill.git_provider,
        "repo_url": skill.git_repo_url,
        "branch": skill.git_branch,
    }


@router.post("/skills/{skill_id}/unbind")
async def unbind_repo(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    """解除仓库绑定"""
    skill = _get_skill_or_404(skill_id, db, current_user)

    skill.git_provider = None
    skill.git_repo_url = None
    skill.git_branch = None
    skill.git_access_token = None
    skill.git_sync_status = None
    skill.git_last_synced_at = None
    skill.git_last_commit_sha = None
    db.commit()

    return {"success": True, "message": "已解除仓库绑定"}


@router.get("/skills/{skill_id}/sync-status", response_model=schemas.GitSyncStatusResponse)
async def get_sync_status(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    skill = _get_skill_or_404(skill_id, db, current_user)
    return skill


@router.post("/skills/{skill_id}/push")
async def push_to_remote(
    skill_id: int,
    req: schemas.GitPushRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    skill = _get_skill_or_404(skill_id, db, current_user)
    if not skill.git_repo_url:
        raise HTTPException(status_code=400, detail="该技能未绑定 Git 仓库")

    try:
        client = _create_client(
            skill.git_provider or "gitlab",
            skill.git_repo_url,
            skill.git_access_token,
            skill.git_branch
        )

        local_tree = load_skill_files(skill_id)
        local_files = flatten_file_tree(local_tree)
        if not local_files:
            raise HTTPException(status_code=400, detail="本地没有文件可推送")

        remote_files = await client.get_tree_files()

        if not req.force and skill.git_last_commit_sha:
            latest = await client.get_latest_commit()
            latest_sha = latest.get("sha") or latest.get("id", "") if latest else ""
            if latest_sha and latest_sha != skill.git_last_commit_sha:
                skill.git_sync_status = "error"
                db.commit()
                raise HTTPException(status_code=409, detail="远程仓库在上次同步后有新变更，请先拉取或使用强制推送")

        # 计算变更
        to_update = {}
        to_delete = []
        for path, content in local_files.items():
            if path not in remote_files or remote_files[path] != content:
                to_update[path] = content
        for path in remote_files:
            if path not in local_files:
                to_delete.append(path)

        if not to_update and not to_delete:
            skill.git_sync_status = "synced"
            db.commit()
            return {"success": True, "message": "无变更需要推送", "sync_status": "synced"}

        commit_message = req.commit_message or f"Update skill: {skill.name}"
        result = await client.create_or_update_files(to_update, commit_message, to_delete)

        skill.git_sync_status = "synced"
        skill.git_last_synced_at = datetime.now(timezone.utc)
        skill.git_last_commit_sha = result.get("sha") or result.get("id", "")
        skill.git_sync_direction = 2  # local → git
        db.commit()
        db.refresh(skill)

        return {
            "success": True,
            "message": f"已推送 {len(to_update) + len(to_delete)} 个文件变更",
            "sync_status": "synced",
        }

    except HTTPException:
        raise
    except GitAPIError as e:
        skill.git_sync_status = "error"
        db.commit()
        raise HTTPException(status_code=e.status_code, detail=f"推送失败: {e.message}")
    except Exception as e:
        skill.git_sync_status = "error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"推送失败: {str(e)}")


@router.post("/skills/{skill_id}/pull")
async def pull_from_remote(
    skill_id: int,
    req: schemas.GitPullRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    skill = _get_skill_or_404(skill_id, db, current_user)
    if not skill.git_repo_url:
        raise HTTPException(status_code=400, detail="该技能未绑定 Git 仓库")

    try:
        client = _create_client(
            skill.git_provider or "gitlab",
            skill.git_repo_url,
            skill.git_access_token,
            skill.git_branch
        )

        remote_files = await client.get_tree_files()
        if not remote_files:
            raise HTTPException(status_code=400, detail="远程仓库为空")

        file_tree = build_file_tree_from_flat(remote_files)
        save_skill_files(skill_id, file_tree)

        # File synchronization never changes the separately managed basic information.
        skill.content = find_skill_md_content(remote_files) or ''

        latest = await client.get_latest_commit()
        skill.git_sync_status = "synced"
        skill.git_last_synced_at = datetime.now(timezone.utc)
        skill.git_sync_direction = 1  # git → local
        if latest:
            skill.git_last_commit_sha = latest.get("sha") or latest.get("id", "")
        db.commit()
        db.refresh(skill)

        return {"success": True, "message": f"已拉取 {len(remote_files)} 个文件", "sync_status": "synced"}

    except HTTPException:
        raise
    except GitAPIError as e:
        skill.git_sync_status = "error"
        db.commit()
        raise HTTPException(status_code=e.status_code, detail=f"拉取失败: {e.message}")
    except Exception as e:
        skill.git_sync_status = "error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"拉取失败: {str(e)}")


@router.get("/skills/{skill_id}/diff")
async def get_diff(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_active_user)
):
    skill = _get_skill_or_404(skill_id, db, current_user)
    if not skill.git_repo_url:
        raise HTTPException(status_code=400, detail="该技能未绑定 Git 仓库")

    try:
        client = _create_client(
            skill.git_provider or "gitlab",
            skill.git_repo_url,
            skill.git_access_token,
            skill.git_branch
        )

        local_tree = load_skill_files(skill_id)
        local_files = flatten_file_tree(local_tree)
        remote_files = await client.get_tree_files()

        local_changes = []
        remote_changes = []
        conflicting_files = []

        all_paths = set(local_files.keys()) | set(remote_files.keys())
        for path in sorted(all_paths):
            in_local = path in local_files
            in_remote = path in remote_files

            if in_local and not in_remote:
                local_changes.append({"path": path, "status": "added"})
            elif not in_local and in_remote:
                remote_changes.append({"path": path, "status": "added"})
            elif in_local and in_remote and local_files[path] != remote_files[path]:
                local_changes.append({"path": path, "status": "modified"})
                remote_changes.append({"path": path, "status": "modified"})
                conflicting_files.append(path)

        return {
            "local_changes": local_changes,
            "remote_changes": remote_changes,
            "conflict": len(conflicting_files) > 0,
            "conflicting_files": conflicting_files,
        }

    except HTTPException:
        raise
    except GitAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=f"操作失败: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取差异失败: {str(e)}")
