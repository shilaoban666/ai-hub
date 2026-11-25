import unittest

from schemas import SkillPublicResponse
from schemas import SkillCreate, SkillUpdate
from pydantic import ValidationError


class PublicSkillSchemaTests(unittest.TestCase):
    def test_conversation_examples_handle_legacy_null_and_validate_limits(self):
        self.assertEqual(SkillCreate(name='Legacy', version='1', conversation_examples=None).conversation_examples, [])
        self.assertIn('conversation_examples', SkillPublicResponse.model_fields)
        self.assertNotIn('conversation_examples', SkillUpdate(description='Only description').model_dump(exclude_unset=True))
        self.assertEqual(SkillUpdate(conversation_examples=None).model_dump(exclude_unset=True), {'conversation_examples': []})
        for value in (['example'] * 11, ['x' * 1001], 'not a list', [42]):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValidationError):
                SkillUpdate(conversation_examples=value)

    def test_public_skill_exposes_git_install_metadata_without_credentials(self):
        fields = set(SkillPublicResponse.model_fields)

        self.assertTrue({
            "git_provider",
            "git_repo_url",
            "git_branch",
            "git_last_synced_at",
            "git_sync_status",
            "git_last_commit_sha",
            "git_sync_direction",
        }.issubset(fields))
        self.assertNotIn("git_access_token", fields)


if __name__ == "__main__":
    unittest.main()
