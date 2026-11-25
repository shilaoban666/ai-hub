import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
import skill_utils
from auth import CurrentUser
from skill_access import (
    get_manageable_skill_or_404,
    get_owned_skill_or_404,
    skill_access_filter,
)


class SkillCollaborationAccessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Skill.__table__.create(self.engine)
        models.SkillCollaborator.__table__.create(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.skill = models.Skill(
            user_id=10,
            name="Shared skill",
            version="1.0.0",
            is_deleted=False,
            is_public=False,
        )
        self.db.add(self.skill)
        self.db.commit()
        self.db.refresh(self.skill)
        self.db.add(models.SkillCollaborator(
            skill_id=self.skill.id,
            user_id=20,
            username="editor",
            created_by=10,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_list_filter_includes_owner_and_collaborator(self):
        owner_skills = self.db.query(models.Skill).filter(skill_access_filter(10)).all()
        collaborator_skills = self.db.query(models.Skill).filter(skill_access_filter(20)).all()
        outsider_skills = self.db.query(models.Skill).filter(skill_access_filter(30)).all()

        self.assertEqual([self.skill.id], [skill.id for skill in owner_skills])
        self.assertEqual([self.skill.id], [skill.id for skill in collaborator_skills])
        self.assertEqual([], outsider_skills)

    def test_collaborator_can_manage_but_cannot_delete(self):
        collaborator = CurrentUser(user_id=20)
        manageable = get_manageable_skill_or_404(self.db, self.skill.id, collaborator)
        self.assertEqual(self.skill.id, manageable.id)

        with self.assertRaises(HTTPException) as context:
            get_owned_skill_or_404(self.db, self.skill.id, collaborator)
        self.assertEqual(404, context.exception.status_code)


class SkillFileValidationTests(unittest.TestCase):
    def test_binary_renames_preserve_bytes_and_unsafe_references_leave_files_intact(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(skill_utils, 'SKILLS_DIR', temp_dir):
            raw = bytes(range(256))
            skill_utils.save_skill_files(1, [
                {'label': 'font.ttf', 'type': 'file', 'content': '', 'raw_content': raw},
            ])
            tree = skill_utils.load_skill_files(1)
            tree[0]['label'] = 'renamed.ttf'
            skill_utils.save_skill_files(1, tree)
            with open(os.path.join(temp_dir, '1', 'renamed.ttf'), 'rb') as handle:
                self.assertEqual(handle.read(), raw)
            tree = skill_utils.load_skill_files(1)
            for source in ('../outside.ttf', '/outside.ttf', 'missing.ttf'):
                tree[0]['original_path'] = source
                with self.assertRaises(ValueError):
                    skill_utils.save_skill_files(1, tree)
                with open(os.path.join(temp_dir, '1', 'renamed.ttf'), 'rb') as handle:
                    self.assertEqual(handle.read(), raw)

    def test_invalid_tree_does_not_remove_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(skill_utils, "SKILLS_DIR", temp_dir):
                skill_utils.save_skill_files(1, [{
                    "label": "SKILL.md",
                    "type": "file",
                    "content": "original",
                }])

                with self.assertRaises(skill_utils.PathTraversalError):
                    skill_utils.save_skill_files(1, [{
                        "label": "..",
                        "type": "file",
                        "content": "invalid",
                    }])

                skill_path = os.path.join(temp_dir, "1", "SKILL.md")
                with open(skill_path, "r", encoding="utf-8") as existing_file:
                    self.assertEqual("original", existing_file.read())


if __name__ == "__main__":
    unittest.main()
