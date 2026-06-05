from __future__ import annotations

import asyncio
import unittest

from app.services import whatsapp_cloud_outbox
from app.services.whatsapp_cloud_outbox import (
    FAILED_OUTBOX_ZSET_KEY,
    WhatsAppCloudOutboxItem,
    deserialize_outbox_item,
    list_outbox_items,
    load_outbox_item,
    save_failed_outbox_item,
    serialize_outbox_item,
)


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.zsets: dict[str, dict[str, int]] = {}

    async def set(self, key, value):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    async def zrevrange(self, key, start, end):
        members = sorted(
            self.zsets.get(key, {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if end == -1:
            selected = members[start:]
        else:
            selected = members[start : end + 1]
        return [member for member, _score in selected]


class WhatsAppCloudOutboxTest(unittest.TestCase):
    def setUp(self):
        self._original_client = whatsapp_cloud_outbox._redis_client
        self._original_checked = whatsapp_cloud_outbox._redis_checked
        self.fake_redis = _FakeRedis()
        whatsapp_cloud_outbox._redis_client = self.fake_redis
        whatsapp_cloud_outbox._redis_checked = True

    def tearDown(self):
        whatsapp_cloud_outbox._redis_client = self._original_client
        whatsapp_cloud_outbox._redis_checked = self._original_checked

    def test_serialize_deserialize_outbox_item(self):
        item = _item("item-1")

        raw = serialize_outbox_item(item)
        parsed = deserialize_outbox_item(raw)

        self.assertEqual(parsed, item)

    def test_invalid_json_rejected_safely(self):
        with self.assertRaises(ValueError):
            deserialize_outbox_item("not-json")

        with self.assertRaises(ValueError):
            deserialize_outbox_item("{}")

    def test_save_load_list_with_fake_redis(self):
        older = _item("older", created_at="2026-06-05T10:00:00+00:00")
        newer = _item("newer", created_at="2026-06-05T11:00:00+00:00")

        asyncio.run(save_failed_outbox_item(older))
        asyncio.run(save_failed_outbox_item(newer))

        loaded = asyncio.run(load_outbox_item("older"))
        listed = asyncio.run(list_outbox_items(limit=10))

        self.assertEqual(loaded, older)
        self.assertEqual([item.id for item in listed], ["newer", "older"])
        self.assertIn("older", self.fake_redis.zsets[FAILED_OUTBOX_ZSET_KEY])


def _item(item_id: str, created_at: str = "2026-06-05T10:00:00+00:00"):
    return WhatsAppCloudOutboxItem(
        id=item_id,
        client_id="client-id",
        wa_id="77780400008",
        send_to="787780400008",
        phone_number_id="12345",
        message_id="wamid.test",
        reply_text="reply text",
        created_at=created_at,
        last_error="WhatsAppCloudSendError: status=400",
        attempts=1,
    )


if __name__ == "__main__":
    unittest.main()
