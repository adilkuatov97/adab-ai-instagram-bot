from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services.whatsapp_cloud_outbox import WhatsAppCloudOutboxItem
from app.services.whatsapp_cloud_outbox_retry import retry_outbox_item
from app.services.whatsapp_cloud_service import WhatsAppCloudSendError


class WhatsAppCloudOutboxRetryTest(unittest.TestCase):
    def test_retry_success_deletes_item(self):
        item = _item("item-1")

        with patch(
            "app.services.whatsapp_cloud_outbox_retry.load_outbox_item",
            new=AsyncMock(return_value=item),
        ):
            with patch(
                "app.services.whatsapp_cloud_outbox_retry.send_whatsapp_cloud_text",
                new=AsyncMock(),
            ) as send_mock:
                with patch(
                    "app.services.whatsapp_cloud_outbox_retry.delete_outbox_item",
                    new=AsyncMock(),
                ) as delete_mock:
                    with patch.dict(
                        "os.environ",
                        {
                            "WHATSAPP_CLOUD_ACCESS_TOKEN": "test-token",
                            "WHATSAPP_CLOUD_API_VERSION": "v25.0",
                        },
                        clear=True,
                    ):
                        ok = asyncio.run(retry_outbox_item("item-1"))

        self.assertTrue(ok)
        send_mock.assert_awaited_once_with(
            to="787780400008",
            text="reply text",
            phone_number_id="12345",
            access_token="test-token",
            api_version="v25.0",
        )
        delete_mock.assert_awaited_once_with("item-1")

    def test_retry_failure_increments_attempts(self):
        item = _item("item-1")

        with patch(
            "app.services.whatsapp_cloud_outbox_retry.load_outbox_item",
            new=AsyncMock(return_value=item),
        ):
            with patch(
                "app.services.whatsapp_cloud_outbox_retry.send_whatsapp_cloud_text",
                new=AsyncMock(side_effect=WhatsAppCloudSendError("status=400")),
            ):
                with patch(
                    "app.services.whatsapp_cloud_outbox_retry.increment_outbox_item_attempts",
                    new=AsyncMock(),
                ) as increment_mock:
                    with patch.dict(
                        "os.environ",
                        {"WHATSAPP_CLOUD_ACCESS_TOKEN": "test-token"},
                        clear=True,
                    ):
                        ok = asyncio.run(retry_outbox_item("item-1"))

        self.assertFalse(ok)
        increment_mock.assert_awaited_once()
        self.assertEqual(increment_mock.call_args.args[0], "item-1")
        self.assertIn("WhatsAppCloudSendError", increment_mock.call_args.args[1])


def _item(item_id: str):
    return WhatsAppCloudOutboxItem(
        id=item_id,
        client_id="client-id",
        wa_id="77780400008",
        send_to="787780400008",
        phone_number_id="12345",
        message_id="wamid.test",
        reply_text="reply text",
        created_at="2026-06-05T10:00:00+00:00",
        last_error="WhatsAppCloudSendError: status=400",
        attempts=1,
    )


if __name__ == "__main__":
    unittest.main()
