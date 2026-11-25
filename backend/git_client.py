import httpx
import base64
import urllib.parse
import io

import zipfile
from abc import ABC, abstractmethod
from typing import Optional


class GitAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Git API error {status_code}: {message}")


# 保留旧名称兼容
GitLabAPIError = GitAPIError


class GitClient(ABC):
    """Git 仓库客户端抽象基类"""

    @abstractmethod
    async def get_project_info(self) -> dict:
        """获取仓库信息"""

    @abstractmethod
    async def get_tree_files(self, path: str = "", ref: str = None) -> dict[str, str]:
        """获取所有文件内容，返回 {path: content}"""

    @abstractmethod
    async def create_or_update_files(self, files: dict[str, str], commit_message: str,
                                      delete_paths: list[str] = None) -> dict:
        """创建/更新/删除文件"""

    @abstractmethod
    async def get_latest_commit(self, ref: str = None) -> Optional[dict]:
        """获取最新 commit"""

    @abstractmethod
    async def test_connection(self) -> dict:
        """测试连接，返回 {success, project_name, default_branch}"""


class GitLabClient(GitClient):
    """GitLab REST API v4 客户端"""

    def __init__(self, base_url: str, project_id: str, access_token: str = None, branch: str = "main"):
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.access_token = access_token
        self.branch = branch
        self._encoded_project_id = urllib.parse.quote(str(project_id), safe="")

    @property
    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["PRIVATE-TOKEN"] = self.access_token
        return headers

    @property
    def _base_api(self) -> str:
        return f"{self.base_url}/api/v4/projects/{self._encoded_project_id}"

    @staticmethod
    def parse_project_id(repo_url: str) -> str:
        url = repo_url.rstrip("/")
        if "://" in url:
            url = url.split("://", 1)[1]
        parts = url.split("/", 1)
        if len(parts) < 2:
            raise ValueError(f"无法从 URL 解析项目 ID: {repo_url}")
        project_path = parts[1]
        if project_path.endswith(".git"):
            project_path = project_path[:-4]
        return project_path

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self._base_api}{path}"
        print(f"[Git:GitLab] _request: {method} {url}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.request(method, url, headers=self._headers, **kwargs)
        print(f"[Git:GitLab] _request response: status={resp.status_code}")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                detail = resp.text[:200]
            print(f"[Git:GitLab] _request ERROR: status={resp.status_code}, detail={detail}, body={resp.text[:300]}")
            raise GitAPIError(resp.status_code, detail)
        return resp

    async def get_project_info(self) -> dict:
        resp = await self._request("GET", "")
        return resp.json()

    async def test_connection(self) -> dict:
        info = await self.get_project_info()
        # 验证分支是否存在
        encoded_branch = urllib.parse.quote(self.branch, safe="")
        await self._request("GET", f"/repository/branches/{encoded_branch}")
        return {
            "success": True,
            "project_name": info.get("name", ""),
            "default_branch": info.get("default_branch", "main"),
        }

    async def get_tree(self, path: str = "", ref: str = None, recursive: bool = True) -> list[dict]:
        params = {"ref": ref or self.branch, "recursive": str(recursive).lower(), "per_page": "100"}
        if path:
            params["path"] = path
        all_items = []
        page = 1
        while True:
            params["page"] = str(page)
            resp = await self._request("GET", "/repository/tree", params=params)
            items = resp.json()
            if not items:
                break
            all_items.extend(items)
            page += 1
        return all_items

    async def get_file(self, file_path: str, ref: str = None) -> Optional[dict]:
        encoded_path = urllib.parse.quote(file_path, safe="")
        params = {"ref": ref or self.branch}
        try:
            resp = await self._request("GET", f"/repository/files/{encoded_path}", params=params)
            data = resp.json()
            if data.get("encoding") == "base64":
                raw = base64.b64decode(data["content"])
                try:
                    data["content"] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    print(f"[Git:GitLab] skipping binary file: {file_path}")
                    return None
            return data
        except GitAPIError as e:
            if e.status_code == 404:
                return None
            raise

    async def get_tree_files(self, path: str = "", ref: str = None) -> dict[str, str]:
        ref_name = ref or self.branch
        return await self._download_archive(ref_name, path)

    async def _download_archive(self, ref: str, filter_path: str = "") -> dict[str, str]:
        """通过 Web archive URL 下载整个仓库 zip，解析返回 {path: content}"""
        from database import settings
        print(f"[Git:GitLab] _download_archive: ref={ref}, filter={filter_path or '(root)'}")

        project_name = self.project_id.split("/")[-1]
        download_url = f"{self.base_url}/{self.project_id}/-/archive/{ref}/{project_name}-{ref}.zip"
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["PRIVATE-TOKEN"] = self.access_token

        print(f"[Git:GitLab] _download_archive: fetching {download_url}")
        async with httpx.AsyncClient(timeout=settings.git_download_timeout) as client:
            dl_resp = await client.get(download_url, headers=headers, follow_redirects=True)
        print(f"[Git:GitLab] _download_archive: status={dl_resp.status_code}")
        if dl_resp.status_code >= 400:
            raise GitAPIError(dl_resp.status_code, "仓库下载失败")
        raw = dl_resp.content
        print(f"[Git:GitLab] _download_archive: downloaded {len(raw)} bytes")

        files = {}
        max_size = 10 * 1024 * 1024  # 10MB per file
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # zip 中路径格式: {project_name}-{ref}/file/path，去掉第一级目录前缀
                parts = info.filename.split("/", 1)
                if len(parts) < 2:
                    continue
                file_path = parts[1]
                if filter_path and not (file_path == filter_path or file_path.startswith(filter_path.rstrip("/") + "/")):
                    continue
                if info.file_size > max_size:
                    print(f"[Git:GitLab] _download_archive: skipping large file {file_path} ({info.file_size} bytes)")
                    continue
                raw_data = zf.read(info.filename)
                try:
                    files[file_path] = raw_data.decode("utf-8")
                except UnicodeDecodeError:
                    print(f"[Git:GitLab] _download_archive: skipping binary file {file_path}")
        print(f"[Git:GitLab] _download_archive: parsed {len(files)} text files")
        return files

    async def create_commit(self, actions: list[dict], commit_message: str, branch: str = None) -> dict:
        payload = {
            "branch": branch or self.branch,
            "commit_message": commit_message,
            "actions": actions,
        }
        resp = await self._request("POST", "/repository/commits", json=payload)
        return resp.json()

    async def create_or_update_files(self, files: dict[str, str], commit_message: str,
                                      delete_paths: list[str] = None) -> dict:
        actions = []
        for path, content in files.items():
            encoded_path = urllib.parse.quote(path, safe="")
            try:
                await self._request("GET", f"/repository/files/{encoded_path}", params={"ref": self.branch})
                action = "update"
            except GitAPIError:
                action = "create"
            actions.append({"action": action, "file_path": path, "content": content, "encoding": "text"})

        for path in (delete_paths or []):
            actions.append({"action": "delete", "file_path": path})

        if not actions:
            return {"id": "", "message": "no changes"}
        return await self.create_commit(actions, commit_message)

    async def get_latest_commit(self, ref: str = None) -> Optional[dict]:
        params = {"ref_name": ref or self.branch, "per_page": "1"}
        resp = await self._request("GET", "/repository/commits", params=params)
        commits = resp.json()
        return commits[0] if commits else None


class GitHubClient(GitClient):
    """GitHub REST API 客户端"""

    def __init__(self, owner: str, repo: str, access_token: str = None, branch: str = "main"):
        self.owner = owner
        self.repo = repo
        self.access_token = access_token
        self.branch = branch

    @property
    def _headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    @property
    def _base_api(self) -> str:
        return f"https://api.github.com/repos/{self.owner}/{self.repo}"

    @staticmethod
    def parse_owner_repo(repo_url: str) -> tuple[str, str]:
        url = repo_url.rstrip("/")
        if "://" in url:
            url = url.split("://", 1)[1]
        parts = url.split("/", 1)
        if len(parts) < 2:
            raise ValueError(f"无法从 URL 解析 owner/repo: {repo_url}")
        path = parts[1]
        if path.endswith(".git"):
            path = path[:-4]
        segments = path.split("/")
        if len(segments) < 2:
            raise ValueError(f"URL 格式不正确: {repo_url}")
        return segments[0], segments[1]

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self._base_api}{path}"
        print(f"[Git:GitHub] _request: {method} {url} params={kwargs.get('params')} has_json={kwargs.get('json') is not None}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.request(method, url, headers=self._headers, **kwargs)
        print(f"[Git:GitHub] _request response: status={resp.status_code}")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                detail = resp.text[:200]
            print(f"[Git:GitHub] _request ERROR: status={resp.status_code}, detail={detail}, body={resp.text[:300]}")
            raise GitAPIError(resp.status_code, detail)
        return resp

    async def get_project_info(self) -> dict:
        print(f"[Git:GitHub] get_project_info")
        resp = await self._request("GET", "")
        result = resp.json()
        print(f"[Git:GitHub] get_project_info: name={result.get('name')}, default_branch={result.get('default_branch')}")
        return result

    async def test_connection(self) -> dict:
        print(f"[Git:GitHub] test_connection")
        info = await self.get_project_info()
        # 验证分支是否存在
        encoded_branch = urllib.parse.quote(self.branch, safe="")
        await self._request("GET", f"/branches/{encoded_branch}")
        print(f"[Git:GitHub] test_connection: success, name={info.get('name')}")
        return {
            "success": True,
            "project_name": info.get("name", ""),
            "default_branch": info.get("default_branch", "main"),
        }

    async def get_tree_files(self, path: str = "", ref: str = None) -> dict[str, str]:
        branch = ref or self.branch
        print(f"[Git:GitHub] get_tree_files: branch={branch}, path={path or '(root)'}")
        # 检查是否有提交
        commit = await self.get_latest_commit(branch)
        if not commit:
            print(f"[Git:GitHub] get_tree_files: no commits found for branch={branch}")
            return {}
        return await self._download_archive(branch, path)

    async def _download_archive(self, ref: str, filter_path: str = "") -> dict[str, str]:
        """通过 GitHub archive URL 下载整个仓库 zip，解析返回 {path: content}"""
        from database import settings
        print(f"[Git:GitHub] _download_archive: ref={ref}, filter={filter_path or '(root)'}")
        # 使用 Web UI 的 archive URL，不依赖 API，公开仓库无需认证
        download_url = f"https://github.com/{self.owner}/{self.repo}/archive/refs/heads/{ref}.zip"
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        print(f"[Git:GitHub] _download_archive: fetching {download_url}")
        async with httpx.AsyncClient(timeout=settings.git_download_timeout) as client:
            dl_resp = await client.get(download_url, headers=headers, follow_redirects=True)
            dl_resp.raise_for_status()
            raw = dl_resp.content
        print(f"[Git:GitHub] _download_archive: downloaded {len(raw)} bytes")

        files = {}
        max_size = 10 * 1024 * 1024  # 10MB per file
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # zip 中路径格式: {owner}-{repo}-{sha}/file/path，去掉第一级前缀
                parts = info.filename.split("/", 1)
                if len(parts) < 2:
                    continue
                file_path = parts[1]
                if filter_path and not (file_path == filter_path or file_path.startswith(filter_path.rstrip("/") + "/")):
                    continue
                if info.file_size > max_size:
                    print(f"[Git:GitHub] _download_archive: skipping large file {file_path} ({info.file_size} bytes)")
                    continue
                raw_data = zf.read(info.filename)
                try:
                    files[file_path] = raw_data.decode("utf-8")
                except UnicodeDecodeError:
                    print(f"[Git:GitHub] _download_archive: skipping binary file {file_path}")
        print(f"[Git:GitHub] _download_archive: parsed {len(files)} text files")
        return files

    async def create_or_update_files(self, files: dict[str, str], commit_message: str,
                                      delete_paths: list[str] = None) -> dict:
        print(f"[Git:GitHub] create_or_update_files: {len(files)} files, delete={len(delete_paths or [])}")
        if not files and not delete_paths:
            return {"id": "", "message": "no changes"}

        # 1. 获取当前 HEAD commit 的 sha 和 tree sha
        parent_commit = await self.get_latest_commit(self.branch)
        if not parent_commit:
            raise GitAPIError(404, f"分支 {self.branch} 没有提交")
        parent_sha = parent_commit["sha"]
        base_tree_sha = parent_commit["commit"]["tree"]["sha"]
        print(f"[Git:GitHub] batch_commit: parent={parent_sha}, base_tree={base_tree_sha}")

        # 2. 构建 tree items（只需要列出变更的文件）
        tree_items = []
        for file_path, content in files.items():
            tree_items.append({
                "path": file_path,
                "mode": "100644",
                "type": "blob",
                "content": content,
            })
        for file_path in (delete_paths or []):
            tree_items.append({
                "path": file_path,
                "mode": "100644",
                "type": "blob",
                "sha": None,
            })

        # 3. 基于 base_tree 创建新 tree（未列出的文件继承自 base_tree）
        resp = await self._request("POST", "/git/trees", json={
            "base_tree": base_tree_sha,
            "tree": tree_items,
        })
        new_tree_sha = resp.json()["sha"]
        print(f"[Git:GitHub] batch_commit: new_tree={new_tree_sha}")

        # 4. 创建 commit
        resp = await self._request("POST", "/git/commits", json={
            "message": commit_message,
            "tree": new_tree_sha,
            "parents": [parent_sha],
        })
        new_commit = resp.json()
        new_commit_sha = new_commit["sha"]
        print(f"[Git:GitHub] batch_commit: new_commit={new_commit_sha}")

        # 5. 移动分支引用
        encoded_branch = urllib.parse.quote(self.branch, safe="")
        await self._request("PATCH", f"/git/refs/heads/{encoded_branch}", json={
            "sha": new_commit_sha,
        })

        print(f"[Git:GitHub] batch_commit: done")
        return new_commit

    async def get_latest_commit(self, ref: str = None) -> Optional[dict]:
        branch = ref or self.branch
        params = {"sha": branch, "per_page": "1"}
        print(f"[Git:GitHub] get_latest_commit: branch={branch}")
        resp = await self._request("GET", "/commits", params=params)
        commits = resp.json()
        print(f"[Git:GitHub] get_latest_commit: got {len(commits) if isinstance(commits, list) else 'N/A'} commits")
        if commits and isinstance(commits, list) and len(commits) > 0:
            c = commits[0]
            print(f"[Git:GitHub] get_latest_commit: sha={c.get('sha')}, has_commit_key={'commit' in c}")
            return c
        return None


def create_git_client(provider: str, repo_url: str, access_token: str, branch: str = "main") -> GitClient:
    """工厂函数：根据 provider 创建对应的 Git 客户端"""
    print(f"[Git] create_git_client: provider={provider}, repo_url={repo_url}, branch={branch}, has_token={bool(access_token)}")
    if provider == "github":
        owner, repo = GitHubClient.parse_owner_repo(repo_url)
        print(f"[Git] GitHubClient: owner={owner}, repo={repo}, branch={branch}")
        return GitHubClient(owner, repo, access_token, branch)
    else:
        # 默认 GitLab
        if not repo_url:
            raise ValueError("GitLab 需要提供仓库地址")
        project_id = GitLabClient.parse_project_id(repo_url)
        # 从 URL 推断 base_url
        protocol = repo_url.split("://")[0] if "://" in repo_url else "https"
        host = repo_url.split("://")[1].split("/")[0] if "://" in repo_url else repo_url.split("/")[0]
        base_url = f"{protocol}://{host}"
        print(f"[Git] GitLabClient: base_url={base_url}, project_id={project_id}, branch={branch}")
        return GitLabClient(base_url, project_id, access_token, branch)
