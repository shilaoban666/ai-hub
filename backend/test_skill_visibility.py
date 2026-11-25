import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
import schemas
from auth import CurrentUser

# Import the real handlers without connecting to the configured application database.
with patch("sqlalchemy.schema.MetaData.create_all"):
    import main


class SkillVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for model in (models.Skill, models.SkillRelease, models.SkillCollaborator, models.SystemSkillInstallation):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user = CurrentUser(user_id=7)
        self.db.add(models.Skill(id=1, user_id=7, name="Sample", version="1.0", is_public=False))
        self.db.commit()

    def add_release(self, status="published", skill_id=1):
        release = models.SkillRelease(
            skill_id=skill_id, version="1.0", status=status,
            scan_status="passed" if status == "published" else "failed",
            reviewed_at=datetime.now() if status == "rejected" else None,
            file_path="release.zip", file_url="/releases/release.zip",
        )
        self.db.add(release)
        self.db.commit()
        return release

    def test_new_skill_cannot_be_created_public(self):
        with self.assertRaises(HTTPException) as error:
            main.create_skill(schemas.SkillCreate(name="New", version="1.0", is_public=True), db=self.db, current_user=self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.query(models.Skill).count(), 1)

    def test_new_private_skill_can_be_created(self):
        skill = main.create_skill(schemas.SkillCreate(name="New", version="1.0"), db=self.db, current_user=self.user)
        self.assertFalse(skill.is_public)

    def test_publication_without_release_rejected_through_both_endpoints(self):
        for operation in (
            lambda: main.toggle_skill_visibility(1, db=self.db, current_user=self.user),
            lambda: main.update_skill(1, schemas.SkillUpdate(is_public=True, name="Changed"), db=self.db, current_user=self.user),
        ):
            with self.assertRaises(HTTPException) as error:
                operation()
            self.assertEqual(error.exception.status_code, 409)
            self.assertIn("发布至少一个", error.exception.detail)
            self.db.rollback()
            self.assertFalse(self.db.get(models.Skill, 1).is_public)
            self.assertEqual(self.db.get(models.Skill, 1).name, "Sample")

    def test_rejected_pending_and_revoked_releases_do_not_allow_publication(self):
        for status in ("rejected", "pending_review", "revoked"):
            with self.subTest(status=status):
                self.db.query(models.SkillRelease).delete()
                self.add_release(status=status)
                with self.assertRaises(HTTPException):
                    main.toggle_skill_visibility(1, db=self.db, current_user=self.user)
                self.db.rollback()
                self.assertFalse(self.db.get(models.Skill, 1).is_public)

    def test_another_skills_release_does_not_allow_publication(self):
        self.db.add(models.Skill(id=2, user_id=7, name="Other", version="1.0"))
        self.add_release(skill_id=2)
        with self.assertRaises(HTTPException):
            main.toggle_skill_visibility(1, db=self.db, current_user=self.user)
        self.db.rollback()
        self.assertFalse(self.db.get(models.Skill, 1).is_public)

    def test_published_release_allows_both_publication_endpoints(self):
        self.add_release()
        self.assertEqual(main.toggle_skill_visibility(1, db=self.db, current_user=self.user), {"is_public": True})
        self.assertEqual(main.toggle_skill_visibility(1, db=self.db, current_user=self.user), {"is_public": False})
        skill = main.update_skill(1, schemas.SkillUpdate(is_public=True), db=self.db, current_user=self.user)
        self.assertTrue(skill.is_public)

    def test_global_installation_must_be_removed_before_making_skill_private(self):
        release = self.add_release()
        main.toggle_skill_visibility(1, db=self.db, current_user=self.user)
        self.db.add(models.SystemSkillInstallation(id=1, skill_id=1, release_id=release.id, created_by=9, status="active"))
        self.db.commit()
        for operation in (
            lambda: main.toggle_skill_visibility(1, db=self.db, current_user=self.user),
            lambda: main.update_skill(1, schemas.SkillUpdate(is_public=False), db=self.db, current_user=self.user),
        ):
            with self.assertRaises(HTTPException) as error:
                operation()
            self.assertEqual(error.exception.status_code, 409)
            self.assertIn("先全局卸载", error.exception.detail)
            self.db.rollback()
            self.assertTrue(self.db.get(models.Skill, 1).is_public)
        self.db.get(models.SystemSkillInstallation, 1).status = "uninstalled"
        self.db.commit()
        self.assertEqual(main.toggle_skill_visibility(1, db=self.db, current_user=self.user), {"is_public": False})

    def test_regular_edits_remain_available_before_first_release(self):
        skill = main.update_skill(1, schemas.SkillUpdate(name="Changed"), db=self.db, current_user=self.user)
        self.assertEqual(skill.name, "Changed")
        self.assertFalse(skill.is_public)

    def test_visibility_change_still_checks_skill_access(self):
        self.add_release()
        with self.assertRaises(HTTPException) as error:
            main.toggle_skill_visibility(1, db=self.db, current_user=CurrentUser(user_id=8))
        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
