from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import whatsapp_cloud_service


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", json_body=None):
        self.status_code = status_code
        self.text = text
        self._json_body = json_body

    def json(self):
        if self._json_body is None:
            raise ValueError("not json")
        return self._json_body


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
                "recipient_type": "individual",
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
        _FakeAsyncClient.response = _FakeResponse(
            400,
            '{"error":{"message":"bad request"}}',
            {"error": {"message": "bad request"}},
        )

        with self.assertRaises(whatsapp_cloud_service.WhatsAppCloudSendError):
            await whatsapp_cloud_service.send_whatsapp_cloud_text(
                to="77000000000",
                text="reply text",
                phone_number_id="12345",
                access_token="test-token",
            )

    def test_extract_graph_api_error_parses_safe_fields(self):
        response = _FakeResponse(
            400,
            '{"error":{"code":100,"details":"Bad recipient","message":"Invalid parameter","type":"OAuthException","fbtrace_id":"TRACE","error_subcode":2018001}}',
            {
                "error": {
                    "code": 100,
                    "details": "Bad recipient",
                    "message": "Invalid parameter",
                    "type": "OAuthException",
                    "fbtrace_id": "TRACE",
                    "error_subcode": 2018001,
                    "extra": "ignored",
                }
            },
        )

        self.assertEqual(
            whatsapp_cloud_service._extract_graph_api_error(response),
            {
                "code": 100,
                "details": "Bad recipient",
                "message": "Invalid parameter",
                "type": "OAuthException",
                "fbtrace_id": "TRACE",
                "error_subcode": 2018001,
            },
        )

    def test_extract_graph_api_error_handles_missing_fields(self):
        response = _FakeResponse(
            400,
            '{"error":{"code":100}}',
            {"error": {"code": 100}},
        )

        self.assertEqual(
            whatsapp_cloud_service._extract_graph_api_error(response),
            {
                "code": 100,
                "details": None,
                "message": None,
                "type": None,
                "fbtrace_id": None,
                "error_subcode": None,
            },
        )

    def test_extract_graph_api_error_handles_non_json(self):
        response = _FakeResponse(400, "not-json")

        self.assertEqual(
            whatsapp_cloud_service._extract_graph_api_error(response),
            {
                "code": None,
                "details": None,
                "message": None,
                "type": None,
                "fbtrace_id": None,
                "error_subcode": None,
            },
        )

    async def test_json_error_log_excludes_access_token_and_full_text(self):
        _FakeAsyncClient.response = _FakeResponse(
            400,
            '{"error":{"code":100,"details":"Bad recipient","message":"Invalid parameter","type":"OAuthException","fbtrace_id":"TRACE"}}',
            {
                "error": {
                    "code": 100,
                    "details": "Bad recipient",
                    "message": "Invalid parameter",
                    "type": "OAuthException",
                    "fbtrace_id": "TRACE",
                }
            },
        )

        with patch.object(whatsapp_cloud_service.logger, "error") as log_error:
            with self.assertRaises(whatsapp_cloud_service.WhatsAppCloudSendError):
                await whatsapp_cloud_service.send_whatsapp_cloud_text(
                    to="77000000000",
                    text="full outbound reply must not be logged",
                    phone_number_id="12345",
                    access_token="secret-access-token",
                )

        logged_args = " ".join(str(arg) for arg in log_error.call_args.args)
        self.assertIn("100", logged_args)
        self.assertIn("Bad recipient", logged_args)
        self.assertIn("Invalid parameter", logged_args)
        self.assertIn("OAuthException", logged_args)
        self.assertIn("TRACE", logged_args)
        self.assertNotIn("secret-access-token", logged_args)
        self.assertNotIn("full outbound reply must not be logged", logged_args)
        self.assertNotIn("messaging_product", logged_args)

    async def test_non_json_error_log_does_not_crash(self):
        _FakeAsyncClient.response = _FakeResponse(400, "not-json")

        with patch.object(whatsapp_cloud_service.logger, "error") as log_error:
            with self.assertRaises(whatsapp_cloud_service.WhatsAppCloudSendError):
                await whatsapp_cloud_service.send_whatsapp_cloud_text(
                    to="77000000000",
                    text="reply text",
                    phone_number_id="12345",
                    access_token="secret-access-token",
                )

        logged_args = " ".join(str(arg) for arg in log_error.call_args.args)
        self.assertIn("body_len", logged_args)
        self.assertNotIn("secret-access-token", logged_args)


if __name__ == "__main__":
    unittest.main()
