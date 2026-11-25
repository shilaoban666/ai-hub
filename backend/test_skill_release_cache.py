from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import skill_release_cache as cache
from agent_workspace import install_skills


class SkillReleaseCacheTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        archive_root = patch("skill_utils.RELEASES_DIR", str(self.root))
        archive_root.start()
        self.addCleanup(archive_root.stop)
        self.cache_root = self.root / "cache"
        self.cache_setting = patch.object(cache.settings, "skill_release_cache_root", str(self.cache_root))
        self.cache_setting.start()
        self.addCleanup(self.cache_setting.stop)
        self.release = self.make_release(1, "original")

    def make_release(self, release_id, content):
        archive = self.root / f"release-{release_id}.zip"
        with ZipFile(archive, "w") as handle:
            handle.writestr("example/SKILL.md", content)
            handle.writestr("example/scripts/tool.py", "print('hello')\n")
        return SimpleNamespace(id=release_id, file_path=str(archive), file_url="", content_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())

    def runtime_skill(self, release=None):
        release = release or self.release
        entry = cache.get_cached_release(release)
        return SimpleNamespace(
            id=1, name="example", content="", files=entry.files_json, cached_files_dir=entry.directory,
            installation_release={"skill_id": 1, "release_id": release.id,
                                  "version": f"{release.id}.0", "content_sha256": entry.content_sha256},
        )

    def test_warm_and_disk_hits_do_not_hash_or_unpack_again(self):
        with patch.object(cache, "_hash_archive", wraps=cache._hash_archive) as hashes, patch.object(cache, "load_release_file_tree", wraps=cache.load_release_file_tree) as unpacks:
            first = cache.get_cached_release(self.release)
            second = cache.get_cached_release(self.release)
            self.assertIs(first, second)
            with cache._memory_lock:
                cache._memory.pop(str(Path(first.directory).parent))
            third = cache.get_cached_release(self.release)
        self.assertEqual(hashes.call_count, 1)
        self.assertEqual(unpacks.call_count, 1)
        self.assertEqual(first.files_json, third.files_json)
        self.assertEqual((Path(third.directory) / "SKILL.md").read_text(), "original")

    def test_binary_resources_survive_cache_and_runtime_installation(self):
        raw = bytes(range(256)) * 4096
        archive = Path(self.release.file_path)
        with ZipFile(archive, 'a') as handle:
            handle.writestr('example/assets/simhei.ttf', raw)
        self.release.content_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        entry = cache.get_cached_release(self.release)
        self.assertEqual((Path(entry.directory) / 'assets/simhei.ttf').read_bytes(), raw)
        self.assertLess(len(entry.files_json), 10000)
        runtime = self.root / 'runtime'
        cache.materialize_cached_skill(entry.directory, runtime)
        self.assertEqual((runtime / 'assets/simhei.ttf').read_bytes(), raw)

    def test_changed_archive_is_verified_even_if_size_and_mtime_are_preserved(self):
        cache.get_cached_release(self.release)
        archive = Path(self.release.file_path)
        old = archive.stat()
        replacement = self.root / "replacement.zip"
        replacement.write_bytes(archive.read_bytes().replace(b"original", b"tampered"))
        os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
        os.replace(replacement, archive)
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            cache.get_cached_release(self.release)

    def test_missing_archive_does_not_use_stale_cache(self):
        cache.get_cached_release(self.release)
        Path(self.release.file_path).unlink()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            cache.get_cached_release(self.release)

    def test_expected_digest_is_checked_on_warm_hits(self):
        cache.get_cached_release(self.release)
        self.release.content_sha256 = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            cache.get_cached_release(self.release)

    def test_cache_corruption_is_rebuilt_from_release(self):
        first = cache.get_cached_release(self.release)
        target = Path(first.directory) / "SKILL.md"
        target.chmod(0o644)
        target.write_text("modified")
        with patch.object(cache, "load_release_file_tree", wraps=cache.load_release_file_tree) as unpacks:
            repaired = cache.get_cached_release(self.release)
        self.assertEqual(unpacks.call_count, 1)
        self.assertEqual((Path(repaired.directory) / "SKILL.md").read_text(), "original")

    def test_partial_or_corrupt_metadata_is_rebuilt(self):
        first = cache.get_cached_release(self.release)
        metadata = Path(first.directory).parent / "metadata.json"
        metadata.chmod(0o644)
        metadata.write_text("{")
        repaired = cache.get_cached_release(self.release)
        self.assertEqual(json.loads(repaired.files_json)[0]["content"], "original")

    def test_new_release_and_rollback_use_separate_cached_versions(self):
        first = cache.get_cached_release(self.release)
        upgraded = cache.get_cached_release(self.make_release(2, "updated"))
        self.assertNotEqual(first.directory, upgraded.directory)
        with patch.object(cache, "load_release_file_tree", side_effect=AssertionError("unexpected unpack")):
            rolled_back = cache.get_cached_release(self.release)
        self.assertEqual(first.directory, rolled_back.directory)

    def test_valid_json_with_corrupted_file_tree_is_rebuilt(self):
        first = cache.get_cached_release(self.release)
        metadata = Path(first.directory).parent / "metadata.json"
        data = json.loads(metadata.read_text(encoding="utf-8"))
        data["files_json"] = data["files_json"].replace("original", "tampered")
        metadata.chmod(0o644)
        metadata.write_text(json.dumps(data), encoding="utf-8")
        repaired = cache.get_cached_release(self.release)
        self.assertEqual(json.loads(repaired.files_json)[0]["content"], "original")

    def test_threads_build_a_version_once(self):
        with patch.object(cache, "load_release_file_tree", wraps=cache.load_release_file_tree) as unpacks:
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _: cache.get_cached_release(self.release), range(8)))
        self.assertEqual(unpacks.call_count, 1)
        self.assertEqual(len({entry.directory for entry in results}), 1)

    def test_worker_processes_build_a_version_once(self):
        script = """
import sys
from pathlib import Path
from types import SimpleNamespace
import skill_release_cache as cache
cache.settings.skill_release_cache_root = sys.argv[1]
import skill_utils
skill_utils.RELEASES_DIR = str(Path(sys.argv[2]).parent)
original = cache.load_release_file_tree
def record(path, **kwargs):
    with open(sys.argv[4], 'a') as log:
        log.write('unpacked\\n')
    return original(path, **kwargs)
cache.load_release_file_tree = record
release = SimpleNamespace(id=1, file_path=sys.argv[2], file_url='', content_sha256=sys.argv[3])
cache.get_cached_release(release)
"""
        log = self.root / "builds.txt"
        processes = [subprocess.Popen(
            [sys.executable, "-c", script, str(self.cache_root), self.release.file_path, self.release.content_sha256, str(log)],
            cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) for _ in range(3)]
        for process in processes:
            self.addCleanup(lambda process=process: process.kill() if process.poll() is None else None)
            stdout, stderr = process.communicate(timeout=40)
            self.assertEqual(process.returncode, 0, stderr.decode(errors="replace"))
        self.assertEqual(log.read_text().splitlines(), ["unpacked"])

    @unittest.skipUnless(sys.platform == "win32", "requires Windows byte-range locks")
    def test_windows_worker_waits_on_an_empty_locked_file(self):
        import msvcrt

        key = "empty-lock"
        stripe = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % len(cache._locks)
        self.cache_root.mkdir()
        lock_path = self.cache_root / f".lock-{stripe}"
        script = """
import sys
from pathlib import Path
import skill_release_cache as cache
print('attempting', flush=True)
with cache._build_lock(Path(sys.argv[1]), sys.argv[2]):
    print('acquired', flush=True)
"""
        worker = None
        try:
            with open(lock_path, "a+b") as owner:
                msvcrt.locking(owner.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    worker = subprocess.Popen(
                        [sys.executable, "-c", script, str(self.cache_root), key],
                        cwd=Path(__file__).parent, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True,
                    )
                    self.assertEqual(worker.stdout.readline().strip(), "attempting")
                    with self.assertRaises(subprocess.TimeoutExpired):
                        worker.communicate(timeout=0.25)
                finally:
                    msvcrt.locking(owner.fileno(), msvcrt.LK_UNLCK, 1)
            stdout, stderr = worker.communicate(timeout=10)
            self.assertEqual(worker.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), "acquired")
            self.assertEqual(lock_path.stat().st_size, 0)
        finally:
            if worker is not None and worker.poll() is None:
                worker.kill()
                worker.communicate()

    def test_workspace_files_are_independent_and_unchanged_copies_are_reused(self):
        skill = self.runtime_skill()
        first = self.root / "user-a"
        second = self.root / "user-b"
        install_skills(str(first), [skill])
        install_skills(str(second), [skill])
        with patch.object(cache, "copy_skill_file", side_effect=AssertionError("unexpected copy")):
            install_skills(str(first), [skill])
        target = first / ".claude" / "skills" / "example" / "SKILL.md"
        target.write_text("user edit")
        self.assertEqual((Path(skill.cached_files_dir) / "SKILL.md").read_text(), "original")
        self.assertEqual((second / ".claude" / "skills" / "example" / "SKILL.md").read_text(), "original")
        install_skills(str(first), [skill])
        self.assertEqual(target.read_text(), "original")
        install_skills(str(first), [])
        self.assertFalse(target.exists())

    def test_cached_skill_staging_defers_file_copy_until_final_workspace(self):
        skill = self.runtime_skill()
        pending = []
        stage = self.root / "stage"
        with patch.object(cache, "copy_skill_file", side_effect=AssertionError("unexpected staging copy")):
            names = install_skills(str(stage), [skill], cached_copies=pending)
        self.assertEqual(names, ["example"])
        self.assertFalse((stage / ".claude" / "skills" / "example").exists())
        final = self.root / "final"
        for source, relative in pending:
            cache.materialize_cached_skill(source, str(final / relative))
        self.assertEqual((final / ".claude" / "skills" / "example" / "SKILL.md").read_text(), "original")
        record = json.loads((final / ".claude/skills/example/.aihub-installed.json").read_text())
        self.assertEqual(record["release"], skill.installation_release)

    def test_container_installs_once_and_mounts_selected_skills_read_only(self):
        from contextlib import ExitStack
        from sandbox.container import ContainerSandbox
        skill = self.runtime_skill()
        other = SimpleNamespace(**{**vars(skill), "id": 2, "name": "other"})
        agent = SimpleNamespace(id=1, runtime_skills=[skill, other], runtime_mcps=[])
        workspace = SimpleNamespace(id=7, workspace_key="user-7")
        sandbox = ContainerSandbox()
        with ExitStack() as stack:
            stack.enter_context(patch.object(sandbox, "_require_docker"))
            stack.enter_context(patch("sandbox.container.settings.user_workspace_root", str(self.root / "users")))
            stack.enter_context(patch("sandbox.container.build_claude_md", return_value="Instructions"))
            stack.enter_context(patch("sandbox.container.build_settings_json", return_value={}))
            stack.enter_context(patch("sandbox.container.build_mcp_json", return_value=({}, {})))
            stack.enter_context(patch("sandbox.container.install_hooks"))
            first = sandbox.prepare_execution(agent, SimpleNamespace(), run_id="run-1", workspace=workspace)
            root = Path(first.handle["skill_root"])
            target = root / "example" / "SKILL.md"
            before = target.stat()
            self.assertEqual(target.read_text(), "original")
            trust_state = json.loads(
                (Path(first.execution_view_path) / ".claude/.claude.json").read_text()
            )
            self.assertTrue(
                trust_state["projects"]["/workspace"]["hasTrustDialogAccepted"]
            )
            self.assertEqual(json.loads((root / "example/.aihub-installed.json").read_text())["release"],
                             skill.installation_release)
            self.assertFalse((Path(first.execution_view_path) / ".claude/skills/example/SKILL.md").exists())
            self.assertIn(f"type=bind,src={root / 'example'},dst=/workspace/.claude/skills/example,readonly", first.argv_prefix)
            sandbox.cleanup(first)
            self.assertEqual(target.read_text(), "original")
            with patch("skill_installation.shutil.copytree", wraps=__import__("shutil").copytree) as copies:
                second = sandbox.prepare_execution(agent, SimpleNamespace(), run_id="run-2", workspace=workspace, filter_skills=[skill])
                self.assertFalse(any(str(call.args[0]) == skill.cached_files_dir for call in copies.call_args_list))
            self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertTrue((root / "other/SKILL.md").exists())
            self.assertFalse(any("dst=/workspace/.claude/skills/other" in arg for arg in second.argv_prefix))
            sandbox.cleanup(second)
            # An uninstall must remove actual files, without destroying the source cache.
            agent.runtime_skills = []
            third = sandbox.prepare_execution(agent, SimpleNamespace(), run_id="run-3", workspace=workspace)
            self.assertFalse(target.exists())
            self.assertFalse((root / "other").exists())
            self.assertEqual((Path(skill.cached_files_dir) / "SKILL.md").read_text(), "original")
            sandbox.cleanup(third)

    def test_installed_files_survive_process_restart_without_recopy(self):
        skill = self.runtime_skill()
        destination = self.root / "durable"
        spec = {"directory": skill.cached_files_dir, "release": skill.installation_release}
        cache.materialize_cached_skill(spec, destination)
        before = {str(path.relative_to(destination)): path.stat().st_mtime_ns
                  for path in destination.rglob("*")}
        script = """
import sys, json
from skill_installation import materialize
def fail(*args):
    raise AssertionError('verified installation must not be recopied')
materialize(json.loads(sys.argv[1]), sys.argv[2], copy_function=fail)
"""
        subprocess.run([sys.executable, "-c", script, json.dumps(spec), str(destination)],
                       cwd=Path(__file__).parent, check=True, capture_output=True)
        after = {str(path.relative_to(destination)): path.stat().st_mtime_ns
                 for path in destination.rglob("*")}
        self.assertEqual(before, after)

    def test_corrupt_installation_is_repaired_after_restart_even_with_same_mtime(self):
        skill = self.runtime_skill()
        destination = self.root / "durable"
        cache.materialize_cached_skill(skill.cached_files_dir, destination)
        target = destination / "SKILL.md"
        before = target.stat()
        target.write_text("tampered")
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        subprocess.run([sys.executable, "-c",
                        "import sys; from skill_installation import materialize; materialize(*sys.argv[1:])",
                        skill.cached_files_dir, str(destination)], cwd=Path(__file__).parent,
                       check=True, capture_output=True)
        self.assertEqual(target.read_text(), "original")

    def test_upgrade_removes_old_files(self):
        workspace = self.root / "workspace"
        install_skills(str(workspace), [self.runtime_skill()])
        release = self.make_release(2, "upgraded")
        with ZipFile(release.file_path, "w") as handle:
            handle.writestr("SKILL.md", "upgraded")
        release.content_sha256 = hashlib.sha256(Path(release.file_path).read_bytes()).hexdigest()
        install_skills(str(workspace), [self.runtime_skill(release)])
        self.assertFalse((workspace / ".claude" / "skills" / "example" / "scripts").exists())


if __name__ == "__main__":
    unittest.main()
