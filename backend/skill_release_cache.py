"""Private, immutable release cache; runtime workspaces receive independent copies."""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import threading

from database import settings
from skill_installation import materialize
from skill_utils import load_release_file_tree, resolve_release_file_path


CACHE_FORMAT = 3
_locks = [threading.RLock() for _ in range(32)]
_memory_lock = threading.RLock()
_memory = OrderedDict()
_MEMORY_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class CachedRelease:
    content_sha256: str
    files_json: str
    directory: str
    fingerprint: tuple
    metadata_signature: tuple


def _signature(path):
    value = os.stat(path, follow_symlinks=False)
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_mode)


def _fingerprint(directory):
    """Detect changed/missing/extra files with metadata reads, without reading contents."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("skill directory is missing or is a symlink")
    result = []
    for parent, dirs, files in os.walk(root):
        for name in sorted(dirs + files):
            path = Path(parent) / name
            signature = _signature(path)
            if not (stat.S_ISREG(signature[-1]) or stat.S_ISDIR(signature[-1])):
                raise ValueError("skill cache contains a non-regular file")
            result.append((path.relative_to(root).as_posix(), signature))
    return tuple(sorted(result))


def _cache_root():
    configured = settings.skill_release_cache_root
    root = Path(configured) if configured else Path(__file__).parent / ".cache" / "skill-releases"
    if not root.is_absolute():
        root = Path(__file__).parent / ".." / root
    root = root.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Runtime users must not be able to read other users' private cached skills.
    root.chmod(0o700)
    return root


@contextmanager
def _build_lock(root, key):
    stripe = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % len(_locks)
    with _locks[stripe]:
        with open(root / f".lock-{stripe}", "a+b") as handle:
            if sys.platform == "win32":
                import msvcrt
                # Windows permits locking past EOF; initialization writes can
                # collide with another process's lock before we acquire it.
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if sys.platform == "win32":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def remove_skill_directory(path):
    path = Path(path)
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        def make_writable_and_retry(function, filename, _error):
            os.chmod(filename, stat.S_IRWXU)
            function(filename)
        shutil.rmtree(path, onerror=make_writable_and_retry)


def _validate_hash(release, digest):
    if release.content_sha256 and release.content_sha256 != digest:
        raise RuntimeError(f"skill release {release.id} failed integrity verification")
    if not release.content_sha256:
        release.content_sha256 = digest


def _hash_archive(archive):
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remember(key, entry):
    with _memory_lock:
        _memory[key] = entry
        _memory.move_to_end(key)
        while len(_memory) > 32 or sum(len(value.files_json) * 4 for value in _memory.values()) > _MEMORY_BYTES:
            _memory.popitem(last=False)


def get_cached_release(release):
    archive = Path(resolve_release_file_path(release.file_path, release.file_url))
    if not archive.is_file():
        raise RuntimeError(f"skill release archive is missing: {release.id}")
    signature = _signature(archive)
    root = _cache_root()
    identity = json.dumps([CACHE_FORMAT, release.id, str(archive), signature])
    key = hashlib.sha256(identity.encode()).hexdigest()
    cache = root / key
    memory_key = str(cache)
    with _build_lock(root, key):
        with _memory_lock:
            entry = _memory.get(memory_key)
        if entry is not None:
            try:
                valid = (entry.metadata_signature == _signature(cache / "metadata.json")
                         and entry.fingerprint == _fingerprint(entry.directory))
            except (OSError, ValueError):
                valid = False
            if valid:
                _validate_hash(release, entry.content_sha256)
                _remember(memory_key, entry)
                return entry
        if cache.exists():
            try:
                data = json.loads((cache / "metadata.json").read_text(encoding="utf-8"))
                fingerprint = _fingerprint(cache / "files")
                if data["identity"] != identity or data["fingerprint"] != json.loads(json.dumps(fingerprint)):
                    raise ValueError("cached files changed")
                if not isinstance(data["files_json"], str) or hashlib.sha256(data["files_json"].encode()).hexdigest() != data["files_json_sha256"]:
                    raise ValueError("cached file tree changed")
                entry = CachedRelease(data["content_sha256"], data["files_json"], str(cache / "files"), fingerprint, _signature(cache / "metadata.json"))
            except (OSError, ValueError, KeyError, TypeError):
                remove_skill_directory(cache)
            else:
                _validate_hash(release, entry.content_sha256)
                _remember(memory_key, entry)
                return entry
        stage = Path(tempfile.mkdtemp(prefix=".building-", dir=root))
        try:
            content_hash = _hash_archive(archive)
            _validate_hash(release, content_hash)
            tree = load_release_file_tree(str(archive), include_binary=True)
            if _signature(archive) != signature:
                raise RuntimeError(f"skill release {release.id} changed while caching")
            files_root = stage / "files"
            files_root.mkdir()

            def write_nodes(nodes, parent):
                for node in nodes:
                    target = parent / node["label"]
                    if node["type"] == "folder":
                        target.mkdir()
                        write_nodes(node.get("children", []), target)
                    else:
                        if 'raw_content' in node:
                            target.write_bytes(node.pop('raw_content'))
                        else:
                            target.write_text(node.get("content", ""), encoding="utf-8", newline="")
                        target.chmod(0o444)

            write_nodes(tree, files_root)
            files_json = json.dumps(tree, ensure_ascii=False)
            metadata = {
                "identity": identity, "content_sha256": content_hash,
                "files_json": files_json, "fingerprint": _fingerprint(files_root),
                "files_json_sha256": hashlib.sha256(files_json.encode()).hexdigest(),
            }
            (stage / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            (stage / "metadata.json").chmod(0o444)
            stage.rename(cache)
            entry = CachedRelease(content_hash, files_json, str(cache / "files"), _fingerprint(cache / "files"), _signature(cache / "metadata.json"))
            _remember(memory_key, entry)
            return entry
        finally:
            remove_skill_directory(stage)


def copy_skill_file(source, destination):
    """Try copy-on-write; never hard-link writable runtime files to the cache."""
    if sys.platform.startswith("linux"):
        import fcntl
        try:
            with open(source, "rb") as src, open(destination, "wb") as dst:
                fcntl.ioctl(dst.fileno(), 0x40049409, src.fileno())  # FICLONE
        except OSError as error:
            if error.errno not in {errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTTY, errno.EINVAL, errno.ENOSYS, errno.EPERM}:
                raise
        else:
            return destination
    return shutil.copyfile(source, destination)


def materialize_cached_skill(source, destination):
    """Keep verified installations across runs and backend restarts."""
    return materialize(source, destination, copy_function=copy_skill_file)
