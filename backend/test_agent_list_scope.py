import unittest
from unittest.mock import MagicMock

from sqlalchemy.dialects import sqlite

from agent_routes import list_agents
from auth import CurrentUser


class AgentListScopeTests(unittest.TestCase):
    def test_expert_list_excludes_personal_default_agent(self):
        query = MagicMock()
        query.options.return_value = query
        query.filter.return_value = query
        query.count.return_value = 0
        query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        db = MagicMock()
        db.query.return_value = query

        result = list_agents(
            skip=0,
            limit=20,
            search=None,
            db=db,
            current_user=CurrentUser(user_id=7),
        )

        filters = query.filter.call_args.args
        compiled = [
            str(expression.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
            for expression in filters
        ]
        self.assertIn("agents.kind = 'expert'", compiled)
        self.assertEqual(0, result.total)
        self.assertEqual([], result.items)


if __name__ == "__main__":
    unittest.main()
