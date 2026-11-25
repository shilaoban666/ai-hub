import asyncio
from types import SimpleNamespace

from fastapi import HTTPException

from auth import (
    CurrentUser,
    _parse_gateway_user,
    _parse_list_value,
    get_current_user,
    require_permission,
)


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


def _request(headers):
    return SimpleNamespace(headers=_Headers(headers))


def test_gateway_identity_headers_are_accepted():
    user = _parse_gateway_user(_request({
        "x-user-id": "7",
        "x-user-is-superuser": "true",
        "x-user-is-staff": "true",
        "x-user-username": "zhang%20san",
        "x-user-first-name": "%E5%BC%A0%E4%B8%89",
        "x-user-email": "zhangsan%40example.com",
        "x-user-permissions": "%5B%22agent.channel.operate%22%2C%22skills.*%22%5D",
        "x-user-roles": "operator,auditor",
    }))

    assert user.user_id == 7
    assert user.is_superuser is True
    assert user.is_staff is True
    assert user.username == "zhang san"
    assert user.first_name == "张三"
    assert user.email == "zhangsan@example.com"
    assert user.has_permission("agent.channel.operate")
    assert user.has_permission("skills.publish")
    assert user.roles == ["operator", "auditor"]


def test_permission_header_formats_are_supported():
    assert _parse_list_value("a,b;c") == ["a", "b", "c"]
    assert _parse_list_value("%5B%22a%22%2C%22b%22%5D") == ["a", "b"]
    assert _parse_list_value(["a", "b"]) == ["a", "b"]


def test_invalid_gateway_user_id_is_rejected():
    assert _parse_gateway_user(_request({"x-user-id": "not-an-integer"})) is None
    assert _parse_gateway_user(_request({"x-user-id": "0"})) is None


def test_non_gateway_credentials_are_rejected():
    for headers in (
        {"authorization": "Bearer token"},
        {"x-gateway-assertion": "assertion"},
    ):
        try:
            asyncio.run(get_current_user(_request(headers)))
            assert False, "Expected authentication failure"
        except HTTPException as exc:
            assert exc.status_code == 401


def test_permission_dependency_rejects_missing_permission():
    checker = require_permission("skills.publish")
    user = CurrentUser(user_id=7, permissions=["skills.read"])
    try:
        asyncio.run(checker(user))
        assert False, "Expected permission denial"
    except HTTPException as exc:
        assert exc.status_code == 403


if __name__ == "__main__":
    test_gateway_identity_headers_are_accepted()
    test_permission_header_formats_are_supported()
    test_invalid_gateway_user_id_is_rejected()
    test_non_gateway_credentials_are_rejected()
    test_permission_dependency_rejects_missing_permission()
    print("auth permission tests passed")
