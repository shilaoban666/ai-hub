"""Capture saved author files once per run, including binary resources."""
import hashlib
import json
from pathlib import Path
import tempfile

from skill_installation import content_inventory
from skill_release_cache import (
    CachedRelease, _build_lock, _cache_root, _fingerprint, remove_skill_directory,
)
from skill_utils import get_skill_dir, load_skill_files


def get_development_snapshot(skill_id):
    directory = get_skill_dir(skill_id)
    before = _fingerprint(directory)
    tree = load_skill_files(skill_id, include_binary=True)
    if before != _fingerprint(directory):
        raise RuntimeError("技能工作区正在保存，请保存完成后重试")
    if not tree:
        raise RuntimeError("技能工作区没有文件，请先保存技能文件")
    # Hash the saved bytes, including binary resources, independently of release metadata.
    digest = hashlib.sha256(json.dumps(
        tree, ensure_ascii=False, sort_keys=True,
        default=lambda value: value.hex(),
    ).encode()).hexdigest()
    root = _cache_root()
    key = f"development-{skill_id}-{digest}"
    cache = root / key
    with _build_lock(root, key):
        stage = Path(tempfile.mkdtemp(prefix=".development-", dir=root))
        try:
            files_root = stage / "files"
            files_root.mkdir()

            def write_nodes(nodes, parent):
                for node in nodes:
                    name = node["label"]
                    if name in {".", "..", ".aihub-installed.json"} or any(c in name for c in "/\\:\x00"):
                        raise ValueError("非法的技能文件名")
                    target = parent / name
                    if node["type"] == "folder":
                        target.mkdir()
                        write_nodes(node.get("children", []), target)
                    else:
                        raw = node.pop("raw_content", None)
                        target.write_bytes(raw if raw is not None else node.get("content", "").encode())
                        target.chmod(0o444)

            write_nodes(tree, files_root)
            # Reuse an identical snapshot, repairing any damaged cached copy.
            if cache.exists():
                try:
                    valid = content_inventory(cache / "files") == content_inventory(files_root)
                except (OSError, ValueError):
                    valid = False
                if not valid:
                    remove_skill_directory(cache)
            if not cache.exists():
                stage.rename(cache)
            return CachedRelease(digest, json.dumps(tree, ensure_ascii=False),
                                 str(cache / "files"), _fingerprint(cache / "files"), ())
        finally:
            remove_skill_directory(stage)
