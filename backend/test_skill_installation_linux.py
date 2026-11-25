"""Exercise native ownership, symlinks and cleanup on real Linux filesystems."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_hooks import pre_tool_use as hook
from skill_installation import materialize, reconcile


@unittest.skipUnless(os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0,
                     "requires Linux root in a disposable test directory")
class NativePhysicalInstallationTests(unittest.TestCase):
    def test_native_permissions_read_access_noop_and_uninstall(self):
        import pwd
        owner = pwd.getpwnam("nobody")
        with tempfile.TemporaryDirectory(prefix="aihub-install-test-") as temporary:
            root = Path(temporary)
            root.chmod(0o755)
            source = root / "release"
            source.mkdir()
            (source / "SKILL.md").write_text("published")
            persistent = root / "persistent"
            spec = {"directory": str(source), "release": {
                "skill_id": 1, "release_id": 11, "version": "1.0", "content_sha256": "a" * 64,
            }}
            reconcile(persistent, {"example": spec}, owner=owner.pw_name)
            target = persistent / "example/SKILL.md"
            marker = persistent / "example/.aihub-installed.json"
            self.assertEqual(json.loads(marker.read_text())["release"], spec["release"])
            before = marker.stat().st_mtime_ns
            view = root / "view"
            skills = view / ".claude/skills"
            skills.mkdir(parents=True)
            (skills / "example").symlink_to(persistent / "example", target_is_directory=True)

            # Match native's recursive ownership passes. Neither may dereference
            # the managed links or alter the persistent skill's runtime group.
            subprocess.run(["chown", "-R", f"{owner.pw_uid}:{owner.pw_gid}", str(view)], check=True)
            subprocess.run(["chown", "-R", "root:root", str(skills)], check=True)
            self.assertEqual((target.stat().st_uid, target.stat().st_gid), (0, owner.pw_gid))
            self.assertEqual(((persistent / "example").stat().st_uid,
                              (persistent / "example").stat().st_gid), (0, owner.pw_gid))
            reference = str(skills / "example/SKILL.md")
            self.assertTrue(hook.resolve_under_ws(reference, str(view), str(view)))
            self.assertTrue(hook.is_protected_target(reference, str(view), str(view)))
            read = subprocess.run(["runuser", "-u", owner.pw_name, "--", "cat", reference],
                                  capture_output=True, text=True, check=True)
            self.assertEqual(read.stdout, "published")
            forbidden = subprocess.run(["runuser", "-u", owner.pw_name, "--", "test", "-w", str(target)])
            self.assertNotEqual(forbidden.returncode, 0)
            with patch("skill_installation.content_inventory", side_effect=AssertionError("unchanged files rehashed")):
                materialize(spec, persistent / "example", owner=owner.pw_name,
                            copy_function=lambda *_: self.fail("valid skill recopied"))
            self.assertEqual(marker.stat().st_mtime_ns, before)

            subprocess.run(["rm", "-rf", str(view)], check=True)
            self.assertEqual(target.read_text(), "published")
            reconcile(persistent, {}, owner=owner.pw_name)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
