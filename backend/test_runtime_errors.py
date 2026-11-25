from runtime_errors import safe_error_detail


def test_error_detail_redacts_credentials_and_retains_provider_diagnostics():
    detail = safe_error_detail('API Error: 503 request_id=req-42; api_key=secret-value; '
                              'Authorization: Bearer secret-token; sk-test-key; ahr_test-token')
    for secret in ('secret-value', 'secret-token', 'sk-test-key', 'ahr_test-token'):
        assert secret not in detail
    assert 'API Error: 503 request_id=req-42' in detail


def test_catalog_warning_is_removed_without_dropping_the_actual_error():
    assert safe_error_detail('[claude-code:unrecognized_model] {"model":"claude-sonnet-5-5"}\n'
                             'API Error: 504 upstream_timeout') == 'API Error: 504 upstream_timeout'
