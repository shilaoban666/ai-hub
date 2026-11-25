"""Ephemeral Docker Runtime Cell backed by a user-owned persistent workspace."""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
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
from skill_release_cache import copy_skill_file
from skill_installation import reconcile
from sandbox.base import Sandbox, WorkspaceContext
from sandbox.native import RUNNER_SCRIPT
from sandbox.legacy_workspace import merge_workspace


class ContainerSandbox(Sandbox):
    type_name = "container"
    is_isolated = True

    def sync_skill_installations(self, agent, workspace):
        user_root = self._user_root(workspace)
        self._assert_user_path(user_root)
        root = os.path.join(user_root, "managed", "skill-installations", str(agent.id))
        with tempfile.TemporaryDirectory(prefix="aihub_skill_sync_") as stage:
            os.makedirs(os.path.join(stage, ".claude", "skills"))
            pending = []
            names = install_skills(stage, agent.runtime_skills, cached_copies=pending)
            reconcile(root, staged_skill_sources(stage, pending), copy_function=copy_skill_file)
        return names

    def prepare(self, agent, model, filter_skills=None) -> WorkspaceContext:
        raise RuntimeError("container execution requires a user workspace and run id")

    def prepare_execution(
        self,
        agent,
        model,
        *,
        run_id: str,
        workspace,
        filter_skills=None,
    ) -> WorkspaceContext:
        self._require_docker()
        user_root = self._user_root(workspace)
        files_root = os.path.join(user_root, "files")
        sessions_root = os.path.join(user_root, "sessions", "projects")
        run_root = os.path.join(user_root, "managed", "runs", run_id)
        view_root = os.path.join(run_root, "view")
        venv_root = os.path.join(user_root, "managed", "container-venv")
        skill_root = os.path.join(user_root, "managed", "skill-installations", str(agent.id))
        self._assert_user_path(user_root)

        if os.path.lexists(run_root):
            shutil.rmtree(run_root)
        os.makedirs(files_root, mode=0o700, exist_ok=True)
        os.makedirs(sessions_root, mode=0o700, exist_ok=True)
        os.makedirs(view_root, mode=0o700, exist_ok=True)
        os.makedirs(venv_root, mode=0o700, exist_ok=True)
        if getattr(workspace, "migration_status", "not_required") == "pending":
            for legacy_agent_id in getattr(workspace, "legacy_agent_ids", [agent.id]):
                for legacy_root in legacy_workspace_roots(legacy_agent_id):
                    merge_workspace(legacy_root, files_root)
            workspace.migration_status = "completed"
        self._assert_no_symlinks(files_root)
        shutil.copytree(files_root, view_root, dirs_exist_ok=True)
        # Pre-create the nested bind target as the backend user, so Docker does
        # not leave a root-owned directory in the disposable host view.
        os.makedirs(os.path.join(view_root, ".venv"), mode=0o700, exist_ok=True)

        skills = (
            agent.runtime_skills if hasattr(agent, "runtime_skills") else getattr(agent, "skills", [])
        )
        mcps = (
            agent.runtime_mcps if hasattr(agent, "runtime_mcps") else getattr(agent, "mcps", [])
        ) or []
        temp_dir = tempfile.mkdtemp(prefix="aihub_container_config_")
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
                build_claude_md(agent, installed_skills, runtime_workspace_root="/workspace"),
            )
            self._write_json(
                os.path.join(temp_dir, ".claude", ".claude.json"),
                build_claude_state_json(["/workspace"]),
            )
            self._write_json(
                os.path.join(temp_dir, ".claude", "settings.json"),
                build_settings_json(
                    agent,
                    model,
                    mcps=mcps,
                    include_secrets=False,
                    sandbox_type=self.type_name,
                ),
            )
            mcp_config, _ = build_mcp_json(
                mcps,
                check_connectivity=False,
                overrides=getattr(agent, "mcp_overrides", []),
            )
            self._write_json(os.path.join(temp_dir, ".mcp.json"), mcp_config)
            reconcile(skill_root, staged_skill_sources(temp_dir, cached_copies), copy_function=copy_skill_file)
            # Skill content lives outside the disposable view. Docker mounts only
            # the selected skills, read-only, without exposing the release cache.
            shutil.rmtree(os.path.join(temp_dir, ".claude", "skills"))
            old_skills = os.path.join(view_root, ".claude", "skills")
            if os.path.exists(old_skills):
                shutil.rmtree(old_skills)
            shutil.copytree(temp_dir, view_root, dirs_exist_ok=True, copy_function=copy_skill_file)
            for name in installed_skills:
                os.makedirs(os.path.join(view_root, ".claude", "skills", name), exist_ok=True)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        container_name = f"aihub-run-{run_id[:20]}"
        uid = os.getuid() if hasattr(os, "getuid") else 1000
        gid = os.getgid() if hasattr(os, "getgid") else uid
        prefix = [
            "docker", "run", "--rm", "--interactive", "--name", container_name,
            "--user", f"{uid}:{gid}",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--memory", settings.claude_code_container_memory,
            "--cpus", settings.claude_code_container_cpus,
            "--pids-limit", str(settings.claude_code_container_pids_limit),
            "--network", settings.claude_code_container_network,
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "--mount", f"type=bind,src={view_root},dst=/workspace",
            "--mount", f"type=bind,src={venv_root},dst=/workspace/.venv",
            "--mount", f"type=bind,src={sessions_root},dst=/workspace/.claude/projects",
            "--workdir", "/workspace",
        ]
        if settings.claude_code_container_network == "bridge":
            prefix.extend(["--add-host", "host.docker.internal:host-gateway"])
        for name in installed_skills:
            # Docker's --mount value uses CSV escaping, including names with commas.
            mount = io.StringIO()
            csv.writer(mount, lineterminator="").writerow([
                "type=bind", f"src={os.path.join(skill_root, name)}",
                f"dst=/workspace/.claude/skills/{name}", "readonly",
            ])
            prefix.extend(["--mount", mount.getvalue()])
        prefix.extend([
            settings.claude_code_container_image,
            "python3", "-c", RUNNER_SCRIPT, "aihub-container-run",
        ])
        return WorkspaceContext(
            sandbox_type=self.type_name,
            workspace_root="/workspace",
            host_workspace_path=view_root,
            argv_prefix=prefix,
            claude_bin="claude",
            env={
                "AIHUB_AGENT_WORKSPACE": "/workspace",
                "AIHUB_BOOTSTRAP_VENV": "1",
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/workspace",
                "USER": "aihub",
                "LOGNAME": "aihub",
                "SHELL": "/bin/sh",
                **(getattr(agent, "runtime_secret_env", None) or {}),
            },
            tunnel_env_via_stdin=True,
            is_isolated=True,
            workspace_id=workspace.id,
            run_id=run_id,
            persistent_files_path=files_root,
            execution_view_path=view_root,
            handle={
                "container_name": container_name,
                "user_root": user_root,
                "run_root": run_root,
                "view_root": view_root,
                "files_root": files_root,
                "skill_root": skill_root,
                "quota_bytes": int(getattr(workspace, "quota_bytes", 0) or 0),
            },
        )

    def cleanup(self, ctx: WorkspaceContext) -> None:
        view_root = ctx.handle.get("view_root")
        files_root = ctx.handle.get("files_root")
        run_root = ctx.handle.get("run_root")
        user_root = ctx.handle.get("user_root")
        if not all((view_root, files_root, run_root, user_root)):
            return
        self._assert_user_path(user_root)
        for rel_path in ("CLAUDE.md", ".mcp.json", ".claude", ".venv"):
            target = os.path.join(view_root, rel_path)
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            elif os.path.lexists(target):
                os.unlink(target)
        self._assert_no_symlinks(view_root)
        quota = int(ctx.handle.get("quota_bytes", 0) or 0)
        if quota and self._tree_size(view_root) > quota:
            raise RuntimeError("workspace quota exceeded")

        staging = os.path.join(user_root, f".files-{ctx.run_id}-{uuid.uuid4().hex}.tmp")
        previous = os.path.join(user_root, f".files-{ctx.run_id}.previous")
        shutil.copytree(view_root, staging)
        if os.path.lexists(previous):
            shutil.rmtree(previous)
        if os.path.lexists(files_root):
            os.replace(files_root, previous)
        try:
            os.replace(staging, files_root)
        except Exception:
            if os.path.lexists(previous) and not os.path.lexists(files_root):
                os.replace(previous, files_root)
            raise
        shutil.rmtree(previous, ignore_errors=True)
        shutil.rmtree(run_root, ignore_errors=True)

    def discard_execution(self, ctx: WorkspaceContext) -> None:
        if not ctx.run_id or not ctx.handle.get("run_root"):
            return
        self._assert_user_path(ctx.handle["user_root"])
        shutil.rmtree(ctx.handle["run_root"], ignore_errors=True)

    def delete(self, agent_id: int) -> None:
        return None

    def host_workspace_path(self, owner) -> str:
        if not hasattr(owner, "workspace_key"):
            raise ValueError("a user workspace is required")
        return os.path.join(self._user_root(owner), "files")

    @staticmethod
    def _require_docker() -> None:
        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Docker daemon is unavailable") from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Docker daemon is unavailable")

    @staticmethod
    def _user_root(workspace) -> str:
        return os.path.join(settings.user_workspace_root, workspace.workspace_key)

    @staticmethod
    def _assert_user_path(path: str) -> None:
        root = os.path.realpath(settings.user_workspace_root)
        target = os.path.realpath(path)
        if target == root or not target.startswith(root + os.sep):
            raise ValueError("invalid user workspace path")

    @staticmethod
    def _assert_no_symlinks(root: str) -> None:
        if os.path.islink(root):
            raise RuntimeError("symbolic links are not allowed in user workspaces")
        for current, dirs, files in os.walk(root, followlinks=False):
            for name in [*dirs, *files]:
                if os.path.islink(os.path.join(current, name)):
                    raise RuntimeError("symbolic links are not allowed in user workspaces")

    @staticmethod
    def _tree_size(root: str) -> int:
        total = 0
        for current, _, files in os.walk(root, followlinks=False):
            for name in files:
                total += os.path.getsize(os.path.join(current, name))
        return total

    @staticmethod
    def _write_text(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as file_obj:
            file_obj.write(content)

    @staticmethod
    def _write_json(path: str, content: dict) -> None:
        with open(path, "w", encoding="utf-8") as file_obj:
            json.dump(content, file_obj, ensure_ascii=False, indent=2)
