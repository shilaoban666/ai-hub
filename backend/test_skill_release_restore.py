import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import skill_utils
import schemas
from skill_utils import PathTraversalError, load_release_file_tree, resolve_release_file_path


class ReleaseFileTreeTests(unittest.TestCase):
    def _create_archive(self, entries):
        temp_dir = tempfile.TemporaryDirectory()
        archive_path = os.path.join(temp_dir.name, "release.zip")
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, content in entries:
                archive.writestr(path, content)
        return temp_dir, archive_path

    def test_loads_wrapped_release_with_windows_paths_and_empty_folders(self):
        temp_dir, archive_path = self._create_archive([
            ("demo-1.0.0\\SKILL.md", "# released"),
            ("demo-1.0.0\\scripts\\run.py", "print('released')"),
            ("demo-1.0.0\\empty\\", ""),
        ])
        with temp_dir:
            tree = load_release_file_tree(archive_path)

        self.assertEqual(["SKILL.md", "empty", "scripts"], [node["label"] for node in tree])
        self.assertEqual("# released", tree[0]["content"])
        self.assertEqual([], tree[1]["children"])
        self.assertEqual("run.py", tree[2]["children"][0]["label"])

    def test_rejects_path_traversal(self):
        temp_dir, archive_path = self._create_archive([
            ("demo-1.0.0/SKILL.md", "# released"),
            ("demo-1.0.0/../outside.txt", "invalid"),
        ])
        with temp_dir, self.assertRaises(PathTraversalError):
            load_release_file_tree(archive_path)

    def test_accepts_release_without_skill_md(self):
        temp_dir, archive_path = self._create_archive([
            ("demo-1.0.0/README.md", "missing skill file"),
        ])
        with temp_dir:
            tree = load_release_file_tree(archive_path)
        self.assertEqual(tree[0]['label'], 'README.md')
        self.assertEqual(tree[0]['content'], 'missing skill file')

    def test_resolves_release_moved_between_wsl_and_windows(self):
        with tempfile.TemporaryDirectory() as releases_dir:
            archive_path = os.path.join(releases_dir, "demo-1.0.0.zip")
            with open(archive_path, "wb") as archive:
                archive.write(b"release")
            with patch.object(skill_utils, "RELEASES_DIR", releases_dir):
                resolved = resolve_release_file_path(
                    "/mnt/d/git_repo/aihub/backend/releases/demo-1.0.0.zip",
                    "/releases/demo-1.0.0.zip",
                )

            self.assertEqual(os.path.realpath(archive_path), resolved)

    def test_restored_tree_completely_replaces_latest_files(self):
        temp_dir, archive_path = self._create_archive([
            ("demo-1.0.0/SKILL.md", "# released"),
            ("demo-1.0.0/scripts/run.py", "print('released')"),
        ])
        with temp_dir, tempfile.TemporaryDirectory() as skills_dir:
            with patch.object(skill_utils, "SKILLS_DIR", skills_dir):
                skill_utils.save_skill_files(7, [
                    {"label": "SKILL.md", "type": "file", "content": "# latest"},
                    {"label": "latest-only.txt", "type": "file", "content": "remove me"},
                ])
                skill_utils.save_skill_files(7, load_release_file_tree(archive_path))
                restored = skill_utils.load_skill_files(7)

        self.assertEqual(["SKILL.md", "scripts"], [node["label"] for node in restored])
        self.assertEqual("# released", restored[0]["content"])
        self.assertEqual("run.py", restored[1]["children"][0]["label"])


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_description_is_optional(self):
        release = schemas.SkillReleaseCreate(version="2.0.0")
        self.assertIsNone(release.description)

    def test_release_description_accepts_update_notes(self):
        release = schemas.SkillReleaseCreate(
            version="2.0.0",
            description="Add import validation and improve error messages.",
        )
        self.assertIn("import validation", release.description)


if __name__ == "__main__":
    unittest.main()
