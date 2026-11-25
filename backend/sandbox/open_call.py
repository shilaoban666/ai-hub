"""Disposable filesystem and OS identity for one external request."""
from __future__ import annotations

import shutil
import subprocess
from copy import copy

from sandbox import get_configured_sandbox_type
from sandbox.container import ContainerSandbox
from sandbox.native import NativeSandbox


def check_open_call_sandbox():
    if get_configured_sandbox_type() not in {"container", "native", "linux_user"}:
        raise ValueError("开放调用需要 container 或 native 隔离运行环境")


class _Disposable:
    def prepare_execution(self, agent, model, *, run_id, workspace, filter_skills=None):
        isolated = copy(workspace)
        isolated.workspace_key = "open-" + run_id
        isolated.migration_status = "not_required"
        isolated.legacy_agent_ids = []
        root = self._open_root(isolated)
        try:
            return super().prepare_execution(
                agent, model, run_id=run_id, workspace=isolated, filter_skills=filter_skills,
            )
        except BaseException:
            self._remove_root(root, run_id)
            raise

    def cleanup(self, ctx):
        self.discard_execution(ctx)

    def discard_execution(self, ctx):
        root = ctx.handle.get("user_root")
        if root:
            self._remove_root(root, ctx.run_id)


class OpenContainerSandbox(_Disposable, ContainerSandbox):
    def _open_root(self, workspace):
        return self._user_root(workspace)

    def _remove_root(self, root, run_id):
        self._assert_user_path(root)
        # Also terminate an orphaned container during lease recovery. Normal
        # completed containers have already exited because docker run uses --rm.
        subprocess.run(
            ["docker", "rm", "-f", "aihub-run-" + run_id[:20]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        )
        shutil.rmtree(root, ignore_errors=True)


class OpenNativeSandbox(_Disposable, NativeSandbox):
    def _username(self, owner):
        if hasattr(owner, "workspace_key") and owner.workspace_key.startswith("open-"):
            return "aiapi_" + owner.workspace_key[5:25]
        return super()._username(owner)

    def _open_root(self, workspace):
        return self._user_workspace_root(workspace)

    def _remove_root(self, root, run_id):
        self._assert_user_workspace_path(root)
        username = "aiapi_" + run_id[:20]
        self._run_root("pkill", "-KILL", "-u", username, check=False)
        self._run_root("userdel", username, check=False)
        self._unlock_managed(root)
        self._run_root("rm", "-rf", root)


def get_open_call_sandbox():
    check_open_call_sandbox()
    return OpenContainerSandbox() if get_configured_sandbox_type() == "container" else OpenNativeSandbox()
