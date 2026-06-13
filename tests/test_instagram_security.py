from __future__ import annotations

import asyncio
import hashlib
import hmac
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app import main
from app.services import instagram_service
from app.services.instagram_service import InstagramSendError


class _FakeRequest:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers


class InstagramWebhookSignatureTest(unittest.TestCase):
    def test_missing_app_secret_rejected_in_production(self):
        request = _FakeRequest({})

        with patch.object(main, "APP_ENV", "production"), patch.object(main, "APP_SECRET", ""):
            with self.assertRaises(HTTPException) as raised:
                main._verify_meta_signature(request, b"{}")

        self.assertEqual(raised.exception.status_code, 503)

    def test_missing_app_secret_allowed_outside_production(self):
        request = _FakeRequest({})

        with patch.object(main, "APP_ENV", "development"), patch.object(main, "APP_SECRET", ""):
            main._verify_meta_signature(request, b"{}")

    def test_invalid_signature_rejected_when_secret_configured(self):
        request = _FakeRequest({"x-hub-signature-256": "sha256=invalid"})

        with patch.object(main, "APP_SECRET", "test-secret"):
            with self.assertRaises(HTTPException) as raised:
                main._verify_meta_signature(request, b"{}")

        self.assertEqual(raised.exception.status_code, 403)

    def test_valid_signature_accepted_when_secret_configured(self):
        raw_body = b'{"object":"instagram"}'
        signature = "sha256=" + hmac.new(
            b"test-secret",
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        request = _FakeRequest({"x-hub-signature-256": signature})

        with patch.object(main, "APP_SECRET", "test-secret"):
            main._verify_meta_signature(request, raw_body)


class InstagramServiceLoggingTest(unittest.TestCase):
    def test_send_error_log_does_not_include_full_graph_body(self):
        response = _FakeGraphResponse(
            400,
            '{"error":{"message":"sensitive customer text","type":"OAuthException"}}',
            {"error": {"message": "sensitive customer text", "type": "OAuthException"}},
        )
        async_client = _FakeAsyncClient(response)

        with patch.object(instagram_service.httpx, "AsyncClient", return_value=async_client):
            with self.assertLogs("app.services.instagram_service", level="ERROR") as logs:
                with self.assertRaises(InstagramSendError):
                    asyncio.run(
                        instagram_service.send_message(
                            "ig-user-id",
                            "reply text",
                            "token",
                        )
                    )

        rendered = "\n".join(logs.output)
        self.assertIn("body_len=", rendered)
        self.assertIn("OAuthException", rendered)
        self.assertNotIn("sensitive customer text", rendered)


class _FakeGraphResponse:
    def __init__(self, status_code: int, text: str, payload: dict):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeGraphResponse):
        self.response = response
        self.post = AsyncMock(return_value=response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None
