"""Merge earlier workspace files, preserving current files and conflicting copies.

This module also runs with system Python under the native sandbox helper.
"""
import filecmp
import os
from pathlib import Path
import shutil
import sys


def merge_workspace(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink():
        raise ValueError("legacy workspace must not be a symlink")
    if not source.is_dir():
        return
    # Generated Claude configuration/venvs are rebuilt for the new execution
    # view; their executable symlinks must never become user workspace files.
    managed = {".claude", ".venv", ".mcp.json", "CLAUDE.md", ".aihub"}
    entries = []
    for directory, directories, files in os.walk(source, followlinks=False):
        if Path(directory) == source:
            directories[:] = [name for name in directories if name not in managed]
            files = [name for name in files if name not in managed]
        entries.extend(Path(directory) / name for name in [*directories, *files])
    entries.sort(key=lambda path: (len(path.parts), str(path)))
    if any(path.is_symlink() or not (path.is_dir() or path.is_file()) for path in entries):
        raise ValueError("legacy workspace contains unsupported file types")
    # Validate the destination before writing, including each existing ancestor.
    for path in [destination, *destination.parents]:
        if path.is_symlink():
            raise ValueError("workspace destination must not contain symlinks")
    if any(path.is_symlink() for path in destination.rglob("*")):
        raise ValueError("workspace destination must not contain symlinks")
    conflicting = []
    for path in entries:
        target = destination / path.relative_to(source)
        if (any(parent.is_file() for parent in target.parents)
                or target.exists() and (path.is_dir() != target.is_dir()
                    or path.is_file() and not filecmp.cmp(path, target, shallow=False))):
            conflicting.append(path)
    if conflicting:
        # Preserve one complete, readable snapshot when any name/type conflicts.
        base = destination / f"legacy-agent-{source.name}"
        archive = base
        suffix = 1
        while archive.exists():
            if archive.is_dir() and all(
                (archive / path.relative_to(source)).is_dir() if path.is_dir() else
                (archive / path.relative_to(source)).is_file()
                and filecmp.cmp(path, archive / path.relative_to(source), shallow=False)
                for path in entries
            ):
                break
            archive = base.with_name(f"{base.name}.{suffix}")
            suffix += 1
        else:
            archive.mkdir(parents=True)
            for path in entries:
                archived = archive / path.relative_to(source)
                if path.is_dir():
                    archived.mkdir(parents=True, exist_ok=True)
                else:
                    archived.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, archived)
    for path in entries:
        target = destination / path.relative_to(source)
        if path in conflicting or any(parent.is_file() for parent in target.parents):
            continue
        if path.is_dir():
            if not target.exists():
                target.mkdir(parents=True)
            continue
        if target.is_file() and filecmp.cmp(path, target, shallow=False):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


if __name__ == "__main__":
    merge_workspace(*sys.argv[1:])
