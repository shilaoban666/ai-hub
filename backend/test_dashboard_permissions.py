import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard_routes
from auth import CurrentUser, get_current_active_user


class DashboardPermissionTests(unittest.TestCase):
    def test_summary_detail_requires_superuser_even_when_numeric_ids_match(self):
        app = FastAPI()
        app.include_router(dashboard_routes.router)
        user = CurrentUser(user_id=7)
        app.dependency_overrides[get_current_active_user] = lambda: user
        with TestClient(app) as client, patch.object(
            dashboard_routes, '_build_user_token_usage_payload', return_value={}
        ) as build:
            self.assertEqual(client.get('/api/dashboard/summary/token-usage/users/7').status_code, 403)
            build.assert_not_called()
            user = CurrentUser(user_id=7, is_superuser=True)
            self.assertEqual(client.get('/api/dashboard/summary/token-usage/users/8').status_code, 200)
            self.assertEqual(build.call_args.args[0], 8)


if __name__ == '__main__':
    unittest.main()
