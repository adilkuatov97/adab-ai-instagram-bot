from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app import whatsapp_cloud_routes
from app.services.claude_service import EMPTY_CLAUDE_FALLBACK, SAFE_CLAUDE_FALLBACK
from app.whatsapp_cloud_routes import (
    WhatsAppCloudConfig,
    WhatsAppCloudInboundTextMessage,
    WHATSAPP_CLOUD_RESPONSE_POLICY,
    _enqueue_text_message,
    _apply_manager_fallback_rules,
    _extract_text_messages,
    _extract_webhook_metadata,
    _get_processing_config,
    _is_valid_signature,
    _mark_message_for_processing,
    _normalize_whatsapp_reply,
    _send_whatsapp_cloud_reply,
    _send_whatsapp_cloud_reply_with_outbox,
    _verify_signature_if_configured,
    resolve_whatsapp_cloud_client_id,
    resolve_whatsapp_cloud_send_to,
    whatsapp_cloud_health,
)
from app.services.whatsapp_cloud_service import WhatsAppCloudSendError


class WhatsAppCloudRoutesTest(unittest.TestCase):
    def test_missing_signature_secret_rejected_in_production(self):
        request = _FakeRequest({})

        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(_verify_signature_if_configured(request, b"{}"))

        self.assertEqual(raised.exception.status_code, 503)

    def test_missing_signature_secret_allowed_outside_production(self):
        request = _FakeRequest({})

        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=True):
            asyncio.run(_verify_signature_if_configured(request, b"{}"))

    def test_invalid_signature_rejected_when_secret_configured(self):
        request = _FakeRequest({"x-hub-signature-256": "sha256=invalid"})

        with patch.dict(
            os.environ,
            {"WHATSAPP_CLOUD_APP_SECRET": "test-secret"},
            clear=True,
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(_verify_signature_if_configured(request, b"{}"))

        self.assertEqual(raised.exception.status_code, 403)

    def test_extract_metadata_for_text_message(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "77000000000",
                                        "id": "wamid.test",
                                        "timestamp": "1710000000",
                                        "text": {"body": "must not be logged by helper"},
                                        "type": "text",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }

        metadata = _extract_webhook_metadata(payload)

        self.assertEqual(metadata.object_name, "whatsapp_business_account")
        self.assertEqual(metadata.entry_count, 1)
        self.assertTrue(metadata.messages_exist)
        self.assertEqual(metadata.message_type, "text")

    def test_extract_metadata_without_messages(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {"statuses": [{"status": "sent"}]}}]}],
        }

        metadata = _extract_webhook_metadata(payload)

        self.assertEqual(metadata.entry_count, 1)
        self.assertFalse(metadata.messages_exist)
        self.assertIsNone(metadata.message_type)

    def test_signature_validation(self):
        raw_body = b'{"object":"whatsapp_business_account"}'
        app_secret = "test-secret"
        signature = "sha256=" + hmac.new(
            app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        self.assertTrue(_is_valid_signature(raw_body, signature, app_secret))
        self.assertFalse(_is_valid_signature(raw_body, "sha256=invalid", app_secret))
        self.assertFalse(_is_valid_signature(raw_body, "", app_secret))

    def test_extract_text_messages(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "12345"},
                                "messages": [
                                    {
                                        "from": "77000000000",
                                        "id": "wamid.text",
                                        "timestamp": "1710000000",
                                        "text": {"body": "customer text"},
                                        "type": "text",
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

        messages = _extract_text_messages(payload)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].wa_id, "77000000000")
        self.assertEqual(messages[0].message_id, "wamid.text")
        self.assertEqual(messages[0].timestamp, "1710000000")
        self.assertEqual(messages[0].message_type, "text")
        self.assertEqual(messages[0].text_body, "customer text")
        self.assertEqual(messages[0].phone_number_id, "12345")

    def test_extract_text_messages_ignores_statuses(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {"id": "wamid.status", "status": "delivered"}
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        self.assertEqual(_extract_text_messages(payload), [])

    def test_extract_text_messages_ignores_unsupported_media(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "77000000000",
                                        "id": "wamid.image",
                                        "type": "image",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        self.assertEqual(_extract_text_messages(payload), [])

    def test_duplicate_helper_continues_without_redis(self):
        self.assertTrue(asyncio.run(_mark_message_for_processing("wamid.no_redis")))

    def test_recipient_override_missing_env_returns_original_wa_id(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                resolve_whatsapp_cloud_send_to("77780400008"),
                "77780400008",
            )

    def test_recipient_override_mapping_returns_target(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_CLOUD_RECIPIENT_OVERRIDES": (
                    "77780400008:787780400008, 77715899999 : 787715899999"
                )
            },
            clear=True,
        ):
            self.assertEqual(
                resolve_whatsapp_cloud_send_to("77780400008"),
                "787780400008",
            )
            self.assertEqual(
                resolve_whatsapp_cloud_send_to("77715899999"),
                "787715899999",
            )

    def test_recipient_override_ignored_in_production(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "WHATSAPP_CLOUD_RECIPIENT_OVERRIDES": "77780400008:787780400008",
            },
            clear=True,
        ):
            self.assertEqual(
                resolve_whatsapp_cloud_send_to("77780400008"),
                "77780400008",
            )

    def test_recipient_override_ignores_malformed_pairs(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_CLOUD_RECIPIENT_OVERRIDES": (
                    "broken,no-target:, :no-source,77780400008:787780400008"
                )
            },
            clear=True,
        ):
            self.assertEqual(
                resolve_whatsapp_cloud_send_to("broken"),
                "broken",
            )
            self.assertEqual(
                resolve_whatsapp_cloud_send_to("77780400008"),
                "787780400008",
            )

    def test_send_reply_uses_mapped_recipient_target(self):
        message = WhatsAppCloudInboundTextMessage(
            wa_id="77780400008",
            message_id="wamid.test",
            timestamp="1710000000",
            message_type="text",
            text_body="customer text",
            phone_number_id="12345",
        )
        config = WhatsAppCloudConfig(
            access_token="test-token",
            client_id="client-id",
            phone_number_id="12345",
            api_version="v25.0",
        )

        with patch.dict(
            os.environ,
            {"WHATSAPP_CLOUD_RECIPIENT_OVERRIDES": "77780400008:787780400008"},
            clear=True,
        ):
            with patch(
                "app.whatsapp_cloud_routes.send_whatsapp_cloud_text",
                new=AsyncMock(),
            ) as send_mock:
                asyncio.run(_send_whatsapp_cloud_reply(message, "reply text", config))

        send_mock.assert_awaited_once_with(
            to="787780400008",
            text="reply text",
            phone_number_id="12345",
            access_token="test-token",
            api_version="v25.0",
        )

    def test_client_map_returns_mapped_client_id(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_CLOUD_CLIENT_MAP": (
                    "1175403148986567:f17a14f4-124a-439a-b3ae-0911ea007037"
                )
            },
            clear=True,
        ):
            self.assertEqual(
                resolve_whatsapp_cloud_client_id("1175403148986567"),
                "f17a14f4-124a-439a-b3ae-0911ea007037",
            )

    def test_client_map_trims_whitespace(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_CLOUD_CLIENT_MAP": (
                    " 1175403148986567 : f17a14f4-124a-439a-b3ae-0911ea007037 "
                )
            },
            clear=True,
        ):
            self.assertEqual(
                resolve_whatsapp_cloud_client_id("1175403148986567"),
                "f17a14f4-124a-439a-b3ae-0911ea007037",
            )

    def test_client_map_ignores_malformed_pairs(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_CLOUD_CLIENT_MAP": (
                    "broken,no-target:, :no-source,1175403148986567:client-id"
                )
            },
            clear=True,
        ):
            self.assertEqual(
                resolve_whatsapp_cloud_client_id("broken"),
                None,
            )
            self.assertEqual(
                resolve_whatsapp_cloud_client_id("1175403148986567"),
                "client-id",
            )

    def test_client_map_falls_back_to_default_client_id(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_CLOUD_CLIENT_MAP": "other-phone:other-client",
                "WHATSAPP_CLOUD_DEFAULT_CLIENT_ID": "default-client",
            },
            clear=True,
        ):
            self.assertEqual(
                resolve_whatsapp_cloud_client_id("1175403148986567"),
                "default-client",
            )

    def test_client_map_returns_none_without_map_or_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(resolve_whatsapp_cloud_client_id("1175403148986567"))

    def test_processing_config_uses_mapped_client_id(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_CLOUD_ACCESS_TOKEN": "test-token",
                "WHATSAPP_CLOUD_CLIENT_MAP": "1175403148986567:mapped-client",
                "WHATSAPP_CLOUD_DEFAULT_CLIENT_ID": "default-client",
                "WHATSAPP_CLOUD_API_VERSION": "v25.0",
            },
            clear=True,
        ):
            config = _get_processing_config("1175403148986567")

        self.assertIsNotNone(config)
        self.assertEqual(config.client_id, "mapped-client")
        self.assertEqual(config.phone_number_id, "1175403148986567")

    def test_health_endpoint_configured_true_with_envs(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "WHATSAPP_CLOUD_ACCESS_TOKEN": "secret-token",
                "WHATSAPP_CLOUD_APP_SECRET": "app-secret",
                "WHATSAPP_CLOUD_PHONE_NUMBER_ID": "1175403148986567",
                "WHATSAPP_CLOUD_CLIENT_MAP": "1175403148986567:client-id",
                "WHATSAPP_CLOUD_API_VERSION": "v25.0",
            },
            clear=True,
        ):
            with patch(
                "app.whatsapp_cloud_routes.count_outbox_items",
                new=AsyncMock(return_value=3),
            ):
                response = asyncio.run(whatsapp_cloud_health())

        self.assertTrue(response["ok"])
        self.assertTrue(response["configured"])
        self.assertTrue(response["production"])
        self.assertTrue(response["production_ready"])
        self.assertTrue(response["access_token_configured"])
        self.assertTrue(response["app_secret_configured"])
        self.assertTrue(response["phone_number_id_configured"])
        self.assertTrue(response["client_id_configured"])
        self.assertTrue(response["client_map_configured"])
        self.assertFalse(response["recipient_overrides_configured"])
        self.assertTrue(response["redis_available"])
        self.assertEqual(response["outbox_failed_count"], 3)
        self.assertEqual(response["api_version"], "v25.0")

    def test_health_endpoint_configured_false_when_required_envs_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "app.whatsapp_cloud_routes.count_outbox_items",
                new=AsyncMock(return_value=None),
            ):
                response = asyncio.run(whatsapp_cloud_health())

        self.assertFalse(response["ok"])
        self.assertFalse(response["configured"])
        self.assertFalse(response["production"])
        self.assertFalse(response["production_ready"])
        self.assertFalse(response["access_token_configured"])
        self.assertFalse(response["app_secret_configured"])
        self.assertFalse(response["phone_number_id_configured"])
        self.assertFalse(response["client_id_configured"])
        self.assertFalse(response["client_map_configured"])
        self.assertFalse(response["recipient_overrides_configured"])
        self.assertFalse(response["redis_available"])
        self.assertIsNone(response["outbox_failed_count"])
        self.assertEqual(response["api_version"], "v25.0")

    def test_health_endpoint_response_does_not_include_secrets(self):
        secret_values = {
            "WHATSAPP_CLOUD_ACCESS_TOKEN": "secret-token",
            "WHATSAPP_CLOUD_PHONE_NUMBER_ID": "1175403148986567",
            "WHATSAPP_CLOUD_DEFAULT_CLIENT_ID": "client-secret-id",
            "WHATSAPP_CLOUD_RECIPIENT_OVERRIDES": "77780400008:787780400008",
        }
        with patch.dict(os.environ, secret_values, clear=True):
            with patch(
                "app.whatsapp_cloud_routes.count_outbox_items",
                new=AsyncMock(return_value=0),
            ):
                response = asyncio.run(whatsapp_cloud_health())

        response_text = str(response)
        for value in secret_values.values():
            self.assertNotIn(value, response_text)

    def test_health_endpoint_redis_unavailable_returns_null_count(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_CLOUD_ACCESS_TOKEN": "secret-token",
                "WHATSAPP_CLOUD_PHONE_NUMBER_ID": "1175403148986567",
                "WHATSAPP_CLOUD_DEFAULT_CLIENT_ID": "client-id",
            },
            clear=True,
        ):
            with patch(
                "app.whatsapp_cloud_routes.count_outbox_items",
                new=AsyncMock(return_value=None),
            ):
                response = asyncio.run(whatsapp_cloud_health())

        self.assertTrue(response["ok"])
        self.assertFalse(response["redis_available"])
        self.assertIsNone(response["outbox_failed_count"])

    def test_health_endpoint_not_ready_in_production_without_app_secret(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "WHATSAPP_CLOUD_ACCESS_TOKEN": "secret-token",
                "WHATSAPP_CLOUD_PHONE_NUMBER_ID": "1175403148986567",
                "WHATSAPP_CLOUD_DEFAULT_CLIENT_ID": "client-id",
            },
            clear=True,
        ):
            with patch(
                "app.whatsapp_cloud_routes.count_outbox_items",
                new=AsyncMock(return_value=0),
            ):
                response = asyncio.run(whatsapp_cloud_health())

        self.assertFalse(response["ok"])
        self.assertTrue(response["configured"])
        self.assertTrue(response["production"])
        self.assertFalse(response["production_ready"])
        self.assertFalse(response["app_secret_configured"])

    def test_health_endpoint_not_ready_in_production_with_recipient_overrides(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "WHATSAPP_CLOUD_ACCESS_TOKEN": "secret-token",
                "WHATSAPP_CLOUD_APP_SECRET": "app-secret",
                "WHATSAPP_CLOUD_PHONE_NUMBER_ID": "1175403148986567",
                "WHATSAPP_CLOUD_DEFAULT_CLIENT_ID": "client-id",
                "WHATSAPP_CLOUD_RECIPIENT_OVERRIDES": "77780400008:787780400008",
            },
            clear=True,
        ):
            with patch(
                "app.whatsapp_cloud_routes.count_outbox_items",
                new=AsyncMock(return_value=0),
            ):
                response = asyncio.run(whatsapp_cloud_health())

        self.assertFalse(response["ok"])
        self.assertTrue(response["configured"])
        self.assertTrue(response["production"])
        self.assertFalse(response["production_ready"])
        self.assertTrue(response["recipient_overrides_configured"])

    def test_failed_send_creates_outbox_item(self):
        message = WhatsAppCloudInboundTextMessage(
            wa_id="77780400008",
            message_id="wamid.test",
            timestamp="1710000000",
            message_type="text",
            text_body="customer text",
            phone_number_id="12345",
        )
        config = WhatsAppCloudConfig(
            access_token="test-token",
            client_id="client-id",
            phone_number_id="12345",
            api_version="v25.0",
        )

        with patch.dict(
            os.environ,
            {"WHATSAPP_CLOUD_RECIPIENT_OVERRIDES": "77780400008:787780400008"},
            clear=True,
        ):
            with patch(
                "app.whatsapp_cloud_routes.send_whatsapp_cloud_text",
                new=AsyncMock(side_effect=WhatsAppCloudSendError("status=400")),
            ):
                with patch(
                    "app.whatsapp_cloud_routes.save_failed_outbox_item",
                    new=AsyncMock(),
                ) as save_mock:
                    with self.assertRaises(WhatsAppCloudSendError):
                        asyncio.run(
                            _send_whatsapp_cloud_reply_with_outbox(
                                message,
                                "reply text",
                                config,
                            )
                        )

        save_mock.assert_awaited_once()
        item = save_mock.call_args.args[0]
        self.assertEqual(item.client_id, "client-id")
        self.assertEqual(item.wa_id, "77780400008")
        self.assertEqual(item.send_to, "787780400008")
        self.assertEqual(item.phone_number_id, "12345")
        self.assertEqual(item.message_id, "wamid.test")
        self.assertEqual(item.reply_text, "reply text")
        self.assertEqual(item.attempts, 1)
        self.assertIn("WhatsAppCloudSendError", item.last_error)

    def test_successful_send_does_not_create_outbox_item(self):
        message = WhatsAppCloudInboundTextMessage(
            wa_id="77780400008",
            message_id="wamid.test",
            timestamp="1710000000",
            message_type="text",
            text_body="customer text",
            phone_number_id="12345",
        )
        config = WhatsAppCloudConfig(
            access_token="test-token",
            client_id="client-id",
            phone_number_id="12345",
            api_version="v25.0",
        )

        with patch(
            "app.whatsapp_cloud_routes.send_whatsapp_cloud_text",
            new=AsyncMock(),
        ):
            with patch(
                "app.whatsapp_cloud_routes.save_failed_outbox_item",
                new=AsyncMock(),
            ) as save_mock:
                asyncio.run(
                    _send_whatsapp_cloud_reply_with_outbox(
                        message,
                        "reply text",
                        config,
                    )
                )

        save_mock.assert_not_awaited()

    def test_whatsapp_policy_blocks_aggressive_competitor_language(self):
        self.assertIn("Не обесценивай конкурентов", WHATSAPP_CLOUD_RESPONSE_POLICY)
        self.assertIn("Максимум 450–600 символов", WHATSAPP_CLOUD_RESPONSE_POLICY)

        reply = _normalize_whatsapp_reply(
            "Мы лучший вариант, конкуренты просто делают плохо и не знают все нюансы. "
            "Сделаем идеально под вас."
        )
        lowered = reply.lower()

        self.assertNotIn("лучший", lowered)
        self.assertNotIn("конкуренты просто", lowered)
        self.assertNotIn("делают плохо", lowered)
        self.assertNotIn("все нюансы", lowered)
        self.assertNotIn("идеально", lowered)

    def test_whatsapp_reply_length_guard(self):
        reply = _normalize_whatsapp_reply("А" * 900)

        self.assertLessEqual(len(reply), 700)

    def test_bath_context_removes_wrong_niche_examples(self):
        reply = _normalize_whatsapp_reply(
            (
                "Да, быстрый шаблон можно поставить за 2 часа. Но конкуренты просто делают плохо. "
                "Например, для маникюра можно настроить запись и услуги. "
                "А для вашей бани лучше учесть бронь, парилку, тарифы и часы работы. "
                "Хотите, покажу на примере вашей бани?"
            ),
            user_text="У нас баня. Вы говорите 5 дней долго, конкуренты делают за 2 часа.",
        )
        lowered = reply.lower()

        self.assertNotIn("маникюр", lowered)
        self.assertNotIn("конкуренты просто", lowered)
        self.assertNotIn("делают плохо", lowered)
        self.assertIn("бани", lowered)
        self.assertLessEqual(len(reply), 600)

    def test_successful_ai_reply_is_not_replaced_with_manager_fallback(self):
        reply = _apply_manager_fallback_rules(
            user_text="Конкуренты делают за 2 часа",
            reply="Да, быстрый шаблон можно поставить за 2 часа.",
            history_before_reply=[{"role": "assistant", "content": "Нормальный предыдущий ответ"}],
        )

        self.assertEqual(reply, "Да, быстрый шаблон можно поставить за 2 часа.")
        self.assertNotEqual(reply, SAFE_CLAUDE_FALLBACK)

    def test_manager_fallback_after_two_empty_fallbacks(self):
        reply = _apply_manager_fallback_rules(
            user_text="Не понял",
            reply=EMPTY_CLAUDE_FALLBACK,
            history_before_reply=[{"role": "assistant", "content": EMPTY_CLAUDE_FALLBACK}],
        )

        self.assertEqual(reply, SAFE_CLAUDE_FALLBACK)

    def test_manager_fallback_when_client_requests_manager(self):
        reply = _apply_manager_fallback_rules(
            user_text="Позовите менеджера",
            reply="Могу подсказать по срокам.",
            history_before_reply=[],
        )

        self.assertEqual(reply, SAFE_CLAUDE_FALLBACK)


class WhatsAppCloudDebounceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        whatsapp_cloud_routes._pending_memory.clear()
        whatsapp_cloud_routes._pending_memory_locks.clear()
        whatsapp_cloud_routes._store._fallback.clear()
        whatsapp_cloud_routes._store._seen_mids.clear()
        whatsapp_cloud_routes._store._redis = None

    async def test_three_fast_messages_send_one_reply(self):
        send_mock = AsyncMock()
        ask_mock = AsyncMock(return_value=("Понимаю. 5 дней — это срок под рабочий бот, а не сырой шаблон.", False, "cold"))

        with self._patch_processing_dependencies(ask_mock=ask_mock, send_mock=send_mock):
            await asyncio.gather(
                _enqueue_text_message(_message("wa-1", "wamid.1", "Вы говорите 5 дней долго")),
                _enqueue_text_message(_message("wa-1", "wamid.2", "Конкуренты делают за 2 часа")),
                _enqueue_text_message(_message("wa-1", "wamid.3", "Почему так?")),
            )

        ask_mock.assert_awaited_once()
        send_mock.assert_awaited_once()
        self.assertEqual(
            ask_mock.call_args.args[1],
            "Вы говорите 5 дней долго\nКонкуренты делают за 2 часа\nПочему так?",
        )

    async def test_duplicate_message_id_is_not_processed_twice(self):
        send_mock = AsyncMock()
        ask_mock = AsyncMock(return_value=("Ответ один.", False, "cold"))

        with self._patch_processing_dependencies(ask_mock=ask_mock, send_mock=send_mock):
            await _enqueue_text_message(_message("wa-1", "wamid.same", "Первое"))
            await _enqueue_text_message(_message("wa-1", "wamid.same", "Дубль"))

        ask_mock.assert_awaited_once()
        send_mock.assert_awaited_once()
        self.assertEqual(ask_mock.call_args.args[1], "Первое")

    async def test_different_wa_ids_are_processed_separately(self):
        send_mock = AsyncMock()
        ask_mock = AsyncMock(return_value=("Ответ.", False, "cold"))

        with self._patch_processing_dependencies(ask_mock=ask_mock, send_mock=send_mock):
            await asyncio.gather(
                _enqueue_text_message(_message("wa-1", "wamid.wa1", "Первый клиент")),
                _enqueue_text_message(_message("wa-2", "wamid.wa2", "Второй клиент")),
            )

        self.assertEqual(ask_mock.await_count, 2)
        self.assertEqual(send_mock.await_count, 2)
        sent_texts = sorted(call.args[1] for call in ask_mock.await_args_list)
        self.assertEqual(sent_texts, ["Второй клиент", "Первый клиент"])

    async def test_redis_unavailable_falls_back_safely(self):
        send_mock = AsyncMock()
        ask_mock = AsyncMock(return_value=("Ответ из fallback.", False, "cold"))
        whatsapp_cloud_routes._store._redis = _FailingRedis()

        with self._patch_processing_dependencies(ask_mock=ask_mock, send_mock=send_mock):
            await asyncio.gather(
                _enqueue_text_message(_message("wa-1", "wamid.fallback.1", "Раз")),
                _enqueue_text_message(_message("wa-1", "wamid.fallback.2", "Два")),
            )

        ask_mock.assert_awaited_once()
        send_mock.assert_awaited_once()
        self.assertEqual(ask_mock.call_args.args[1], "Раз\nДва")

    def _patch_processing_dependencies(self, *, ask_mock: AsyncMock, send_mock: AsyncMock):
        return _CombinedPatches(
            patch.dict(
                os.environ,
                {
                    "WHATSAPP_CLOUD_ACCESS_TOKEN": "test-token",
                    "WHATSAPP_CLOUD_DEFAULT_CLIENT_ID": "client-id",
                    "WHATSAPP_CLOUD_PHONE_NUMBER_ID": "phone-id",
                },
                clear=True,
            ),
            patch("app.whatsapp_cloud_routes._get_debounce_delay_seconds", return_value=0.01),
            patch("app.whatsapp_cloud_routes.async_session_factory", _FakeSessionFactory),
            patch("app.whatsapp_cloud_routes.client_service.get_by_id", new=AsyncMock(return_value=_FakeClient())),
            patch("app.whatsapp_cloud_routes.client_service.get_or_create_conversation", new=AsyncMock(return_value=_FakeConversation())),
            patch("app.whatsapp_cloud_routes.client_service.save_message", new=AsyncMock()),
            patch("app.whatsapp_cloud_routes.client_service.save_lead", new=AsyncMock()),
            patch("app.whatsapp_cloud_routes.ask_claude", new=ask_mock),
            patch("app.whatsapp_cloud_routes._send_whatsapp_cloud_reply_with_outbox", new=send_mock),
            patch("app.whatsapp_cloud_routes.send_lead_notification", new=AsyncMock()),
        )


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


class _FakeClient:
    id = "client-id"
    status = "active"
    whatsapp_system_prompt = ""
    system_prompt = "Base prompt"
    telegram_manager_chat_id = ""
    whatsapp_link = ""


class _FakeConversation:
    id = "conversation-id"


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, *args, **kwargs):
        return None

    async def commit(self):
        return None


def _FakeSessionFactory():
    return _FakeSession()


class _FailingRedis:
    async def get(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    async def set(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    async def rpush(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    async def lrange(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    async def llen(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    async def setnx(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    async def expire(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")

    async def delete(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")


class _CombinedPatches:
    def __init__(self, *patches):
        self._patches = patches

    def __enter__(self):
        for patcher in self._patches:
            patcher.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        for patcher in reversed(self._patches):
            patcher.__exit__(exc_type, exc, tb)
        return False


def _message(wa_id: str, message_id: str, text: str) -> WhatsAppCloudInboundTextMessage:
    return WhatsAppCloudInboundTextMessage(
        wa_id=wa_id,
        message_id=message_id,
        timestamp="1710000000",
        message_type="text",
        text_body=text,
        phone_number_id="phone-id",
    )


if __name__ == "__main__":
    unittest.main()
