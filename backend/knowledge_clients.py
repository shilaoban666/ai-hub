"""Minimal HTTP clients for Alibaba Cloud Bailian (2023-12-29 ROA APIs) and DingTalk drive.

No vendor SDK is required: Bailian requests are signed with ACS3-HMAC-SHA256 here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

BAILIAN_API_VERSION = "2023-12-29"
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
UPLOAD_TIMEOUT = httpx.Timeout(300.0, connect=15.0)


THROTTLE_RETRIES = 3
THROTTLE_BACKOFF_SECONDS = 0.5


class KnowledgeServiceError(RuntimeError):
    """A readable error from Bailian or DingTalk, safe to show to the user."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Token estimate
# ---------------------------------------------------------------------------

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿　-〿＀-￯]")


def estimate_tokens(text: str | None) -> int:
    """Rough tokenizer-free estimate: one token per CJK char, ~4 chars per token otherwise."""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    rest = len(_CJK.sub("", text).strip())
    return cjk + math.ceil(rest / 4)


# ---------------------------------------------------------------------------
# Bailian
# ---------------------------------------------------------------------------

def _percent(value: str) -> str:
    return quote(str(value), safe="-_.~")


def canonical_query(params: dict | None) -> str:
    if not params:
        return ""
    items = sorted((str(k), "" if v is None else str(v)) for k, v in params.items())
    return "&".join(f"{_percent(k)}={_percent(v)}" for k, v in items)


def _stringify(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _clean(params: dict | None) -> dict:
    return {k: _stringify(v) for k, v in (params or {}).items() if v is not None and v != ""}


def sign_acs3(*, method: str, host: str, path: str, query: dict, headers: dict,
              body: bytes, access_key_id: str, access_key_secret: str) -> dict:
    """Return headers including Authorization for an ACS3-HMAC-SHA256 request."""
    signed = {k.lower(): str(v).strip() for k, v in headers.items()}
    signed["host"] = host
    signed["x-acs-content-sha256"] = hashlib.sha256(body).hexdigest()
    names = sorted(k for k in signed if k == "host" or k == "content-type" or k.startswith("x-acs-"))
    canonical_headers = "".join(f"{name}:{signed[name]}\n" for name in names)
    signed_headers = ";".join(names)
    canonical_request = "\n".join((
        method.upper(),
        quote(path or "/", safe="/-_.~"),
        canonical_query(query),
        canonical_headers,
        signed_headers,
        signed["x-acs-content-sha256"],
    ))
    string_to_sign = "ACS3-HMAC-SHA256\n" + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    signature = hmac.new(access_key_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    signed["authorization"] = (
        f"ACS3-HMAC-SHA256 Credential={access_key_id},SignedHeaders={signed_headers},Signature={signature}"
    )
    return signed


def _bailian_message(payload, status_code: int) -> str:
    if isinstance(payload, dict):
        code = payload.get("Code") or payload.get("code") or ""
        message = payload.get("Message") or payload.get("message") or ""
        text = f"{code}: {message}".strip(": ") if code or message else ""
        if text:
            return f"百炼接口错误（{text}）"
    return f"百炼接口错误（HTTP {status_code}）"


class BailianClient:
    def __init__(self, *, endpoint: str, access_key_id: str, access_key_secret: str,
                 workspace_id: str, transport: httpx.BaseTransport | None = None):
        if not (access_key_id and access_key_secret and workspace_id):
            raise KnowledgeServiceError("百炼尚未配置 AccessKey 或业务空间 ID", status_code=400)
        self.host = (endpoint or "bailian.cn-beijing.aliyuncs.com").replace("https://", "").strip("/")
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.workspace_id = workspace_id
        self._transport = transport

    def _client(self, timeout=HTTP_TIMEOUT):
        return httpx.Client(timeout=timeout, transport=self._transport)

    def call(self, action: str, method: str, path: str, *, query: dict | None = None,
             form: dict | None = None) -> dict:
        query = _clean(query)
        form = _clean(form)
        body = canonical_query(form).encode("utf-8") if form else b""
        headers = {
            "x-acs-action": action,
            "x-acs-version": BAILIAN_API_VERSION,
            "x-acs-date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "x-acs-signature-nonce": uuid.uuid4().hex,
            "accept": "application/json",
        }
        if form:
            headers["content-type"] = "application/x-www-form-urlencoded"
        signed = sign_acs3(
            method=method, host=self.host, path=path, query=query, headers=headers, body=body,
            access_key_id=self.access_key_id, access_key_secret=self.access_key_secret,
        )
        qs = canonical_query(query)
        url = f"https://{self.host}{quote(path, safe='/-_.~')}" + (f"?{qs}" if qs else "")
        for attempt in range(THROTTLE_RETRIES + 1):
            if attempt:  # signatures carry a timestamp and nonce, so each retry is signed afresh
                headers["x-acs-date"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                headers["x-acs-signature-nonce"] = uuid.uuid4().hex
                signed = sign_acs3(
                    method=method, host=self.host, path=path, query=query, headers=headers, body=body,
                    access_key_id=self.access_key_id, access_key_secret=self.access_key_secret,
                )
            try:
                with self._client() as client:
                    response = client.request(method, url, headers=signed, content=body or None)
            except httpx.HTTPError as exc:
                raise KnowledgeServiceError(f"无法连接百炼服务：{exc.__class__.__name__}") from exc
            try:
                payload = response.json()
            except ValueError:
                payload = None
            code = str((payload or {}).get("Code") or "") if isinstance(payload, dict) else ""
            # Bailian rate-limits per account (Throttling.*); back off briefly instead of failing the page.
            if not code.startswith("Throttling") or attempt == THROTTLE_RETRIES:
                break
            time.sleep(THROTTLE_BACKOFF_SECONDS * (2 ** attempt))
        success = isinstance(payload, dict) and str(payload.get("Success", "true")).lower() != "false"
        if response.status_code >= 400 or not success:
            raise KnowledgeServiceError(_bailian_message(payload, response.status_code),
                                        status_code=400 if response.status_code in (400, 403, 404) else 502)
        return payload.get("Data") or {}

    # -- read ------------------------------------------------------------
    def list_indices(self, page_number=1, page_size=50) -> dict:
        return self.call("ListIndices", "GET", f"/{self.workspace_id}/index/list_indices",
                         query={"PageNumber": page_number, "PageSize": page_size})

    def list_categories(self, parent_id=None, next_token=None, max_results=200) -> dict:
        return self.call("ListCategory", "POST", f"/{self.workspace_id}/datacenter/categories",
                         form={"CategoryType": "UNSTRUCTURED", "ParentCategoryId": parent_id,
                               "NextToken": next_token, "MaxResults": max_results})

    def list_index_documents(self, index_id, page_number=1, page_size=20, name=None) -> dict:
        return self.call("ListIndexDocuments", "GET", f"/{self.workspace_id}/index/list_index_documents",
                         query={"IndexId": index_id, "PageNumber": page_number, "PageSize": page_size,
                                "DocumentName": name})

    def retrieve(self, index_id, query_text, *, rerank_top_n=5, enable_rerank=True) -> dict:
        return self.call("Retrieve", "POST", f"/{self.workspace_id}/index/retrieve",
                         query={"IndexId": index_id, "Query": query_text, "EnableReranking": enable_rerank,
                                "RerankTopN": rerank_top_n})

    # -- upload ----------------------------------------------------------
    def apply_upload_lease(self, category_id, file_name, md5, size) -> dict:
        return self.call("ApplyFileUploadLease", "POST",
                         f"/{self.workspace_id}/datacenter/category/{category_id}",
                         form={"FileName": file_name, "Md5": md5, "SizeInBytes": size,
                               "CategoryType": "UNSTRUCTURED"})

    def put_to_lease(self, lease: dict, path: str) -> None:
        param = lease.get("Param") or {}
        url = param.get("Url")
        if not url:
            raise KnowledgeServiceError("百炼上传租约缺少上传地址")
        headers = {str(k): str(v) for k, v in (param.get("Headers") or {}).items()}
        with open(path, "rb") as handle, self._client(UPLOAD_TIMEOUT) as client:
            response = client.request(param.get("Method") or "PUT", url, headers=headers, content=handle.read())
        if response.status_code >= 300:
            raise KnowledgeServiceError(f"文件上传到百炼存储失败（HTTP {response.status_code}）")

    def add_file(self, lease_id, category_id, parser="DASHSCOPE_DOCMIND") -> dict:
        return self.call("AddFile", "PUT", f"/{self.workspace_id}/datacenter/file",
                         form={"LeaseId": lease_id, "Parser": parser, "CategoryId": category_id,
                               "CategoryType": "UNSTRUCTURED"})

    def describe_file(self, file_id) -> dict:
        return self.call("DescribeFile", "GET", f"/{self.workspace_id}/datacenter/file/{file_id}/")

    def add_documents_to_index(self, index_id, file_ids) -> dict:
        return self.call("SubmitIndexAddDocumentsJob", "POST", f"/{self.workspace_id}/index/add_documents_to_index",
                         query={"IndexId": index_id, "SourceType": "DATA_CENTER_FILE", "DocumentIds": list(file_ids)})

    # -- delete (both idempotent) -----------------------------------------
    def delete_index_document(self, index_id, file_ids) -> dict:
        return self.call("DeleteIndexDocument", "POST", f"/{self.workspace_id}/index/delete_index_document",
                         query={"IndexId": index_id, "DocumentIds": list(file_ids)})

    def delete_file(self, file_id) -> dict:
        return self.call("DeleteFile", "DELETE", f"/{self.workspace_id}/datacenter/file/{file_id}/")

    def index_job_status(self, index_id, job_id) -> dict:
        return self.call("GetIndexJobStatus", "GET", f"/{self.workspace_id}/index/job/status",
                         query={"IndexId": index_id, "JobId": job_id})


def file_md5(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# DingTalk
# ---------------------------------------------------------------------------

DINGTALK_API = "https://api.dingtalk.com"
DINGTALK_LOGIN = "https://login.dingtalk.com/oauth2/auth"
_app_tokens: dict[str, tuple[str, float]] = {}
_app_token_lock = threading.Lock()


def _dingtalk_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    code = payload.get("code") or payload.get("errcode") or response.status_code
    message = payload.get("message") or payload.get("errmsg") or ""
    return f"钉钉接口错误（{code}{'：' + message if message else ''}）"


class DingtalkClient:
    def __init__(self, *, client_id: str, client_secret: str, transport: httpx.BaseTransport | None = None):
        if not (client_id and client_secret):
            raise KnowledgeServiceError("钉钉应用尚未配置 Client ID / Client Secret", status_code=400)
        self.client_id = client_id
        self.client_secret = client_secret
        self._transport = transport

    def _client(self, timeout=HTTP_TIMEOUT):
        return httpx.Client(timeout=timeout, transport=self._transport)

    def _request(self, method, path, *, token=None, params=None, json_body=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["x-acs-dingtalk-access-token"] = token
        try:
            with self._client() as client:
                response = client.request(method, f"{DINGTALK_API}{path}", headers=headers,
                                          params={k: v for k, v in (params or {}).items() if v not in (None, "")},
                                          json=json_body)
        except httpx.HTTPError as exc:
            raise KnowledgeServiceError(f"无法连接钉钉服务：{exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise KnowledgeServiceError(_dingtalk_message(response),
                                        status_code=400 if response.status_code in (400, 403) else 502)
        return response.json() if response.content else {}

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        query = canonical_query({
            "redirect_uri": redirect_uri, "response_type": "code", "client_id": self.client_id,
            "scope": "openid", "state": state, "prompt": "consent",
        })
        return f"{DINGTALK_LOGIN}?{query}"

    def app_token(self) -> str:
        with _app_token_lock:
            cached = _app_tokens.get(self.client_id)
            if cached and cached[1] > time.time() + 60:
                return cached[0]
        data = self._request("POST", "/v1.0/oauth2/accessToken",
                             json_body={"appKey": self.client_id, "appSecret": self.client_secret})
        token = data.get("accessToken")
        if not token:
            raise KnowledgeServiceError("钉钉未返回应用访问凭证")
        with _app_token_lock:
            _app_tokens[self.client_id] = (token, time.time() + int(data.get("expireIn") or 7200))
        return token

    def user_by_code(self, code: str) -> dict:
        data = self._request("POST", "/v1.0/oauth2/userAccessToken", json_body={
            "clientId": self.client_id, "clientSecret": self.client_secret,
            "code": code, "grantType": "authorization_code",
        })
        user_token = data.get("accessToken")
        if not user_token:
            raise KnowledgeServiceError("钉钉授权码无效或已过期，请重新扫码", status_code=400)
        me = self._request("GET", "/v1.0/contact/users/me", token=user_token)
        if not me.get("unionId"):
            raise KnowledgeServiceError("钉钉未返回用户 unionId")
        return {"union_id": me["unionId"], "nick": me.get("nick") or ""}

    # -- 团队文件 (drive spaces) ---------------------------------------------
    # 钉盘「团队文件」lists the org spaces (全员文件夹 and shared team folders) the user can see; the wiki
    # workspace API below is a different list (钉钉知识库). Calls carry the bound user's unionId, so
    # DingTalk returns only what that person is allowed to see.
    def list_team_spaces(self, union_id: str) -> list[dict]:
        token = self.app_token()
        items, next_token = [], None
        for _ in range(20):
            data = self._request("GET", "/v1.0/drive/spaces", token=token, params={
                "unionId": union_id, "spaceType": "org", "maxResults": 50, "nextToken": next_token,
            })
            items.extend(data.get("spaces") or [])
            next_token = data.get("nextToken")
            if not next_token:
                break
        return items

    def list_space_folders(self, union_id: str, space_id: str, parent_id: str = "0") -> list[dict]:
        token = self.app_token()
        items, next_token = [], None
        for _ in range(20):
            data = self._request("GET", f"/v1.0/storage/spaces/{quote(space_id, safe='')}/dentries", token=token,
                                 params={"parentId": parent_id or "0", "unionId": union_id, "maxResults": 50,
                                         "nextToken": next_token, "orderBy": "NAME", "order": "ASC"})
            items.extend(d for d in data.get("dentries") or [] if d.get("type") == "FOLDER")
            next_token = data.get("nextToken")
            if not next_token:
                break
        return items

    def upload_to_space(self, union_id: str, space_id: str, parent_id: str, path: str, name: str, size: int,
                        parent_uuid: str | None = None) -> dict:
        """Upload into a 团队文件 folder. Folders are addressed by their dentry uuid (the API DingTalk
        recommends, and the one that may write into shared team folders); only when no uuid can be found
        does it fall back to the older spaceId + parentId upload."""
        uuid = parent_uuid or self.dentry_uuid(union_id, space_id, parent_id or "0")
        if uuid:
            return self.upload_file(union_id, uuid, path, name, size)
        token = self.app_token()
        space = quote(space_id, safe="")
        info = self._request(
            "POST", f"/v1.0/storage/spaces/{space}/files/uploadInfos/query", token=token,
            params={"unionId": union_id},
            json_body={"protocol": "HEADER_SIGNATURE", "multipart": False,
                       "option": {"storageDriver": "DINGTALK", "preferIntranet": False,
                                  "preCheckParam": {"size": size, "parentId": parent_id or "0", "name": name}}},
        )
        self._put_signed(info, path)
        data = self._request(
            "POST", f"/v1.0/storage/spaces/{space}/files/commit", token=token, params={"unionId": union_id},
            json_body={"uploadKey": info["uploadKey"], "name": name, "parentId": parent_id or "0",
                       "option": {"size": size, "conflictStrategy": "AUTO_RENAME"}},
        )
        return data.get("dentry") or {}

    def dentry_uuid(self, union_id: str, space_id: str, dentry_id: str) -> str | None:
        try:
            data = self._request(
                "POST", f"/v1.0/storage/spaces/{quote(space_id, safe='')}/dentries/{quote(dentry_id, safe='')}/query",
                token=self.app_token(), params={"unionId": union_id}, json_body={})
        except KnowledgeServiceError:
            return None
        uuid = (data.get("dentry") or {}).get("uuid")
        return str(uuid) if uuid else None

    def resolve_dentry(self, union_id: str, dentry_uuid: str) -> dict:
        """A 钉盘 file or folder from its uuid (the id in its link): space, id, name, path and type."""
        token = self.app_token()
        ids = self._request("GET", f"/v2.0/doc/dentries/{quote(dentry_uuid, safe='')}/queryDentryId", token=token,
                            params={"operatorId": union_id})
        space_id, dentry_id = ids.get("spaceId"), ids.get("dentryId")
        if not space_id or not dentry_id:
            raise KnowledgeServiceError("钉盘没有找到这个链接对应的文件夹", status_code=400)
        data = self._request(
            "POST", f"/v1.0/storage/spaces/{quote(str(space_id), safe='')}/dentries/{quote(str(dentry_id), safe='')}/query",
            token=token, params={"unionId": union_id}, json_body={})
        dentry = data.get("dentry") or data
        return {"space_id": str(space_id), "dentry_id": str(dentry_id), "uuid": dentry_uuid,
                "name": dentry.get("name") or "", "path": dentry.get("path") or "", "type": dentry.get("type"),
                "status": dentry.get("status") or "NORMAL"}

    def delete_dentry(self, union_id: str, space_id: str, dentry_id: str) -> None:
        self._request("DELETE", f"/v1.0/storage/spaces/{quote(space_id, safe='')}/dentries/{quote(dentry_id, safe='')}",
                      token=self.app_token(), params={"unionId": union_id})

    def _put_signed(self, info: dict, path: str) -> None:
        signature = info.get("headerSignatureInfo") or {}
        urls = signature.get("resourceUrls") or []
        if not info.get("uploadKey") or not urls:
            raise KnowledgeServiceError("钉钉未返回上传地址")
        headers = {str(k): str(v) for k, v in (signature.get("headers") or {}).items()}
        try:
            with open(path, "rb") as handle, self._client(UPLOAD_TIMEOUT) as client:
                response = client.put(urls[0], headers=headers, content=handle.read())
        except httpx.HTTPError as exc:
            raise KnowledgeServiceError(f"文件上传到钉盘失败：{exc.__class__.__name__}") from exc
        if response.status_code >= 300:
            raise KnowledgeServiceError(f"文件上传到钉盘失败（HTTP {response.status_code}）")

    # -- upload by folder uuid (also used for rows recorded with the old 知识库 picker) -------------
    def upload_file(self, union_id: str, parent_node_id: str, path: str, name: str, size: int) -> dict:
        token = self.app_token()
        info = self._request(
            "POST", f"/v2.0/storage/spaces/files/{quote(parent_node_id, safe='')}/uploadInfos/query",
            token=token, params={"unionId": union_id},
            json_body={"protocol": "HEADER_SIGNATURE",
                       "option": {"storageDriver": "DINGTALK", "preCheckParam": {"size": size, "name": name},
                                  "preferIntranet": False}},
        )
        self._put_signed(info, path)
        data = self._request(
            "POST", f"/v2.0/storage/spaces/files/{quote(parent_node_id, safe='')}/commit",
            token=token, params={"unionId": union_id},
            json_body={"uploadKey": info["uploadKey"], "name": name,
                       "option": {"size": size, "conflictStrategy": "AUTO_RENAME"}},
        )
        return data.get("dentry") or {}

    def node_url(self, union_id: str, node_uuid: str) -> str:
        """Browser link of a drive node; falls back to the standard alidocs node URL."""
        fallback = f"https://alidocs.dingtalk.com/i/nodes/{quote(node_uuid, safe='')}"
        try:
            data = self._request("GET", f"/v2.0/wiki/nodes/{quote(node_uuid, safe='')}",
                                 token=self.app_token(), params={"operatorId": union_id})
        except KnowledgeServiceError:
            return fallback
        url = (data.get("node") or data).get("url")
        return url if isinstance(url, str) and url.startswith("https://") else fallback
