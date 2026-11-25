import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from fastapi import HTTPException

from sqlalchemy import Integer, create_engine, event
from sqlalchemy.orm import sessionmaker

from asset_routes import list_catalog_skill_releases, list_skill_catalog
from auth import CurrentUser
from models import AssetSecurityEvent, Skill, SkillCollaborator, SkillInstallation, SkillRelease, SystemSkillInstallation


class SkillCatalogTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for model in (Skill, SkillCollaborator, SkillRelease, SkillInstallation, SystemSkillInstallation, AssetSecurityEvent):
            if model is AssetSecurityEvent:
                model.__table__.c.id.type = Integer()
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        staff_user = CurrentUser(user_id=7)
        staff_user.is_staff = True
        self.users = [
            CurrentUser(user_id=7),
            CurrentUser(user_id=7, is_superuser=True),
            staff_user,
            CurrentUser(user_id=7, permissions=["aihub:assets:review"]),
        ]
        for skill_id, owner, public, deleted in (
            (1, 7, False, False),
            (2, 7, True, False),
            (3, 8, True, False),
            (4, 8, False, False),
            (5, 8, True, True),
            (6, 8, False, False),
        ):
            self.db.add(Skill(
                id=skill_id, user_id=owner, name=f"Skill {skill_id}",
                version="1.0.0", is_public=public, is_deleted=deleted,
            ))
            self.db.add(SkillRelease(
                id=skill_id, skill_id=skill_id, version="1.0.0",
                file_path="release.zip", file_url="/releases/release.zip",
                status="published", scan_status="passed",
            ))
        self.db.add(SystemSkillInstallation(
            id=1, skill_id=6, release_id=6, created_by=9, status="active",
        ))
        self.db.commit()
        self.archive_exists = patch("asset_routes.os.path.isfile", return_value=True)
        self.archive_exists.start()

    def tearDown(self):
        self.archive_exists.stop()
        self.db.close()
        self.engine.dispose()

    def test_enterprise_alias_includes_owned_and_other_public_skills_for_every_role(self):
        for user in self.users:
            with self.subTest(user=user):
                result = list_skill_catalog(source="enterprise", db=self.db, current_user=user)
                self.assertEqual(result["total"], 2)
                self.assertEqual(
                    {item["skill_id"]: item["source"] for item in result["items"]},
                    {2: "mine", 3: "enterprise"},
                )

    def test_all_sources_excludes_others_private_skills_even_with_legacy_global_install(self):
        for user in self.users:
            with self.subTest(user=user):
                result = list_skill_catalog(db=self.db, current_user=user)
                self.assertEqual(result["total"], 3)
                self.assertEqual(
                    {item["skill_id"]: item["source"] for item in result["items"]},
                    {1: "mine", 2: "mine", 3: "enterprise"},
                )

    def test_catalog_exposes_current_examples_without_changing_releases(self):
        skill = self.db.get(Skill, 3)
        skill.conversation_examples = ['xxx品销量怎么样？', '帮我查看本周任务']
        self.db.commit()
        result = list_skill_catalog(db=self.db, current_user=self.users[0])
        item = next(item for item in result['items'] if item['skill_id'] == 3)
        self.assertEqual(item['conversation_examples'], skill.conversation_examples)
        self.assertEqual(item['latest_release']['id'], 3)
        skill.conversation_examples = None
        self.db.commit()
        result = list_skill_catalog(db=self.db, current_user=self.users[0])
        item = next(item for item in result['items'] if item['skill_id'] == 3)
        self.assertEqual(item['conversation_examples'], [])

    def test_private_skills_are_only_available_to_owner(self):
        for source, expected in (("mine", {1, 2}), ("system_default", set())):
            result = list_skill_catalog(source=source, db=self.db, current_user=self.users[0])
            self.assertEqual({item["skill_id"] for item in result["items"]}, expected)

    def test_search_cannot_expose_private_skills_to_reviewer(self):
        result = list_skill_catalog(q="Skill 4", db=self.db, current_user=self.users[-1])
        self.assertEqual(result, {"total": 0, "items": []})

    def test_global_installation_preserves_origin_and_source_filters(self):
        self.db.get(Skill, 1).is_public = True
        self.db.add_all([
            SystemSkillInstallation(id=2, skill_id=1, release_id=1, created_by=9, status="active"),
            SystemSkillInstallation(id=3, skill_id=3, release_id=3, created_by=9, status="active"),
        ])
        self.db.commit()
        for user in self.users:
            with self.subTest(user=user):
                for source, expected in (
                    ("mine", {1, 2}),
                    ("enterprise", {1, 2, 3}),
                    ("system_default", {1, 3}),
                ):
                    result = list_skill_catalog(source=source, db=self.db, current_user=user)
                    self.assertEqual({item["skill_id"] for item in result["items"]}, expected)
                    for item in result["items"]:
                        self.assertEqual(item["source"], "mine" if item["owner_user_id"] == user.user_id else "enterprise")
                        if item["skill_id"] in {1, 3}:
                            self.assertIsNotNone(item["system_installation"])

    def test_public_system_default_release_remains_available(self):
        self.db.get(Skill, 6).is_public = True
        self.db.commit()
        result = list_catalog_skill_releases(6, db=self.db, current_user=self.users[0])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], 6)

    def test_system_catalog_only_shows_public_skills_even_for_the_owner(self):
        for user in self.users[1:]:
            with self.subTest(user=user):
                result = list_skill_catalog(system_mode=True, db=self.db, current_user=user)
                self.assertEqual({item["skill_id"] for item in result["items"]}, {2, 3})
                owned = list_skill_catalog(source="mine", system_mode=True, db=self.db, current_user=user)
                self.assertEqual({item["skill_id"] for item in owned["items"]}, {2})

    def test_system_catalog_requires_admin_permission(self):
        with self.assertRaises(HTTPException) as error:
            list_skill_catalog(system_mode=True, db=self.db, current_user=self.users[0])
        self.assertEqual(error.exception.status_code, 403)

    def test_metadata_filters_combine_with_source_and_search_and_return_card_tags(self):
        for skill_id in (1, 2, 3, 4, 5):
            skill = self.db.get(Skill, skill_id)
            skill.module = "订单，物流"
            skill.roles = "运营,采购" if skill_id != 3 else "运营主管"
        self.db.commit()
        result = list_skill_catalog(module="物流", role="运营", db=self.db, current_user=self.users[0])
        self.assertEqual({item["skill_id"] for item in result["items"]}, {1, 2})
        for item in result["items"]:
            self.assertEqual(item["module"], "订单，物流")
            self.assertEqual(item["roles"], "运营,采购")
        result = list_skill_catalog(module="物流", role="运营", source="public", q="Skill 2", db=self.db, current_user=self.users[0])
        self.assertEqual([item["skill_id"] for item in result["items"]], [2])
        result = list_skill_catalog(module="物流", role="运营", source="public", q="Skill 4", db=self.db, current_user=self.users[-1])
        self.assertEqual(result["total"], 0)

    def test_collaboration_includes_only_non_owned_skills_shared_with_current_user(self):
        for skill_id, user_id in ((1, 7), (3, 7), (4, 7), (5, 7), (6, 42)):
            self.db.add(SkillCollaborator(skill_id=skill_id, user_id=user_id, username='collaborator', created_by=8))
        self.db.commit()
        for user in self.users:
            with self.subTest(user=user):
                result = list_skill_catalog(source='collaboration', db=self.db, current_user=user)
                self.assertEqual({item['skill_id'] for item in result['items']}, {3, 4})
                self.assertTrue(all(item['is_collaborator'] and not item['is_mine'] for item in result['items']))
                self.assertTrue(all(item['latest_release']['installable'] for item in result['items']))
                result = list_skill_catalog(db=self.db, current_user=user)
                self.assertEqual({item['skill_id'] for item in result['items']}, {1, 2, 3, 4})
        self.db.get(Skill, 4).module = '订单'
        self.db.get(Skill, 4).roles = '运营'
        self.db.commit()
        result = list_skill_catalog(source='collaboration', q='Skill 4', module='订单', role='运营', db=self.db, current_user=self.users[0])
        self.assertEqual([item['skill_id'] for item in result['items']], [4])
        result = list_skill_catalog(source='mine', db=self.db, current_user=self.users[0])
        self.assertEqual({item['skill_id'] for item in result['items']}, {1, 2})
        result = list_skill_catalog(source='collaboration', system_mode=True, db=self.db, current_user=self.users[1])
        self.assertEqual({item['skill_id'] for item in result['items']}, {3})
        self.db.query(SkillCollaborator).filter(SkillCollaborator.skill_id == 4).delete()
        self.db.commit()
        with self.assertRaises(HTTPException):
            list_catalog_skill_releases(4, db=self.db, current_user=self.users[0])

    def test_pagination_filters_before_count_and_does_not_scan_off_page_archives(self):
        for skill_id in range(10, 50):
            self.db.add(Skill(id=skill_id, user_id=7, name=f'Paged {skill_id}', version='1', is_public=True))
            self.db.add(SkillRelease(skill_id=skill_id, version='1', status='published',
                                     file_path='release.zip', file_url='/releases/release.zip'))
        self.db.add(Skill(id=60, user_id=7, name='Paged no release', version='1'))
        self.db.commit()
        statements = []
        def record(_connection, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith('SELECT'):
                statements.append(statement)
        event.listen(self.engine, 'before_cursor_execute', record)
        try:
            with patch('asset_routes._catalog_release_access', return_value=(True, None)) as access:
                first = list_skill_catalog(q='Paged', limit=2, db=self.db, current_user=self.users[0])
                self.assertEqual(first['total'], 41)
                self.assertEqual(len(first['items']), 2)
                self.assertEqual(access.call_count, 1)
            small_page_query_count = len(statements)
            statements.clear()
            second = list_skill_catalog(q='Paged', skip=2, limit=16, db=self.db, current_user=self.users[0])
            self.assertEqual(second['total'], 41)
            self.assertEqual(len(second['items']), 16)
            self.assertEqual(len(statements), small_page_query_count)
            self.assertLessEqual(len(statements), 8)
            self.assertFalse({item['skill_id'] for item in first['items']} & {item['skill_id'] for item in second['items']})
            statements.clear()
            one = list_catalog_skill_releases(10, db=self.db, current_user=self.users[0])
            self.assertEqual(one['total'], 1)
            self.assertLessEqual(len(statements), 8)
        finally:
            event.remove(self.engine, 'before_cursor_execute', record)

    def test_installed_filter_and_system_mode_use_correct_scope(self):
        self.db.add(SkillInstallation(id=1, user_id=7, workspace_id=7, scope_agent_id=0,
                                      skill_id=1, release_id=1, status='active'))
        self.db.add(SystemSkillInstallation(id=2, skill_id=3, release_id=3, created_by=9, status='active'))
        self.db.commit()
        first = list_skill_catalog(installed_only=True, limit=1, db=self.db, current_user=self.users[0])
        second = list_skill_catalog(installed_only=True, skip=1, limit=1, db=self.db, current_user=self.users[0])
        self.assertEqual(first['total'], 2)
        self.assertEqual({item['skill_id'] for item in first['items'] + second['items']}, {1, 3})
        system = list_skill_catalog(installed_only=True, system_mode=True, db=self.db, current_user=self.users[1])
        self.assertEqual(system['total'], 1)
        self.assertEqual(system['items'][0]['skill_id'], 3)

    def test_missing_archive_is_disabled_without_corrupting_pagination(self):
        with patch('asset_routes.os.path.isfile', return_value=False):
            result = list_skill_catalog(limit=2, db=self.db, current_user=self.users[0])
        self.assertEqual(result['total'], 3)
        self.assertEqual(len(result['items']), 2)
        for item in result['items']:
            self.assertFalse(item['latest_release']['installable'])
            self.assertEqual(item['latest_release']['unavailable_reason'], '版本发布文件缺失')

    def test_page_size_is_bounded_and_out_of_range_page_retains_total(self):
        for parameters in ({'skip': -1}, {'limit': 0}, {'limit': 101}):
            with self.assertRaises(HTTPException) as error:
                list_skill_catalog(db=self.db, current_user=self.users[0], **parameters)
            self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(HTTPException) as error:
            list_skill_catalog(sort_by='unknown', db=self.db, current_user=self.users[0])
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(list_skill_catalog(skip=100, db=self.db, current_user=self.users[0]), {'total': 3, 'items': []})

    def test_catalog_supports_creation_download_and_install_sorting(self):
        for skill_id, created_at, install_count in (
            (1, datetime(2026, 1, 3, tzinfo=timezone.utc), 1),
            (2, datetime(2026, 1, 2, tzinfo=timezone.utc), 5),
            (3, datetime(2026, 1, 1, tzinfo=timezone.utc), 10),
        ):
            skill = self.db.get(Skill, skill_id)
            skill.created_at = created_at
            skill.install_count = install_count
        self.db.add_all([
            AssetSecurityEvent(asset_type='skill', asset_id=2, action='downloaded', actor_user_id=7),
            AssetSecurityEvent(asset_type='skill', asset_id=2, action='downloaded', actor_user_id=8),
            AssetSecurityEvent(asset_type='skill', asset_id=2, action='downloaded', actor_user_id=9),
            AssetSecurityEvent(asset_type='skill', asset_id=3, action='downloaded', actor_user_id=7),
            AssetSecurityEvent(asset_type='skill', asset_id=3, action='downloaded', actor_user_id=8),
            AssetSecurityEvent(asset_type='skill', asset_id=1, action='downloaded', actor_user_id=7),
        ])
        self.db.commit()

        def ids(sort_by):
            return [item['skill_id'] for item in list_skill_catalog(
                sort_by=sort_by, db=self.db, current_user=self.users[0],
            )['items']]

        self.assertEqual(ids('created_at'), [1, 2, 3])
        self.assertEqual(ids('download_count'), [2, 3, 1])
        self.assertEqual(ids('install_count'), [3, 2, 1])


if __name__ == "__main__":
    unittest.main()
