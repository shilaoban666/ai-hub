import unittest
from unittest.mock import Mock

from runtimes.attachments import MAX_IMAGE_BYTES, build_runtime_attachments


class RuntimeAttachmentTests(unittest.TestCase):
    def test_images_use_bounded_provider_access_and_files_remain_references(self):
        provider = Mock()
        provider.read_file_limited.return_value = (b"png-data", "screen.PNG")
        workspace = object()
        attachments = build_runtime_attachments(
            provider, workspace, ["screen.PNG", "notes.txt", "screen.PNG"], "claude_code",
        )
        provider.read_file_limited.assert_called_once_with(workspace, "screen.PNG", MAX_IMAGE_BYTES)
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].media_type, "image/png")
        self.assertEqual(attachments[0].image_data, b"png-data")
        self.assertIsNone(attachments[1].image_data)


    def test_invalid_paths_are_rejected_by_provider(self):
        provider = Mock()
        provider.read_file_limited.side_effect = ValueError("invalid path")
        with self.assertRaisesRegex(ValueError, "invalid path"):
            build_runtime_attachments(provider, object(), ["../secret.png"], "claude_code")

    def test_empty_oversized_and_total_limit_images_are_rejected(self):
        provider = Mock()
        for data in [b"", b"x" * (MAX_IMAGE_BYTES + 1)]:
            provider.read_file_limited.return_value = (data, "screen.png")
            with self.assertRaisesRegex(ValueError, "5 MB"):
                build_runtime_attachments(provider, object(), ["screen.png"], "claude_code")
        provider.read_file_limited.return_value = (b"x" * MAX_IMAGE_BYTES, "screen.png")
        with self.assertRaisesRegex(ValueError, "20 MB"):
            build_runtime_attachments(provider, object(), [f"{i}.png" for i in range(5)], "claude_code")


if __name__ == "__main__":
    unittest.main()
