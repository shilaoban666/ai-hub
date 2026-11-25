"""智能体沙箱抽象

把"工作区供给 + claude 执行环境"抽象成 Sandbox,支持两种隔离类型:
  - directory: 当前行为,无隔离,claude 直接在宿主工作区目录运行(本地调试用)
  - native:    Linux 用户 + chattr 不可变,物理隔离(WSL/Linux 生产运行)

Configure Claude Code isolation with CLAUDE_CODE_SANDBOX_TYPE.

为何需要沙箱:default 权限模式下 PreToolUse hook 与 deny 规则均生效(路径越界/
危险命令检查),但 Linux 用户隔离提供纵深防御,保证初始化文件(chattr +i)
不可删。directory 沙箱仅用于受信任的本地调试。
"""
from __future__ import annotations

import os
import stat
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


MAX_WORKSPACE_DOWNLOAD_BYTES = 20 * 1024 * 1024


class WorkspaceDownloadTooLarge(ValueError):
    pass


class WorkspacePreparationError(RuntimeError):
    """Workspace setup failure with a message safe to return to the user."""

    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


@dataclass
class WorkspaceContext:
    """沙箱供给完成后的运行上下文:runtime 据此启动 claude。

    Attributes:
        sandbox_type: directory | native
        workspace_root: claude 进程看到的 cwd/home
        host_workspace_path: 后端进程可见的工作区路径
        argv_prefix: claude 命令前缀，directory 为空，native 用 sudo/runuser 切换用户
        claude_bin: 沙箱内 claude 可执行名(默认 "claude")
        run_cwd: 宿主侧 subprocess 的 cwd(空串表示继承当前进程)
        env: 注入子进程的额外 env(directory 通常为空,runtime 从 config 取)
        tunnel_env_via_stdin: 通过包装器 stdin 传递运行环境，避免依赖 sudo -E
        is_isolated: 是否使用 Linux 用户隔离
        handle: 沙箱专属清理信息(如用户名、容器 id)
    """
    sandbox_type: str
    workspace_root: str
    host_workspace_path: str
    argv_prefix: list[str]
    claude_bin: str = "claude"
    run_cwd: str = ""
    env: dict = field(default_factory=dict)
    tunnel_env_via_stdin: bool = False
    is_isolated: bool = False
    handle: dict = field(default_factory=dict)
    workspace_id: int | None = None
    run_id: str | None = None
    persistent_files_path: str = ""
    execution_view_path: str = ""


class Sandbox(ABC):
    """沙箱抽象基类。

    生命周期:
      - 智能体创建/更新: 仅持久化配置和工作区绑定，不准备运行环境
      - 对话运行:        prepare_execution -> runtime.run(ctx) -> cleanup(ctx)
      - 智能体删除:      delete(agent_id) 清理沙箱资源
      - 文件浏览/下载:   host_workspace_path(agent_id) 取宿主可见路径
    """
    type_name: str = ""
    is_isolated: bool = False

    @abstractmethod
    def prepare(self, agent, model, filter_skills=None) -> WorkspaceContext:
        """供给工作区(写 CLAUDE.md/.claude/.mcp.json/.venv 等)并返回运行上下文。"""
        ...

    def cleanup(self, ctx: WorkspaceContext) -> None:
        """单次运行后清理(默认无操作)。"""
        return None

    def snapshot_execution_files(self, ctx: WorkspaceContext, runtime_type: str) -> dict:
        from workspace_artifacts import snapshot_execution_files
        return snapshot_execution_files(ctx, runtime_type)

    def discard_execution(self, ctx: WorkspaceContext) -> None:
        """Remove a disposable Run view without writing persistent files."""
        return None

    def sync_skill_installations(self, agent, workspace) -> list[str]:
        """Reconcile durable skills only, under the workspace execution lease."""
        raise NotImplementedError

    def prepare_execution(
        self,
        agent,
        model,
        *,
        run_id: str,
        workspace,
        filter_skills=None,
    ) -> WorkspaceContext:
        """Build one isolated Run view; legacy sandboxes fall back to prepare()."""
        context = self.prepare(agent, model, filter_skills=filter_skills)
        context.workspace_id = getattr(workspace, "id", None)
        context.run_id = run_id
        context.execution_view_path = context.host_workspace_path
        return context

    @abstractmethod
    def delete(self, agent_id: int) -> None:
        """智能体删除时清理沙箱资源(目录/用户/容器)。"""
        ...

    @abstractmethod
    def host_workspace_path(self, agent_id: int) -> str:
        """返回宿主侧可见的工作区路径(文件浏览/下载端点用)。"""
        ...

    # ---- 文件浏览(默认基于 host_workspace_path 用 os 实现;隔离沙箱覆写) ----

    def list_dir(self, agent_id: int, rel_path: str = "") -> dict:
        """列出工作区文件。

        Returns:
            {"type": "dir"|"file", "path": rel_path, "items": [...]}
            items: [{"name", "path", "type": "dir"|"file", "size"?}]
        Raises:
            ValueError: 非法路径或不支持浏览
            FileNotFoundError: 路径不存在
        """
        ws = self.host_workspace_path(agent_id)
        if not ws:
            raise ValueError("当前沙箱类型不支持文件浏览")
        ws_norm = os.path.realpath(ws)
        target = os.path.realpath(os.path.join(ws_norm, rel_path)) if rel_path else ws_norm
        if not (target == ws_norm or target.startswith(ws_norm + os.sep)):
            raise ValueError("非法路径")
        if not os.path.exists(target):
            raise FileNotFoundError("路径不存在")
        if os.path.isfile(target):
            return {"type": "file", "path": rel_path}
        items = []
        for name in sorted(os.listdir(target)):
            if name.startswith("."):
                continue
            full = os.path.join(target, name)
            if os.path.islink(full):
                continue
            rel = os.path.relpath(full, ws).replace("\\", "/")
            if os.path.isdir(full):
                items.append({"name": name, "path": rel, "type": "dir"})
            else:
                items.append({"name": name, "path": rel, "type": "file",
                              "size": os.path.getsize(full)})
        return {"type": "dir", "path": rel_path, "items": items}

    def read_file(self, agent_id: int, rel_path: str) -> tuple[bytes, str]:
        """读取文件内容供下载,返回 (content_bytes, filename)。"""
        ws = self.host_workspace_path(agent_id)
        if not ws:
            raise ValueError("当前沙箱类型不支持文件下载")
        ws_norm = os.path.realpath(ws)
        requested = os.path.join(ws_norm, rel_path)
        target = os.path.realpath(requested)
        if not (target == ws_norm or target.startswith(ws_norm + os.sep)):
            raise ValueError("非法路径")
        if os.path.islink(requested):
            raise ValueError("不允许读取符号链接")
        if not os.path.isfile(target):
            raise FileNotFoundError("文件不存在")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags)
        with os.fdopen(fd, "rb") as f:
            return f.read(), os.path.basename(target)

    def read_file_limited(
        self, agent_id: int, rel_path: str, max_bytes: int, *, reject_oversized: bool = False
    ) -> tuple[bytes, str]:
        """Read at most max_bytes + 1 bytes so callers can reject oversized files."""
        if max_bytes < 1:
            raise ValueError("无效的读取大小限制")
        ws = self.host_workspace_path(agent_id)
        if not ws:
            raise ValueError("当前沙箱类型不支持文件预览")
        ws_norm = os.path.realpath(ws)
        requested = os.path.join(ws_norm, rel_path)
        target = os.path.realpath(requested)
        if not (target == ws_norm or target.startswith(ws_norm + os.sep)):
            raise ValueError("非法路径")
        if os.path.islink(requested):
            raise ValueError("不允许读取符号链接")
        if not os.path.isfile(target):
            raise FileNotFoundError("文件不存在")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(target, flags)
        with os.fdopen(fd, "rb") as file:
            metadata = os.fstat(file.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("仅支持读取普通文件")
            if reject_oversized and metadata.st_size > max_bytes:
                raise WorkspaceDownloadTooLarge("工作区文件下载最大支持 20 MiB")
            content = file.read(max_bytes + 1)
            # Also bound a file that grows after fstat.
            if reject_oversized and len(content) > max_bytes:
                raise WorkspaceDownloadTooLarge("工作区文件下载最大支持 20 MiB")
            return content, os.path.basename(target)

    def read_file_for_download(self, agent_id: int, rel_path: str) -> tuple[bytes, str]:
        return self.read_file_limited(
            agent_id, rel_path, MAX_WORKSPACE_DOWNLOAD_BYTES, reject_oversized=True,
        )

    def write_file(self, agent_id: int, rel_path: str, content: bytes) -> str:
        """写入文件到工作区,返回工作区相对路径。

        Args:
            agent_id: 智能体 ID
            rel_path: 相对路径（sanitized，只取 basename 防路径穿越）
            content: 文件内容（bytes）
        Returns:
            写入的文件在工作区内的相对路径
        Raises:
            ValueError: 非法路径或沙箱不支持写入
        """
        ws = self.host_workspace_path(agent_id)
        if not ws:
            raise ValueError("当前沙箱类型不支持文件写入")
        # 防路径穿越：只取文件名
        safe_name = os.path.basename(rel_path.replace("\\", "/"))
        if not safe_name:
            raise ValueError("无效文件名")
        ws_norm = os.path.realpath(ws)
        target = os.path.join(ws_norm, safe_name)
        if not (target == ws_norm or target.startswith(ws_norm + os.sep)):
            raise ValueError("非法路径")
        if os.path.lexists(target) and os.path.islink(target):
            raise ValueError("不允许覆盖符号链接")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        return safe_name

    def delete_file(self, agent_id: int, rel_path: str) -> None:
        """Delete one regular file from the workspace."""
        ws = self.host_workspace_path(agent_id)
        if not ws:
            raise ValueError("当前沙箱类型不支持删除文件")
        ws_norm = os.path.realpath(ws)
        requested = os.path.join(ws_norm, rel_path)
        target = os.path.realpath(requested)
        if target == ws_norm or not target.startswith(ws_norm + os.sep):
            raise ValueError("非法路径")
        if os.path.islink(requested):
            raise ValueError("不允许删除符号链接")
        if not os.path.isfile(target):
            raise FileNotFoundError("文件不存在")
        os.unlink(target)

    def delete_path(self, agent_id: int, rel_path: str) -> None:
        """Delete one regular file or directory tree from the workspace."""
        ws = self.host_workspace_path(agent_id)
        if not ws:
            raise ValueError("当前沙箱类型不支持删除工作区内容")
        ws_norm = os.path.realpath(ws)
        requested = os.path.join(ws_norm, rel_path)
        target = os.path.realpath(requested)
        if target == ws_norm or not target.startswith(ws_norm + os.sep):
            raise ValueError("非法路径")
        if os.path.islink(requested):
            raise ValueError("不允许删除符号链接")
        if os.path.isfile(target):
            os.unlink(target)
            return
        if os.path.isdir(target):
            shutil.rmtree(target)
            return
        raise FileNotFoundError("文件或目录不存在")
