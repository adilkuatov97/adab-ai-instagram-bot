from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.whatsapp_cloud_routes import (
    WhatsAppCloudConfig,
    WhatsAppCloudInboundTextMessage,
    _extract_text_messages,
    _extract_webhook_metadata,
    _is_valid_signature,
    _mark_message_for_processing,
    _send_whatsapp_cloud_reply,
    resolve_whatsapp_cloud_send_to,
)


class WhatsAppCloudRoutesTest(unittest.TestCase):
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
            default_client_id="client-id",
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


if __name__ == "__main__":
    unittest.main()
