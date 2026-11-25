"""Knowledge base console (Bailian), DingTalk drive sync, retrieval proxy and call usage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import CurrentUser, get_current_active_user
from credential_crypto import AgentCredentialError, decrypt_agent_credential, encrypt_agent_credential
from dashboard_routes import LOCAL_TZ, _resolve_period
from database import SessionLocal, get_db, settings as app_settings
from knowledge_clients import (
    BailianClient, DingtalkClient, KnowledgeServiceError, estimate_tokens, file_md5,
)
from knowledge_models import (
    KnowledgeCallHit, KnowledgeCallLog, KnowledgeDingtalkIdentity, KnowledgeDocLink, KnowledgeSettings,
    KnowledgeUpload, utcnow,
)
from knowledge_models import ensure_schema as ensure_knowledge_schema  # noqa: F401  (called from main)

logger = logging.getLogger("aihub.knowledge")

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
usage_router = APIRouter(prefix="/api/dashboard/summary/knowledge-usage", tags=["knowledge-usage"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads", "knowledge_tmp")
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_FILES_PER_REQUEST = 10
ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "txt", "md", "ppt", "pptx", "xls", "xlsx", "html", "htm",
    "png", "jpg", "jpeg", "bmp", "gif", "csv", "epub", "mobi", "json",
}
POLL_INTERVAL_SECONDS = 3.0
PARSE_TIMEOUT_SECONDS = 30 * 60
INDEX_TIMEOUT_SECONDS = 30 * 60
STALE_AFTER = timedelta(minutes=10)
ACTIVE_STATUSES = ("uploading", "parsing", "indexing")
CALLBACK_PATH = "/admin/knowledge/dingtalk-callback"
STATE_TTL_SECONDS = 600
SECRET_PURPOSE_BAILIAN = "knowledge:bailian-secret"
SECRET_PURPOSE_DINGTALK = "knowledge:dingtalk-secret"
SOURCES = ("xiaoqu", "workbuddy", "mcp", "api", "agent", "skill", "console")
TEST_SOURCE = "console"
LINK_TABLE_NAME = "钉钉文件链接对照表"
LINK_MISS_RETRY = timedelta(hours=12)
LINK_LOOKUP_WORKERS = 5
DOC_LIST_TTL_SECONDS = 300
DOC_LIST_PAGE = 100

_active_uploads: set[int] = set()
_active_lock = threading.Lock()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _require_superuser(user: CurrentUser):
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="仅超级管理员可以执行此操作")


def _service_error(exc: KnowledgeServiceError):
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _mask(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value[:4] + "****" + value[-4:] if len(value) > 10 else "****"


def _settings_row(db: Session) -> Optional[KnowledgeSettings]:
    return db.query(KnowledgeSettings).filter(KnowledgeSettings.id == 1).first()


def _decrypt(envelope, purpose) -> Optional[str]:
    if not envelope:
        return None
    try:
        return decrypt_agent_credential(envelope, purpose=purpose)
    except AgentCredentialError as exc:
        raise KnowledgeServiceError("已保存的密钥无法解密，请超级管理员重新填写", status_code=400) from exc


def bailian_client(db: Session) -> BailianClient:
    row = _settings_row(db)
    if row is None:
        raise KnowledgeServiceError("知识库尚未配置，请超级管理员先完成百炼配置", status_code=400)
    return BailianClient(
        endpoint=row.bailian_endpoint, access_key_id=row.bailian_access_key_id,
        access_key_secret=_decrypt(row.bailian_access_key_secret_encrypted, SECRET_PURPOSE_BAILIAN),
        workspace_id=row.bailian_workspace_id,
    )


def dingtalk_client(db: Session) -> DingtalkClient:
    row = _settings_row(db)
    if row is None:
        raise KnowledgeServiceError("钉钉应用尚未配置", status_code=400)
    return DingtalkClient(
        client_id=row.dingtalk_client_id,
        client_secret=_decrypt(row.dingtalk_client_secret_encrypted, SECRET_PURPOSE_DINGTALK),
    )


def _state_key() -> bytes:
    raw = str(app_settings.agent_credential_encryption_key or "") or "aihub-knowledge"
    return hashlib.sha256(f"knowledge-dingtalk-oauth:{raw}".encode("utf-8")).digest()


def make_state(user_id: int, now: Optional[float] = None) -> str:
    body = json.dumps({"u": user_id, "e": int((now or time.time()) + STATE_TTL_SECONDS),
                       "n": secrets.token_hex(6)}, separators=(",", ":")).encode("utf-8")
    payload = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    signature = hmac.new(_state_key(), payload.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{signature}"


def verify_state(state: str, user_id: int, now: Optional[float] = None) -> bool:
    try:
        payload, signature = state.split(".", 1)
        expected = hmac.new(_state_key(), payload.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(signature, expected):
            return False
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return data.get("u") == user_id and int(data.get("e", 0)) >= int(now or time.time())
    except (ValueError, TypeError):
        return False


def _safe_file_name(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = re.sub(r'[\t*"<>\\|?:/]', "_", name).rstrip(". ")
    return name[:200]


def _upload_dict(row: KnowledgeUpload) -> dict:
    return {
        "id": row.id, "user_id": row.user_id, "index_id": row.index_id, "index_name": row.index_name,
        "category_id": row.category_id, "category_name": row.category_name,
        "file_name": row.file_name, "file_size": row.file_size, "status": row.status,
        "bailian_file_id": row.bailian_file_id, "error_message": row.error_message,
        "sync_dingtalk": bool(row.sync_dingtalk), "dingtalk_folder_path": row.dingtalk_folder_path,
        "dingtalk_status": row.dingtalk_status, "dingtalk_error": row.dingtalk_error,
        "dingtalk_url": row.dingtalk_url,
        "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
    }


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

class SettingsPayload(BaseModel):
    bailian_endpoint: Optional[str] = Field(default=None, max_length=200)
    bailian_access_key_id: Optional[str] = Field(default=None, max_length=200)
    bailian_access_key_secret: Optional[str] = Field(default=None, max_length=500)
    bailian_workspace_id: Optional[str] = Field(default=None, max_length=100)
    default_index_id: Optional[str] = Field(default=None, max_length=100)
    default_category_id: Optional[str] = Field(default=None, max_length=100)
    dingtalk_client_id: Optional[str] = Field(default=None, max_length=200)
    dingtalk_client_secret: Optional[str] = Field(default=None, max_length=500)
    usage_departments: Optional[list[str]] = Field(default=None, max_length=50)
    upload_departments: Optional[list[str]] = Field(default=None, max_length=50)


# ---------------------------------------------------------------------------
# department access: who may view the usage board and who may upload
# ---------------------------------------------------------------------------

DEFAULT_USAGE_DEPARTMENTS = ("软件开发部",)
USAGE_FORBIDDEN = "知识库调用用量仅对指定部门开放，请联系管理员"
DEFAULT_UPLOAD_DEPARTMENTS = ("软件开发部", "人力资源部")
ACCESS_CACHE_SECONDS = 300
_access_cache: dict[int, tuple[float, tuple[str, ...]]] = {}
_access_lock = threading.Lock()


def _department_list(raw, default) -> list[str]:
    if raw is None:
        return list(default)
    try:
        names = json.loads(raw)
    except ValueError:
        return list(default)
    return [str(name).strip() for name in names if str(name).strip()] if isinstance(names, list) else list(default)


def configured_departments(row: Optional[KnowledgeSettings]) -> dict:
    return {
        "usage": _department_list(row.usage_departments if row else None, DEFAULT_USAGE_DEPARTMENTS),
        "upload": _department_list(row.upload_departments if row else None, DEFAULT_UPLOAD_DEPARTMENTS),
    }


def user_departments(user_id: int, authorization: Optional[str]) -> tuple[str, ...]:
    return ()


def knowledge_access(db: Session, user: CurrentUser, authorization: Optional[str]) -> dict:
    """Superusers may always; everyone else by being in one of the configured departments.
    When departments cannot be looked up, nothing is granted (the lookup's 503 propagates)."""
    allowed = configured_departments(_settings_row(db))
    if user.is_superuser:
        return {"can_view_usage": True, "can_upload": True, "departments": [], **{f"{k}_departments": v for k, v in allowed.items()}}
    mine = user_departments(user.user_id, authorization)
    return {
        "can_view_usage": any(name in mine for name in allowed["usage"]),
        "can_upload": any(name in mine for name in allowed["upload"]),
        "departments": list(mine),
        "usage_departments": allowed["usage"], "upload_departments": allowed["upload"],
    }


def _require_access(db, user, authorization, key, message):
    if not knowledge_access(db, user, authorization)[key]:
        raise HTTPException(status_code=403, detail=message)


def _settings_dict(row: Optional[KnowledgeSettings], user: CurrentUser) -> dict:
    bailian_ready = bool(row and row.bailian_access_key_id and row.bailian_access_key_secret_encrypted
                         and row.bailian_workspace_id)
    dingtalk_ready = bool(row and row.dingtalk_client_id and row.dingtalk_client_secret_encrypted)
    result = {
        "bailian_configured": bailian_ready,
        "dingtalk_configured": dingtalk_ready,
        "default_index_id": row.default_index_id if row else None,
        "default_category_id": row.default_category_id if row else None,
        "can_manage": bool(user.is_superuser),
    }
    if user.is_superuser:
        result.update({
            "bailian_endpoint": row.bailian_endpoint if row else "bailian.cn-beijing.aliyuncs.com",
            "bailian_access_key_id": row.bailian_access_key_id if row else None,
            "bailian_access_key_secret_masked": "已保存" if row and row.bailian_access_key_secret_encrypted else None,
            "bailian_workspace_id": row.bailian_workspace_id if row else None,
            "dingtalk_client_id": row.dingtalk_client_id if row else None,
            "dingtalk_client_secret_masked": "已保存" if row and row.dingtalk_client_secret_encrypted else None,
            "updated_at": _iso(row.updated_at) if row else None,
            **{f"{key}_departments": names for key, names in configured_departments(row).items()},
        })
    return result


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    return _settings_dict(_settings_row(db), user)


@router.get("/access")
def get_access(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user),
               authorization: Optional[str] = Header(None)):
    """What the current user may do here, for showing or hiding the upload form and the usage menu."""
    try:
        return knowledge_access(db, user, authorization)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return {"can_view_usage": False, "can_upload": False, "departments": [], "error": exc.detail}


@router.get("/department-options")
def department_options(user: CurrentUser = Depends(get_current_active_user),
                       authorization: Optional[str] = Header(None)):
    _require_superuser(user)
    return {"items": []}


@router.put("/settings")
def update_settings(payload: SettingsPayload, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(get_current_active_user)):
    _require_superuser(user)
    row = _settings_row(db) or KnowledgeSettings(id=1)
    for field in ("bailian_access_key_id", "bailian_workspace_id", "default_index_id",
                  "default_category_id", "dingtalk_client_id"):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value.strip() or None)
    for field in ("usage_departments", "upload_departments"):
        names = getattr(payload, field)
        if names is not None:
            cleaned = list(dict.fromkeys(name.strip()[:100] for name in names if name and name.strip()))
            setattr(row, field, json.dumps(cleaned, ensure_ascii=False))
    with _access_lock:
        _access_cache.clear()
    if payload.bailian_endpoint is not None:
        endpoint = payload.bailian_endpoint.strip().replace("https://", "").strip("/")
        if endpoint and not re.fullmatch(r"[a-z0-9.-]+\.aliyuncs\.com", endpoint):
            raise HTTPException(status_code=400, detail="百炼服务地址必须是 *.aliyuncs.com 域名")
        row.bailian_endpoint = endpoint or "bailian.cn-beijing.aliyuncs.com"
    for field, column, purpose in (
        ("bailian_access_key_secret", "bailian_access_key_secret_encrypted", SECRET_PURPOSE_BAILIAN),
        ("dingtalk_client_secret", "dingtalk_client_secret_encrypted", SECRET_PURPOSE_DINGTALK),
    ):
        value = getattr(payload, field)
        if value:
            encrypted = encrypt_agent_credential(value.strip(), purpose=purpose)
            if not encrypted:
                raise HTTPException(status_code=500, detail="服务端未配置 AGENT_CREDENTIAL_ENCRYPTION_KEY，无法加密保存密钥")
            setattr(row, column, encrypted)
    row.updated_by = user.user_id
    db.add(row)
    db.commit()
    db.refresh(row)
    return _settings_dict(row, user)


@router.post("/settings/test")
def test_settings(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    _require_superuser(user)
    result = {}
    try:
        data = bailian_client(db).list_indices(page_size=10)
        result["bailian"] = {"ok": True, "message": f"连接成功，共 {data.get('TotalCount', len(data.get('Indices') or []))} 个知识库"}
    except KnowledgeServiceError as exc:
        result["bailian"] = {"ok": False, "message": str(exc)}
    try:
        dingtalk_client(db).app_token()
        result["dingtalk"] = {"ok": True, "message": "钉钉应用凭证有效"}
    except KnowledgeServiceError as exc:
        result["dingtalk"] = {"ok": False, "message": str(exc)}
    return result


# ---------------------------------------------------------------------------
# Bailian browsing
# ---------------------------------------------------------------------------

@router.get("/indices")
def list_indices(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    try:
        data = bailian_client(db).list_indices()
    except KnowledgeServiceError as exc:
        raise _service_error(exc)
    items = [{
        "id": item.get("Id"), "name": item.get("Name"), "description": item.get("Description"),
        "structure_type": item.get("StructureType"), "source_type": item.get("SourceType"),
    } for item in data.get("Indices") or []]
    return {"total": len(items), "items": items}


@router.get("/categories")
def list_categories(parent_id: Optional[str] = Query(None, max_length=100),
                    db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    try:
        client = bailian_client(db)
        items, token = [], None
        for _ in range(20):
            data = client.list_categories(parent_id=parent_id, next_token=token)
            items.extend(data.get("CategoryList") or [])
            token = data.get("NextToken")
            if not token or str(data.get("HasNext", "true")).lower() == "false":
                break
    except KnowledgeServiceError as exc:
        raise _service_error(exc)
    return {"total": len(items), "items": [{
        "id": item.get("CategoryId"), "name": item.get("CategoryName"),
        "parent_id": item.get("ParentId"), "is_default": bool(item.get("IsDefault")),
    } for item in items]}


@router.get("/documents")
def list_documents(index_id: str = Query(..., max_length=100), page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100), name: Optional[str] = Query(None, max_length=200),
                   db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    keyword = (name or "").strip()
    try:
        if keyword:
            # Bailian only filters on the exact full name, so search a cached copy of the whole list instead.
            matches = [doc for doc in all_index_documents(db, index_id)
                       if keyword.casefold() in (doc.get("Name") or "").casefold()]
            data = {"TotalCount": len(matches), "Documents": matches[(page - 1) * page_size:page * page_size]}
        else:
            data = bailian_client(db).list_index_documents(index_id, page, page_size, None)
    except KnowledgeServiceError as exc:
        raise _service_error(exc)
    documents = data.get("Documents") or []
    links = dingtalk_links(db, index_id, documents)
    missing = [doc.get("Name") for doc in documents if not links.get(doc.get("Id")) and doc.get("Name")]
    links_pending = False
    if missing:
        # Cached links come back now; unknown ones are looked up in the background so the list never
        # waits on a dozen retrievals. The page asks again shortly (links_pending) to pick them up.
        from_table, todo = cached_table_links(db, index_id, missing)
        if todo:
            links_pending = True
            _start_link_lookup(index_id, todo)
        for doc in documents:
            if not links.get(doc.get("Id")):
                links[doc.get("Id")] = from_table.get((doc.get("Name") or "").strip())
    return {"total": int(data.get("TotalCount") or 0), "links_pending": links_pending, "items": [{
        "id": doc.get("Id"), "name": doc.get("Name"), "status": doc.get("Status"),
        "size": doc.get("Size"), "document_type": doc.get("DocumentType"),
        "updated_at": doc.get("GmtModified"), "message": doc.get("Message"),
        "dingtalk_url": links.get(doc.get("Id")),
    } for doc in documents]}


_doc_list_cache: dict[str, tuple[float, list[dict]]] = {}
_doc_list_lock = threading.Lock()


def all_index_documents(db: Session, index_id: str) -> list[dict]:
    """Every document of an index, in Bailian's order, cached for a few minutes for name search."""
    with _doc_list_lock:
        cached = _doc_list_cache.get(index_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]
    client = bailian_client(db)
    first = client.list_index_documents(index_id, 1, DOC_LIST_PAGE, None)
    total = int(first.get("TotalCount") or 0)
    pages = min((total + DOC_LIST_PAGE - 1) // DOC_LIST_PAGE, 200)
    with ThreadPoolExecutor(max_workers=3) as pool:  # Bailian rate-limits; the client retries throttled calls
        rest = list(pool.map(lambda n: client.list_index_documents(index_id, n, DOC_LIST_PAGE, None), range(2, pages + 1)))
    documents = [doc for data in [first, *rest] for doc in data.get("Documents") or []]
    with _doc_list_lock:
        _doc_list_cache[index_id] = (time.monotonic() + DOC_LIST_TTL_SECONDS, documents)
    return documents


def dingtalk_links(db: Session, index_id: str, documents: list[dict]) -> dict:
    """Map Bailian document ids to the DingTalk drive copy made when they were uploaded here.

    Matches by Bailian file id first; documents re-imported under a new id fall back to the
    latest synced upload with the same file name in the same knowledge base.
    """
    if not documents:
        return {}
    # Bailian lists documents without their extension ("报销制度" for "报销制度.pdf"), so names are
    # compared on both forms in Python; only synced uploads of this knowledge base are candidates.
    rows = db.query(KnowledgeUpload.bailian_file_id, KnowledgeUpload.file_name, KnowledgeUpload.dingtalk_url).filter(
        KnowledgeUpload.index_id == index_id, KnowledgeUpload.dingtalk_url.isnot(None),
    ).order_by(KnowledgeUpload.id.desc()).limit(5000).all()
    by_id, by_name = {}, {}
    for file_id, name, url in reversed(rows):  # oldest first, so the latest upload wins
        if file_id:
            by_id[file_id] = url
        by_name[name] = url
        by_name[name.rsplit(".", 1)[0]] = url
    return {doc.get("Id"): by_id.get(doc.get("Id")) or by_name.get(doc.get("Name")) for doc in documents}


def parse_link_rows(text: str) -> list[tuple[str, Optional[str], str]]:
    """Rows of the link table as Bailian chunks them: 文件名 / 文件目录 / 钉钉链接 lines."""
    rows, current = [], {}

    def flush():
        if current.get("name") and (current.get("url") or "").startswith("http"):
            rows.append((current["name"], current.get("folder"), current["url"]))

    for line in (text or "").splitlines():
        key, sep, value = line.replace("：", ":", 1).partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "文件名":
            flush()
            current = {"name": value}
        elif key == "文件目录":
            current["folder"] = value
        elif key == "钉钉链接":
            current["url"] = value
    flush()
    return rows


def _lookup_link_rows(client, index_id: str, name: str) -> list[tuple[str, Optional[str], str]]:
    data = client.retrieve(index_id, f"{LINK_TABLE_NAME} {name}", rerank_top_n=10)
    rows = []
    for node in data.get("Nodes") or []:
        meta = node.get("Metadata") or {}
        source = meta.get("doc_name") or meta.get("file_name") or meta.get("title") or ""
        if LINK_TABLE_NAME in source:
            rows.extend(parse_link_rows(node.get("Text") or ""))
    return rows


_link_inflight: set[tuple[str, str]] = set()
_link_inflight_lock = threading.Lock()


def _link_names(names) -> list[str]:
    return list(dict.fromkeys(n.strip()[:255] for n in names if n and n.strip() and n.strip() != LINK_TABLE_NAME))


def cached_table_links(db: Session, index_id: str, names: list[str]) -> tuple[dict, list[str]]:
    """Links already known, and the names that still need (or are due for another) lookup."""
    names = _link_names(names)
    cached = {row.doc_name: row for row in db.query(KnowledgeDocLink).filter(
        KnowledgeDocLink.index_id == index_id, KnowledgeDocLink.doc_name.in_(names)).all()} if names else {}
    retry_before = utcnow() - LINK_MISS_RETRY
    todo = [n for n in names if n not in cached or (
        not cached[n].dingtalk_url and (cached[n].checked_at or retry_before) <= retry_before)]
    return {n: row.dingtalk_url for n, row in cached.items() if row.dingtalk_url}, todo


def _start_link_lookup(index_id: str, names: list[str]) -> None:
    with _link_inflight_lock:
        fresh = [n for n in names if (index_id, n) not in _link_inflight]
        _link_inflight.update((index_id, n) for n in fresh)
    if not fresh:
        return

    def run():
        db = SessionLocal()
        try:
            table_links(db, index_id, fresh)
        except Exception:  # pragma: no cover - a failed lookup only leaves links empty for now
            logger.exception("background link lookup failed for index %s", index_id)
        finally:
            db.close()
            with _link_inflight_lock:
                _link_inflight.difference_update((index_id, n) for n in fresh)

    threading.Thread(target=run, name=f"knowledge-links-{index_id}", daemon=True).start()


def table_links(db: Session, index_id: str, names: list[str], *, client_factory=None) -> dict:
    """DingTalk links for documents without an upload row, from the link table inside the index.

    Lookups are cached in knowledge_doc_links (misses too, retried after LINK_MISS_RETRY). They are
    system lookups that put nothing into a model's context, so they are not logged as RAG usage.
    """
    names = list(dict.fromkeys(n.strip()[:255] for n in names if n and n.strip() and n.strip() != LINK_TABLE_NAME))
    if not names:
        return {}
    cached = {row.doc_name: row for row in db.query(KnowledgeDocLink).filter(
        KnowledgeDocLink.index_id == index_id, KnowledgeDocLink.doc_name.in_(names)).all()}
    retry_before = utcnow() - LINK_MISS_RETRY
    todo = [n for n in names if n not in cached or (
        not cached[n].dingtalk_url and (cached[n].checked_at or retry_before) <= retry_before)]
    if todo:
        try:
            client = (client_factory or bailian_client)(db)
        except KnowledgeServiceError:
            client = None
        if client is not None:
            def lookup(name):
                try:
                    return name, _lookup_link_rows(client, index_id, name)
                except Exception as exc:  # one failed lookup only leaves that link empty for now
                    logger.warning("link table lookup failed for %s: %s", name, exc)
                    return name, None

            with ThreadPoolExecutor(max_workers=LINK_LOOKUP_WORKERS) as pool:
                results = list(pool.map(lookup, todo))
            found = {}
            for _, rows in results:
                for row_name, folder, url in rows or []:
                    found.setdefault(row_name[:255], (folder, url))
            now = utcnow()
            looked_up = {name for name, rows in results if rows is not None}
            # Every exact row seen is cached, not just the names asked for: neighbouring rows come back
            # with each lookup and save later page views a call.
            for name in looked_up | (set(found) - set(cached)):
                folder, url = found.get(name, (None, None))
                row = cached.get(name) or db.query(KnowledgeDocLink).filter(
                    KnowledgeDocLink.index_id == index_id, KnowledgeDocLink.doc_name == name).first()
                if row is None:
                    row = KnowledgeDocLink(index_id=index_id, doc_name=name)
                    db.add(row)
                row.dingtalk_url, row.folder_path, row.checked_at = url and url[:500], folder and folder[:500], now
                cached[name] = row
            try:
                db.commit()
            except IntegrityError:  # a concurrent page view cached the same rows first
                db.rollback()
                cached = {row.doc_name: row for row in db.query(KnowledgeDocLink).filter(
                    KnowledgeDocLink.index_id == index_id, KnowledgeDocLink.doc_name.in_(names)).all()}
    return {name: cached[name].dingtalk_url for name in names if name in cached and cached[name].dingtalk_url}


# ---------------------------------------------------------------------------
# DingTalk binding and folders
# ---------------------------------------------------------------------------

class BindPayload(BaseModel):
    code: str = Field(min_length=1, max_length=500)
    state: str = Field(min_length=1, max_length=500)


def _identity(db, user_id) -> Optional[KnowledgeDingtalkIdentity]:
    return db.query(KnowledgeDingtalkIdentity).filter(KnowledgeDingtalkIdentity.user_id == user_id).first()


@router.get("/dingtalk/status")
def dingtalk_status(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    identity = _identity(db, user.user_id)
    row = _settings_row(db)
    return {
        "configured": bool(row and row.dingtalk_client_id and row.dingtalk_client_secret_encrypted),
        "bound": identity is not None,
        "nick": identity.nick if identity else None,
        "bound_at": _iso(identity.updated_at) if identity else None,
    }


@router.get("/dingtalk/authorize-url")
def dingtalk_authorize_url(redirect_uri: str = Query(..., max_length=500), db: Session = Depends(get_db),
                           user: CurrentUser = Depends(get_current_active_user)):
    if not re.fullmatch(r"https?://[^/?#]+" + re.escape(CALLBACK_PATH), redirect_uri):
        raise HTTPException(status_code=400, detail="回调地址无效")
    try:
        url = dingtalk_client(db).authorize_url(redirect_uri, make_state(user.user_id))
    except KnowledgeServiceError as exc:
        raise _service_error(exc)
    return {"url": url}


@router.post("/dingtalk/bind")
def dingtalk_bind(payload: BindPayload, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(get_current_active_user)):
    if not verify_state(payload.state, user.user_id):
        raise HTTPException(status_code=400, detail="授权状态无效或已过期，请重新扫码")
    try:
        profile = dingtalk_client(db).user_by_code(payload.code)
    except KnowledgeServiceError as exc:
        raise _service_error(exc)
    identity = _identity(db, user.user_id) or KnowledgeDingtalkIdentity(user_id=user.user_id)
    identity.union_id = profile["union_id"]
    identity.nick = profile["nick"][:100] or None
    db.add(identity)
    db.commit()
    return {"bound": True, "nick": identity.nick}


@router.delete("/dingtalk/binding")
def dingtalk_unbind(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    identity = _identity(db, user.user_id)
    if identity:
        db.delete(identity)
        db.commit()
    return {"bound": False}


def _require_identity(db, user) -> KnowledgeDingtalkIdentity:
    identity = _identity(db, user.user_id)
    if identity is None:
        raise HTTPException(status_code=400, detail="请先扫码绑定钉钉账号")
    return identity


@router.get("/dingtalk/workspaces")
def dingtalk_workspaces(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    """The bound user's 钉盘「团队文件」: 全员文件夹 and the shared team folders they can see."""
    identity = _require_identity(db, user)
    try:
        items = dingtalk_client(db).list_team_spaces(identity.union_id)
    except KnowledgeServiceError as exc:
        raise _service_error(exc)
    return {"items": [{
        "workspace_id": str(item["spaceId"]), "root_node_id": folder_ref(item["spaceId"], "0"),
        "name": item.get("spaceName") or str(item["spaceId"]), "type": item.get("spaceType"),
    } for item in items if item.get("spaceId")]}


@router.get("/dingtalk/folders")
def dingtalk_folders(parent_node_id: str = Query(..., min_length=1, max_length=100),
                     db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    """Subfolders the bound user can see. DingTalk leaves out folders the user cannot read, so a folder
    shared only deep down a tree cannot be reached here: for those, see /dingtalk/resolve-folder."""
    identity = _require_identity(db, user)
    space_id, parent_id = parse_folder_ref(parent_node_id)
    if not space_id or parent_id == UNKNOWN_DENTRY:
        raise HTTPException(status_code=400, detail="钉盘目录无效，请重新选择")
    try:
        items = dingtalk_client(db).list_space_folders(identity.union_id, space_id, parent_id)
    except KnowledgeServiceError as exc:
        raise _service_error(exc)
    items = sorted((item for item in items if item.get("id")), key=lambda item: _natural_key(item.get("name") or ""))
    return {"items": [{
        "node_id": folder_ref(space_id, item["id"], item.get("uuid")), "name": item.get("name"), "has_children": True,
    } for item in items]}


FOLDER_LINK = re.compile(r"/(?:nodes|folders)/([A-Za-z0-9]{16,64})")


@router.get("/dingtalk/resolve-folder")
def dingtalk_resolve_folder(link: str = Query(..., min_length=8, max_length=500),
                            db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    """Turn a pasted 钉盘 folder link (…/i/nodes/<uuid> or …/folders/<uuid>) into an upload target.

    DingTalk answers as the bound user, so only folders that person can open resolve.
    """
    identity = _require_identity(db, user)
    match = FOLDER_LINK.search(link.strip()) or re.fullmatch(r"([A-Za-z0-9]{16,64})", link.strip())
    if not match:
        raise HTTPException(status_code=400, detail="请粘贴钉盘文件夹的链接（在钉钉文档里打开文件夹后复制地址栏）")
    client = dingtalk_client(db)
    try:
        folder = client.resolve_dentry(identity.union_id, match.group(1))
    except KnowledgeServiceError as exc:
        if "permissionDenied" in str(exc) or "documentNotExist" in str(exc):
            raise HTTPException(status_code=400, detail="打不开这个链接：文件夹不存在，或你的钉钉账号没有它的访问权限") from exc
        raise _service_error(exc)
    if folder.get("status", "NORMAL") != "NORMAL":
        raise HTTPException(status_code=400, detail="这个文件夹已被删除或已过期")
    if folder["type"] != "FOLDER":
        raise HTTPException(status_code=400, detail="这个链接是文件，不是文件夹，请粘贴文件夹的链接")
    space_name = ""
    try:
        space_name = next((item.get("spaceName") or "" for item in client.list_team_spaces(identity.union_id)
                           if str(item.get("spaceId")) == folder["space_id"]), "")
    except KnowledgeServiceError:
        pass
    path = " / ".join(part for part in [space_name, *folder["path"].strip("/").split("/")] if part)
    return {"node_id": folder_ref(folder["space_id"], folder["dentry_id"], folder["uuid"]),
            "name": folder["name"], "path": path or folder["name"]}


@router.get("/dingtalk/recent-folders")
def dingtalk_recent_folders(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    """The 钉盘 folders this user last uploaded to successfully, newest first, for one-click reuse."""
    rows = db.query(KnowledgeUpload.dingtalk_folder_id, KnowledgeUpload.dingtalk_folder_path).filter(
        KnowledgeUpload.user_id == user.user_id, KnowledgeUpload.dingtalk_status == "success",
        KnowledgeUpload.dingtalk_folder_id.isnot(None),
    ).order_by(KnowledgeUpload.id.desc()).limit(50).all()
    seen, items = set(), []
    for folder_id, path in rows:
        if parse_folder_ref(folder_id)[0] and folder_id not in seen:
            seen.add(folder_id)
            items.append({"node_id": folder_id, "path": path or folder_id})
        if len(items) == 5:
            break
    return {"items": items}


UNKNOWN_DENTRY = "-"  # a folder only the node API returned: known by uuid, not by storage dentry id


def _natural_key(name: str):
    """Sort "2.软件开发部" before "10.大健产品部", as DingTalk shows them."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
            for part in re.split(r"(\d+)", name or "") if part]


def folder_ref(space_id, dentry_id, uuid=None) -> str:
    """A 团队文件 folder as one picker value: "<spaceId>/<dentryId>[/<uuid>]", the space root being dentry 0."""
    return f"{space_id}/{dentry_id}/{uuid}" if uuid else f"{space_id}/{dentry_id}"


def parse_folder_ref(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    space_id, dentry_id, _uuid = parse_folder_ref_full(value)
    return space_id, dentry_id


def parse_folder_ref_full(value: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    parts = (value or "").split("/")
    if len(parts) < 2 or not parts[0]:
        return None, None, None
    return parts[0], parts[1] or "0", (parts[2] if len(parts) > 2 and parts[2] else None)


# ---------------------------------------------------------------------------
# uploads
# ---------------------------------------------------------------------------

def _update(db, upload_id, **values):
    values["updated_at"] = utcnow()
    db.query(KnowledgeUpload).filter(KnowledgeUpload.id == upload_id).update(values)
    db.commit()


def _wait(check, timeout, label):
    deadline = time.monotonic() + timeout
    while True:
        done = check()
        if done:
            return done
        if time.monotonic() > deadline:
            raise KnowledgeServiceError(f"{label}超时，请稍后在百炼控制台确认")
        time.sleep(POLL_INTERVAL_SECONDS)


def process_upload(upload_id: int, temp_path: str, *, session_factory=SessionLocal,
                   bailian_factory=bailian_client, dingtalk_factory=dingtalk_client) -> None:
    """Import one file into the Bailian dataset and index first; only then copy it to DingTalk drive.

    Runs in a worker thread. The DingTalk copy is made only after the knowledge base import
    succeeds, so the drive never holds files the knowledge base rejected.
    """
    db = session_factory()
    try:
        row = db.query(KnowledgeUpload).filter(KnowledgeUpload.id == upload_id).one()
        imported = _import_to_bailian(db, row, temp_path, bailian_factory)
        if row.sync_dingtalk:
            if imported:
                _copy_to_dingtalk(db, row, temp_path, dingtalk_factory)
            else:
                _update(db, upload_id, dingtalk_status="failed", dingtalk_error="知识库导入未成功，未同步到钉盘")
    except Exception:  # pragma: no cover - unexpected bug must not leave the row spinning
        logger.exception("knowledge upload %s crashed", upload_id)
        try:
            db.rollback()
            values = {"status": "failed", "error_message": "处理异常，请重试"}
            current = db.query(KnowledgeUpload).filter(KnowledgeUpload.id == upload_id).first()
            if current is not None and current.status == "completed":
                values = {}
            if current is not None and current.dingtalk_status == "pending":
                values.update(dingtalk_status="failed", dingtalk_error="处理异常")
            if values:
                _update(db, upload_id, **values)
        except Exception:
            logger.exception("knowledge upload %s could not be marked failed", upload_id)
    finally:
        db.close()
        with _active_lock:
            _active_uploads.discard(upload_id)
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _import_to_bailian(db, row, temp_path, bailian_factory) -> bool:
    upload_id = row.id
    try:
        client = bailian_factory(db)
        lease = client.apply_upload_lease(row.category_id, row.file_name, file_md5(temp_path), row.file_size)
        client.put_to_lease(lease, temp_path)
        file_id = (client.add_file(lease["FileUploadLeaseId"], row.category_id) or {}).get("FileId")
        if not file_id:
            raise KnowledgeServiceError("百炼未返回文件 ID")
        _update(db, upload_id, bailian_file_id=file_id, status="parsing")

        def parsed():
            status = (client.describe_file(file_id) or {}).get("Status")
            if status in ("PARSE_FAILED", "FAILED"):
                raise KnowledgeServiceError("百炼文件解析失败，请检查文件内容或格式")
            return status == "PARSE_SUCCESS"

        _wait(parsed, PARSE_TIMEOUT_SECONDS, "文件解析")
        job_id = (client.add_documents_to_index(row.index_id, [file_id]) or {}).get("Id")
        if not job_id:
            raise KnowledgeServiceError("百炼未返回知识库导入任务 ID")
        _update(db, upload_id, bailian_job_id=job_id, status="indexing")

        def indexed():
            status = (client.index_job_status(row.index_id, job_id) or {}).get("Status")
            if status == "FAILED":
                raise KnowledgeServiceError("百炼知识库导入任务失败")
            return status == "COMPLETED"

        _wait(indexed, INDEX_TIMEOUT_SECONDS, "知识库导入")
        _update(db, upload_id, status="completed", error_message=None)
        with _doc_list_lock:  # name search should find the new file right away
            _doc_list_cache.pop(row.index_id, None)
        return True
    except (KnowledgeServiceError, KeyError) as exc:
        _update(db, upload_id, status="failed", error_message=str(exc) or "上传失败")
        return False


def _copy_to_dingtalk(db, row, temp_path, dingtalk_factory) -> None:
    try:
        identity = _identity(db, row.user_id)
        if identity is None:
            raise KnowledgeServiceError("未绑定钉钉账号")
        dingtalk = dingtalk_factory(db)
        space_id, parent_id, parent_uuid = parse_folder_ref_full(row.dingtalk_folder_id)
        if space_id:
            dentry = dingtalk.upload_to_space(identity.union_id, space_id, parent_id, temp_path,
                                              row.file_name, row.file_size, parent_uuid=parent_uuid)
        else:  # rows picked from the old 钉钉知识库 picker carry a wiki node id
            dentry = dingtalk.upload_file(identity.union_id, row.dingtalk_folder_id, temp_path,
                                          row.file_name, row.file_size)
        node_uuid = str(dentry.get("uuid") or "")
        # Space uploads keep "<spaceId>/<dentryId>" so the copy can be deleted later; the link uses the uuid.
        dentry_ref = folder_ref(dentry.get("spaceId") or space_id, dentry["id"]) if space_id and dentry.get("id") else ""
        _update(db, row.id, dingtalk_status="success",
                dingtalk_dentry_id=dentry_ref or node_uuid or str(dentry.get("id") or ""),
                dingtalk_url=dingtalk.node_url(identity.union_id, node_uuid) if node_uuid else None)
    except KnowledgeServiceError as exc:
        message = str(exc)
        if "permissionDenied" in message:
            message = f"你在所选钉盘目录没有上传权限，请换一个你能编辑的目录或找该目录管理员开通（{message}）"
        _update(db, row.id, dingtalk_status="failed", dingtalk_error=message[:2000])


def _start_worker(upload_id: int, temp_path: str):
    with _active_lock:
        _active_uploads.add(upload_id)
    threading.Thread(target=process_upload, args=(upload_id, temp_path),
                     name=f"knowledge-upload-{upload_id}", daemon=True).start()


def _expire_stale(db: Session):
    """Rows left in progress by a restarted server would otherwise spin forever."""
    limit = utcnow() - STALE_AFTER
    with _active_lock:
        active = set(_active_uploads)
    stale = db.query(KnowledgeUpload).filter(KnowledgeUpload.status.in_(ACTIVE_STATUSES),
                                             KnowledgeUpload.updated_at < limit).all()
    changed = False
    for row in stale:
        if row.id not in active:
            row.status = "failed"
            row.error_message = "处理中断（服务重启），请重新上传"
            if row.dingtalk_status == "pending":
                row.dingtalk_status = "failed"
                row.dingtalk_error = "处理中断"
            changed = True
    if changed:
        db.commit()


@router.post("/uploads")
async def create_uploads(
    files: list[UploadFile] = File(...),
    index_id: str = Form(..., max_length=100),
    category_id: str = Form(..., max_length=100),
    index_name: Optional[str] = Form(None, max_length=200),
    category_name: Optional[str] = Form(None, max_length=200),
    sync_dingtalk: bool = Form(False),
    dingtalk_workspace_id: Optional[str] = Form(None, max_length=100),
    dingtalk_folder_id: Optional[str] = Form(None, max_length=100),
    dingtalk_folder_path: Optional[str] = Form(None, max_length=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_active_user),
    authorization: Optional[str] = Header(None),
):
    _require_access(db, user, authorization, "can_upload", "你所在的部门暂未开通知识库上传，请联系管理员")
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的文件")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"单次最多上传 {MAX_FILES_PER_REQUEST} 个文件")
    try:
        bailian_client(db)
        if sync_dingtalk:
            dingtalk_client(db)
    except KnowledgeServiceError as exc:
        raise _service_error(exc)
    if sync_dingtalk:
        _require_identity(db, user)
        if not dingtalk_folder_id:
            raise HTTPException(status_code=400, detail="请选择钉盘存储目录")

    prepared = []
    for upload in files:
        name = _safe_file_name(upload.filename)
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if not name or extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型：{upload.filename}")
        prepared.append((upload, name))

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    created = []
    for upload, name in prepared:
        temp_path = os.path.join(UPLOAD_DIR, f"{secrets.token_hex(12)}.{name.rsplit('.', 1)[-1].lower()}")
        size = 0
        with open(temp_path, "wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    handle.close()
                    os.remove(temp_path)
                    raise HTTPException(status_code=400, detail=f"{name} 超过 100 MB 上限")
                handle.write(chunk)
        if size == 0:
            os.remove(temp_path)
            raise HTTPException(status_code=400, detail=f"{name} 是空文件")
        row = KnowledgeUpload(
            user_id=user.user_id, index_id=index_id.strip(), index_name=index_name,
            category_id=category_id.strip(), category_name=category_name, file_name=name, file_size=size,
            status="uploading", sync_dingtalk=bool(sync_dingtalk),
            dingtalk_workspace_id=dingtalk_workspace_id if sync_dingtalk else None,
            dingtalk_folder_id=dingtalk_folder_id if sync_dingtalk else None,
            dingtalk_folder_path=dingtalk_folder_path if sync_dingtalk else None,
            dingtalk_status="pending" if sync_dingtalk else "none",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        created.append((row, temp_path))
    for row, temp_path in created:
        _start_worker(row.id, temp_path)
    return {"items": [_upload_dict(row) for row, _ in created]}


@router.get("/uploads")
def list_uploads(skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
                 db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user)):
    """Upload records are private: everyone, superusers included, sees only their own."""
    _expire_stale(db)
    query = db.query(KnowledgeUpload).filter(KnowledgeUpload.user_id == user.user_id)
    total = query.count()
    rows = query.order_by(KnowledgeUpload.id.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": [_upload_dict(row) for row in rows]}


@router.delete("/uploads/{upload_id}")
def delete_upload(upload_id: int, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(get_current_active_user)):
    """Remove an uploaded file everywhere it went: the knowledge base, Bailian's data center and the 钉盘 copy.

    Only the uploader may do this. Every remote delete is idempotent, so a failed attempt can be retried.
    """
    row = db.query(KnowledgeUpload).filter(KnowledgeUpload.id == upload_id,
                                          KnowledgeUpload.user_id == user.user_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="上传记录不存在")
    if row.status in ACTIVE_STATUSES or row.dingtalk_status == "pending":
        raise HTTPException(status_code=409, detail="文件还在处理中，完成后再删除")
    removed = []
    try:
        if row.bailian_file_id:
            client = bailian_client(db)
            if row.status == "completed" or row.bailian_job_id:  # in the index, imported or not
                client.delete_index_document(row.index_id, [row.bailian_file_id])
                removed.append("知识库")
            client.delete_file(row.bailian_file_id)
            removed.append("百炼应用数据")
        space_id, dentry_id = parse_folder_ref(row.dingtalk_dentry_id)
        if row.dingtalk_status == "success" and space_id:
            identity = _require_identity(db, user)
            dingtalk_client(db).delete_dentry(identity.union_id, space_id, dentry_id)
            removed.append("钉盘")
        elif row.dingtalk_status == "success":
            removed.append("钉盘副本需手动删除（旧版目录上传）")
    except KnowledgeServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code,
                            detail=f"删除未完成（已删除：{'、'.join(removed) or '无'}）：{exc}") from exc
    with _doc_list_lock:
        # Drop it from the cached list rather than refetching: Bailian keeps listing a deleted file briefly.
        cached = _doc_list_cache.get(row.index_id)
        if cached and row.bailian_file_id:
            _doc_list_cache[row.index_id] = (cached[0], [d for d in cached[1] if d.get("Id") != row.bailian_file_id])
    db.delete(row)
    db.commit()
    return {"deleted": True, "removed": removed}


# ---------------------------------------------------------------------------
# retrieval (logged for usage)
# ---------------------------------------------------------------------------

class RetrievePayload(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    index_id: Optional[str] = Field(default=None, max_length=100)
    index_name: Optional[str] = Field(default=None, max_length=200)
    top_n: int = Field(default=5, ge=1, le=20)
    # Channel the question came from: xiaoqu (默认助手小趣), workbuddy (WorkBuddy via MCP), mcp (other MCP
    # clients), api (access token), agent (other custom agents), skill, console (检索测试 page).
    source: str = Field(default="api", pattern=f"^({'|'.join(SOURCES)})$")
    session_id: Optional[str] = Field(default=None, max_length=64)


def record_call(db, *, user_id, index_id, index_name, source, query, status, nodes=None,
                latency_ms=0, error=None, session_id=None, external_id=None, created_at=None,
                commit=True) -> KnowledgeCallLog:
    # A failed retrieval injects nothing into the model context, so it consumes no RAG tokens.
    query_tokens = estimate_tokens(query) if status == "success" else 0
    result_tokens = sum(estimate_tokens(node.get("text")) for node in nodes or [])
    log = KnowledgeCallLog(
        user_id=user_id, index_id=index_id, index_name=index_name, source=source,
        query=query[:1000], status=status, result_count=len(nodes or []),
        query_tokens=query_tokens, result_tokens=result_tokens, rag_tokens=query_tokens + result_tokens,
        latency_ms=int(latency_ms), error_message=(error or None) and str(error)[:1000],
        session_id=(str(session_id or "")).strip()[:64] or None,
        external_id=(external_id or None) and str(external_id)[:100], created_at=created_at or utcnow(),
    )
    db.add(log)
    db.flush()
    for name in dict.fromkeys((node.get("doc_name") or node.get("title") or "").strip()[:255] for node in nodes or []):
        if name:
            db.add(KnowledgeCallHit(call_id=log.id, index_id=index_id, doc_name=name, created_at=log.created_at))
    if commit:
        db.commit()
    return log


# ---------------------------------------------------------------------------
# chats: the agent searches through its own knowledge base MCP server, which calls Bailian directly.
# Those searches are read back from the saved reply so the usage board counts them as channel 小趣.
# ---------------------------------------------------------------------------

CHAT_SOURCE = "xiaoqu"
CHAT_TOOL_SUFFIXES = ("__BailianKnowledgeBaseRetrieve", "__BailianKnowledgeSearch")


def _tool_text(content) -> str:
    if isinstance(content, list):  # MCP results may arrive as content blocks
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def parse_chat_retrieval(text: str) -> list[dict]:
    """Passages from a knowledge base MCP result; tolerant of results trimmed when stored."""
    try:
        data = json.loads(text)
        raw = data.get("nodes") or data.get("Nodes")
        for wrapper in ("data", "Data", "result"):  # Retrieve returns nodes at the top, Search under "data"
            if not raw and isinstance(data.get(wrapper), dict):
                raw = data[wrapper].get("nodes") or data[wrapper].get("Nodes")
        raw = raw or []
    except (ValueError, AttributeError):
        raw = None
    if isinstance(raw, list):
        nodes = []
        for node in raw:
            if not isinstance(node, dict):
                continue
            meta = node.get("metadata") or node.get("Metadata") or {}
            nodes.append({"text": meta.get("content") or node.get("text") or node.get("Text") or "",
                          "doc_name": meta.get("doc_name") or meta.get("file_name") or meta.get("title") or None,
                          "doc_id": meta.get("doc_id")})
        return nodes
    # Stored replies cut long results mid-JSON: count the passages that survived.
    return [{"text": json.loads(f'"{content}"') if content else "", "doc_name": None, "doc_id": doc_id}
            for doc_id, content in re.findall(
                r'"doc_id":\s*"([^"]+)".*?"content":\s*"((?:[^"\\]|\\.)*)"', text, flags=re.S)]


def chat_knowledge_calls(blocks: list[dict], default_index_id: str | None) -> list[dict]:
    """Knowledge base searches in one assistant reply, paired with their results."""
    results = {block.get("tool_use_id"): block for block in blocks or []
               if isinstance(block, dict) and block.get("type") == "tool_result"}
    calls = []
    for block in blocks or []:
        if not (isinstance(block, dict) and block.get("type") == "tool_use"
                and str(block.get("name") or "").endswith(CHAT_TOOL_SUFFIXES)):
            continue
        args = block.get("input") if isinstance(block.get("input"), dict) else {}
        query = str(args.get("Query") or args.get("query") or args.get("keyword") or "").strip()
        result = results.get(block.get("tool_use_id"))
        if not query or result is None:
            continue
        text = _tool_text(result.get("content"))
        failed = bool(result.get("is_error"))
        calls.append({
            "external_id": block.get("tool_use_id"), "query": query,
            "index_id": str(args.get("IndexId") or args.get("index_id") or default_index_id or "unknown"),
            "status": "error" if failed else "success", "nodes": [] if failed else parse_chat_retrieval(text),
            "error": text[:500] if failed else None, "latency_ms": block.get("duration_ms") or 0,
        })
    return calls


def _doc_names(db: Session, index_id: str) -> dict:
    try:
        return {doc.get("Id"): doc.get("Name") for doc in all_index_documents(db, index_id)}
    except Exception:  # names are a nicety; a passage without one is still counted
        return {}


def record_chat_knowledge_calls(db: Session, blocks: list[dict], *, user_id: int, session_id,
                                created_at=None) -> int:
    """Log the knowledge base searches of one saved reply; returns how many were new."""
    settings_row = _settings_row(db)
    calls = chat_knowledge_calls(blocks, settings_row.default_index_id if settings_row else None)
    if not calls:
        return 0
    known = {row[0] for row in db.query(KnowledgeCallLog.external_id).filter(
        KnowledgeCallLog.external_id.in_([call["external_id"] for call in calls if call["external_id"]])).all()}
    names_by_index, index_names, added = {}, {}, 0
    for call in calls:
        if call["external_id"] and call["external_id"] in known:
            continue
        index_id = call["index_id"]
        if any(not node["doc_name"] for node in call["nodes"]) and index_id not in names_by_index:
            names_by_index[index_id] = _doc_names(db, index_id)
        for node in call["nodes"]:
            node["doc_name"] = node["doc_name"] or names_by_index.get(index_id, {}).get(node.get("doc_id"))
        if index_id not in index_names:
            index_names[index_id] = db.query(func.max(KnowledgeCallLog.index_name)).filter(
                KnowledgeCallLog.index_id == index_id).scalar()
        record_call(db, user_id=user_id, index_id=index_id, index_name=index_names[index_id], source=CHAT_SOURCE,
                    query=call["query"], status=call["status"], nodes=call["nodes"], latency_ms=call["latency_ms"],
                    error=call["error"], session_id=session_id, external_id=call["external_id"],
                    created_at=created_at, commit=False)
        added += 1
    db.commit()
    return added


def record_chat_knowledge_safely(bind, blocks, *, user_id, session_id, background: bool = True) -> None:
    """Called after a chat reply is saved. The work runs on a daemon thread with its own session, so the
    chat (and the event loop serving everyone else) never waits on it, and no failure reaches the chat."""
    if not any(isinstance(b, dict) and b.get("type") == "tool_use"
               and str(b.get("name") or "").endswith(CHAT_TOOL_SUFFIXES) for b in blocks or []):
        return
    import copy
    snapshot = copy.deepcopy(blocks)  # the caller keeps using its list

    def run():
        from sqlalchemy.orm import Session as OrmSession
        db = OrmSession(bind=bind)
        try:
            record_chat_knowledge_calls(db, snapshot, user_id=user_id, session_id=session_id)
        except Exception:
            db.rollback()
            logger.warning("chat knowledge usage not recorded: session_id=%s", session_id, exc_info=True)
        finally:
            db.close()

    if background:
        threading.Thread(target=run, name="knowledge-chat-usage", daemon=True).start()
    else:
        run()


@router.post("/retrieve")
def retrieve(payload: RetrievePayload, db: Session = Depends(get_db),
             user: CurrentUser = Depends(get_current_active_user)):
    row = _settings_row(db)
    index_id = (payload.index_id or (row.default_index_id if row else "") or "").strip()
    if not index_id:
        raise HTTPException(status_code=400, detail="请指定知识库 ID")
    started = time.monotonic()
    try:
        data = bailian_client(db).retrieve(index_id, payload.query.strip(), rerank_top_n=payload.top_n)
    except KnowledgeServiceError as exc:
        record_call(db, user_id=user.user_id, index_id=index_id, index_name=payload.index_name,
                    source=payload.source, query=payload.query, status="error", session_id=payload.session_id,
                    latency_ms=(time.monotonic() - started) * 1000, error=str(exc))
        raise _service_error(exc)
    nodes = []
    for node in (data.get("Nodes") or [])[:payload.top_n]:
        meta = node.get("Metadata") or {}
        nodes.append({"score": node.get("Score"), "text": node.get("Text") or "",
                      "doc_name": meta.get("doc_name") or meta.get("file_name"), "title": meta.get("title")})
    log = record_call(db, user_id=user.user_id, index_id=index_id, index_name=payload.index_name,
                      source=payload.source, query=payload.query, status="success", nodes=nodes,
                      session_id=payload.session_id, latency_ms=(time.monotonic() - started) * 1000)
    return {"nodes": nodes, "usage": {"query_tokens": log.query_tokens, "result_tokens": log.result_tokens,
                                      "rag_tokens": log.rag_tokens, "latency_ms": log.latency_ms}}


# ---------------------------------------------------------------------------
# usage dashboard (superuser)
# ---------------------------------------------------------------------------

def _usage_range(period, start_date, end_date):
    try:
        start, end, _, _ = _resolve_period(period, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式无效") from exc
    if end - start > timedelta(days=366):
        raise HTTPException(status_code=400, detail="统计范围不能超过 366 天")
    return start.astimezone(timezone.utc).replace(tzinfo=None), end.astimezone(timezone.utc).replace(tzinfo=None)


def _bucket_start(value: datetime, granularity: str) -> datetime:
    local = value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    if granularity == "hour":
        return local.replace(minute=0, second=0, microsecond=0)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday()) if granularity == "week" else day


def _pct(part, whole):
    return round(part / whole * 100, 2) if whole else 0.0


def _scoped(query, user_id: Optional[int], include_tests: bool):
    if user_id is not None:
        query = query.filter(KnowledgeCallLog.user_id == user_id)
    if not include_tests:
        query = query.filter(KnowledgeCallLog.source != TEST_SOURCE)
    return query


def build_knowledge_usage(db: Session, start: datetime, end: datetime, granularity: str,
                          user_id: Optional[int] = None, include_tests: bool = False) -> dict:
    """Usage answering who uses the knowledge base, how far it has spread and how many questions it answered.

    A question counts as answered when the retrieval succeeded and recalled at least one passage: the
    knowledge base had something to say about it. Unanswered questions point at content gaps.
    Test calls from the console page are left out unless include_tests is set.
    """
    base = _scoped(db.query(KnowledgeCallLog).filter(
        KnowledgeCallLog.created_at >= start, KnowledgeCallLog.created_at < end), user_id, include_tests)
    ok = case((KnowledgeCallLog.status == "success", 1), else_=0)
    answered_case = case(((KnowledgeCallLog.status == "success") & (KnowledgeCallLog.result_count > 0), 1), else_=0)
    totals = base.with_entities(
        func.count(KnowledgeCallLog.id), func.coalesce(func.sum(ok), 0),
        func.coalesce(func.sum(KnowledgeCallLog.rag_tokens), 0),
        func.coalesce(func.sum(KnowledgeCallLog.query_tokens), 0),
        func.coalesce(func.sum(KnowledgeCallLog.result_tokens), 0),
        func.count(func.distinct(KnowledgeCallLog.user_id)),
        func.coalesce(func.avg(KnowledgeCallLog.latency_ms), 0),
        func.count(func.distinct(KnowledgeCallLog.session_id)),
        func.coalesce(func.sum(answered_case), 0),
    ).one()
    calls, success, rag, q_tokens, r_tokens, users, latency, sessions, answered = (int(totals[i] or 0) for i in range(9))

    # Adoption: a user is new in the period when their first ever call falls inside it.
    firsts = _scoped(db.query(KnowledgeCallLog.user_id, func.min(KnowledgeCallLog.created_at).label("first_at"))
                     .filter(KnowledgeCallLog.created_at < end), user_id, include_tests
                     ).group_by(KnowledgeCallLog.user_id).subquery()
    total_users, new_users = db.query(
        func.count(firsts.c.user_id),
        func.coalesce(func.sum(case((firsts.c.first_at >= start, 1), else_=0)), 0),
    ).one()
    first_seen = {uid: first for uid, first in db.query(firsts.c.user_id, firsts.c.first_at).filter(
        firsts.c.first_at >= start).all()}

    def grouped(column, limit=20):
        rows = base.with_entities(column, func.count(KnowledgeCallLog.id),
                                  func.coalesce(func.sum(KnowledgeCallLog.rag_tokens), 0),
                                  func.coalesce(func.sum(ok), 0), func.coalesce(func.sum(answered_case), 0),
                                  func.max(KnowledgeCallLog.created_at),
                                  ).group_by(column).order_by(func.count(KnowledgeCallLog.id).desc()).limit(limit).all()
        return [{"key": key, "calls": int(count), "rag_tokens": int(tokens), "success_calls": int(good),
                 "answered_calls": int(hit), "answer_rate": _pct(int(hit), int(count)),
                 "call_ratio": _pct(int(count), calls), "token_ratio": _pct(int(tokens), rag),
                 "last_used_at": _iso(last)}
                for key, count, tokens, good, hit, last in rows]

    names = dict(base.with_entities(KnowledgeCallLog.index_id, func.max(KnowledgeCallLog.index_name))
                 .group_by(KnowledgeCallLog.index_id).all())
    by_index = grouped(KnowledgeCallLog.index_id)
    for item in by_index:
        item["index_id"] = item.pop("key")
        item["index_name"] = names.get(item["index_id"]) or item["index_id"]
    # AI Hub's own agents are 小趣, so their calls land in the same channel as explicit xiaoqu ones.
    channel = case((KnowledgeCallLog.source == "agent", "xiaoqu"), else_=KnowledgeCallLog.source)
    by_source = grouped(channel)
    for item in by_source:
        item["source"] = item.pop("key")
    by_user = grouped(KnowledgeCallLog.user_id, limit=100)
    for item in by_user:
        item["user_id"] = item.pop("key")
        item["is_new"] = item["user_id"] in first_seen

    hits = db.query(KnowledgeCallHit.doc_name, func.count(KnowledgeCallHit.id)).join(
        KnowledgeCallLog, KnowledgeCallLog.id == KnowledgeCallHit.call_id,
    ).filter(KnowledgeCallLog.created_at >= start, KnowledgeCallLog.created_at < end)
    hits = _scoped(hits, user_id, include_tests)
    top_documents = [{"doc_name": name, "hits": int(count), "hit_rate": _pct(int(count), success)}
                     for name, count in hits.group_by(KnowledgeCallHit.doc_name)
                     .order_by(func.count(KnowledgeCallHit.id).desc(), KnowledgeCallHit.doc_name).limit(10).all()]

    buckets, days = {}, {}
    new_buckets = {}
    for first in first_seen.values():
        naive = first.replace(tzinfo=None) if first.tzinfo else first
        key = _bucket_start(naive, granularity)
        new_buckets[key] = new_buckets.get(key, 0) + 1
    for created_at, tokens, status, call_user, session, latency_ms, result_count in base.with_entities(
            KnowledgeCallLog.created_at, KnowledgeCallLog.rag_tokens, KnowledgeCallLog.status,
            KnowledgeCallLog.user_id, KnowledgeCallLog.session_id, KnowledgeCallLog.latency_ms,
            KnowledgeCallLog.result_count).all():
        naive = created_at.replace(tzinfo=None) if created_at.tzinfo else created_at
        key = _bucket_start(naive, granularity)
        entry = buckets.setdefault(key, {"calls": 0, "tokens": 0, "failed": 0, "answered": 0, "users": set()})
        entry["calls"] += 1
        entry["tokens"] += int(tokens or 0)
        entry["failed"] += 0 if status == "success" else 1
        entry["answered"] += 1 if status == "success" and (result_count or 0) > 0 else 0
        entry["users"].add(call_user)
        day = days.setdefault(_bucket_start(naive, "day"), {"calls": 0, "success": 0, "tokens": 0, "latency": 0,
                                                            "answered": 0, "users": set(), "sessions": set()})
        day["calls"] += 1
        day["answered"] += 1 if status == "success" and (result_count or 0) > 0 else 0
        day["success"] += 1 if status == "success" else 0
        day["tokens"] += int(tokens or 0)
        day["latency"] += int(latency_ms or 0)
        day["users"].add(call_user)
        if session:
            day["sessions"].add(session)
    daily = [{
        "date": day.date().isoformat(), "calls": item["calls"], "success_calls": item["success"],
        "failed_calls": item["calls"] - item["success"], "success_rate": _pct(item["success"], item["calls"]),
        "answered_calls": item["answered"], "unanswered_calls": item["success"] - item["answered"],
        "answer_rate": _pct(item["answered"], item["calls"]),
        "rag_tokens": item["tokens"], "users": len(item["users"]), "sessions": len(item["sessions"]),
        "avg_latency_ms": round(item["latency"] / item["calls"]) if item["calls"] else 0,
    } for day, item in sorted(days.items(), reverse=True)]
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=7 if granularity == "week" else 1)
    cursor, last, trend = _bucket_start(start, granularity), _bucket_start(end - timedelta(microseconds=1), granularity), []
    while cursor <= last and len(trend) < 2000:
        entry = buckets.get(cursor) or {"calls": 0, "tokens": 0, "failed": 0, "answered": 0, "users": ()}
        trend.append({"bucket": cursor.isoformat(), "calls": entry["calls"], "rag_tokens": entry["tokens"],
                      "failed_calls": entry["failed"], "answered_calls": entry["answered"],
                      "unanswered_calls": entry["calls"] - entry["answered"] - entry["failed"],
                      "users": len(entry["users"]), "new_users": new_buckets.get(cursor, 0)})
        cursor += step

    return {
        "period": {"start_at": _iso(start), "end_at": _iso(end), "granularity": granularity},
        "summary": {
            "total_calls": calls, "success_calls": success, "failed_calls": calls - success,
            "success_rate": _pct(success, calls), "rag_tokens": rag, "query_tokens": q_tokens,
            "result_tokens": r_tokens, "avg_rag_tokens": round(rag / calls, 1) if calls else 0,
            "active_users": users, "sessions": sessions, "avg_latency_ms": latency,
            "answered_calls": answered, "unanswered_calls": success - answered,
            "answer_rate": _pct(answered, calls), "new_users": int(new_users or 0),
            "total_users": int(total_users or 0), "include_tests": include_tests,
        },
        "trend": trend, "by_index": by_index, "by_source": by_source, "by_user": by_user,
        "top_documents": top_documents, "daily": daily,
    }


@usage_router.get("")
def knowledge_usage(period: str = Query("7d", pattern="^(today|7d|month|custom)$"),
                    start_date: Optional[str] = None, end_date: Optional[str] = None,
                    granularity: str = Query("day", pattern="^(hour|day|week)$"),
                    user_id: Optional[int] = Query(None, ge=1), include_tests: bool = False,
                    db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user),
                    authorization: Optional[str] = Header(None)):
    _require_access(db, user, authorization, "can_view_usage", USAGE_FORBIDDEN)
    start, end = _usage_range(period, start_date, end_date)
    result = build_knowledge_usage(db, start, end, granularity, user_id, include_tests)
    _attach_names(result["by_user"], authorization)
    return result


def _attach_names(items: list[dict], authorization: Optional[str]) -> None:
    """Attach local user display names for the knowledge usage board."""
    ids = sorted({item["user_id"] for item in items if item.get("user_id")})
    if not ids:
        return
    from models import User
    with SessionLocal() as db:
        rows = db.query(User).filter(User.id.in_(ids)).all()
        directory = {row.id: row for row in rows}
    for item in items:
        person = directory.get(item.get("user_id"))
        if person is not None:
            item["user_name"] = person.first_name or person.username or None


@usage_router.post("/backfill-chats")
def backfill_chat_usage(days: int = Query(7, ge=1, le=90), rebuild: bool = False, db: Session = Depends(get_db),
                        user: CurrentUser = Depends(get_current_active_user)):
    """Count knowledge base searches from chats of the last few days that happened before live recording.
    Safe to repeat: each tool call is recorded once. rebuild=true first drops the chat records of the
    window and reads them again (after a parsing fix)."""
    _require_superuser(user)
    from models import AgentMessage, AgentSession
    since = utcnow() - timedelta(days=days)
    rebuilt = 0
    if rebuild:
        stale = [row[0] for row in db.query(KnowledgeCallLog.id).filter(
            KnowledgeCallLog.source == CHAT_SOURCE, KnowledgeCallLog.external_id.isnot(None),
            KnowledgeCallLog.created_at >= since).all()]
        if stale:
            db.query(KnowledgeCallHit).filter(KnowledgeCallHit.call_id.in_(stale)).delete(synchronize_session=False)
            rebuilt = db.query(KnowledgeCallLog).filter(KnowledgeCallLog.id.in_(stale)).delete(synchronize_session=False)
            db.commit()
    rows = db.query(AgentMessage.id, AgentMessage.content, AgentMessage.created_at, AgentSession.user_id,
                    AgentMessage.session_id).join(AgentSession, AgentSession.id == AgentMessage.session_id).filter(
        AgentMessage.role == "assistant", AgentMessage.created_at >= since,
        AgentMessage.content.like("%BailianKnowledge%"),
    ).order_by(AgentMessage.id).all()
    scanned = added = 0
    for _id, content, created_at, owner_id, session_id in rows:
        try:
            blocks = (json.loads(content or "{}") or {}).get("blocks") or []
        except (ValueError, AttributeError):
            continue
        scanned += 1
        naive = created_at.astimezone(timezone.utc).replace(tzinfo=None) if created_at and created_at.tzinfo else created_at
        added += record_chat_knowledge_calls(db, blocks, user_id=owner_id, session_id=session_id, created_at=naive)
    return {"days": days, "messages": scanned, "recorded": added, "rebuilt": rebuilt}


@usage_router.get("/calls")
def knowledge_usage_calls(period: str = Query("7d", pattern="^(today|7d|month|custom)$"),
                          start_date: Optional[str] = None, end_date: Optional[str] = None,
                          user_id: Optional[int] = Query(None, ge=1),
                          status: str = Query("all", pattern="^(all|success|error|unanswered)$"),
                          include_tests: bool = False,
                          skip: int = Query(0, ge=0), limit: int = Query(16, ge=1, le=100),
                          db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_active_user),
                          authorization: Optional[str] = Header(None)):
    _require_access(db, user, authorization, "can_view_usage", USAGE_FORBIDDEN)
    start, end = _usage_range(period, start_date, end_date)
    query = _scoped(db.query(KnowledgeCallLog).filter(
        KnowledgeCallLog.created_at >= start, KnowledgeCallLog.created_at < end), user_id, include_tests)
    if status == "unanswered":
        query = query.filter(KnowledgeCallLog.status == "success", KnowledgeCallLog.result_count == 0)
    elif status != "all":
        query = query.filter(KnowledgeCallLog.status == status)
    total = query.count()
    rows = query.order_by(KnowledgeCallLog.id.desc()).offset(skip).limit(limit).all()
    items = [{
        "id": row.id, "user_id": row.user_id, "index_id": row.index_id,
        "index_name": row.index_name or row.index_id, "source": row.source, "query": row.query,
        "status": row.status, "result_count": row.result_count, "query_tokens": row.query_tokens,
        "result_tokens": row.result_tokens, "rag_tokens": row.rag_tokens, "latency_ms": row.latency_ms,
        "error_message": row.error_message, "session_id": row.session_id, "created_at": _iso(row.created_at),
    } for row in rows]
    _attach_names(items, authorization)
    return {"total": total, "items": items}
