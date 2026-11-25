import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from asset_routes import (
    _can_manage_mcp_definition,
    create_system_prompt,
    list_workspace_prompts,
    list_system_prompts,
    import_prompt_snapshot,
    remove_workspace_prompt,
)
from asset_schemas import PromptImportRequest, SystemPromptCreateRequest
from auth import CurrentUser
from fastapi import HTTPException
from main import delete_prompt_template, get_prompt_template, get_prompt_templates, get_usable_prompt_templates, get_public_prompt_template
from models import Base, PromptTemplate, WorkspacePromptRemoval, WorkspacePromptReference


class SystemResourcePermissionTests(unittest.TestCase):
    def test_owner_can_manage_personal_mcp_definition(self):
        definition = SimpleNamespace(owner_user_id=7, scope="user")

        self.assertTrue(_can_manage_mcp_definition(definition, CurrentUser(user_id=7)))

    def test_regular_user_cannot_manage_system_mcp_definition(self):
        definition = SimpleNamespace(owner_user_id=8, scope="system")

        self.assertFalse(_can_manage_mcp_definition(definition, CurrentUser(user_id=7)))

    def test_system_mcp_creator_cannot_manage_it_after_losing_permission(self):
        definition = SimpleNamespace(owner_user_id=7, scope="system")

        self.assertFalse(_can_manage_mcp_definition(definition, CurrentUser(user_id=7)))

    def test_reviewer_can_manage_system_mcp_definition(self):
        definition = SimpleNamespace(owner_user_id=8, scope="system")
        reviewer = CurrentUser(user_id=7, permissions=["aihub:assets:review"])

        self.assertTrue(_can_manage_mcp_definition(definition, reviewer))

    def test_reviewer_cannot_manage_another_users_private_definition(self):
        definition = SimpleNamespace(owner_user_id=8, scope="user")
        reviewer = CurrentUser(user_id=7, permissions=["aihub:assets:review"])

        self.assertFalse(_can_manage_mcp_definition(definition, reviewer))

    def test_reviewer_cannot_manage_another_users_marketplace_definition(self):
        definition = SimpleNamespace(owner_user_id=8, scope="public")
        reviewer = CurrentUser(user_id=7, permissions=["aihub:assets:review"])

        self.assertFalse(_can_manage_mcp_definition(definition, reviewer))

    def test_system_prompt_schema_does_not_expose_visibility(self):
        prompt = SystemPromptCreateRequest(
            name="默认摘要",
            content="请总结以下内容",
        )

        self.assertNotIn("is_public", prompt.model_dump())
        self.assertNotIn("is_system", prompt.model_dump())


class SystemPromptPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[PromptTemplate.__table__, WorkspacePromptRemoval.__table__, WorkspacePromptReference.__table__],
        )
        self.db = sessionmaker(bind=self.engine)()
        self.reviewer = CurrentUser(user_id=7, permissions=["aihub:assets:review"])
        self.reviewer.username = "admin"

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_custom_agent_identity_only_offers_own_and_public_non_system_templates(self):
        self.db.add_all([
            PromptTemplate(id=1, user_id=7, name="我的模板", content="mine"),
            PromptTemplate(id=2, user_id=8, name="公开模板", content="public", is_public=True),
            PromptTemplate(id=3, user_id=8, name="系统公开模板", content="system", is_system=True, is_public=True),
            PromptTemplate(id=4, user_id=7, name="自己创建的系统模板", content="system", is_system=True),
            PromptTemplate(id=5, user_id=8, name="他人私有模板", content="private"),
            PromptTemplate(id=6, user_id=7, name="已删除模板", content="deleted", is_deleted=True),
        ])
        self.db.commit()
        user = CurrentUser(user_id=7)
        result = get_usable_prompt_templates(include_system=False, db=self.db, current_user=user)
        self.assertEqual(2, result["total"])
        self.assertEqual({1, 2}, {item.id for item in result["items"]})
        page = get_usable_prompt_templates(include_system=False, limit=1, db=self.db, current_user=user)
        self.assertEqual(2, page["total"])
        self.assertEqual(1, len(page["items"]))
        default = get_usable_prompt_templates(db=self.db, current_user=user)
        self.assertEqual({1, 2, 3, 4}, {item.id for item in default["items"]})

    def test_workspace_removal_preserves_management_public_access_and_other_users(self):
        owner = CurrentUser(user_id=7)
        self.db.add(PromptTemplate(id=1, user_id=7, name="shared", content="original", is_public=True))
        self.db.commit()
        for _ in range(2):
            remove_workspace_prompt(1, db=self.db, current_user=owner)
        self.assertEqual(1, self.db.query(WorkspacePromptRemoval).count())
        self.assertEqual(0, list_workspace_prompts(db=self.db, current_user=owner)["total"])
        self.assertEqual(0, get_usable_prompt_templates(db=self.db, current_user=owner)["total"])
        self.assertEqual(1, get_prompt_templates(db=self.db, current_user=owner)["total"])
        self.assertEqual("original", get_prompt_template(1, db=self.db, current_user=owner).content)
        self.assertEqual("original", get_public_prompt_template(1, db=self.db).content)
        self.assertEqual(1, get_usable_prompt_templates(db=self.db, current_user=CurrentUser(user_id=8))["total"])
        self.assertFalse(self.db.get(PromptTemplate, 1).is_deleted)

    def test_readding_removed_template_restores_it_without_creating_a_duplicate(self):
        owner = CurrentUser(user_id=7)
        self.db.add(PromptTemplate(id=1, user_id=7, name="mine", content="original"))
        self.db.commit()
        remove_workspace_prompt(1, db=self.db, current_user=owner)
        restored = import_prompt_snapshot(PromptImportRequest(source_template_id=1), db=self.db, current_user=owner)
        self.assertEqual(1, restored["id"])
        self.assertEqual(1, self.db.query(PromptTemplate).count())
        self.assertEqual(0, self.db.query(WorkspacePromptRemoval).count())
        self.assertEqual(1, list_workspace_prompts(db=self.db, current_user=owner)["total"])
        self.assertEqual(1, get_usable_prompt_templates(db=self.db, current_user=owner)["total"])

    def test_removing_imported_reference_preserves_source_without_creating_personal_templates(self):
        owner = CurrentUser(user_id=7)
        self.db.add(PromptTemplate(id=1, user_id=8, name="public", content="original", is_public=True))
        self.db.commit()
        copied = import_prompt_snapshot(PromptImportRequest(source_template_id=1), db=self.db, current_user=owner)
        self.assertEqual(1, copied["id"])
        self.assertEqual(1, self.db.query(PromptTemplate).count())
        self.assertEqual(1, self.db.query(WorkspacePromptReference).count())
        self.assertEqual(0, get_prompt_templates(db=self.db, current_user=owner)["total"])
        remove_workspace_prompt(copied["id"], db=self.db, current_user=owner)
        self.assertFalse(self.db.get(PromptTemplate, 1).is_deleted)
        self.assertFalse(self.db.get(PromptTemplate, copied["id"]).is_deleted)
        self.assertEqual(0, list_workspace_prompts(db=self.db, current_user=owner)["total"])
        self.assertEqual(0, get_prompt_templates(db=self.db, current_user=owner)["total"])

    def test_workspace_removal_cannot_target_other_users_or_system_prompts(self):
        self.db.add_all([
            PromptTemplate(id=1, user_id=8, name="other", content="original", is_public=True),
            PromptTemplate(id=2, user_id=7, name="system", content="system", is_system=True),
        ])
        self.db.commit()
        for prompt_id in [1, 2, 999]:
            with self.subTest(prompt_id=prompt_id):
                with self.assertRaises(HTTPException) as raised:
                    remove_workspace_prompt(prompt_id, db=self.db, current_user=CurrentUser(user_id=7))
                self.assertEqual(404, raised.exception.status_code)
        self.assertEqual(0, self.db.query(WorkspacePromptRemoval).count())
        self.assertEqual(0, self.db.query(PromptTemplate).filter(PromptTemplate.is_deleted == True).count())

    def test_system_prompt_is_public_but_marketplace_prompt_is_not_system(self):
        self.db.add(PromptTemplate(
            user_id=8,
            name="用户公开模板",
            category="其他",
            content="公开内容",
            author="user",
            is_public=True,
            is_system=False,
        ))
        self.db.commit()

        with patch("asset_routes.audit_asset"):
            created = create_system_prompt(
                SystemPromptCreateRequest(name="系统摘要", content="请总结"),
                db=self.db,
                current_user=self.reviewer,
            )
        result = list_system_prompts(db=self.db, current_user=self.reviewer)

        self.assertTrue(created["is_system"])
        stored = self.db.query(PromptTemplate).filter(PromptTemplate.id == created["id"]).one()
        self.assertTrue(stored.is_public)
        self.assertTrue(stored.is_system)
        self.assertEqual(["系统摘要"], [item["name"] for item in result["items"]])

    def test_workspace_prompts_include_system_and_own_but_not_other_public_prompts(self):
        self.db.add_all([
            PromptTemplate(
                user_id=8,
                name="系统模板",
                category="其他",
                content="系统内容",
                is_public=True,
                is_system=True,
            ),
            PromptTemplate(
                user_id=7,
                name="我的模板",
                category="其他",
                content="个人内容",
                is_public=False,
                is_system=False,
            ),
            PromptTemplate(
                user_id=9,
                name="其他公开模板",
                category="其他",
                content="市场内容",
                is_public=True,
                is_system=False,
            ),
        ])
        self.db.commit()

        result = list_workspace_prompts(db=self.db, current_user=CurrentUser(user_id=7))

        self.assertEqual({"系统模板", "我的模板"}, {item["name"] for item in result["items"]})
        system_item = next(item for item in result["items"] if item["is_system"])
        self.assertEqual("system_default", system_item["source"])

    def test_system_prompt_is_usable_but_not_managed_as_a_personal_prompt(self):
        system_prompt = PromptTemplate(
            user_id=7,
            name="系统写作助手",
            category="写作",
            content="系统内容",
            is_public=True,
            is_system=True,
        )
        personal_prompt = PromptTemplate(
            user_id=7,
            name="我的写作助手",
            category="写作",
            content="个人内容",
            is_public=False,
            is_system=False,
        )
        self.db.add_all([system_prompt, personal_prompt])
        self.db.commit()

        personal = get_prompt_templates(db=self.db, current_user=CurrentUser(user_id=7))
        usable = get_usable_prompt_templates(db=self.db, current_user=CurrentUser(user_id=7))

        self.assertEqual(["我的写作助手"], [item.name for item in personal["items"]])
        self.assertEqual("系统写作助手", usable["items"][0].name)
        self.assertTrue(usable["items"][0].is_system)
        with self.assertRaises(HTTPException) as context:
            delete_prompt_template(
                system_prompt.id,
                db=self.db,
                current_user=CurrentUser(user_id=7),
            )
        self.assertEqual(404, context.exception.status_code)


if __name__ == "__main__":
    unittest.main()
