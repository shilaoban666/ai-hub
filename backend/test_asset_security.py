import json
import unittest

from asset_security import normalize_grants, read_skill_manifest


class SkillManifestTests(unittest.TestCase):
    def test_network_capability_does_not_require_domain_declaration(self):
        manifest = read_skill_manifest([{
            "path": "aihub-manifest.json", "type": "file",
            "content": json.dumps({"capabilities": ["network_access"]}),
        }])
        self.assertEqual(manifest["network_domains"], [])
        self.assertEqual(normalize_grants(manifest, None), ["network_access"])

    def test_scripts_and_urls_do_not_trigger_content_scanning(self):
        manifest = read_skill_manifest([
            {"path": "SKILL.md", "type": "file", "content": "https://example.test"},
            {"path": "run.py", "type": "file", "content": "import requests; requests.get(target)"},
        ])
        self.assertEqual(manifest["capabilities"], [])
        self.assertEqual(manifest["network_domains"], [])

    def test_missing_or_malformed_optional_manifest_does_not_block_release(self):
        for content in ("not-json", "[]", '{"capabilities":true}', '{"network_domains":[{}]}'):
            with self.subTest(content=content):
                manifest = read_skill_manifest([{"path": "aihub-manifest.json", "type": "file", "content": content}])
                self.assertEqual(normalize_grants(manifest, None), [])


if __name__ == "__main__":
    unittest.main()
