from __future__ import annotations

import unittest

from app.scripts.whatsapp_cloud_outbox import format_outbox_item, mask_phone
from app.services.whatsapp_cloud_outbox import WhatsAppCloudOutboxItem


class WhatsAppCloudOutboxCliTest(unittest.TestCase):
    def test_mask_phone(self):
        self.assertEqual(mask_phone("77780400008"), "***0008")
        self.assertEqual(mask_phone("123"), "***")

    def test_format_outbox_item_masks_numbers_and_hides_reply_text(self):
        item = WhatsAppCloudOutboxItem(
            id="item-1",
            client_id="client-id",
            wa_id="77780400008",
            send_to="787780400008",
            phone_number_id="12345",
            message_id="wamid.test",
            reply_text="secret reply text",
            created_at="2026-06-05T10:00:00+00:00",
            last_error="WhatsAppCloudSendError: status=400",
            attempts=2,
        )

        line = format_outbox_item(item)

        self.assertIn("wa_id=***0008", line)
        self.assertIn("send_to=***0008", line)
        self.assertNotIn("77780400008", line)
        self.assertNotIn("787780400008", line)
        self.assertNotIn("secret reply text", line)


if __name__ == "__main__":
    unittest.main()
