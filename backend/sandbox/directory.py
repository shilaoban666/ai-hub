"""目录沙箱:claude 直接在宿主工作区目录运行,无物理隔离(本地调试用)。

行为与重构前完全一致:工作区在 backend/agent_workspaces/<id>/,
claude 作为本机子进程以 cwd=工作区 运行。适合本地调试,零开销。

注意:此沙箱不提供文件系统隔离，仅用于受信任的本地调试。
生产/多用户场景请在 Linux 或 WSL 中使用 native 沙箱。
"""
from __future__ import annotations

import os
import subprocess
import sys

import agent_workspace as ws
from sandbox.base import Sandbox, WorkspaceContext, WorkspacePreparationError


class DirectorySandbox(Sandbox):
    type_name = "directory"
    is_isolated = False

    def sync_skill_installations(self, agent, workspace):
        return ws.install_skills(ws.get_workspace_dir(agent.id), agent.runtime_skills)

    def prepare(self, agent, model, filter_skills=None) -> WorkspaceContext:
        """复用现有 sync_workspace 写入工作区,返回目录运行上下文。"""
        ws_dir = ws.sync_workspace(agent, model, filter_skills=filter_skills)
        self._ensure_venv(ws_dir)
        return WorkspaceContext(
            sandbox_type=self.type_name,
            workspace_root=ws_dir,
            host_workspace_path=ws_dir,
            argv_prefix=[],
            claude_bin="claude",
            run_cwd=ws_dir,
            env=dict(getattr(agent, "runtime_secret_env", None) or {}),
            is_isolated=False,
        )

    def delete(self, agent_id: int) -> None:
        ws.delete_workspace(agent_id)

    def host_workspace_path(self, agent_id: int) -> str:
        return ws.get_workspace_dir(agent_id)

    @staticmethod
    def _ensure_venv(ws_dir: str) -> None:
        """确保工作区内有可用的 .venv(不存在或残缺才创建,幂等)。"""
        venv_dir = os.path.join(ws_dir, ".venv")
        py = os.path.join(venv_dir, "Scripts" if os.name == "nt" else "bin",
                          "python" + (".exe" if os.name == "nt" else ""))
        if os.path.exists(py):
            return  # venv 已就绪
        try:
            subprocess.run([sys.executable, "-m", "venv", venv_dir],
                           check=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkspacePreparationError("工作区 .venv 创建失败，请检查 Python venv 支持及目录权限") from exc
