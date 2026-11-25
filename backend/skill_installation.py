"""Durable skill reconciliation. Standard library only for privileged native use."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


MARKER = ".aihub-installed.json"
INSTALLATION_FORMAT = 2


def installation_source(source):
    """Unpack trusted release identity, never infer it from SKILL.md or a name."""
    if not isinstance(source, dict):
        return source, None  # Legacy callers without a published release.
    release = source.get("release")
    if not isinstance(release, dict):
        raise ValueError("missing skill release identity")
    development = release.get("source") == "workspace"
    if development and (release.get("release_id") is not None or release.get("version") != "latest"):
        raise ValueError("invalid skill workspace identity")
    for key in (("skill_id",) if development else ("skill_id", "release_id")):
        if type(release.get(key)) is not int or release[key] <= 0:
            raise ValueError("invalid skill release identity")
    if not isinstance(release.get("version"), str) or not release["version"].strip():
        raise ValueError("invalid skill release version")
    digest = release.get("content_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
        raise ValueError("invalid skill release hash")
    identity = {key: release[key] for key in (
        "skill_id", "release_id", "version", "content_sha256",
    )}
    if development:
        identity["source"] = "workspace"
    return source["directory"], identity


def remove_directory(path):
    path = Path(path)
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        def retry(function, filename, _error):
            os.chmod(filename, stat.S_IRWXU)
            function(filename)
        shutil.rmtree(path, onerror=retry)


def fingerprint(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid skill directory")
    info = root.stat()
    result = [[".", [info.st_dev, info.st_ino, 0, 0, 0, info.st_mode, info.st_uid, info.st_gid]]]
    for parent, dirs, files in os.walk(root):
        for name in sorted(dirs + files):
            path = Path(parent) / name
            if path == root / MARKER:
                continue
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError("skill contains a symlink or special file")
            result.append([path.relative_to(root).as_posix(), [
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid,
            ]])
    return sorted(result)


def content_inventory(root):
    result = []
    for relative, signature in fingerprint(root):
        if stat.S_ISDIR(signature[5]):
            result.append([relative, None])
        else:
            digest = hashlib.sha256()
            with open(Path(root) / relative, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            result.append([relative, digest.hexdigest()])
    return result


def materialize(source, destination, *, copy_function=shutil.copyfile, owner=None):
    """Verify a persistent installation; copy only on missing/changed content.

    The durable marker enables metadata-only checks after process restarts.
    Changed metadata triggers content verification before deciding to reinstall.
    Native installs are root-owned and readable only by the runtime user's group.
    """
    source, release = installation_source(source)
    source, destination = Path(source), Path(destination)
    if (source / MARKER).exists():
        raise ValueError("reserved skill installation metadata filename")
    source_signature = fingerprint(source)
    previous = {}
    try:
        marker = destination / MARKER
        if marker.is_symlink():
            raise ValueError("invalid installation marker")
        previous = json.loads(marker.read_text(encoding="utf-8"))
        if (previous.get("format") == INSTALLATION_FORMAT
                and previous.get("release") == release
                and previous.get("source") == source_signature
                and previous.get("owner") == owner
                and previous.get("installed") == fingerprint(destination)):
            # Windows ctime is creation time, so a same-size edit with a restored
            # mtime requires content verification. Linux ctime detects that edit.
            if os.name != "nt" or content_inventory(source) == content_inventory(destination):
                return False
    except (OSError, ValueError, TypeError, AttributeError):
        previous = {}

    expected = content_inventory(source)
    try:
        valid = content_inventory(destination) == expected
    except (OSError, ValueError):
        valid = False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not valid:
        stage = Path(tempfile.mkdtemp(prefix=".installing-", dir=destination.parent))
        try:
            shutil.copytree(source, stage, dirs_exist_ok=True, copy_function=copy_function)
            if content_inventory(stage) != expected or fingerprint(source) != source_signature:
                raise RuntimeError("skill files changed during installation")
            remove_directory(destination)
            stage.rename(destination)
        finally:
            remove_directory(stage)
    if owner is not None:
        import pwd
        gid = pwd.getpwnam(owner).pw_gid
        for parent, dirs, files in os.walk(destination):
            for path in [Path(parent), *(Path(parent) / name for name in files)]:
                if path.name == MARKER:
                    continue
                os.chown(path, 0, gid)
                os.chmod(path, 0o750 if path.is_dir() else 0o640)
    record = {"format": INSTALLATION_FORMAT, "release": release,
              "source": source_signature, "owner": owner,
              "installed": fingerprint(destination)}
    fd, pending = tempfile.mkstemp(prefix=".metadata-", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
        marker = destination / MARKER
        if marker.exists() or marker.is_symlink():
            remove_directory(marker)
        os.replace(pending, marker)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    return not valid


def reconcile(root, sources, *, owner=None, copy_function=shutil.copyfile):
    """Call under the workspace execution lease, before exposing the run view."""
    root = Path(root)
    if root.is_symlink():
        raise ValueError("installation root must not be a symlink")
    for name in sources:
        if not name or name in {".", ".."} or any(ch in name for ch in ("/", "\\", ":", "\0")):
            raise ValueError("invalid skill directory name")
        installation_source(sources[name])
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.name not in sources:
            remove_directory(child)
    for name, source in sources.items():
        materialize(source, root / name, owner=owner, copy_function=copy_function)
    if owner is not None:
        import pwd
        os.chown(root, 0, pwd.getpwnam(owner).pw_gid)
        os.chmod(root, 0o750)


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as handle:
        plan = json.load(handle)
    reconcile(plan["root"], plan["sources"], owner=plan["owner"])
