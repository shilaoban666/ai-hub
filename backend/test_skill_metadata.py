import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth import CurrentUser
from models import Skill, SkillCollaborator
from skill_metadata import (
    apply_skill_metadata_filters, get_public_skill_metadata_options,
    get_skill_metadata_options, parse_metadata_tags,
)


class SkillMetadataTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Skill.__table__.create(engine)
        SkillCollaborator.__table__.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

    def test_options_include_owned_shared_and_public_but_not_private_or_deleted(self):
        for skill_id, owner, public, deleted, module, roles in (
            (1, 7, False, False, "订单，物流", "运营, 采购"),
            (2, 8, False, False, "协作模块", "协作角色"),
            (3, 9, True, False, "数据分析;物流", "分析师；运营"),
            (4, 9, False, False, "私有模块", "私有角色"),
            (5, 7, True, True, "已删除模块", "已删除角色"),
        ):
            self.db.add(Skill(
                id=skill_id, user_id=owner, name=str(skill_id), version="1.0.0",
                is_public=public, is_deleted=deleted, module=module, roles=roles,
            ))
        self.db.add(SkillCollaborator(skill_id=2, user_id=7, username="editor", created_by=8))
        self.db.commit()
        for user in (CurrentUser(user_id=7), CurrentUser(user_id=7, is_superuser=True)):
            with self.subTest(superuser=user.is_superuser):
                result = get_skill_metadata_options(db=self.db, current_user=user)
                self.assertEqual(set(result["modules"]), {"全局", "订单", "物流", "协作模块", "数据分析"})
                self.assertEqual(set(result["roles"]), {"通用", "运营", "采购", "协作角色", "分析师"})
                self.assertEqual(result["modules"].count("物流"), 1)

    def test_empty_catalog_still_offers_existing_defaults(self):
        self.assertEqual(
            get_skill_metadata_options(db=self.db, current_user=CurrentUser(user_id=7)),
            {"modules": ["全局"], "roles": ["通用"]},
        )

    def test_saved_custom_values_become_reusable_options(self):
        skill = Skill(id=1, user_id=7, name="test", version="1.0.0", module="新品研发", roles="测试工程师")
        self.db.add(skill)
        self.db.commit()
        result = get_skill_metadata_options(db=self.db, current_user=CurrentUser(user_id=7))
        self.assertIn("新品研发", result["modules"])
        self.assertIn("测试工程师", result["roles"])
        skill.module = ""
        self.db.commit()
        self.assertNotIn("新品研发", get_skill_metadata_options(db=self.db, current_user=CurrentUser(user_id=7))["modules"])

    def test_legacy_separators_spaces_and_duplicates(self):
        self.assertEqual(parse_metadata_tags("  订单,物流，订单;客服；研发\n数据\r\n  "), ["订单", "物流", "客服", "研发", "数据"])
        self.assertEqual(parse_metadata_tags(None), [])
        self.assertEqual(parse_metadata_tags("产品 设计"), ["产品 设计"])

    def test_exact_filters_with_legacy_separators_and_literal_regex_characters(self):
        for index, (module, roles) in enumerate([
            ("订单， 物流 ; C++\n产品 设计", "运营；采购"),
            ("订单管理,物流", "运营主管"),
            ("订单", "运营"),
            ("a.b,(x),[y],C++", "采购"),
            (None, None),
        ], 1):
            self.db.add(Skill(id=index, user_id=7, name=str(index), version="1.0.0", module=module, roles=roles))
        self.db.commit()
        query = self.db.query(Skill)
        for module, role, expected in [
            ("订单", "运营", {1, 3}), ("物流", "运营", {1}),
            ("", "运营", {1, 3}), ("C++", "", {1, 4}),
            ("a.b", "", {4}), ("(x)", "", {4}), ("[y]", "", {4}),
            ("产品 设计", "", {1}), ("不存在", "", set()),
        ]:
            with self.subTest(module=module, role=role):
                filtered = apply_skill_metadata_filters(query, module, role)
                self.assertEqual({s.id for s in filtered.all()}, expected)
                self.assertEqual(filtered.count(), len(expected))
        filtered = apply_skill_metadata_filters(query, "订单", "运营")
        self.assertEqual([s.id for s in filtered.order_by(Skill.id).offset(1).limit(1)], [3])

    def test_public_options_exclude_private_and_deleted_tags(self):
        self.db.add_all([
            Skill(id=1, user_id=7, name="public", version="1.0.0", is_public=True, module="公开模块", roles="公开角色"),
            Skill(id=2, user_id=7, name="private", version="1.0.0", is_public=False, module="私有模块", roles="私有角色"),
            Skill(id=3, user_id=7, name="deleted", version="1.0.0", is_public=True, is_deleted=True, module="删除模块", roles="删除角色"),
        ])
        self.db.commit()
        result = get_public_skill_metadata_options(db=self.db)
        self.assertEqual(set(result["modules"]), {"全局", "公开模块"})
        self.assertEqual(set(result["roles"]), {"通用", "公开角色"})


if __name__ == "__main__":
    unittest.main()
