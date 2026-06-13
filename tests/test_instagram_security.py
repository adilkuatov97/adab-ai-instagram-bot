from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app import main
from app.services import instagram_service
from app.services.instagram_service import InstagramSendError


class _FakeRequest:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers


class _FakeWebhookRequest:
    headers: dict[str, str] = {}

    def __init__(self, payload: dict):
        self._payload = payload

    async def body(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


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


class InstagramWebhookFlowTest(unittest.TestCase):
    def test_known_instagram_account_id_resolves_client(self):
        client = _fake_client(instagram_account_id="17841400368456767")
        payload = _instagram_payload(
            account_id="17841400368456767",
            sender_id="ig-user-1",
            message={"mid": "mid-known", "text": "Здравствуйте"},
        )
        fake_task = _FakeTask()

        with _patched_webhook_dependencies(client=client) as deps:
            deps["create_task"].side_effect = _close_coroutine_and_return(fake_task)

            result = asyncio.run(main.webhook(_FakeWebhookRequest(payload), db=object()))

        self.assertEqual(result, {"status": "ok"})
        deps["get_by_instagram_id"].assert_awaited_once()
        deps["add_message_to_buffer"].assert_awaited_once_with(
            client_id=str(client.id),
            user_id="ig-user-1",
            message_text="Здравствуйте",
            is_voice=False,
        )
        self.assertTrue(fake_task.callback_added)

    def test_unknown_instagram_account_id_logs_safe_warning_and_skips(self):
        payload = _instagram_payload(
            account_id="17841400368456767",
            sender_id="ig-user-1",
            message={"mid": "mid-unknown", "text": "private customer text"},
        )

        with _patched_webhook_dependencies(client=None) as deps:
            with self.assertLogs("app.main", level="WARNING") as logs:
                result = asyncio.run(main.webhook(_FakeWebhookRequest(payload), db=object()))

        self.assertEqual(result, {"status": "ok"})
        deps["add_message_to_buffer"].assert_not_awaited()
        rendered = "\n".join(logs.output)
        self.assertIn("CLIENT_RESOLVED source=none", rendered)
        self.assertIn("account_id=17841400368456767", rendered)
        self.assertNotIn("private customer text", rendered)

    def test_echo_message_skipped(self):
        client = _fake_client(instagram_account_id="17841400368456767")
        payload = _instagram_payload(
            account_id="17841400368456767",
            sender_id="ig-user-1",
            message={"mid": "mid-echo", "text": "echo text", "is_echo": True},
        )

        with _patched_webhook_dependencies(client=client) as deps:
            result = asyncio.run(main.webhook(_FakeWebhookRequest(payload), db=object()))

        self.assertEqual(result, {"status": "ok"})
        deps["add_message_to_buffer"].assert_not_awaited()
        deps["is_seen"].assert_not_awaited()

    def test_unsupported_no_text_message_skipped(self):
        client = _fake_client(instagram_account_id="17841400368456767")
        payload = _instagram_payload(
            account_id="17841400368456767",
            sender_id="ig-user-1",
            message={"mid": "mid-image", "attachments": [{"type": "image"}]},
        )

        with _patched_webhook_dependencies(client=client) as deps:
            result = asyncio.run(main.webhook(_FakeWebhookRequest(payload), db=object()))

        self.assertEqual(result, {"status": "ok"})
        deps["is_seen"].assert_awaited_once_with("mid-image")
        deps["add_message_to_buffer"].assert_not_awaited()


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


class _FakeTask:
    callback_added = False

    def add_done_callback(self, callback):
        self.callback_added = True


def _fake_client(instagram_account_id: str):
    return SimpleNamespace(
        id="f17a14f4-124a-439a-b3ae-0911ea007037",
        instagram_account_id=instagram_account_id,
        business_name="Adab AI Agency",
        system_prompt="",
        whatsapp_link="",
        telegram_manager_chat_id="",
        status="active",
    )


def _instagram_payload(*, account_id: str, sender_id: str, message: dict) -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": account_id,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "message": message,
                    }
                ],
            }
        ],
    }


def _close_coroutine_and_return(task: _FakeTask):
    def fake_create_task(coro):
        coro.close()
        return task

    return fake_create_task


class _patched_webhook_dependencies:
    def __init__(self, *, client):
        self.client = client
        self._patches = []
        self._deps = {}

    def __enter__(self):
        self._deps = {
            "verify": patch.object(main, "_verify_meta_signature"),
            "get_by_instagram_id": patch.object(
                main.client_service,
                "get_by_instagram_id",
                new_callable=AsyncMock,
                return_value=self.client,
            ),
            "get_legacy_client": patch.object(main, "_get_legacy_client", return_value=None),
            "resolve_token": patch.object(main, "_resolve_token", return_value="token"),
            "resolve_groq_key": patch.object(main, "_resolve_groq_key", return_value="groq"),
            "is_seen": patch.object(main._store, "is_seen", new_callable=AsyncMock, return_value=False),
            "add_message_to_buffer": patch.object(
                main._debounce,
                "add_message_to_buffer",
                new_callable=AsyncMock,
                return_value=123.0,
            ),
            "create_task": patch.object(main.asyncio, "create_task"),
        }
        started = {}
        for name, patcher in self._deps.items():
            self._patches.append(patcher)
            started[name] = patcher.start()
        return started

    def __exit__(self, exc_type, exc, tb):
        for patcher in reversed(self._patches):
            patcher.stop()
        return None
