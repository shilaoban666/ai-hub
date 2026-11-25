import io
import os
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from main import upload_image
from auth import CurrentUser
from chat_image_storage import ImageStorageError
import chat_image_storage


class AssistantImageUploadTests(unittest.IsolatedAsyncioTestCase):
    async def upload(self, size, purpose):
        file = UploadFile(filename='avatar.png', file=io.BytesIO(b'x' * size),
                          headers=Headers({'content-type': 'image/png'}))
        try:
            return await upload_image(file=file, current_user=CurrentUser(user_id=7), purpose=purpose)
        finally:
            await file.close()

    async def test_assistant_limit_rejects_oversize_before_writing(self):
        with tempfile.TemporaryDirectory() as directory, patch('main.IMAGES_DIR', directory):
            with self.assertRaises(HTTPException) as raised:
                await self.upload(200 * 1024 + 1, 'assistant')
            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn('200KB', raised.exception.detail)
            self.assertEqual(os.listdir(directory), [])
            result = await self.upload(200 * 1024, 'assistant')
            self.assertEqual(os.path.getsize(os.path.join(directory, result['url'].split('/')[-1])), 200 * 1024)

    async def test_editor_keeps_existing_limit(self):
        with tempfile.TemporaryDirectory() as directory, patch('main.IMAGES_DIR', directory):
            await self.upload(300 * 1024, 'content')
            with self.assertRaises(HTTPException):
                await self.upload(1048577, 'content')

    async def test_feedback_accepts_three_mb_and_rejects_larger_images(self):
        limit = 3 * 1024 * 1024
        with tempfile.TemporaryDirectory() as directory, patch('main.IMAGES_DIR', directory), patch(
            'main.upload_feedback_image', return_value='https://images.example/feedback/images/proof.png'
        ) as upload:
            result = await self.upload(limit, 'feedback')
            self.assertEqual(result['url'], 'https://images.example/feedback/images/proof.png')
            self.assertEqual(upload.call_args.args[2], 7)
            self.assertEqual(len(upload.call_args.args[0]), limit)
            self.assertEqual(os.listdir(directory), [])
            with self.assertRaises(HTTPException) as raised:
                await self.upload(limit + 1, 'feedback')
            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn('3MB', raised.exception.detail)
            upload.assert_called_once()

    async def test_feedback_oss_failure_does_not_fall_back_to_disk(self):
        with tempfile.TemporaryDirectory() as directory, patch('main.IMAGES_DIR', directory), patch(
            'main.upload_feedback_image', side_effect=ImageStorageError('OSS 图片上传失败')
        ):
            with self.assertRaises(HTTPException) as raised:
                await self.upload(16, 'feedback')
            self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(os.listdir(directory), [])

    def test_feedback_storage_uses_permanent_oss_owner_directory(self):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        with patch.object(chat_image_storage.settings, 'oss_access_key_id', 'test-id'), patch.object(
            chat_image_storage.settings, 'oss_access_key_secret', 'test-secret'
        ), patch.object(chat_image_storage.requests, 'put', return_value=response) as put:
            url = chat_image_storage.upload_feedback_image(b'\x89PNG\r\n\x1a\n', 'image/png', 7)
        self.assertIn('/feedback/images/7/', url)
        self.assertTrue(url.startswith('https://'))
        self.assertNotIn('?', url)
        self.assertEqual(put.call_args.kwargs['headers']['x-oss-object-acl'], 'public-read')


if __name__ == '__main__':
    unittest.main()
