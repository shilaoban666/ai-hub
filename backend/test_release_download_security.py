"""Real handlers, temporary archives and an isolated SQLite database."""
import asyncio
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

with patch('sqlalchemy.schema.MetaData.create_all'):
    import main
from asset_routes import download_catalog_skill_release
from auth import CurrentUser
from database import get_db
from models import Skill, SkillCollaborator, SkillRelease, AssetSecurityEvent
from release_downloads import router
from schemas import SkillReleaseCreate, SkillUpdate
from skill_utils import resolve_release_file_path, PathTraversalError, load_skill_files, get_skill_dir


class ReleaseDownloadSecurityTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.releases = self.root / 'releases'
        self.releases.mkdir()
        for module in ('main', 'skill_utils'):
            replacement = patch(f'{module}.RELEASES_DIR', str(self.releases))
            replacement.start()
            self.addCleanup(replacement.stop)
        engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        self.addCleanup(engine.dispose)
        with patch.object(SQLiteTypeCompiler, 'visit_BIGINT', return_value='INTEGER'):
            for model in (Skill, SkillCollaborator, SkillRelease, AssetSecurityEvent):
                model.__table__.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.skill = Skill(id=1, user_id=7, name='中文技能', version='1', is_public=True)
        archive = self.releases / 'legacy.zip'
        with ZipFile(archive, 'w') as handle:
            handle.writestr('skill/SKILL.md', '# Safe test skill')
        self.release = SkillRelease(id=1, skill_id=1, version='1', file_path=str(archive),
                                    file_url='/releases/legacy.zip', status='published')
        self.db.add_all([self.skill, self.release])
        self.db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_legacy_link_rechecks_visibility_revocation_and_deletion(self):
        response = self.client.get('/releases/legacy.zip')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.skill.is_public = False
        self.db.commit()
        # Direct static proxy identity headers do not grant private access.
        self.assertEqual(self.client.get('/releases/legacy.zip', headers={'x-user-id': '7'}).status_code, 404)
        self.skill.is_public = True
        self.release.status = 'revoked'
        self.db.commit()
        self.assertEqual(self.client.get('/releases/legacy.zip').status_code, 404)
        self.release.status = 'published'
        self.skill.is_deleted = True
        self.db.commit()
        self.assertEqual(self.client.get('/releases/legacy.zip').status_code, 404)

    def test_private_download_requires_owner_or_collaborator(self):
        self.skill.is_public = False
        self.db.add(SkillCollaborator(skill_id=1, user_id=8, username='test', created_by=7))
        self.db.commit()
        for user_id in (7, 8):
            response = download_catalog_skill_release(1, self.db, CurrentUser(user_id))
            self.assertEqual(response.path, str((self.releases / 'legacy.zip').resolve()))
        with self.assertRaises(HTTPException) as error:
            download_catalog_skill_release(1, self.db, CurrentUser(9))
        self.assertEqual(error.exception.status_code, 404)
        self.release.status = 'revoked'
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            download_catalog_skill_release(1, self.db, CurrentUser(7))
        self.assertEqual(error.exception.status_code, 409)

    def test_unregistered_and_nested_files_are_not_downloadable(self):
        (self.releases / 'unregistered.zip').write_bytes(b'private')
        for path in ('unregistered.zip', 'nested/legacy.zip', 'C:%5Clegacy.zip'):
            self.assertEqual(self.client.get('/releases/' + path).status_code, 404)
        self.assertFalse(any(getattr(route, 'name', None) == 'releases' for route in main.app.routes))

    def test_external_stored_paths_and_symlinks_cannot_escape_release_root(self):
        outside = self.root / 'outside.zip'
        outside.write_bytes(b'private')
        self.assertEqual(resolve_release_file_path(str(outside), '/releases/missing.zip'), '')
        self.assertEqual(resolve_release_file_path(None, '/releases/..'), '')
        self.release.file_path = str(outside)
        self.release.file_url = '/releases/outside.zip'
        self.db.commit()
        self.assertEqual(self.client.get('/releases/outside.zip').status_code, 404)
        try:
            (self.releases / 'link.zip').symlink_to(outside)
        except OSError:
            return  # Windows may not grant symlink creation.
        self.assertEqual(resolve_release_file_path(str(self.releases / 'link.zip')), '')

    def test_display_names_and_versions_never_become_storage_paths(self):
        tree = [{'type': 'file', 'label': 'SKILL.md', 'content': '# Test'}]
        for index, name in enumerate(('../escape', '/absolute', 'C:\\escape', '正常中文技能')):
            with self.subTest(name=name), patch('main.load_skill_files', return_value=tree):
                self.skill.name = name
                self.db.commit()
                release = asyncio.run(main.release_skill(1, SkillReleaseCreate(version=f'../v{index}'), self.db, CurrentUser(7)))
                self.assertEqual(Path(release.file_path).parent, self.releases.resolve())
                with ZipFile(release.file_path) as archive:
                    self.assertEqual(archive.namelist(), ['skill-1/SKILL.md'])
        self.assertEqual({path.name for path in self.root.iterdir()}, {'releases'})

    def test_unsafe_archive_entry_is_rejected_and_failed_commit_cleans_file(self):
        with patch('main.load_skill_files', return_value=[{'type': 'file', 'label': '../x', 'content': 'x'}]):
            with self.assertRaises(PathTraversalError):
                asyncio.run(main.release_skill(1, SkillReleaseCreate(version='2'), self.db, CurrentUser(7)))
        tree = [{'type': 'file', 'label': 'SKILL.md', 'content': '# Test'}]
        with patch('main.load_skill_files', return_value=tree), patch.object(self.db, 'commit', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                asyncio.run(main.release_skill(1, SkillReleaseCreate(version='2'), self.db, CurrentUser(7)))
        self.assertEqual([path.name for path in self.releases.iterdir()], ['legacy.zip'])

    def test_import_edit_export_publish_and_restore_preserve_original_bytes(self):
        resources = {
            'SKILL.md': b'---\r\nname: Resource skill\r\n---\r\n# Original\r\n',
            'assets/simhei.ttf': bytes(range(256)) * 2048,
            'assets/image.png': b'\x89PNG\r\n\x1a\n\xff',
            'assets/data.custom': b'\xff\xfe\x00\x80',
            'scripts/run.py': b'\xef\xbb\xbfprint("original")\r\n',
            '.config/settings.json': b'{"enabled": true}\r\n',
        }
        buffer = io.BytesIO()
        with ZipFile(buffer, 'w') as archive:
            for path, raw in resources.items():
                archive.writestr('wrapper/' + path, raw)
            archive.writestr('wrapper/empty/', b'')
        with patch('skill_utils.SKILLS_DIR', str(self.root / 'skills')):
            skill = asyncio.run(main.import_skill(
                UploadFile(filename='resources.zip', file=io.BytesIO(buffer.getvalue())),
                self.db, CurrentUser(7),
            ))
            tree = load_skill_files(skill.id)
            tree.append({'label': 'notes.txt', 'type': 'file', 'content': 'new notes'})
            main.update_skill(skill.id, SkillUpdate(files=json.dumps({'tree': tree})), self.db, CurrentUser(7))
            exported = main.export_skill(skill.id, self.db, CurrentUser(7))
            with ZipFile(io.BytesIO(exported.body)) as archive:
                for path, raw in resources.items():
                    self.assertEqual(archive.read(f'skill-{skill.id}/{path}'), raw, path)
                self.assertIn(f'skill-{skill.id}/empty/', archive.namelist())
            release = asyncio.run(main.release_skill(skill.id, SkillReleaseCreate(version='2.0'), self.db, CurrentUser(7)))
            with ZipFile(release.file_path) as archive:
                for path, raw in resources.items():
                    self.assertEqual(archive.read(f'skill-{skill.id}/{path}'), raw, path)
            font_path = Path(get_skill_dir(skill.id)) / 'assets/simhei.ttf'
            font_path.write_bytes(b'changed')
            main.restore_skill_release(skill.id, release.id, self.db, CurrentUser(7))
            for path, raw in resources.items():
                self.assertEqual((Path(get_skill_dir(skill.id)) / path).read_bytes(), raw, path)
            with self.assertRaises(HTTPException):
                main.export_skill(skill.id, self.db, CurrentUser(999))


if __name__ == '__main__':
    unittest.main()
