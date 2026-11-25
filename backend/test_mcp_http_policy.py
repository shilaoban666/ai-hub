import unittest
from unittest.mock import patch

from asset_security import AssetPolicyError, validate_http_target
from database import settings


class McpHttpPolicyTests(unittest.TestCase):
    def setUp(self):
        self.private_policy = patch.object(settings, "mcp_allow_private_networks", False)
        self.private_policy.start()
        self.addCleanup(self.private_policy.stop)

    @patch("asset_security.socket.getaddrinfo")
    def test_public_http_mcp_does_not_require_enterprise_egress_settings(self, getaddrinfo):
        getaddrinfo.return_value = [(2, 1, 6, "", ("8.8.8.8", 443))]
        with (
            patch.object(settings, "mcp_allowed_hosts", ""),
            patch.object(settings, "mcp_egress_proxy_url", ""),
        ):
            result = validate_http_target("https://mcp.example.com/sse")

        self.assertEqual("mcp.example.com", result["host"])

    @patch("asset_security.socket.getaddrinfo")
    def test_configured_allowlist_still_restricts_hosts(self, getaddrinfo):
        getaddrinfo.return_value = [(2, 1, 6, "", ("8.8.8.8", 443))]
        with patch.object(settings, "mcp_allowed_hosts", "approved.example.com"):
            with self.assertRaisesRegex(AssetPolicyError, "not approved"):
                validate_http_target("https://other.example.com/sse")

    def test_private_targets_remain_blocked(self):
        with patch.object(settings, "mcp_allowed_hosts", ""):
            with self.assertRaisesRegex(AssetPolicyError, "non-public address"):
                validate_http_target("http://127.0.0.1:9000/sse")

    def test_self_test_mode_accepts_public_private_and_loopback_targets(self):
        with (
            patch.object(settings, "mcp_allow_private_networks", True),
            patch.object(settings, "mcp_allowed_hosts", ""),
        ):
            for host in ("8.8.8.8", "172.26.36.234", "10.1.2.3", "192.168.1.2", "127.0.0.1", "[::1]", "[fd00::1]"):
                with self.subTest(host=host):
                    self.assertTrue(validate_http_target(f"http://{host}:3333/mcp")["resolved_addresses"])

    @patch("asset_security.socket.getaddrinfo")
    def test_self_test_mode_accepts_private_dns_and_localhost(self, getaddrinfo):
        with (
            patch.object(settings, "mcp_allow_private_networks", True),
            patch.object(settings, "mcp_allowed_hosts", ""),
        ):
            getaddrinfo.return_value = [(2, 1, 6, "", ("172.26.36.234", 3333))]
            self.assertEqual(validate_http_target("http://gitlab-mcp.internal:3333/mcp")["host"], "gitlab-mcp.internal")
            getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 3333)), (10, 1, 6, "", ("::1", 3333))]
            self.assertEqual(validate_http_target("http://localhost:3333/mcp")["host"], "localhost")

    def test_self_test_mode_preserves_url_validation(self):
        with (
            patch.object(settings, "mcp_allow_private_networks", True),
            patch.object(settings, "mcp_allowed_hosts", ""),
        ):
            for url in (
                "http://169.254.169.254/mcp", "http://metadata.google.internal/mcp",
                "http://0.0.0.0/mcp", "http://224.0.0.1/mcp",
                "file:///tmp/mcp", "http://user:secret@172.26.36.234/mcp",
                "http://172.26.36.234/mcp?token=secret",
            ):
                with self.subTest(url=url), self.assertRaises(AssetPolicyError):
                    validate_http_target(url)

    def test_explicit_host_policy_still_applies_in_self_test_mode(self):
        with (
            patch.object(settings, "mcp_allow_private_networks", True),
            patch.object(settings, "mcp_allowed_hosts", "approved.example.com"),
        ):
            with self.assertRaisesRegex(AssetPolicyError, "not approved"):
                validate_http_target("http://172.26.36.234:3333/mcp")


if __name__ == "__main__":
    unittest.main()
