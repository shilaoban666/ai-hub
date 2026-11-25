import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth import CurrentUser
from git_routes import import_from_remote, pull_from_remote, push_to_remote
from models import Skill, SkillCollaborator
from schemas import GitBindRequest, GitPullRequest, GitPushRequest
from skill_utils import load_skill_files, parse_skill_md, save_skill_files, build_file_tree_from_flat, flatten_file_tree


class GitSkillVersionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Skill.__table__.create(engine)
        SkillCollaborator.__table__.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.skill = Skill(
            id=1, user_id=7, name="Local skill", version="2.3.4", description="Local description", author="Local author",
            git_provider="gitlab", git_repo_url="https://git.example.com/team/skill",
            git_branch="main",
        )
        self.db.add(self.skill)
        self.db.commit()
        self.user = CurrentUser(user_id=7)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        files_patch = patch("skill_utils.SKILLS_DIR", str(Path(temp.name) / "skills"))
        files_patch.start()
        self.addCleanup(files_patch.stop)
        self.client = AsyncMock()
        self.client.get_latest_commit.return_value = {"sha": "remote-commit"}
        client_patch = patch("git_routes._create_client", return_value=self.client)
        client_patch.start()
        self.addCleanup(client_patch.stop)

    async def assert_synced_version(self, route, request, version_line, expected):
        content = f"---\nname: Remote skill\n{version_line}description: Remote description\n---\n# Instructions\n"
        self.client.get_tree_files.return_value = {"SKILL.md": content}
        result = await route(1, request, db=self.db, current_user=self.user)
        self.db.expire_all()
        saved = self.db.get(Skill, 1)
        self.assertTrue(result["success"])
        self.assertEqual(saved.version, expected)
        self.assertEqual(saved.name, "Local skill")
        self.assertEqual(saved.description, "Local description")
        self.assertEqual(saved.author, "Local author")
        self.assertEqual(saved.content, content)
        self.assertEqual(saved.git_sync_direction, 1)
        self.assertEqual(saved.git_last_commit_sha, "remote-commit")
        self.assertEqual(load_skill_files(1)[0]["content"], content)

    async def test_pull_preserves_version_when_missing(self):
        await self.assert_synced_version(pull_from_remote, GitPullRequest(), "", "2.3.4")

    async def test_pull_preserves_version_when_empty(self):
        await self.assert_synced_version(pull_from_remote, GitPullRequest(), "version:   \n", "2.3.4")

    async def test_pull_preserves_local_version_with_explicit_remote_version(self):
        await self.assert_synced_version(pull_from_remote, GitPullRequest(), "version: 3.0.0\n", "2.3.4")

    async def test_pull_does_not_reset_to_remote_one_zero_zero(self):
        await self.assert_synced_version(pull_from_remote, GitPullRequest(), "version: 1.0.0\n", "2.3.4")

    async def test_pull_preserves_local_version_with_localized_remote_version(self):
        await self.assert_synced_version(pull_from_remote, GitPullRequest(), "版本：3.0.0\n", "2.3.4")

    async def test_pull_replaces_files_but_preserves_basic_information(self):
        save_skill_files(1, build_file_tree_from_flat({'SKILL.md': '# Local file'}))
        await self.assert_synced_version(pull_from_remote, GitPullRequest(), "version: 9.0.0\n", "2.3.4")

    async def test_pull_without_metadata_preserves_basic_information(self):
        self.client.get_tree_files.return_value = {'SKILL.md': '# Only instructions'}
        await pull_from_remote(1, GitPullRequest(), db=self.db, current_user=self.user)
        self.db.refresh(self.skill)
        self.assertEqual((self.skill.name, self.skill.version, self.skill.description), ('Local skill', '2.3.4', 'Local description'))

    async def test_push_sends_file_metadata_unchanged_after_basic_info_edit(self):
        content = '---\nname: File name\nversion: 1.0.0\ndescription: File description\n---\n'
        save_skill_files(1, build_file_tree_from_flat({'SKILL.md': content}))
        self.skill.name = 'Edited display name'
        self.skill.version = '8.0.0'
        self.skill.description = 'Edited display description'
        self.db.commit()
        self.client.get_tree_files.return_value = {}
        self.client.create_or_update_files.return_value = {'sha': 'pushed'}
        await push_to_remote(1, GitPushRequest(), db=self.db, current_user=self.user)
        self.assertEqual(self.client.create_or_update_files.call_args.args[0], {'SKILL.md': content})

    async def test_git_import_initializes_once_then_pull_only_updates_files(self):
        for provider in ('gitlab', 'github'):
            with self.subTest(provider=provider):
                content = '---\nname: Imported name\nversion: 5.0.0\ndescription: Imported description\n---\n'
                self.client.get_tree_files.return_value = {'wrapper/SKILL.md': content, 'wrapper/nested/SKILL.md': 'name: Nested'}
                skill = await import_from_remote(GitBindRequest(provider=provider, repo_url='https://git.example.com/team/new'), db=self.db, current_user=self.user)
                self.assertEqual((skill.name, skill.version, skill.description), ('Imported name', '5.0.0', 'Imported description'))
                self.assertEqual(skill.user_id, self.user.user_id)
                self.assertEqual(skill.git_provider, provider)
                self.assertIn(content, flatten_file_tree(load_skill_files(skill.id)).values())
                self.client.get_tree_files.return_value = {'SKILL.md': 'name: New remote name\nversion: 9.0.0\ndescription: New remote description'}
                await pull_from_remote(skill.id, GitPullRequest(), db=self.db, current_user=self.user)
                self.assertEqual((skill.name, skill.version, skill.description), ('Imported name', '5.0.0', 'Imported description'))

    async def test_git_import_without_version_uses_initial_default(self):
        self.client.get_tree_files.return_value = {'SKILL.md': 'name: Imported\ndescription: Initial'}
        skill = await import_from_remote(GitBindRequest(repo_url='https://git.example.com/team/new'), db=self.db, current_user=self.user)
        self.assertEqual(skill.version, '1.0.0')

    async def test_failed_git_import_leaves_no_placeholder(self):
        initial_count = self.db.query(Skill).count()
        for files in ({}, {'other-skill.md': 'name: Wrong file'}, {'SKILL.md': ''}):
            self.client.get_tree_files.return_value = files
            with self.assertRaises(HTTPException) as error:
                await import_from_remote(GitBindRequest(repo_url='https://git.example.com/team/new'), db=self.db, current_user=self.user)
            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(self.db.query(Skill).count(), initial_count)
        self.client.get_tree_files.return_value = {'SKILL.md': 'name: Valid'}
        with patch('git_routes.save_skill_files', side_effect=OSError('disk full')):
            with self.assertRaises(HTTPException):
                await import_from_remote(GitBindRequest(repo_url='https://git.example.com/team/new'), db=self.db, current_user=self.user)
        self.assertEqual(self.db.query(Skill).count(), initial_count)


class SkillVersionParsingTests(unittest.TestCase):
    def test_frontmatter_multiline_description_quotes_and_body_are_distinct(self):
        content = '---\nname: "Display: name"\nversion: "01.02"\ndescription: |\n  First line\n  Second line\n---\nname: Not metadata\nversion: 9.0.0\n'
        metadata, original = parse_skill_md(content)
        self.assertEqual(metadata['name'], 'Display: name')
        self.assertEqual(metadata['version'], '01.02')
        self.assertEqual(metadata['description'], 'First line\nSecond line')
        self.assertEqual(original, content)
        metadata, _ = parse_skill_md('---\nname: Test\n---\nversion: 9.0.0\ndescription: Body')
        self.assertEqual(metadata['version'], '')
        self.assertEqual(metadata['description'], '')

    def test_missing_and_blank_versions_are_not_invented(self):
        for content in (
            "# Skill without metadata\n",
            "version:\ndescription: Something\n",
            "version:  \r\ndescription: Something\r\n",
            "version:   ",
        ):
            with self.subTest(content=content):
                metadata, _ = parse_skill_md(content)
                self.assertEqual(metadata["version"], "")


if __name__ == "__main__":
    unittest.main()
