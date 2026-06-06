from __future__ import annotations

import asyncio
import unittest

from app.services import whatsapp_cloud_outbox
from app.services.whatsapp_cloud_outbox import (
    FAILED_OUTBOX_ZSET_KEY,
    WhatsAppCloudOutboxItem,
    close_outbox_redis_client,
    delete_outbox_item,
    deserialize_outbox_item,
    increment_outbox_item_attempts,
    count_outbox_items,
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

    async def delete(self, key):
        self.values.pop(key, None)

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

    async def zrem(self, key, member):
        self.zsets.get(key, {}).pop(member, None)

    async def zcard(self, key):
        return len(self.zsets.get(key, {}))


class _AsyncCloseRedis(_FakeRedis):
    def __init__(self):
        super().__init__()
        self.closed = False

    async def aclose(self):
        self.closed = True


class _SyncCloseRedis(_FakeRedis):
    def __init__(self):
        super().__init__()
        self.closed = False

    def close(self):
        self.closed = True


class _FailingCloseRedis(_FakeRedis):
    async def aclose(self):
        raise RuntimeError("close failed")


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

    def test_delete_outbox_item_removes_item_and_zset_member(self):
        item = _item("delete-me")

        asyncio.run(save_failed_outbox_item(item))
        asyncio.run(delete_outbox_item("delete-me"))

        self.assertIsNone(asyncio.run(load_outbox_item("delete-me")))
        self.assertNotIn("delete-me", self.fake_redis.zsets[FAILED_OUTBOX_ZSET_KEY])

    def test_increment_outbox_item_attempts_updates_error(self):
        item = _item("retry-me")

        asyncio.run(save_failed_outbox_item(item))
        asyncio.run(increment_outbox_item_attempts("retry-me", "new error\nwith newline"))
        updated = asyncio.run(load_outbox_item("retry-me"))

        self.assertIsNotNone(updated)
        self.assertEqual(updated.attempts, 2)
        self.assertEqual(updated.last_error, "new error with newline")

    def test_count_outbox_items_with_fake_redis(self):
        asyncio.run(save_failed_outbox_item(_item("item-1")))
        asyncio.run(save_failed_outbox_item(_item("item-2")))

        self.assertEqual(asyncio.run(count_outbox_items()), 2)

    def test_close_outbox_redis_client_resets_cached_state(self):
        redis = _AsyncCloseRedis()
        whatsapp_cloud_outbox._redis_client = redis
        whatsapp_cloud_outbox._redis_checked = True

        asyncio.run(close_outbox_redis_client())

        self.assertTrue(redis.closed)
        self.assertIsNone(whatsapp_cloud_outbox._redis_client)
        self.assertFalse(whatsapp_cloud_outbox._redis_checked)

    def test_close_outbox_redis_client_supports_sync_close(self):
        redis = _SyncCloseRedis()
        whatsapp_cloud_outbox._redis_client = redis
        whatsapp_cloud_outbox._redis_checked = True

        asyncio.run(close_outbox_redis_client())

        self.assertTrue(redis.closed)
        self.assertIsNone(whatsapp_cloud_outbox._redis_client)
        self.assertFalse(whatsapp_cloud_outbox._redis_checked)

    def test_close_outbox_redis_client_failure_does_not_crash(self):
        redis = _FailingCloseRedis()
        whatsapp_cloud_outbox._redis_client = redis
        whatsapp_cloud_outbox._redis_checked = True

        asyncio.run(close_outbox_redis_client())

        self.assertIsNone(whatsapp_cloud_outbox._redis_client)
        self.assertFalse(whatsapp_cloud_outbox._redis_checked)


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
