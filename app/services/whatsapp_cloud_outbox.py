from __future__ import annotations

import json
import logging
import os
import time
import inspect
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "")
FAILED_OUTBOX_ZSET_KEY = "whatsapp_cloud:outbox:failed:zset"
FAILED_OUTBOX_ITEM_KEY_PREFIX = "whatsapp_cloud:outbox:failed:item:"

_redis_client = None
_redis_checked = False


@dataclass(frozen=True)
class WhatsAppCloudOutboxItem:
    id: str
    client_id: str
    wa_id: str
    send_to: str
    phone_number_id: str
    message_id: str | None
    reply_text: str
    created_at: str
    last_error: str
    attempts: int


def serialize_outbox_item(item: WhatsAppCloudOutboxItem) -> str:
    return json.dumps(asdict(item), separators=(",", ":"))


def deserialize_outbox_item(raw: str) -> WhatsAppCloudOutboxItem:
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid WhatsApp Cloud outbox JSON") from exc

    if not isinstance(data, dict):
        raise ValueError("Invalid WhatsApp Cloud outbox payload")

    try:
        return WhatsAppCloudOutboxItem(
            id=_required_str(data, "id"),
            client_id=_required_str(data, "client_id"),
            wa_id=_required_str(data, "wa_id"),
            send_to=_required_str(data, "send_to"),
            phone_number_id=_required_str(data, "phone_number_id"),
            message_id=_optional_str(data, "message_id"),
            reply_text=_required_str(data, "reply_text"),
            created_at=_required_str(data, "created_at"),
            last_error=_required_str(data, "last_error"),
            attempts=_required_int(data, "attempts"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid WhatsApp Cloud outbox payload") from exc


async def save_failed_outbox_item(item: WhatsAppCloudOutboxItem) -> None:
    redis = await _get_redis_client()
    if redis is None:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_SAVE_SKIP redis_available=false")
        return

    item_key = _item_key(item.id)
    try:
        await redis.set(item_key, serialize_outbox_item(item))
        await redis.zadd(FAILED_OUTBOX_ZSET_KEY, {item.id: _created_at_score_ms(item.created_at)})
        logger.info(
            "WHATSAPP_CLOUD_OUTBOX_SAVE_OK item_id=%s client_id=%s message_id=%s",
            item.id,
            item.client_id,
            item.message_id,
        )
    except Exception as exc:
        logger.warning(
            "WHATSAPP_CLOUD_OUTBOX_SAVE_ERROR item_id=%s error=%s",
            item.id,
            exc.__class__.__name__,
        )


async def load_outbox_item(item_id: str) -> WhatsAppCloudOutboxItem | None:
    redis = await _get_redis_client()
    if redis is None:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_LOAD_SKIP redis_available=false")
        return None

    try:
        raw = await redis.get(_item_key(item_id))
    except Exception as exc:
        logger.warning(
            "WHATSAPP_CLOUD_OUTBOX_LOAD_ERROR item_id=%s error=%s",
            item_id,
            exc.__class__.__name__,
        )
        return None

    if not raw:
        return None

    try:
        return deserialize_outbox_item(raw)
    except ValueError:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_LOAD_INVALID item_id=%s", item_id)
        return None


async def list_outbox_items(limit: int = 20) -> list[WhatsAppCloudOutboxItem]:
    redis = await _get_redis_client()
    if redis is None:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_LIST_SKIP redis_available=false")
        return []

    safe_limit = max(0, min(limit, 100))
    if safe_limit == 0:
        return []

    try:
        item_ids = await redis.zrevrange(FAILED_OUTBOX_ZSET_KEY, 0, safe_limit - 1)
    except Exception as exc:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_LIST_ERROR error=%s", exc.__class__.__name__)
        return []

    items: list[WhatsAppCloudOutboxItem] = []
    for item_id in item_ids:
        item = await load_outbox_item(str(item_id))
        if item is not None:
            items.append(item)
    return items


async def count_outbox_items() -> int | None:
    redis = await _get_redis_client()
    if redis is None:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_COUNT_SKIP redis_available=false")
        return None

    try:
        return int(await redis.zcard(FAILED_OUTBOX_ZSET_KEY))
    except Exception as exc:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_COUNT_ERROR error=%s", exc.__class__.__name__)
        return None


async def delete_outbox_item(item_id: str) -> None:
    redis = await _get_redis_client()
    if redis is None:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_DELETE_SKIP redis_available=false")
        return

    try:
        await redis.delete(_item_key(item_id))
        await redis.zrem(FAILED_OUTBOX_ZSET_KEY, item_id)
        logger.info("WHATSAPP_CLOUD_OUTBOX_DELETE_OK item_id=%s", item_id)
    except Exception as exc:
        logger.warning(
            "WHATSAPP_CLOUD_OUTBOX_DELETE_ERROR item_id=%s error=%s",
            item_id,
            exc.__class__.__name__,
        )


async def increment_outbox_item_attempts(item_id: str, last_error: str) -> None:
    item = await load_outbox_item(item_id)
    if item is None:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_INCREMENT_SKIP item_found=false item_id=%s", item_id)
        return

    redis = await _get_redis_client()
    if redis is None:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_INCREMENT_SKIP redis_available=false")
        return

    updated = WhatsAppCloudOutboxItem(
        id=item.id,
        client_id=item.client_id,
        wa_id=item.wa_id,
        send_to=item.send_to,
        phone_number_id=item.phone_number_id,
        message_id=item.message_id,
        reply_text=item.reply_text,
        created_at=item.created_at,
        last_error=_truncate_error(last_error),
        attempts=item.attempts + 1,
    )

    try:
        await redis.set(_item_key(item_id), serialize_outbox_item(updated))
        await redis.zadd(FAILED_OUTBOX_ZSET_KEY, {item_id: int(time.time() * 1000)})
        logger.info(
            "WHATSAPP_CLOUD_OUTBOX_INCREMENT_OK item_id=%s attempts=%d",
            item_id,
            updated.attempts,
        )
    except Exception as exc:
        logger.warning(
            "WHATSAPP_CLOUD_OUTBOX_INCREMENT_ERROR item_id=%s error=%s",
            item_id,
            exc.__class__.__name__,
        )


async def close_outbox_redis_client() -> None:
    global _redis_checked, _redis_client

    redis = _redis_client
    _redis_client = None
    _redis_checked = False

    if redis is None:
        return

    close_method = getattr(redis, "aclose", None) or getattr(redis, "close", None)
    if close_method is None:
        return

    try:
        result = close_method()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_REDIS_CLOSE_ERROR error=%s", exc.__class__.__name__)


async def _get_redis_client():
    global _redis_checked, _redis_client

    if _redis_checked:
        return _redis_client

    _redis_checked = True
    if not REDIS_URL:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_REDIS_MISSING")
        return None

    try:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    except Exception as exc:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_REDIS_INIT_ERROR error=%s", exc.__class__.__name__)
        _redis_client = None

    return _redis_client


def _item_key(item_id: str) -> str:
    return f"{FAILED_OUTBOX_ITEM_KEY_PREFIX}{item_id}"


def _created_at_score_ms(created_at: str) -> int:
    try:
        normalized = created_at.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp() * 1000)
    except ValueError:
        return int(time.time() * 1000)


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing string field: {key}")
    return value


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid string field: {key}")
    return value


def _required_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Missing int field: {key}")
    return value


def _truncate_error(last_error: str) -> str:
    return last_error.replace("\n", " ").replace("\r", " ").strip()[:500]
