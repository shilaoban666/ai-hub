import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import user_management_routes as management
from auth import CurrentUser, get_current_active_user


class UserManagementTests(unittest.TestCase):
    def test_filters_apply_before_pagination_and_preserve_false(self):
        users = [
            {"id": 1, "first_name": "Alice", "is_superuser": True},
            {"id": 2, "first_name": "Bob", "is_superuser": False},
            {"id": 3, "first_name": "Carol", "is_superuser": False},
            {"id": 4, "first_name": ""},
        ]
        departments = {"Alice": {"Sales"}, "Bob": {"Sales", "Support"}, "Carol": {"Sales"}}
        result = management.build_user_page(users, departments, 1, 1, "Sales", False)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0]["id"], 3)
        self.assertEqual(result["department_options"], ["Sales", "Support"])
        self.assertEqual(management.build_user_page(users, departments, 3, 1, None, None)["items"][0]["departments"], [])

    def test_batches_iam_and_reads_departments_once(self):
        requests = []

        def respond(request):
            requests.append(request)
            if request.url.path.endswith("/sql-query/"):
                return httpx.Response(200, json={"code": 200, "data": {
                    "total": 6, "items": [
                        {"staff": "Alice", "department": "Sales"},
                        {"staff": "Alice", "department": "Support"},
                        {"staff": "Alice", "department": "Sales"},
                        {"staff": "Alice", "department": None},
                        {"staff": "Alice", "department": " "},
                        {"staff": "Bob", "department": "Support"},
                    ],
                }})
            offset = int(request.url.params["skip"])
            self.assertEqual(request.url.params["search"], "alice")
            self.assertEqual(request.url.params["is_active"], "true")
            return httpx.Response(200, json={"total": 2, "items": [
                {"id": offset + 1, "first_name": "Alice" if offset == 0 else "Bob"},
            ]})

        real_client = httpx.Client
        with patch.object(management.httpx, "Client", side_effect=lambda **kwargs: real_client(
            **kwargs, transport=httpx.MockTransport(respond),
        )):
            users, departments = management.load_management_directory("Bearer test", "alice")
        self.assertEqual(len(users), 2)
        self.assertEqual(departments["Alice"], {"Sales", "Support"})
        self.assertEqual(len(requests), 3)

    def test_missing_credentials_and_truncated_departments_fail_explicitly(self):
        with self.assertRaises(HTTPException):
            management.load_management_directory(None)
        real_client = httpx.Client
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200, json={"total": 2, "items": [{"staff": "Alice", "department": ""}]},
        ))
        with patch.object(management.httpx, "Client", side_effect=lambda **kwargs: real_client(
            **kwargs, transport=transport,
        )), self.assertRaises(HTTPException) as raised:
            management.load_management_directory("Bearer test")
        self.assertEqual(raised.exception.status_code, 503)

    def test_endpoint_requires_superuser_and_parses_boolean_filter(self):
        app = FastAPI()
        app.include_router(management.router)
        user = CurrentUser(7)
        app.dependency_overrides[get_current_active_user] = lambda: user
        with TestClient(app) as client, patch.object(management, "load_management_directory") as load:
            self.assertEqual(client.get("/api/admin/user-management/").status_code, 403)
            load.assert_not_called()
            user.is_superuser = True
            load.return_value = ([{"id": 1, "is_superuser": False}], {})
            response = client.get("/api/admin/user-management/?is_superuser=false")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["total"], 1)
            self.assertEqual(client.get("/api/admin/user-management/?skip=-1").status_code, 422)
            self.assertEqual(client.get("/api/admin/user-management/?user_id=0").status_code, 422)
            self.assertEqual(client.get("/api/admin/user-management/?user_id=2").json()["total"], 0)

    def test_username_selection_is_exact_and_combines_with_filters(self):
        users = [
            {"id": 2, "username": "user2", "first_name": "Bob", "is_superuser": False},
            {"id": 20, "username": "user20", "first_name": "Carol", "is_superuser": True},
        ]
        departments = {"Bob": {"Sales"}, "Carol": {"Support"}}
        result = management.build_user_page(users, departments, 0, 20, "Sales", False, 2)
        self.assertEqual([user["id"] for user in result["items"]], [2])
        self.assertEqual(len(result["user_options"]), 2)
        self.assertEqual(result["user_options"][0]["first_name"], "Bob")
        self.assertEqual(management.build_user_page(users, departments, 0, 20, "Support", False, 2)["total"], 0)


if __name__ == "__main__":
    unittest.main()
