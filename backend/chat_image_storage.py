"""OSS REST storage for public chat images; credentials never leave the backend."""

import base64
import hashlib
import hmac
import re
import uuid
from datetime import datetime, timezone
from email.utils import formatdate
from urllib.parse import urlsplit

import requests

from database import settings

MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


class ImageStorageError(RuntimeError):
    pass


def _origin(endpoint):
    host = endpoint.removeprefix("https://").rstrip("/")
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
        raise ImageStorageError("OSS endpoint 配置无效")
    return f"https://{settings.oss_bucket}.{host}"


def _prefix():
    prefix = settings.oss_chat_image_prefix.strip("/")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*", prefix):
        raise ImageStorageError("OSS 图片目录配置无效")
    return prefix


def image_object_key(url, workspace_id=None):
    """Accept only canonical URLs issued here, never arbitrary remote URLs."""
    origin = _origin(settings.oss_public_endpoint)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or f"https://{parsed.netloc}" != origin or parsed.query or parsed.fragment:
        raise ValueError("无效的 OSS 图片链接")
    owner = str(int(workspace_id)) if workspace_id is not None else r"[0-9]+"
    pattern = rf"/{re.escape(_prefix())}/{owner}/[0-9]{{8}}/[a-f0-9]{{32}}\.(png|jpg|gif|webp)"
    if not re.fullmatch(pattern, parsed.path):
        raise ValueError("无效的 OSS 图片链接或图片不属于当前工作区")
    return parsed.path[1:]


def _headers(method, key, content_type="", public=False):
    if not settings.oss_access_key_id or not settings.oss_access_key_secret:
        raise ImageStorageError("尚未配置 OSS 图片存储认证信息")
    date = formatdate(usegmt=True)
    oss_headers = "x-oss-object-acl:public-read\n" if public else ""
    canonical = f"{method}\n\n{content_type}\n{date}\n{oss_headers}/{settings.oss_bucket}/{key}"
    signature = base64.b64encode(hmac.new(
        settings.oss_access_key_secret.encode(), canonical.encode(), hashlib.sha1,
    ).digest()).decode()
    headers = {"Date": date, "Authorization": f"OSS {settings.oss_access_key_id}:{signature}"}
    if content_type:
        headers["Content-Type"] = content_type
    if public:
        headers["x-oss-object-acl"] = "public-read"
    return headers


def validate_image(content, media_type):
    if media_type not in IMAGE_TYPES:
        raise ValueError("图片仅支持 PNG、JPEG、GIF 和 WebP 格式")
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("单张图片必须大于 0 字节且不能超过 5 MB")
    matches = {
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/gif": content.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    if not matches[media_type]:
        raise ValueError("图片内容与格式不匹配")


def _upload_public_image(content, media_type, owner_id, prefix):
    """Upload a validated image under a server-selected owner directory."""
    validate_image(content, media_type)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*", prefix):
        raise ImageStorageError("OSS 图片目录配置无效")
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = f"{prefix}/{int(owner_id)}/{day}/{uuid.uuid4().hex}.{IMAGE_TYPES[media_type]}"
    try:
        with requests.put(
            f"{_origin(settings.oss_endpoint)}/{key}", data=content,
            headers=_headers("PUT", key, media_type, public=True),
            timeout=(5, 30), allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ImageStorageError(f"OSS 图片上传失败（HTTP {response.status_code}）")
    except requests.RequestException:
        raise ImageStorageError("OSS 图片上传失败，请稍后重试") from None
    return f"{_origin(settings.oss_public_endpoint)}/{key}"


def upload_chat_image(content, media_type, workspace_id):
    return _upload_public_image(content, media_type, workspace_id, _prefix())


def upload_feedback_image(content, media_type, user_id):
    """Feedback evidence uses a permanent prefix, separate from chat temp files."""
    if len(content) > 3 * 1024 * 1024:
        raise ValueError("反馈截图不能超过3MB")
    return _upload_public_image(content, media_type, user_id, settings.oss_feedback_image_prefix.strip("/"))


def read_chat_image(url, workspace_id):
    key = image_object_key(url, workspace_id)
    try:
        with requests.get(
            f"{_origin(settings.oss_endpoint)}/{key}", headers=_headers("GET", key),
            stream=True, timeout=(5, 30), allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ImageStorageError(f"OSS 图片读取失败（HTTP {response.status_code}）")
            content = bytearray()
            for chunk in response.iter_content(64 * 1024):
                content.extend(chunk)
                if len(content) > MAX_IMAGE_BYTES:
                    raise ValueError("单张图片不能超过 5 MB")
    except requests.RequestException:
        raise ImageStorageError("OSS 图片读取失败，请稍后重试") from None
    media_type = {ext: mime for mime, ext in IMAGE_TYPES.items()}[key.rsplit(".", 1)[1]]
    validate_image(content, media_type)
    return bytes(content), key.rsplit("/", 1)[1]
