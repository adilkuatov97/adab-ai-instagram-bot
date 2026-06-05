from __future__ import annotations

import unittest

from app.services import whatsapp_cloud_service


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    last_timeout = None
    last_url = None
    last_json = None
    last_headers = None
    response = _FakeResponse(200, "{}")

    def __init__(self, timeout):
        self.__class__.last_timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json, headers):
        self.__class__.last_url = url
        self.__class__.last_json = json
        self.__class__.last_headers = headers
        return self.__class__.response


class WhatsAppCloudServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._original_async_client = whatsapp_cloud_service.httpx.AsyncClient
        whatsapp_cloud_service.httpx.AsyncClient = _FakeAsyncClient
        _FakeAsyncClient.response = _FakeResponse(200, "{}")

    async def asyncTearDown(self):
        whatsapp_cloud_service.httpx.AsyncClient = self._original_async_client

    async def test_send_text_builds_graph_api_request(self):
        await whatsapp_cloud_service.send_whatsapp_cloud_text(
            to="77000000000",
            text="reply text",
            phone_number_id="12345",
            access_token="test-token",
            api_version="v25.0",
        )

        self.assertEqual(
            _FakeAsyncClient.last_url,
            "https://graph.facebook.com/v25.0/12345/messages",
        )
        self.assertEqual(
            _FakeAsyncClient.last_json,
            {
                "messaging_product": "whatsapp",
                "to": "77000000000",
                "type": "text",
                "text": {"body": "reply text"},
            },
        )
        self.assertEqual(
            _FakeAsyncClient.last_headers,
            {
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
        )

    async def test_send_text_raises_on_graph_api_failure(self):
        _FakeAsyncClient.response = _FakeResponse(400, '{"error":"bad request"}')

        with self.assertRaises(whatsapp_cloud_service.WhatsAppCloudSendError):
            await whatsapp_cloud_service.send_whatsapp_cloud_text(
                to="77000000000",
                text="reply text",
                phone_number_id="12345",
                access_token="test-token",
            )


if __name__ == "__main__":
    unittest.main()
