"""Exercise the actual main.py handlers without running its database startup."""
import ast
import io
import json
import logging
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import Depends, File, HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import models
import schemas
import skill_utils
from auth import CurrentUser, get_current_active_user
from database import get_db
from skill_access import get_manageable_skill_or_404
from skill_utils import (
    PathTraversalError, find_skill_md_content, flatten_file_tree, load_skill_files,
    parse_skill_md, save_skill_files, delete_skill_files,
)

logger = logging.getLogger(__name__)


def load_handlers():
    source = ast.parse(Path(__file__).with_name('main.py').read_text(encoding='utf-8'))
    skill_imports = [node for node in source.body if (
        isinstance(node, ast.ImportFrom) and node.module == 'skill_utils'
    ) or (
        isinstance(node, ast.Import) and any(alias.name == 'skill_utils' for alias in node.names)
    )]
    handlers = [node for node in source.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in {'create_skill', 'update_skill', 'import_skill', 'import_skill_into_existing'}]
    for node in handlers:
        node.decorator_list = []
    namespace = dict(globals())
    # Use production imports so this test's module import cannot hide a missing one.
    namespace.pop('skill_utils', None)
    exec(compile(ast.Module(body=skill_imports + handlers, type_ignores=[]), 'main.py', 'exec'), namespace)
    return namespace


class SkillInformationIndependenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        models.Skill.__table__.create(engine)
        models.SkillCollaborator.__table__.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.user = CurrentUser(user_id=7)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        files_patch = patch.object(skill_utils, 'SKILLS_DIR', temp.name)
        files_patch.start()
        self.addCleanup(files_patch.stop)
        self.handlers = load_handlers()

    def files(self, content):
        return json.dumps({'tree': [{'id': 1, 'label': 'SKILL.md', 'path': 'SKILL.md', 'type': 'file', 'content': content}]})

    def test_create_initializes_metadata_and_later_edits_are_independent(self):
        content = '---\nname: File name\nversion: 2.0.0\ndescription: File description\n---\n'
        skill = self.handlers['create_skill'](schemas.SkillCreate(name='Form name', version='1.0.0', files=self.files(content)), db=self.db, current_user=self.user)
        self.assertEqual((skill.name, skill.version, skill.description), ('File name', '2.0.0', 'File description'))
        self.handlers['update_skill'](skill.id, schemas.SkillUpdate(name='Display name', version='3.0.0', description='Display description'), db=self.db, current_user=self.user)
        self.assertEqual(load_skill_files(skill.id)[0]['content'], content)
        edited_content = '---\nname: Changed file\nversion: 9.0.0\ndescription: Changed file description\n---\n'
        self.handlers['update_skill'](skill.id, schemas.SkillUpdate(files=self.files(edited_content)), db=self.db, current_user=self.user)
        self.db.refresh(skill)
        self.assertEqual((skill.name, skill.version, skill.description), ('Display name', '3.0.0', 'Display description'))
        self.assertEqual(load_skill_files(skill.id)[0]['content'], edited_content)

    def test_edit_does_not_replace_skill_author_with_editor(self):
        skill = self.handlers['create_skill'](
            schemas.SkillCreate(name='Owned skill', version='1.0.0', author='Original author'),
            db=self.db,
            current_user=self.user,
        )
        self.handlers['update_skill'](
            skill.id,
            schemas.SkillUpdate(description='Edited description', author='Editor'),
            db=self.db,
            current_user=CurrentUser(user_id=7),
        )
        self.db.refresh(skill)
        self.assertEqual(skill.author, 'Original author')

    async def test_markdown_and_zip_import_initialize_metadata_once(self):
        content = '---\nname: Imported name\nversion: 4.0.0\ndescription: Imported description\n---\n'
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('wrapper/SKILL.md', content)
        for name, data in [('SKILL.md', content.encode()), ('skill.zip', archive.getvalue())]:
            with self.subTest(filename=name):
                skill = await self.handlers['import_skill'](UploadFile(filename=name, file=io.BytesIO(data)), db=self.db, current_user=self.user)
                self.assertEqual((skill.name, skill.version, skill.description), ('Imported name', '4.0.0', 'Imported description'))
                self.handlers['update_skill'](skill.id, schemas.SkillUpdate(files=self.files('name: Edited\nversion: 8.0.0\ndescription: Edited')), db=self.db, current_user=self.user)
                self.db.refresh(skill)
                self.assertEqual((skill.name, skill.version, skill.description), ('Imported name', '4.0.0', 'Imported description'))

    def test_conversation_examples_persist_independently_and_can_be_cleared(self):
        content = '# Original skill instructions'
        skill = self.handlers['create_skill'](
            schemas.SkillCreate(name='Examples', version='1', files=self.files(content),
                                conversation_examples=['  xxx品销量怎么样？  ', '帮我查看本周任务']),
            db=self.db, current_user=self.user,
        )
        self.assertEqual(skill.conversation_examples, ['xxx品销量怎么样？', '帮我查看本周任务'])
        self.handlers['update_skill'](skill.id, schemas.SkillUpdate(description='Metadata only'),
                                      db=self.db, current_user=self.user)
        self.db.expire_all()
        self.assertEqual(self.db.get(models.Skill, skill.id).conversation_examples,
                         ['xxx品销量怎么样？', '帮我查看本周任务'])
        self.handlers['update_skill'](skill.id, schemas.SkillUpdate(conversation_examples=[' 新的示例 ', '', '  ']),
                                      db=self.db, current_user=self.user)
        self.assertEqual(skill.conversation_examples, ['新的示例'])
        self.assertEqual(load_skill_files(skill.id)[0]['content'], content)
        self.handlers['update_skill'](skill.id, schemas.SkillUpdate(conversation_examples=[]),
                                      db=self.db, current_user=self.user)
        self.assertEqual(skill.conversation_examples, [])

    async def test_zip_import_keeps_binary_assets_out_of_text_content(self):
        content = '---\nname: Binary asset skill\n---\n\nUse the bundled template.\n'
        assets = {
            'assets/template.xlsx': b'PK\x03\x04' + bytes(range(256)) * 128,
            'assets/simhei.ttf': bytes(range(256)) * (9 * 1024 * 1024 // 256),
            'assets/unknown.data': b'\xff\x80\x00resource',
            'scripts/windows.py': b'\xef\xbb\xbfprint("hello")\r\n',
            '.config/settings.json': b'{"enabled": true}\r\n',
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('wrapper/SKILL.md', content)
            z.writestr('wrapper/empty/', b'')
            for path, raw in assets.items():
                z.writestr('wrapper/' + path, raw)

        skill = await self.handlers['import_skill'](
            UploadFile(filename='binary-assets.zip', file=io.BytesIO(archive.getvalue())),
            db=self.db,
            current_user=self.user,
        )
        tree = load_skill_files(skill.id)
        files = flatten_file_tree(tree)
        self.assertEqual(files['SKILL.md'], content)
        self.assertEqual(files['assets/template.xlsx'], '')
        font = next(node for node in tree if node['label'] == 'assets')['children']
        font = next(node for node in font if node['label'] == 'simhei.ttf')
        self.assertTrue(font['is_binary'])
        self.assertEqual(font['size'], 9 * 1024 * 1024)
        self.assertNotIn('raw_content', font)
        self.assertLess(len(json.dumps(tree)), 10000)
        skill_dir = Path(skill_utils.get_skill_dir(skill.id))
        self.assertTrue((skill_dir / 'empty').is_dir())
        for path, raw in assets.items():
            self.assertEqual((skill_dir / path).read_bytes(), raw, path)

        # Editing another file must not overwrite resource placeholders with empty text.
        next(node for node in tree if node['label'] == 'SKILL.md')['content'] = '# Edited instructions\r\n'
        self.handlers['update_skill'](
            skill.id, schemas.SkillUpdate(files=json.dumps({'tree': tree})),
            db=self.db, current_user=self.user,
        )
        for path, raw in assets.items():
            self.assertEqual((skill_dir / path).read_bytes(), raw, path)

    async def test_failed_zip_import_does_not_leave_a_skill_record(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('SKILL.md', '# Valid skill')
        with patch.dict(self.handlers, save_skill_files=unittest.mock.Mock(side_effect=OSError('disk full'))):
            with self.assertRaises(HTTPException):
                await self.handlers['import_skill'](
                    UploadFile(filename='skill.zip', file=io.BytesIO(archive.getvalue())),
                    db=self.db, current_user=self.user,
                )
        self.assertEqual(self.db.query(models.Skill).count(), 0)

    async def test_existing_skill_import_preserves_information_and_replaces_entire_workspace(self):
        original = '---\nname: Original\nversion: 1.0.0\ndescription: Old\n---\n# old'
        skill = self.handlers['create_skill'](
            schemas.SkillCreate(name='Original', version='1.0.0', author='Original author', files=self.files(original)),
            db=self.db,
            current_user=self.user,
        )
        skill.module = '业务模块'
        skill.roles = '开发,运营'
        skill.cover = '/uploads/covers/original.png'
        skill.icon = 'original-icon'
        skill.is_public = True
        skill.development_mode = True
        skill.conversation_examples = [{'question': '原有示例', 'answer': '原有回答'}]
        skill.git_repo_url = 'https://example.com/original.git'
        skill.git_branch = 'custom'
        skill.git_last_commit_sha = 'a' * 40
        self.db.add(models.SkillCollaborator(
            skill_id=skill.id, user_id=8, username='Collaborator', created_by=7,
        ))
        models.SkillRelease.__table__.create(self.db.get_bind())
        self.db.add(models.SkillRelease(
            skill_id=skill.id, version='0.9.0', file_path='original.zip', file_url='/releases/original.zip',
        ))
        self.db.commit()
        previous_values = {column.name: getattr(skill, column.name) for column in models.Skill.__table__.columns}
        replacement = '---\nname: Replacement\nversion: 2.0.0\ndescription: New\nroles: New role\n---\n# new'
        binary = b'\x00\xff\x89PNG\r\n'
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('wrapper/SKILL.md', replacement)
            z.writestr('wrapper/assets/icon.png', binary)
            z.writestr('wrapper/scripts/new.py', 'print("new")')

        for filename, data in [('SKILL.md', replacement.encode()), ('skill.zip', archive.getvalue())]:
            with self.subTest(filename=filename):
                directory = Path(skill_utils.get_skill_dir(skill.id))
                (directory / 'obsolete.txt').write_text('remove me')
                (directory / '.hidden' / 'nested').mkdir(parents=True, exist_ok=True)
                (directory / '.hidden' / 'nested' / 'old.bin').write_bytes(binary)
                result = await self.handlers['import_skill_into_existing'](
                    skill.id,
                    UploadFile(filename=filename, file=io.BytesIO(data)),
                    db=self.db, current_user=self.user,
                )
                self.assertEqual(
                    {column.name: getattr(result, column.name) for column in models.Skill.__table__.columns},
                    previous_values,
                )
                self.assertEqual(self.db.query(models.SkillCollaborator).filter_by(skill_id=skill.id).count(), 1)
                self.assertEqual(self.db.query(models.SkillRelease).filter_by(skill_id=skill.id).one().version, '0.9.0')
                expected_paths = {'SKILL.md'}
                if filename.endswith('.zip'):
                    expected_paths.update({'assets', 'assets/icon.png', 'scripts', 'scripts/new.py'})
                    self.assertEqual((directory / 'assets' / 'icon.png').read_bytes(), binary)
                self.assertEqual({path.relative_to(directory).as_posix() for path in directory.rglob('*')}, expected_paths)
                self.assertEqual((directory / 'SKILL.md').read_text(), replacement)

    async def test_existing_skill_failed_import_preserves_original_workspace(self):
        skill = self.handlers['create_skill'](
            schemas.SkillCreate(name='Original', version='1.0.0', files=self.files('# original')),
            db=self.db, current_user=self.user,
        )
        directory = Path(skill_utils.get_skill_dir(skill.id))
        (directory / '.hidden').mkdir()
        (directory / '.hidden' / 'original.bin').write_bytes(b'\x00\xfforiginal')
        (directory / 'empty').mkdir()
        previous_tree = load_skill_files(skill.id, include_binary=True)
        invalid_archive = io.BytesIO()
        with zipfile.ZipFile(invalid_archive, 'w') as z:
            z.writestr('wrapper/README.md', 'missing entrypoint')
        with self.assertRaises(HTTPException) as invalid:
            await self.handlers['import_skill_into_existing'](
                skill.id, UploadFile(filename='skill.zip', file=io.BytesIO(invalid_archive.getvalue())),
                db=self.db, current_user=self.user,
            )
        self.assertEqual(invalid.exception.status_code, 400)
        self.assertEqual(load_skill_files(skill.id, include_binary=True), previous_tree)

        # A failure after replacement must restore the complete previous tree.
        with patch.object(self.db, 'commit', side_effect=RuntimeError('commit failed')):
            with self.assertRaises(HTTPException) as failed:
                await self.handlers['import_skill_into_existing'](
                    skill.id, UploadFile(filename='SKILL.md', file=io.BytesIO(b'# replacement')),
                    db=self.db, current_user=self.user,
                )
        self.assertEqual(failed.exception.status_code, 500)
        self.assertEqual(load_skill_files(skill.id, include_binary=True), previous_tree)
        self.db.refresh(skill)
        self.assertEqual((skill.name, skill.version), ('Original', '1.0.0'))

        # A write error after clearing the workspace must also remove partial
        # imported files and recover binary resources and empty directories.
        save_attempts = 0

        def fail_after_partial_write(skill_id, tree):
            nonlocal save_attempts
            save_attempts += 1
            if save_attempts > 1:
                return save_skill_files(skill_id, tree)
            target = Path(skill_utils.get_skill_dir(skill_id))
            (target / 'partial-import.txt').write_text('incomplete')
            raise OSError('disk full')

        with patch.dict(self.handlers, save_skill_files=fail_after_partial_write):
            with self.assertRaises(HTTPException) as failed:
                await self.handlers['import_skill_into_existing'](
                    skill.id, UploadFile(filename='SKILL.md', file=io.BytesIO(b'# replacement')),
                    db=self.db, current_user=self.user,
                )
        self.assertEqual(failed.exception.status_code, 500)
        self.assertEqual(load_skill_files(skill.id, include_binary=True), previous_tree)

    def test_manual_create_preserves_multiline_and_special_characters(self):
        name = 'Orders: "assistant"'
        description = 'First line: details\nSecond line'
        content = f'---\nname: {json.dumps(name)}\nversion: "1.0.0"\ndescription: {json.dumps(description)}\n---\n'
        skill = self.handlers['create_skill'](schemas.SkillCreate(name=name, version='1.0.0', description=description, files=self.files(content)), db=self.db, current_user=self.user)
        self.assertEqual(skill.name, name)
        self.assertEqual(skill.description, description)


if __name__ == '__main__':
    unittest.main()
