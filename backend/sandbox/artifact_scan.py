"""Metadata-only scanner, also executable by the native sandbox's reader."""
import json
import os
import stat
import sys


def snapshot(root, managed):
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    ignored_dirs = {"node_modules", "__pycache__", "venv", "env", "tmp", "temp"}
    ignored_suffixes = (".pyc", ".pyo", ".tmp", ".temp", ".part", ".swp")
    result = {}
    visited = 0
    pending = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                visited += 1
                if visited > 50000:
                    raise ValueError("workspace artifact scan limit exceeded")
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                relative = prefix + entry.name
                if relative.casefold() in managed:
                    continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    if entry.name.casefold() not in ignored_dirs:
                        pending.append((entry.path, relative + "/"))
                elif stat.S_ISREG(info.st_mode) and not entry.name.lower().endswith(ignored_suffixes):
                    result[relative] = [info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    return result


if __name__ == "__main__":
    print(json.dumps(snapshot(sys.argv[1], set(json.loads(sys.argv[2])))))
