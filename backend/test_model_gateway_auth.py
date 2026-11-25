import json
import pytest

from model_gateway import _upstream_auth_headers, _upstream_error_content


def test_proxy_upstream_uses_bearer_authentication() -> None:
    assert _upstream_auth_headers("https://sub2api.example.test", "secret") == {
        "authorization": "Bearer secret"
    }


def test_official_anthropic_upstream_uses_api_key_header() -> None:
    assert _upstream_auth_headers("https://api.anthropic.com/v1", "secret") == {
        "x-api-key": "secret"
    }


@pytest.mark.parametrize('body', [
    b'{"message":"provider unavailable", "request_id":"req-body"}',
    b'{"error":"provider unavailable"}',
    b'<html>provider unavailable</html>',
])
def test_nonstandard_provider_errors_keep_the_body_status_and_request_id(body):
    payload = json.loads(_upstream_error_content(body, 503, 'req-header'))
    assert payload['error']['type'] == 'upstream_error'
    assert 'provider unavailable' in payload['error']['message']
    assert 'HTTP 503; request_id=req-header' in payload['error']['message']
