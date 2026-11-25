import os
import tempfile

from agent_workspace import (
    is_managed_workspace_path,
    is_text_preview_path,
    normalize_workspace_relative_path,
)
from sandbox.base import Sandbox, WorkspaceContext


class _TempSandbox(Sandbox):
    type_name = "test"

    def __init__(self, root: str):
        self.root = root

    def prepare(self, agent, model, filter_skills=None) -> WorkspaceContext:
        raise NotImplementedError

    def delete(self, agent_id: int) -> None:
        return None

    def host_workspace_path(self, agent_id: int) -> str:
        return self.root


def test_workspace_file_access_rejects_symbolic_links():
    with tempfile.TemporaryDirectory() as parent:
        workspace = os.path.join(parent, "workspace")
        os.makedirs(workspace)
        outside = os.path.join(parent, "outside.txt")
        with open(outside, "wb") as file:
            file.write(b"secret")

        link = os.path.join(workspace, "link.txt")
        try:
            os.symlink(outside, link)
        except OSError:
            return

        sandbox = _TempSandbox(workspace)
        assert sandbox.list_dir(1)["items"] == []

        for operation in (
            lambda: sandbox.read_file(1, "link.txt"),
            lambda: sandbox.write_file(1, "link.txt", b"overwrite"),
            lambda: sandbox.delete_file(1, "link.txt"),
            lambda: sandbox.delete_path(1, "link.txt"),
        ):
            try:
                operation()
            except ValueError:
                pass
            else:
                raise AssertionError("symbolic link access must be rejected")

        with open(outside, "rb") as file:
            assert file.read() == b"secret"


def test_workspace_file_access_keeps_normal_files_working():
    with tempfile.TemporaryDirectory() as workspace:
        sandbox = _TempSandbox(workspace)
        assert sandbox.write_file(1, "note.txt", b"hello") == "note.txt"
        content, filename = sandbox.read_file(1, "note.txt")
        assert content == b"hello"
        assert filename == "note.txt"
        limited_content, limited_filename = sandbox.read_file_limited(1, "note.txt", 3)
        assert limited_content == b"hell"
        assert limited_filename == "note.txt"
        sandbox.delete_file(1, "note.txt")
        assert not os.path.exists(os.path.join(workspace, "note.txt"))

        nested = os.path.join(workspace, "reports", "daily")
        os.makedirs(nested)
        with open(os.path.join(nested, "summary.txt"), "wb") as file:
            file.write(b"summary")
        sandbox.delete_path(1, "reports")
        assert not os.path.exists(os.path.join(workspace, "reports"))

        try:
            sandbox.delete_path(1, "")
        except ValueError:
            pass
        else:
            raise AssertionError("workspace root deletion must be rejected")


def test_managed_workspace_paths_are_runtime_specific():
    assert is_managed_workspace_path("claude_code", "CLAUDE.md")
    assert is_managed_workspace_path("claude_code", "claude.md")
    assert is_managed_workspace_path("claude_code", ".claude")
    assert is_managed_workspace_path("claude_code", ".claude/skills/example/SKILL.md")
    assert is_managed_workspace_path("claude_code", ".venv/bin/python")
    assert not is_managed_workspace_path("claude_code", "notes.md")


def test_text_preview_extensions_are_conservative():
    assert is_text_preview_path("README.md")
    assert is_text_preview_path("page.HTML")
    assert is_text_preview_path("src/component.vue")
    assert not is_text_preview_path("archive.zip")
    assert not is_text_preview_path("image.png")


def test_workspace_relative_path_normalization_rejects_delete_aliases():
    assert normalize_workspace_relative_path("reports\\daily") == "reports/daily"
    for path in ("", ".", "..", "../memory", "/memory", "C:\\workspace\\memory"):
        try:
            normalize_workspace_relative_path(path)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe workspace path must be rejected: {path}")


if __name__ == "__main__":
    test_workspace_file_access_rejects_symbolic_links()
    test_workspace_file_access_keeps_normal_files_working()
    test_managed_workspace_paths_are_runtime_specific()
    test_text_preview_extensions_are_conservative()
    test_workspace_relative_path_normalization_rejects_delete_aliases()
    print("workspace file safety tests passed")
