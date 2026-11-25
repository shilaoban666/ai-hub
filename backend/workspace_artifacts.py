"""Identify user-facing files changed within one execution view."""
import os

from agent_workspace import (
    CLAUDE_CODE_MANAGED_PATHS, is_text_preview_path,
)
from sandbox.artifact_scan import snapshot


def managed_artifact_paths(runtime_type):
    paths = CLAUDE_CODE_MANAGED_PATHS
    return sorted(path.casefold() for path in paths)


def snapshot_execution_files(ctx, runtime_type):
    root = ctx.execution_view_path or ctx.host_workspace_path
    return snapshot(root, set(managed_artifact_paths(runtime_type)))


def changed_artifacts(before, after):
    if before is None or after is None:
        return []
    return [
        {"path": path, "name": os.path.basename(path), "size": metadata[0],
         "is_previewable": is_text_preview_path(path)
         or os.path.splitext(path)[1].lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}}
        for path, metadata in sorted(after.items())
        if before.get(path) != metadata
    ]
