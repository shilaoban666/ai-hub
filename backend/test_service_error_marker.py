"""503 business errors must be distinguishable from gateway outages."""
import json
import unittest

from starlette.exceptions import HTTPException
from exception_handlers import http_exception_handler


class ServiceErrorMarkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_business_503_preserves_message_and_existing_headers(self):
        response = await http_exception_handler(None, HTTPException(
            status_code=503, detail='模型当前不可用', headers={'Retry-After': '10'},
        ))
        self.assertEqual(response.headers['x-aihub-error'], 'business')
        self.assertEqual(response.headers['retry-after'], '10')
        self.assertEqual(json.loads(response.body)['message'], '模型当前不可用')

    async def test_other_errors_keep_their_existing_contract(self):
        response = await http_exception_handler(None, HTTPException(403, '权限不足'))
        self.assertNotIn('x-aihub-error', response.headers)
        self.assertEqual(json.loads(response.body)['code'], 403)


if __name__ == '__main__':
    unittest.main()
