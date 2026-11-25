"""Native Linux system-user sandbox for agents.

Each agent gets an isolated Linux user and a private workspace. The backend
must run as root, or as a service account with passwordless sudo for user and
filesystem management commands.
"""
from __future__ import annotations

import json
import logging
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile
import uuid

from agent_workspace import (
    build_claude_md,
    build_claude_state_json,
    build_mcp_json,
    build_settings_json,
    install_hooks,
    install_skills,
    _claude_skill_name,
    staged_skill_sources,
    legacy_workspace_roots,
)
from database import settings
from sandbox.base import Sandbox, WorkspaceContext, WorkspacePreparationError, WorkspaceDownloadTooLarge


logger = logging.getLogger(__name__)


def resolve_native_claude_bin(configured_path: str = "") -> str:
    """Resolve the shared CLI path used by isolated Linux users."""
    return configured_path.strip() or shutil.which("claude") or "/usr/local/bin/claude"


NATIVE_CLAUDE_BIN = resolve_native_claude_bin(
    settings.claude_code_native_claude_bin
)
# Some sudo implementations ignore -E. Read exactly one environment header
# without buffering bytes that belong to Claude's prompt, then exec the CLI.
RUNNER_SCRIPT = (
    "import base64,json,os,subprocess,sys\n"
    "header=bytearray()\n"
    "while len(header)<=1048576:\n"
    "    char=os.read(0,1)\n"
    "    if not char: raise SystemExit('missing AI Hub runtime environment')\n"
    "    if char==b'\\n': break\n"
    "    header.extend(char)\n"
    "else: raise SystemExit('AI Hub runtime environment is too large')\n"
    "try:\n"
    "    runtime_env=json.loads(base64.b64decode(header,validate=True).decode('utf-8'))\n"
    "except Exception as exc:\n"
    "    raise SystemExit(f'invalid AI Hub runtime environment: {exc}')\n"
    "if not isinstance(runtime_env,dict): raise SystemExit('invalid AI Hub runtime environment')\n"
    "os.environ.update({str(key):str(value) for key,value in runtime_env.items()})\n"
    "workspace=os.environ.get('AIHUB_AGENT_WORKSPACE')\n"
    "if not workspace: raise SystemExit('missing AIHUB_AGENT_WORKSPACE')\n"
    "try:\n"
    "    os.chdir(workspace)\n"
    "except PermissionError:\n"
    "    raise SystemExit(f'Runtime user cannot access workspace: {workspace}; check directory ownership and execute permissions on every parent directory')\n"
    "if os.environ.get('AIHUB_BOOTSTRAP_VENV')=='1':\n"
    "    venv=os.path.join(workspace,'.venv')\n"
    "    python=os.path.join(venv,'bin','python')\n"
    "    def venv_ready():\n"
    "        if not os.path.isfile(python): return False\n"
    "        try:\n"
    "            probe=subprocess.run([python,'-I','-c','import os,pip,sys; sys.exit(sys.prefix == sys.base_prefix or os.path.realpath(sys.prefix) != os.path.realpath(sys.argv[1]))',venv],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)\n"
    "            return probe.returncode==0\n"
    "        except (OSError,subprocess.SubprocessError): return False\n"
    "    if not venv_ready():\n"
    "        try:\n"
    "            created=subprocess.run([sys.executable,'-I','-m','venv',venv],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)\n"
    "        except (OSError,subprocess.SubprocessError) as exc:\n"
    "            raise SystemExit(f'工作区 .venv 初始化失败：{exc}')\n"
    "        if created.returncode or not venv_ready():\n"
    "            detail=created.stdout.strip()[-3000:]\n"
    "            raise SystemExit('工作区 .venv 初始化失败。请检查目录权限，并重建包含 python3-venv 的 Claude Runtime 镜像。\\n'+detail)\n"
    "os.execvpe(sys.argv[2],sys.argv[2:],os.environ)\n"
)
WORKSPACE_ACCESS_SCRIPT = """
import os, stat, sys
for target in sys.argv[1:]:
    path = os.path.abspath(target)
    parents = []
    while True:
        parents.append(path)
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    for path in reversed(parents):
        try:
            info = os.stat(path)
            if not os.access(path, os.X_OK):
                raise SystemExit(
                    f'uid={os.getuid()} gid={os.getgid()}: cannot traverse {path}; '
                    f'owner={info.st_uid}:{info.st_gid} mode={stat.filemode(info.st_mode)}'
                )
        except OSError as exc:
            raise SystemExit(f'uid={os.getuid()} gid={os.getgid()}: {path}: {exc}')
try:
    os.chdir(sys.argv[-1])
except OSError as exc:
    raise SystemExit(f'cannot enter workspace {sys.argv[-1]}: {exc}')
"""
LIST_DIR_SCRIPT = (
    "import os,sys,json\n"
    "target=os.path.realpath(sys.argv[1]); root=os.path.realpath(sys.argv[2])\n"
    "if target!=root and not target.startswith(root+os.sep):\n"
    "    print(json.dumps({'error':'invalid path'})); sys.exit(0)\n"
    "if not os.path.exists(target):\n"
    "    print(json.dumps({'error':'path not found'})); sys.exit(0)\n"
    "if os.path.isfile(target):\n"
    "    print(json.dumps({'type':'file','path':os.path.relpath(target,root).replace(os.sep,'/')})); sys.exit(0)\n"
    "items=[]\n"
    "for name in sorted(os.listdir(target)):\n"
    "    if name.startswith('.'): continue\n"
    "    full=os.path.join(target,name); rel=os.path.relpath(full,root).replace(os.sep,'/')\n"
    "    if os.path.islink(full): continue\n"
    "    item={'name':name,'path':rel,'type':'dir' if os.path.isdir(full) else 'file'}\n"
    "    if os.path.isfile(full): item['size']=os.path.getsize(full)\n"
    "    items.append(item)\n"
    "rel=os.path.relpath(target,root).replace(os.sep,'/') if target!=root else ''\n"
    "print(json.dumps({'type':'dir','path':rel,'items':items},ensure_ascii=False))\n"
)
READ_FILE_SCRIPT = (
    "import os,sys\n"
    "path=sys.argv[1]; root=os.path.realpath(sys.argv[2])\n"
    "parent=os.path.realpath(os.path.dirname(path))\n"
    "if parent!=root and not parent.startswith(root+os.sep): sys.exit(41)\n"
    "if os.path.islink(path): sys.exit(42)\n"
    "fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))\n"
    "with os.fdopen(fd,'rb') as f: sys.stdout.buffer.write(f.read())\n"
)
WRITE_FILE_SCRIPT = (
    "import os,sys,shutil,pwd\n"
    "src,path,root,user=sys.argv[1:5]; root=os.path.realpath(root)\n"
    "parent=os.path.realpath(os.path.dirname(path))\n"
    "if parent!=root and not parent.startswith(root+os.sep): sys.exit(41)\n"
    "if os.path.lexists(path) and os.path.islink(path): sys.exit(42)\n"
    "fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o644)\n"
    "with open(src,'rb') as s, os.fdopen(fd,'wb') as d: shutil.copyfileobj(s,d)\n"
    "pw=pwd.getpwnam(user); os.chown(path,pw.pw_uid,pw.pw_gid); os.chmod(path,0o644)\n"
)
READ_FILE_LIMITED_SCRIPT = (
    "import os,sys,stat\n"
    "path=sys.argv[1]; root=os.path.realpath(sys.argv[2]); limit=int(sys.argv[3])\n"
    "reject=len(sys.argv)>4 and sys.argv[4]=='1'\n"
    "parent=os.path.realpath(os.path.dirname(path))\n"
    "if parent!=root and not parent.startswith(root+os.sep): sys.exit(41)\n"
    "if os.path.islink(path): sys.exit(42)\n"
    "fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))\n"
    "with os.fdopen(fd,'rb') as f:\n"
    "    metadata=os.fstat(f.fileno())\n"
    "    if not stat.S_ISREG(metadata.st_mode): sys.exit(42)\n"
    "    if reject and metadata.st_size>limit: sys.exit(43)\n"
    "    content=f.read(limit+1)\n"
    "    if reject and len(content)>limit: sys.exit(43)\n"
    "    sys.stdout.buffer.write(content)\n"
)
DELETE_FILE_SCRIPT = (
    "import os,sys\n"
    "path=sys.argv[1]; root=os.path.realpath(sys.argv[2])\n"
    "parent=os.path.realpath(os.path.dirname(path))\n"
    "if parent!=root and not parent.startswith(root+os.sep): sys.exit(41)\n"
    "if os.path.islink(path): sys.exit(42)\n"
    "if not os.path.isfile(path): sys.exit(44)\n"
    "os.unlink(path)\n"
)
DELETE_PATH_SCRIPT = (
    "import os,sys,shutil\n"
    "path=sys.argv[1]; root=os.path.realpath(sys.argv[2])\n"
    "parent=os.path.realpath(os.path.dirname(path))\n"
    "if path==root or (parent!=root and not parent.startswith(root+os.sep)): sys.exit(41)\n"
    "if os.path.islink(path): sys.exit(42)\n"
    "if os.path.isfile(path): os.unlink(path)\n"
    "elif os.path.isdir(path): shutil.rmtree(path)\n"
    "else: sys.exit(44)\n"
)
SYNC_VIEW_SCRIPT = (
    "import os,sys,shutil\n"
    "src,dst,root,quota_arg=sys.argv[1:5]\n"
    "src=os.path.realpath(src); dst=os.path.realpath(dst); root=os.path.realpath(root)\n"
    "if not src.startswith(root+os.sep) or not dst.startswith(root+os.sep): sys.exit(41)\n"
    "total=0\n"
    "for base,dirs,files in os.walk(src,followlinks=False):\n"
    "    for name in dirs+files:\n"
    "        path=os.path.join(base,name)\n"
    "        if os.path.islink(path): sys.exit(42)\n"
    "    for name in files: total+=os.path.getsize(os.path.join(base,name))\n"
    "quota=int(quota_arg)\n"
    "if quota>0 and total>quota: sys.exit(43)\n"
    "stage=dst+'.sync-'+os.urandom(6).hex(); backup=dst+'.old-'+os.urandom(6).hex()\n"
    "shutil.rmtree(stage,ignore_errors=True); shutil.copytree(src,stage)\n"
    "os.rename(dst,backup); os.rename(stage,dst); shutil.rmtree(backup,ignore_errors=True)\n"
    "print(total)\n"
)


class NativeSandbox(Sandbox):
    """Run each agent as a dedicated Linux user on the host."""

    type_name = "native"
    is_isolated = True

    def __init__(self):
        if not sys.platform.startswith("linux"):
            raise RuntimeError(
                "native sandbox requires Linux; use directory for Windows or macOS development"
            )
        workspace_root = (
            settings.claude_code_native_workspace_root
            or settings.agent_native_workspace_root
            or settings.agent_linux_workspace_root
        )
        user_prefix = (
            settings.claude_code_native_user_prefix
            or settings.agent_native_user_prefix
            or settings.agent_linux_user_prefix
            or "aihub_agent_"
        )
        self._workspace_root = os.path.normpath(workspace_root)
        self._user_prefix = user_prefix

    def prepare(self, agent, model, filter_skills=None) -> WorkspaceContext:
        """Create/sync the Linux workspace and return runtime context."""
        username = self._username(agent.id)
        workspace = self._workspace(agent.id)
        skills = filter_skills if filter_skills is not None else getattr(agent, "skills", [])
        mcps = getattr(agent, "mcps", []) or []

        self._assert_workspace_path(workspace)
        self._ensure_user(username, workspace)

        temp_dir = tempfile.mkdtemp(prefix="aihub_linux_agent_")
        try:
            os.makedirs(os.path.join(temp_dir, ".claude", "skills"), exist_ok=True)
            os.makedirs(os.path.join(temp_dir, ".claude", "hooks"), exist_ok=True)

            cached_copies = []
            installed_skills = install_skills(temp_dir, skills, cached_copies=cached_copies)
            install_hooks(temp_dir)
            claude_md = build_claude_md(agent, installed_skills, runtime_workspace_root=workspace)
            claude_settings = build_settings_json(
                agent,
                model,
                mcps=mcps,
                include_secrets=False,
                sandbox_type=self.type_name,
            )
            mcp_config, _ = build_mcp_json(
                mcps,
                check_connectivity=False,
                overrides=getattr(agent, "mcp_overrides", []),
            )

            self._write_text(os.path.join(temp_dir, "CLAUDE.md"), claude_md)
            self._write_json(
                os.path.join(temp_dir, ".claude", ".claude.json"),
                build_claude_state_json([workspace]),
            )
            self._write_json(os.path.join(temp_dir, ".claude", "settings.json"), claude_settings)
            self._write_json(os.path.join(temp_dir, ".mcp.json"), mcp_config)

            self._sync_managed_files(
                temp_dir, workspace, cached_copies,
                skill_root=os.path.join(self._workspace_root, ".skill-installations", str(agent.id)),
                skill_owner=username, selected_names=installed_skills,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self._ensure_venv(workspace)
        self._apply_permissions(username, workspace)

        return WorkspaceContext(
            sandbox_type=self.type_name,
            workspace_root=workspace,
            host_workspace_path=workspace,
            argv_prefix=self._run_as_user_prefix(username),
            claude_bin=NATIVE_CLAUDE_BIN,
            run_cwd="",
            env={
                "AIHUB_AGENT_WORKSPACE": workspace,
                "HOME": workspace,
                "USER": username,
                "LOGNAME": username,
                "SHELL": "/bin/bash",
            },
            tunnel_env_via_stdin=True,
            is_isolated=True,
            handle={"username": username, "workspace": workspace},
        )

    def prepare_execution(
        self,
        agent,
        model,
        *,
        run_id: str,
        workspace,
        filter_skills=None,
    ) -> WorkspaceContext:
        """Create a unique physical Run view backed by the user's persistent files."""
        username = self._username(workspace)
        user_root = self._user_workspace_root(workspace)
        files_root = os.path.join(user_root, "files")
        sessions_root = os.path.join(user_root, "sessions")
        run_root = os.path.join(user_root, "managed", "runs", run_id)
        view_root = os.path.join(run_root, "view")
        stable_root = os.path.join(user_root, "current")
        self._assert_user_workspace_path(user_root)

        # Isolated users must traverse the shared root to reach their private view.
        self._run_root("mkdir", "-p", settings.user_workspace_root)
        self._run_root("chmod", "o+x", settings.user_workspace_root)
        self._ensure_user(username, user_root)
        self._run_root("rm", "-rf", run_root, check=False)
        self._run_root("mkdir", "-p", files_root, os.path.join(sessions_root, "projects"), view_root)
        if getattr(workspace, "migration_status", "not_required") == "pending":
            for legacy_agent_id in getattr(workspace, "legacy_agent_ids", [agent.id]):
                for legacy_root in legacy_workspace_roots(legacy_agent_id):
                    if os.path.isdir(legacy_root):
                        self._run_root("python3", os.path.join(os.path.dirname(__file__), "legacy_workspace.py"),
                                       legacy_root, files_root)
            workspace.migration_status = "completed"
        self._run_root("chown", "-R", f"{username}:{username}", files_root, sessions_root, view_root)
        self._run_root("chmod", "700", files_root, sessions_root, view_root)
        self._run_root("cp", "-a", os.path.join(files_root, "."), view_root)

        skills = (
            agent.runtime_skills if hasattr(agent, "runtime_skills") else getattr(agent, "skills", [])
        )
        mcps = (
            agent.runtime_mcps if hasattr(agent, "runtime_mcps") else getattr(agent, "mcps", [])
        ) or []
        temp_dir = tempfile.mkdtemp(prefix="aihub_run_config_")
        try:
            os.makedirs(os.path.join(temp_dir, ".claude", "skills"), exist_ok=True)
            os.makedirs(os.path.join(temp_dir, ".claude", "hooks"), exist_ok=True)
            cached_copies = []
            installed_skills = install_skills(temp_dir, skills, cached_copies=cached_copies)
            if filter_skills is not None:
                selected_names = {_claude_skill_name(skill) for skill in filter_skills}
                installed_skills = [name for name in installed_skills if name in selected_names]
            install_hooks(temp_dir)
            self._write_text(
                os.path.join(temp_dir, "CLAUDE.md"),
                build_claude_md(agent, installed_skills, runtime_workspace_root=stable_root),
            )
            self._write_json(
                os.path.join(temp_dir, ".claude", ".claude.json"),
                build_claude_state_json([view_root, stable_root]),
            )
            self._write_json(
                os.path.join(temp_dir, ".claude", "settings.json"),
                build_settings_json(
                    agent,
                    model,
                    mcps=mcps,
                    include_secrets=False,
                    sandbox_type=self.type_name,
                    runtime_workspace_root=stable_root,
                ),
            )
            mcp_config, _ = build_mcp_json(
                mcps,
                check_connectivity=False,
                overrides=getattr(agent, "mcp_overrides", []),
            )
            self._write_json(os.path.join(temp_dir, ".mcp.json"), mcp_config)
            self._sync_managed_files(
                temp_dir, view_root, cached_copies,
                skill_root=os.path.join(user_root, "managed", "skill-installations", str(agent.id)),
                skill_owner=username, selected_names=installed_skills,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self._run_root("rm", "-rf", os.path.join(view_root, ".claude", "projects"))
        self._run_root(
            "ln", "-s", os.path.join(sessions_root, "projects"),
            os.path.join(view_root, ".claude", "projects"),
        )
        self._ensure_venv(user_root, username=username)
        self._run_root("ln", "-sfn", os.path.join(user_root, ".venv"), os.path.join(view_root, ".venv"))
        self._apply_permissions(username, view_root)

        self._run_root("rm", "-f", stable_root, check=False)
        self._run_root("ln", "-s", view_root, stable_root)
        self._run_root("chown", "-h", "root:root", stable_root, check=False)
        for protected in (user_root, os.path.join(user_root, "managed"), os.path.join(user_root, "managed", "runs"), run_root):
            self._run_root("chown", "root:root", protected)
            self._run_root("chmod", "711", protected)

        # The protected parent chain is root-owned, while the execution view
        # itself must remain private and accessible to the isolated user.
        self._run_root("chown", f"{username}:{username}", view_root)
        self._run_root("chmod", "700", view_root)

        # Check the physical path first so a denied symlink target names its parent.
        access = self._run_root(
            "runuser", "-u", username, "--", "python3", "-c",
            WORKSPACE_ACCESS_SCRIPT, view_root, stable_root, check=False,
        )
        if access.returncode != 0:
            detail = (access.stderr or access.stdout or "directory access denied").strip()
            raise WorkspacePreparationError(
                f"工作区目录权限异常（{username}）：{detail}"
            )

        return WorkspaceContext(
            sandbox_type=self.type_name,
            workspace_root=stable_root,
            host_workspace_path=view_root,
            argv_prefix=self._run_as_user_prefix(username),
            claude_bin=NATIVE_CLAUDE_BIN,
            env={
                "AIHUB_AGENT_WORKSPACE": stable_root,
                "HOME": stable_root,
                "USER": username,
                "LOGNAME": username,
                "SHELL": "/bin/bash",
                **(getattr(agent, "runtime_secret_env", None) or {}),
            },
            tunnel_env_via_stdin=True,
            is_isolated=True,
            workspace_id=workspace.id,
            run_id=run_id,
            persistent_files_path=files_root,
            execution_view_path=view_root,
            handle={
                "username": username,
                "workspace": stable_root,
                "user_root": user_root,
                "run_root": run_root,
                "view_root": view_root,
                "files_root": files_root,
                "quota_bytes": int(getattr(workspace, "quota_bytes", 0) or 0),
            },
        )

    def snapshot_execution_files(self, ctx: WorkspaceContext, runtime_type: str) -> dict:
        from sandbox import artifact_scan
        from workspace_artifacts import managed_artifact_paths
        self._assert_user_workspace_path(ctx.handle["user_root"])
        result = self._run_root(
            "python3", os.path.abspath(artifact_scan.__file__),
            ctx.execution_view_path or ctx.host_workspace_path,
            json.dumps(managed_artifact_paths(runtime_type)),
        )
        return json.loads(result.stdout)

    def cleanup(self, ctx: WorkspaceContext) -> None:
        if not ctx.run_id or not ctx.handle.get("view_root"):
            return
        view_root = ctx.handle["view_root"]
        files_root = ctx.handle["files_root"]
        user_root = ctx.handle["user_root"]
        run_root = ctx.handle["run_root"]
        self._assert_user_workspace_path(user_root)
        self._unlock_managed(view_root)
        for rel_path in ("CLAUDE.md", ".mcp.json", ".claude", ".venv"):
            self._run_root("rm", "-rf", os.path.join(view_root, rel_path), check=False)
        result = self._run_root(
            "python3", "-c", SYNC_VIEW_SCRIPT,
            view_root, files_root, user_root,
            str(ctx.handle.get("quota_bytes", 0)),
            check=False,
        )
        if result.returncode != 0:
            codes = {41: "invalid workspace sync path", 42: "symbolic links are not allowed", 43: "workspace quota exceeded"}
            raise RuntimeError(codes.get(result.returncode, result.stderr.strip() or "workspace sync failed"))
        self._run_root("rm", "-f", os.path.join(user_root, "current"), check=False)
        self.discard_execution(ctx)

    def discard_execution(self, ctx: WorkspaceContext) -> None:
        if not ctx.run_id or not ctx.handle.get("run_root"):
            return
        user_root = ctx.handle["user_root"]
        self._assert_user_workspace_path(user_root)
        self._unlock_managed(ctx.handle["view_root"])
        # The stale owner cannot safely change the shared current link.
        self._run_root("rm", "-rf", ctx.handle["run_root"], check=False)

    def delete(self, agent_id: int) -> None:
        """Delete the Linux user and workspace for an agent."""
        username = self._username(agent_id)
        workspace = self._workspace(agent_id)
        self._assert_workspace_path(workspace)
        self._run_root("pkill", "-KILL", "-u", username, check=False)
        self._unlock_managed(workspace)
        self._run_root("userdel", username, check=False)
        self._run_root("rm", "-rf", workspace, check=False)

    def host_workspace_path(self, agent_id: int) -> str:
        """Return the Linux workspace path."""
        return self._workspace(agent_id)

    def list_dir(self, agent_id: int, rel_path: str = "") -> dict:
        """List non-hidden files in the agent workspace."""
        workspace = self._workspace(agent_id)
        target = self._resolve_workspace_path(agent_id, rel_path)
        result = self._run_root(
            "python3",
            "-c",
            LIST_DIR_SCRIPT,
            target,
            workspace,
            check=True,
        )
        stdout = (result.stdout or "").strip()
        if not stdout:
            raise RuntimeError("linux sandbox returned empty file listing")
        data = json.loads(stdout)
        if "error" in data:
            raise FileNotFoundError(data["error"])
        return data

    def read_file(self, agent_id: int, rel_path: str) -> tuple[bytes, str]:
        """Read a workspace file using privileged access."""
        target = self._resolve_workspace_path(agent_id, rel_path)
        workspace = self._workspace(agent_id)
        result = self._run_root_bytes(
            "python3", "-c", READ_FILE_SCRIPT, target, workspace, check=False
        )
        if result.returncode != 0:
            if result.returncode in {41, 42}:
                raise ValueError("invalid path or symbolic link")
            raise FileNotFoundError("file not found")
        return result.stdout, posixpath.basename(target)

    def read_file_limited(
        self, agent_id: int, rel_path: str, max_bytes: int, *, reject_oversized: bool = False
    ) -> tuple[bytes, str]:
        """Read a bounded file prefix using privileged workspace access."""
        if max_bytes < 1:
            raise ValueError("invalid read limit")
        target = self._resolve_workspace_path(agent_id, rel_path)
        workspace = self._workspace(agent_id)
        result = self._run_root_bytes(
            "python3", "-c", READ_FILE_LIMITED_SCRIPT,
            target, workspace, str(max_bytes), '1' if reject_oversized else '0', check=False,
        )
        if result.returncode != 0:
            if result.returncode == 43:
                raise WorkspaceDownloadTooLarge("工作区文件下载最大支持 20 MiB")
            if result.returncode in {41, 42}:
                raise ValueError("invalid path or symbolic link")
            raise FileNotFoundError("file not found")
        return result.stdout, posixpath.basename(target)

    def write_file(self, agent_id: int, rel_path: str, content: bytes) -> str:
        """Upload a file into the agent workspace."""
        safe_name = posixpath.basename(rel_path.replace("\\", "/"))
        if not safe_name:
            raise ValueError("invalid filename")
        username = self._username(agent_id)
        workspace = self._workspace(agent_id)
        target = self._resolve_workspace_path(agent_id, safe_name)

        fd, temp_path = tempfile.mkstemp(prefix="aihub_upload_")
        try:
            with os.fdopen(fd, "wb") as temp_file:
                temp_file.write(content)
            self._run_root("mkdir", "-p", workspace)
            result = self._run_root(
                "python3", "-c", WRITE_FILE_SCRIPT,
                temp_path, target, workspace, username,
                check=False,
            )
            if result.returncode in {41, 42}:
                raise ValueError("invalid path or symbolic link")
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "linux sandbox upload failed")
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                logger.debug("temporary upload file already removed: %s", temp_path)
        return safe_name

    def delete_file(self, agent_id: int, rel_path: str) -> None:
        """Delete one regular file using privileged workspace access."""
        target = self._resolve_workspace_path(agent_id, rel_path)
        workspace = self._workspace(agent_id)
        result = self._run_root(
            "python3", "-c", DELETE_FILE_SCRIPT, target, workspace, check=False
        )
        if result.returncode in {41, 42}:
            raise ValueError("invalid path or symbolic link")
        if result.returncode == 44:
            raise FileNotFoundError("file not found")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "linux sandbox file deletion failed")

    def delete_path(self, agent_id: int, rel_path: str) -> None:
        """Delete one regular file or directory using privileged workspace access."""
        workspace = self._workspace(agent_id)
        rel = str(rel_path or "").replace("\\", "/")
        normalized = posixpath.normpath(rel)
        if not rel or posixpath.isabs(rel) or normalized in {".", ".."} or normalized.startswith("../"):
            raise ValueError("invalid path")
        target = os.path.join(workspace, *normalized.split("/"))
        result = self._run_root(
            "python3", "-c", DELETE_PATH_SCRIPT, target, workspace, check=False
        )
        if result.returncode in {41, 42}:
            raise ValueError("invalid path or symbolic link")
        if result.returncode == 44:
            raise FileNotFoundError("file or directory not found")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "linux sandbox path deletion failed")

    def _sync_managed_files(self, temp_dir: str, workspace: str, cached_copies=(), *,
                            skill_root: str, skill_owner: str, selected_names) -> None:
        """Copy generated platform-managed files into the workspace."""
        self._unlock_managed(workspace)
        self._run_root("mkdir", "-p", workspace, os.path.join(workspace, ".claude"))
        self._run_root("mkdir", "-p", os.path.join(workspace, ".claude", "projects"))
        self._run_root("rm", "-rf", os.path.join(workspace, ".claude", "skills"), check=False)
        self._run_root("rm", "-rf", os.path.join(workspace, ".claude", "hooks"), check=False)
        self._run_root("cp", os.path.join(temp_dir, "CLAUDE.md"), os.path.join(workspace, "CLAUDE.md"))
        self._run_root("cp", os.path.join(temp_dir, ".mcp.json"), os.path.join(workspace, ".mcp.json"))
        self._run_root(
            "cp",
            os.path.join(temp_dir, ".claude", ".claude.json"),
            os.path.join(workspace, ".claude", ".claude.json"),
        )
        self._run_root(
            "cp",
            os.path.join(temp_dir, ".claude", "settings.json"),
            os.path.join(workspace, ".claude", "settings.json"),
        )
        self._sync_skill_installations(temp_dir, cached_copies, skill_root, skill_owner)
        self._run_root("mkdir", "-p", os.path.join(workspace, ".claude", "skills"))
        for name in selected_names:
            self._run_root("ln", "-s", os.path.join(skill_root, name),
                           os.path.join(workspace, ".claude", "skills", name))
        self._run_root("cp", "-a", os.path.join(temp_dir, ".claude", "hooks"), os.path.join(workspace, ".claude"))

    def sync_skill_installations(self, agent, workspace):
        user_root = self._user_workspace_root(workspace)
        self._assert_user_workspace_path(user_root)
        username = self._username(workspace)
        self._run_root("mkdir", "-p", settings.user_workspace_root)
        self._run_root("chmod", "o+x", settings.user_workspace_root)
        self._ensure_user(username, user_root)
        self._run_root("mkdir", "-p", os.path.join(user_root, "managed"))
        for parent in (user_root, os.path.join(user_root, "managed")):
            self._run_root("chown", "root:root", parent)
            self._run_root("chmod", "711", parent)
        root = os.path.join(user_root, "managed", "skill-installations", str(agent.id))
        with tempfile.TemporaryDirectory(prefix="aihub_skill_sync_") as stage:
            os.makedirs(os.path.join(stage, ".claude", "skills"))
            pending = []
            names = install_skills(stage, agent.runtime_skills, cached_copies=pending)
            self._sync_skill_installations(stage, pending, root, username)
        return names

    def _sync_skill_installations(self, temp_dir, cached_copies, skill_root, skill_owner):
        plan_path = os.path.join(temp_dir, "skill-installation-plan.json")
        self._write_json(plan_path, {
            "root": skill_root, "owner": skill_owner,
            "sources": staged_skill_sources(temp_dir, cached_copies),
        })
        self._run_root("mkdir", "-p", os.path.dirname(skill_root))
        self._run_root("chown", "root:root", os.path.dirname(skill_root))
        self._run_root("chmod", "711", os.path.dirname(skill_root))
        self._run_root(
            "python3", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "skill_installation.py")),
            plan_path,
        )

    def _ensure_user(self, username: str, workspace: str) -> None:
        """Ensure the Linux user and home directory exist."""
        self._run_root("mkdir", "-p", self._workspace_root)
        existing = self._run_root("id", "-u", username, check=False)
        if existing.returncode != 0:
            home_exists = self._run_root("test", "-d", workspace, check=False).returncode == 0
            create_home_flag = "--no-create-home" if home_exists else "--create-home"
            self._run_root(
                "useradd",
                create_home_flag,
                "--home-dir",
                workspace,
                "--shell",
                "/bin/bash",
                "--comment",
                f"AIHub Agent {username}",
                username,
            )
            self._run_root("passwd", "-l", username, check=False)
        self._run_root("mkdir", "-p", workspace)
        self._run_root("chown", f"{username}:{username}", workspace)
        self._run_root("chmod", "700", workspace)

    def _ensure_venv(self, workspace: str, username: str = "") -> None:
        """Create the workspace virtualenv if it does not exist."""
        python_path = os.path.join(workspace, ".venv", "bin", "python")
        if self._run_root("test", "-x", python_path, check=False).returncode != 0:
            created = self._run_root("python3", "-m", "venv", os.path.join(workspace, ".venv"), check=False)
            if created.returncode != 0:
                raise WorkspacePreparationError("工作区 .venv 创建失败，请检查服务器是否安装 python3-venv")
        venv_root = os.path.join(workspace, ".venv")
        if username and self._run_root("runuser", "-u", username, "--", "test", "-w", venv_root, check=False).returncode != 0:
            self._run_root("chown", "-R", f"{username}:{username}", venv_root)

    def _apply_permissions(self, username: str, workspace: str) -> None:
        """Keep the workspace writable while protecting platform-managed files."""
        self._run_root("chown", "-R", f"{username}:{username}", workspace)
        self._run_root("chmod", "700", workspace)

        managed_paths = [
            "CLAUDE.md",
            ".mcp.json",
            ".claude/.claude.json",
            ".claude/settings.json",
            ".claude/hooks",
            ".claude/skills",
        ]
        for rel_path in managed_paths:
            self._run_root("chown", "-R", "root:root", os.path.join(workspace, rel_path), check=False)

        projects_dir = os.path.join(workspace, ".claude", "projects")
        self._run_root("mkdir", "-p", projects_dir)
        self._run_root("chown", "-R", f"{username}:{username}", projects_dir)
        self._run_root("chmod", "700", projects_dir)

        # Claude owns the config directory so it can create session-env and other
        # runtime state. Individual platform files below remain root-owned/immutable.
        self._run_root("chown", f"{username}:{username}", os.path.join(workspace, ".claude"), check=False)
        self._run_root("chmod", "700", os.path.join(workspace, ".claude"), check=False)
        self._run_root("chmod", "755", os.path.join(workspace, ".claude", "hooks"), check=False)
        self._run_root("chmod", "755", os.path.join(workspace, ".claude", "skills"), check=False)
        self._run_root("chmod", "644", os.path.join(workspace, "CLAUDE.md"), check=False)
        self._run_root("chmod", "644", os.path.join(workspace, ".mcp.json"), check=False)
        self._run_root("chmod", "644", os.path.join(workspace, ".claude", ".claude.json"), check=False)
        self._run_root("chmod", "644", os.path.join(workspace, ".claude", "settings.json"), check=False)
        self._run_root(
            "find",
            os.path.join(workspace, ".claude", "hooks"),
            "-type",
            "f",
            "-exec",
            "chmod",
            "644",
            "{}",
            "+",
            check=False,
        )
        self._run_root(
            "find",
            os.path.join(workspace, ".claude", "skills"),
            "-type",
            "f",
            "-exec",
            "chmod",
            "644",
            "{}",
            "+",
            check=False,
        )
        self._lock_managed(workspace)

    def _lock_managed(self, workspace: str) -> None:
        """Mark managed files/directories immutable when the filesystem supports it."""
        plain_paths = [
            "CLAUDE.md",
            ".mcp.json",
            ".claude/.claude.json",
            ".claude/settings.json",
        ]
        recursive_paths = [
            ".claude/hooks",
            ".claude/skills",
        ]
        for rel_path in plain_paths:
            self._run_root("chattr", "+i", os.path.join(workspace, rel_path), check=False)
        for rel_path in recursive_paths:
            self._run_root("chattr", "-R", "+i", os.path.join(workspace, rel_path), check=False)

    def _unlock_managed(self, workspace: str) -> None:
        """Remove immutable flags before syncing or deleting managed files."""
        paths = [
            ".claude",
            ".venv",
            "CLAUDE.md",
            ".mcp.json",
        ]
        for rel_path in paths:
            self._run_root("chattr", "-R", "-i", os.path.join(workspace, rel_path), check=False)

    def _run_as_user_prefix(self, username: str) -> list[str]:
        """Build the argv prefix used by runtimes to execute as the agent user."""
        if self._is_root():
            return [
                "runuser", "-u", username, "--",
                "python3", "-c", RUNNER_SCRIPT, "aihub-agent-run",
            ]
        return [
            "sudo",
            "-n",
            "-u",
            username,
            "--",
            "python3",
            "-c",
            RUNNER_SCRIPT,
            "aihub-agent-run",
        ]

    def _resolve_workspace_path(self, agent_id: int, rel_path: str) -> str:
        """Resolve a user-provided path and ensure it stays inside the workspace."""
        workspace = os.path.realpath(self._workspace(agent_id))
        rel = (rel_path or "").replace("\\", "/").lstrip("/")
        target = os.path.realpath(os.path.join(workspace, rel)) if rel else workspace
        if target != workspace and not target.startswith(workspace + os.sep):
            raise ValueError("invalid path")
        return target

    def _assert_workspace_path(self, workspace: str) -> None:
        """Ensure destructive operations stay below the configured workspace root."""
        root = os.path.realpath(self._workspace_root)
        target = os.path.realpath(workspace)
        if target == root or not target.startswith(root + os.sep):
            raise ValueError("invalid linux sandbox workspace path")

    def _workspace(self, owner) -> str:
        if hasattr(owner, "workspace_key"):
            return os.path.join(self._user_workspace_root(owner), "files")
        return os.path.join(self._workspace_root, str(owner))

    def _username(self, owner) -> str:
        if hasattr(owner, "workspace_key"):
            return f"{settings.user_workspace_user_prefix}{owner.user_id}"
        return f"{self._user_prefix}{owner}"

    @staticmethod
    def _user_workspace_root(workspace) -> str:
        return os.path.join(settings.user_workspace_root, workspace.workspace_key)

    @staticmethod
    def _assert_user_workspace_path(workspace_root: str) -> None:
        root = os.path.realpath(settings.user_workspace_root)
        target = os.path.realpath(workspace_root)
        if target == root or not target.startswith(root + os.sep):
            raise ValueError("invalid user workspace path")

    @staticmethod
    def _write_text(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as file_obj:
            file_obj.write(content)

    @staticmethod
    def _write_json(path: str, content: dict) -> None:
        with open(path, "w", encoding="utf-8") as file_obj:
            json.dump(content, file_obj, ensure_ascii=False, indent=2)

    @staticmethod
    def _is_root() -> bool:
        return hasattr(os, "geteuid") and os.geteuid() == 0

    def _privileged_prefix(self) -> list[str]:
        return [] if self._is_root() else ["sudo", "-n"]

    def _run_root(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a privileged command without exposing sensitive environment values."""
        cmd = [*self._privileged_prefix(), *args]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"linux sandbox command failed: {args[0]} exited with {result.returncode}"
                + (f": {detail}" if detail else "")
            )
        return result

    def _run_root_bytes(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a privileged command and keep stdout as bytes."""
        cmd = [*self._privileged_prefix(), *args]
        result = subprocess.run(cmd, capture_output=True)
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"linux sandbox command failed: {args[0]} exited with {result.returncode}"
                + (f": {detail}" if detail else "")
            )
        return result
