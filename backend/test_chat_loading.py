"""Read-scope, query volume and bootstrap payload regressions for chat entry."""
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

from agent_routes import _get_agent_or_404, get_agent, list_sessions
from asset_routes import list_available_skills, list_skill_catalog
from auth import CurrentUser
from database import Base
from enterprise_routes import bootstrap_user
from models import Agent, AgentSession, AIModel, PlatformAgentSettings, Skill, SkillRelease, SkillInstallation, SystemSkillInstallation, ExpertSkillBinding


class ChatLoadingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with patch.object(SQLiteTypeCompiler, "visit_BIGINT", return_value="INTEGER"):
            Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.db = self.factory()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user = CurrentUser(user_id=7)
        self.statements = []
        event.listen(self.engine, "before_cursor_execute", self.record)

    def record(self, connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            self.statements.append(statement)

    def reset(self):
        self.db.expunge_all()
        self.statements.clear()

    def add_history(self):
        self.db.add(Agent(id=1, user_id=7, name="Assistant", kind="personal_default", default_agent_user_id=7))
        self.db.add_all([AgentSession(id=i, agent_id=1, user_id=7, is_deleted=i > 990)
                         for i in range(1, 1001)])
        self.db.commit()
        self.reset()

    def test_ownership_check_does_not_load_relationships(self):
        self.add_history()
        agent = _get_agent_or_404(self.db, 1, self.user)
        self.assertEqual(len(self.statements), 1)
        self.assertTrue({"sessions", "skills", "mcps", "models", "runtime_instance"}.issubset(inspect(agent).unloaded))
        self.assertFalse(any(isinstance(item, AgentSession) for item in self.db.identity_map.values()))
        with self.assertRaises(HTTPException) as error:
            _get_agent_or_404(self.db, 1, CurrentUser(user_id=8))
        self.assertEqual(error.exception.status_code, 403)

    def test_session_page_only_fetches_requested_twenty_sessions(self):
        self.add_history()
        result = list_sessions(1, skip=0, limit=20, db=self.db, current_user=self.user)
        self.assertEqual(result.total, 990)
        self.assertEqual(len(result.items), 20)
        self.assertEqual(len(self.statements), 3)  # ownership, count, bounded page
        self.assertFalse(any(" IN (" in sql and "FROM agent_sessions" in sql for sql in self.statements))

    def test_agent_detail_still_contains_requested_bindings(self):
        self.db.add(AIModel(id=1, user_id=7, name="model", provider="anthropic"))
        self.db.add(Skill(id=1, user_id=7, name="skill", version="1", conversation_examples=["整理本周进度"]))
        agent = Agent(id=1, user_id=7, name="Assistant")
        self.db.add(agent)
        self.db.flush()
        agent.models = [self.db.get(AIModel, 1)]
        agent.skills = [self.db.get(Skill, 1)]
        self.db.add_all([
            SkillRelease(id=1, skill_id=1, version="1", status="published", file_path="unused", file_url=""),
            SkillInstallation(id=1, user_id=7, workspace_id=1, scope_agent_id=1,
                              skill_id=1, release_id=1, status="active"),
            ExpertSkillBinding(agent_id=1, installation_id=1),
        ])
        self.db.commit()
        self.reset()
        result = get_agent(1, self.db, self.user)
        self.assertEqual(result.model_ids, [1])
        self.assertEqual(result.skills, [{"id": 1, "name": "skill", "conversation_examples": ["整理本周进度"]}])
        self.assertEqual(result.session_count, 0)
        self.db.get(Skill, 1).conversation_examples = None
        self.db.commit()
        self.assertEqual(get_agent(1, self.db, self.user).skills[0]["conversation_examples"], [])

    def test_available_list_is_two_queries_and_excludes_uninstalled_and_foreign_skills(self):
        for i in range(1, 101):
            self.db.add(Skill(id=i, user_id=7 if i != 3 else 8, name=f"Skill {i}", version="draft", is_public=True,
                              conversation_examples=[f"示例 {i}"] if i != 2 else None))
            self.db.add(SkillRelease(id=i, skill_id=i, version="1.0", status="published", file_path="must-not-be-read.zip", file_url=""))
        self.db.add(SkillRelease(id=101, skill_id=1, version="2.0", status="published", file_path="unused", file_url=""))
        self.db.add_all([
            SkillInstallation(id=1, user_id=7, workspace_id=1, skill_id=1, release_id=1, status="active"),
            SkillInstallation(id=2, user_id=7, workspace_id=1, skill_id=2, release_id=2, status="active"),
            SkillInstallation(id=3, user_id=8, workspace_id=2, skill_id=3, release_id=3, status="active"),
            SkillInstallation(id=4, user_id=7, workspace_id=1, skill_id=4, release_id=4, status="uninstalled"),
            SystemSkillInstallation(id=1, skill_id=1, release_id=101, created_by=9, status="active"),
        ])
        self.db.commit()
        self.reset()
        with patch("asset_routes.resolve_release_file_path", side_effect=AssertionError("must not inspect archives")):
            result = list_available_skills(self.db, self.user)
        self.assertEqual(len(self.statements), 2)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0], {"skill_id": 1, "name": "Skill 1", "release_id": 101, "version": "2.0", "source": "system_default", "conversation_examples": ["示例 1"]})
        self.assertEqual(result["items"][1]["skill_id"], 2)
        self.assertEqual(result["items"][1]["conversation_examples"], [])
        self.assertFalse(any("skills.content" in sql or "skills.files" in sql for sql in self.statements))
        self.db.get(SkillRelease, 101).status = "revoked"
        self.db.get(Skill, 2).is_deleted = True
        self.db.commit()
        result = list_available_skills(self.db, self.user)
        self.assertEqual([item["release_id"] for item in result["items"]], [1])
        self.db.get(Skill, 1).conversation_examples = ["更新后的示例"]
        self.db.commit()
        self.assertEqual(list_available_skills(self.db, self.user)["items"][0]["conversation_examples"], ["更新后的示例"])
        self.db.get(Skill, 1).is_public = False
        self.db.get(SkillRelease, 101).status = "published"
        self.db.commit()
        # A private global skill is excluded; the user's own private installation remains.
        result = list_available_skills(self.db, self.user)
        self.assertEqual([item["release_id"] for item in result["items"]], [1])

    def test_expert_picker_matches_its_installed_market_after_visibility_changes(self):
        self.db.add(Agent(id=99, user_id=7, name="Expert", kind="expert"))
        for skill_id in (1, 2, 3):
            self.db.add(Skill(id=skill_id, user_id=8, name=f"Skill {skill_id}", version="1", is_public=True,
                              conversation_examples=[f"示例 {skill_id}"]))
            self.db.add(SkillRelease(id=skill_id, skill_id=skill_id, version="1", status="published", file_path="unused", file_url=""))
        # Skill 3 is public but has never been installed for this Agent.
        for skill_id in (1, 2):
            self.db.add(SkillInstallation(id=skill_id, user_id=7, scope_agent_id=99,
                                          workspace_id=99, skill_id=skill_id, release_id=skill_id, status="active"))
            self.db.add(ExpertSkillBinding(agent_id=99, installation_id=skill_id))
        self.db.commit()

        def check(expected):
            response = get_agent(99, self.db, self.user)
            market = list_skill_catalog(agent_id=99, installed_only=True, db=self.db, current_user=self.user)
            self.assertEqual(set(response.skill_ids), expected)
            self.assertEqual({s["id"]: s["conversation_examples"] for s in response.skills},
                             {skill_id: [f"示例 {skill_id}"] for skill_id in expected})
            self.assertEqual({s["skill_id"] for s in market["items"]}, expected)

        with patch("asset_routes.os.path.isfile", return_value=True):
            check({1, 2})
            self.db.get(Skill, 1).is_public = False
            self.db.commit()
            check({2})
            self.db.get(Skill, 2).is_deleted = True
            self.db.commit()
            check(set())

    def test_bootstrap_returns_safe_models_and_balance_without_loading_history_entities(self):
        self.add_history()
        self.db.add_all([
            AIModel(id=1, user_id=7, name="new", provider="anthropic", scope="platform", api_key="secret-new"),
            AIModel(id=2, user_id=7, name="old", provider="anthropic", scope="platform", api_key="secret-old"),
            PlatformAgentSettings(id=1, version=1, status="published", default_model_id=1, created_by=9),
        ])
        self.db.get(AgentSession, 1).model_id = 2
        self.db.commit()
        self.reset()
        with patch("enterprise_workspace.configured_sandbox_type", return_value="native"):
            response = bootstrap_user(self.db, self.user)
        self.assertEqual(response.assistant.id, 1)
        self.assertEqual(response.assistant.default_model_id, 1)
        self.assertEqual([item["id"] for item in response.assistant.models], [1, 2])
        self.assertEqual(response.credit.status, "active")
        self.assertNotIn("secret-", response.model_dump_json())
        self.assertFalse(any(isinstance(item, AgentSession) for item in self.db.identity_map.values()))
        self.assertFalse(any(" IN (" in sql and "FROM agent_sessions" in sql for sql in self.statements))
        # Expired eager-loaded collections can be queried and discarded before
        # the identity-map assertion sees them. Guard the actual SQL as well.
        self.assertFalse(any("FROM agent_sessions" in sql for sql in self.statements))
        self.assertLessEqual(len(self.statements), 30)
        self.assertTrue(self.db.expire_on_commit)

        self.reset()
        with patch("enterprise_workspace.configured_sandbox_type", return_value="native"):
            repeated = bootstrap_user(self.db, self.user)
        self.assertEqual(repeated.assistant_id, response.assistant_id)
        self.assertFalse(any("FROM agent_sessions" in sql for sql in self.statements))
        self.assertLessEqual(len(self.statements), 25)
        # Bindings must survive closing the request Session.
        self.db.close()
        with self.factory() as saved:
            agent = saved.query(Agent).filter_by(id=response.assistant_id).one()
            self.assertEqual({model.id for model in agent.models}, {1, 2})

    def test_bootstrap_restores_session_expiration_when_configuration_is_missing(self):
        with self.assertRaises(HTTPException) as error:
            bootstrap_user(self.db, self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertTrue(self.db.expire_on_commit)

    def test_first_visit_binds_one_workspace_and_reuses_it_on_retry(self):
        from enterprise_workspace import bind_agent_workspace
        from models import CreditClaimRecord, UserWorkspace

        self.db.add_all([
            AIModel(id=1, user_id=0, name="platform", provider="anthropic", scope="platform"),
            PlatformAgentSettings(id=1, version=1, status="published", default_model_id=1, created_by=9),
        ])
        self.db.commit()
        with patch("enterprise_workspace.configured_sandbox_type", return_value="native"), \
             patch("enterprise_routes.bind_agent_workspace", wraps=bind_agent_workspace) as bind:
            first = bootstrap_user(self.db, self.user)
            self.assertEqual(bind.call_count, 1)
            repeated = bootstrap_user(self.db, self.user)
            self.assertEqual(bind.call_count, 2)
        self.assertEqual(first.assistant_id, repeated.assistant_id)
        self.db.expire_all()
        agent = self.db.query(Agent).filter_by(id=first.assistant_id).one()
        workspace = self.db.query(UserWorkspace).filter_by(user_id=7, agent_id=None).one()
        self.assertEqual(agent.workspace_id, workspace.id)
        self.assertEqual(self.db.query(CreditClaimRecord).filter_by(user_id=7, claim_type="initial").count(), 1)


if __name__ == "__main__":
    unittest.main()
