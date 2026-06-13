from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import update as sa_update

from app.db.database import async_session_factory
from app.db.models import Lead
from app.services import client_service
from app.services.claude_service import EMPTY_CLAUDE_FALLBACK, SAFE_CLAUDE_FALLBACK, ask_claude
from app.services.conversation_store import ConversationStore
from app.services.telegram_service import send_lead_notification
from app.services.whatsapp_cloud_outbox import (
    WhatsAppCloudOutboxItem,
    count_outbox_items,
    save_failed_outbox_item,
)
from app.services.whatsapp_cloud_service import (
    DEFAULT_WHATSAPP_CLOUD_API_VERSION,
    WhatsAppCloudSendError,
    send_whatsapp_cloud_text,
)

logger = logging.getLogger(__name__)

WHATSAPP_CLOUD_VERIFY_TOKEN_ENV = "WHATSAPP_CLOUD_VERIFY_TOKEN"
WHATSAPP_CLOUD_APP_SECRET_ENV = "WHATSAPP_CLOUD_APP_SECRET"
WHATSAPP_CLOUD_ACCESS_TOKEN_ENV = "WHATSAPP_CLOUD_ACCESS_TOKEN"
WHATSAPP_CLOUD_PHONE_NUMBER_ID_ENV = "WHATSAPP_CLOUD_PHONE_NUMBER_ID"
WHATSAPP_CLOUD_DEFAULT_CLIENT_ID_ENV = "WHATSAPP_CLOUD_DEFAULT_CLIENT_ID"
WHATSAPP_CLOUD_API_VERSION_ENV = "WHATSAPP_CLOUD_API_VERSION"
WHATSAPP_CLOUD_RECIPIENT_OVERRIDES_ENV = "WHATSAPP_CLOUD_RECIPIENT_OVERRIDES"
WHATSAPP_CLOUD_CLIENT_MAP_ENV = "WHATSAPP_CLOUD_CLIENT_MAP"
WHATSAPP_CLOUD_DEBOUNCE_SECONDS_ENV = "WHATSAPP_CLOUD_DEBOUNCE_SECONDS"
WHATSAPP_CLOUD_LOCK_TTL_SECONDS_ENV = "WHATSAPP_CLOUD_LOCK_TTL_SECONDS"
PRODUCTION_ENV_NAMES = {"production", "prod", "live"}
REDIS_URL = os.getenv("REDIS_URL", "")
PENDING_BUFFER_TTL_SECONDS = 30
DEFAULT_WHATSAPP_CLOUD_DEBOUNCE_SECONDS = 3.0
DEFAULT_WHATSAPP_CLOUD_LOCK_TTL_SECONDS = 120
WHATSAPP_CLOUD_RESPONSE_POLICY = """

═══════════════════════════════════════
WHATSAPP RESPONSE POLICY

Пиши как живой менеджер в WhatsApp: спокойно, уверенно, конкретно.
Максимум 450–600 символов.
Одна мысль = один короткий ответ.
Не повторяй CTA в каждом сообщении.
Не дави на Zoom/созвон сразу.
Если клиент возражает — сначала признай возражение, потом спокойно объясни разницу.
Не обесценивай конкурентов.
Не используй фразы "идеально", "лучший", "все нюансы" без доказательств.
Не звучать как агрессивный продажник.
Не перечисляй всё подряд, не пиши воду.
Если несколько сообщений клиента объединены, отвечай одним цельным сообщением.
В конце максимум один мягкий вопрос.

Если клиент говорит, что конкуренты делают за 2 часа, стиль такой:
"Да, быстрый шаблон можно поставить за 2 часа. Разница в том, что мы не просто подключаем кнопки, а настраиваем ответы под ваш бизнес: услуги, цены, бронирование и частые вопросы. Можно начать с быстрого MVP, а затем за несколько дней довести до нормального качества. Хотите, покажу разницу на вашем примере?"
"""
BANNED_WHATSAPP_REPLY_PHRASES = (
    "идеально",
    "лучший",
    "все нюансы",
    "конкуренты просто",
    "делают плохо",
    "не знают",
    "конкуренты делают плохо",
    "у конкурентов плохо",
)

router = APIRouter()
_store = ConversationStore(REDIS_URL)
_pending_memory: dict[str, list[dict[str, Any]]] = {}
_pending_memory_locks: dict[str, float] = {}
_pending_memory_guard = asyncio.Lock()


@dataclass(frozen=True)
class WhatsAppCloudWebhookMetadata:
    object_name: str | None
    entry_count: int
    messages_exist: bool
    message_type: str | None


@dataclass(frozen=True)
class WhatsAppCloudInboundTextMessage:
    wa_id: str
    message_id: str
    timestamp: str | None
    message_type: str
    text_body: str
    phone_number_id: str | None


@dataclass(frozen=True)
class WhatsAppCloudPendingTextMessage:
    wa_id: str
    message_id: str
    timestamp: str | None
    text_body: str
    phone_number_id: str | None
    queued_at: float


@dataclass(frozen=True)
class WhatsAppCloudConfig:
    access_token: str
    client_id: str
    phone_number_id: str
    api_version: str


def _get_env(name: str) -> str:
    return os.getenv(name, "").strip()


def _get_cloud_api_version() -> str:
    return _get_env(WHATSAPP_CLOUD_API_VERSION_ENV) or DEFAULT_WHATSAPP_CLOUD_API_VERSION


def _get_debounce_delay_seconds() -> float:
    return _get_float_env(
        WHATSAPP_CLOUD_DEBOUNCE_SECONDS_ENV,
        DEFAULT_WHATSAPP_CLOUD_DEBOUNCE_SECONDS,
        min_value=2.0,
        max_value=4.0,
    )


def _get_lock_ttl_seconds() -> int:
    return int(
        _get_float_env(
            WHATSAPP_CLOUD_LOCK_TTL_SECONDS_ENV,
            float(DEFAULT_WHATSAPP_CLOUD_LOCK_TTL_SECONDS),
            min_value=10.0,
            max_value=300.0,
        )
    )


def _get_float_env(name: str, default: float, *, min_value: float, max_value: float) -> float:
    raw = _get_env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("WHATSAPP_CLOUD_ENV_FLOAT_INVALID name=%s", name)
        return default
    return max(min_value, min(value, max_value))


def _is_production_environment() -> bool:
    raw = (
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENVIRONMENT")
        or os.getenv("NODE_ENV")
        or ""
    )
    return raw.strip().lower() in PRODUCTION_ENV_NAMES


def resolve_whatsapp_cloud_send_to(wa_id: str) -> str:
    overrides = _get_env(WHATSAPP_CLOUD_RECIPIENT_OVERRIDES_ENV)
    if not overrides:
        return wa_id
    if _is_production_environment():
        logger.error("WHATSAPP_CLOUD_RECIPIENT_OVERRIDE_IGNORED production=true")
        return wa_id

    for raw_pair in overrides.split(","):
        pair = raw_pair.strip()
        if ":" not in pair:
            continue

        source, target = pair.split(":", 1)
        source = source.strip()
        target = target.strip()
        if not source or not target:
            continue

        if source == wa_id:
            return target

    return wa_id


def resolve_whatsapp_cloud_client_id(phone_number_id: str | None) -> str | None:
    client_map = _get_env(WHATSAPP_CLOUD_CLIENT_MAP_ENV)
    if phone_number_id and client_map:
        for raw_pair in client_map.split(","):
            pair = raw_pair.strip()
            if ":" not in pair:
                continue

            source, target = pair.split(":", 1)
            source = source.strip()
            target = target.strip()
            if not source or not target:
                continue

            if source == phone_number_id:
                logger.info("WHATSAPP_CLOUD_CLIENT_RESOLVED source=phone_number_id_map")
                return target

    fallback_client_id = _get_env(WHATSAPP_CLOUD_DEFAULT_CLIENT_ID_ENV)
    if fallback_client_id:
        logger.info("WHATSAPP_CLOUD_CLIENT_RESOLVED source=default_client_id")
        return fallback_client_id

    logger.warning("WHATSAPP_CLOUD_CLIENT_RESOLVED source=none")
    return None


def _get_processing_config(payload_phone_number_id: str | None) -> WhatsAppCloudConfig | None:
    access_token = _get_env(WHATSAPP_CLOUD_ACCESS_TOKEN_ENV)
    client_id = resolve_whatsapp_cloud_client_id(payload_phone_number_id)
    phone_number_id = payload_phone_number_id or _get_env(WHATSAPP_CLOUD_PHONE_NUMBER_ID_ENV)
    missing = []
    if not access_token:
        missing.append(WHATSAPP_CLOUD_ACCESS_TOKEN_ENV)
    if not client_id:
        missing.append("whatsapp_cloud_client_id")
    if not phone_number_id:
        missing.append(WHATSAPP_CLOUD_PHONE_NUMBER_ID_ENV)

    if missing:
        logger.error("WHATSAPP_CLOUD_CONFIG_MISSING vars=%s", ",".join(missing))
        return None

    return WhatsAppCloudConfig(
        access_token=access_token,
        client_id=client_id,
        phone_number_id=phone_number_id,
        api_version=_get_cloud_api_version(),
    )


def _is_whatsapp_cloud_client_configured() -> bool:
    return bool(_get_env(WHATSAPP_CLOUD_DEFAULT_CLIENT_ID_ENV) or _get_env(WHATSAPP_CLOUD_CLIENT_MAP_ENV))


def _is_valid_signature(raw_body: bytes, signature: str, app_secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def _extract_webhook_metadata(payload: dict[str, Any]) -> WhatsAppCloudWebhookMetadata:
    entries = payload.get("entry")
    if not isinstance(entries, list):
        entries = []

    message_type: str | None = None
    messages_exist = False

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue

        for change in changes:
            if not isinstance(change, dict):
                continue

            value = change.get("value")
            if not isinstance(value, dict):
                continue

            messages = value.get("messages")
            if not isinstance(messages, list) or not messages:
                continue

            messages_exist = True
            first_message = messages[0]
            if isinstance(first_message, dict):
                raw_type = first_message.get("type")
                message_type = raw_type if isinstance(raw_type, str) else None
            return WhatsAppCloudWebhookMetadata(
                object_name=_safe_object_name(payload),
                entry_count=len(entries),
                messages_exist=messages_exist,
                message_type=message_type,
            )

    return WhatsAppCloudWebhookMetadata(
        object_name=_safe_object_name(payload),
        entry_count=len(entries),
        messages_exist=messages_exist,
        message_type=message_type,
    )


def _extract_text_messages(payload: dict[str, Any]) -> list[WhatsAppCloudInboundTextMessage]:
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []

    parsed: list[WhatsAppCloudInboundTextMessage] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue

        for change in changes:
            if not isinstance(change, dict):
                continue

            value = change.get("value")
            if not isinstance(value, dict):
                continue

            metadata = value.get("metadata")
            phone_number_id = None
            if isinstance(metadata, dict):
                raw_phone_number_id = metadata.get("phone_number_id")
                phone_number_id = (
                    raw_phone_number_id if isinstance(raw_phone_number_id, str) else None
                )

            messages = value.get("messages")
            if not isinstance(messages, list):
                continue

            for message in messages:
                parsed_message = _parse_text_message(message, phone_number_id)
                if parsed_message is not None:
                    parsed.append(parsed_message)

    return parsed


def _parse_text_message(
    message: Any,
    phone_number_id: str | None,
) -> WhatsAppCloudInboundTextMessage | None:
    if not isinstance(message, dict):
        return None

    raw_type = message.get("type")
    if raw_type != "text":
        return None

    wa_id = message.get("from")
    message_id = message.get("id")
    text_payload = message.get("text")
    if not isinstance(wa_id, str) or not isinstance(message_id, str):
        return None
    if not isinstance(text_payload, dict):
        return None

    text_body = text_payload.get("body")
    if not isinstance(text_body, str) or not text_body.strip():
        return None

    raw_timestamp = message.get("timestamp")
    timestamp = raw_timestamp if isinstance(raw_timestamp, str) else None
    return WhatsAppCloudInboundTextMessage(
        wa_id=wa_id,
        message_id=message_id,
        timestamp=timestamp,
        message_type=raw_type,
        text_body=text_body,
        phone_number_id=phone_number_id,
    )


def _safe_object_name(payload: dict[str, Any]) -> str | None:
    object_name = payload.get("object")
    return object_name if isinstance(object_name, str) else None


async def _verify_signature_if_configured(request: Request, raw_body: bytes) -> None:
    app_secret = _get_env(WHATSAPP_CLOUD_APP_SECRET_ENV)
    if not app_secret:
        if _is_production_environment():
            logger.error("WHATSAPP_CLOUD_SIG_REJECT app_secret_configured=false production=true")
            raise HTTPException(
                status_code=503,
                detail="WhatsApp Cloud signature verification is not configured",
            )
        logger.warning("WHATSAPP_CLOUD_SIG_SKIP app_secret_configured=false production=false")
        return

    signature = request.headers.get("x-hub-signature-256", "")
    if not _is_valid_signature(raw_body, signature, app_secret):
        raise HTTPException(status_code=403, detail="Invalid WhatsApp Cloud signature")


async def _mark_message_for_processing(message_id: str) -> bool:
    redis_key = f"whatsapp_cloud:processed:{message_id}"
    mark_result = await _store.mark_once_redis(redis_key)
    if mark_result is None:
        logger.warning("WHATSAPP_CLOUD_IDEMPOTENCY_UNAVAILABLE message_id=%s", message_id)
        seen = await _store.is_seen(redis_key)
        if seen:
            logger.info("WHATSAPP_CLOUD_DUPLICATE_SKIPPED fallback=memory message_id=%s", message_id)
            return False
        return True
    if not mark_result:
        logger.info("WHATSAPP_CLOUD_DUPLICATE_SKIPPED message_id=%s", message_id)
        return False
    return True


def _pending_key(client_id: str, wa_id: str) -> str:
    return f"whatsapp_cloud:{client_id}:{wa_id}:pending"


def _pending_lock_key(client_id: str, wa_id: str) -> str:
    return f"whatsapp_cloud:{client_id}:{wa_id}:lock"


def _get_store_redis():
    return getattr(_store, "_redis", None)


async def _append_pending_text_message(
    config: WhatsAppCloudConfig,
    message: WhatsAppCloudInboundTextMessage,
) -> None:
    pending = WhatsAppCloudPendingTextMessage(
        wa_id=message.wa_id,
        message_id=message.message_id,
        timestamp=message.timestamp,
        text_body=message.text_body,
        phone_number_id=message.phone_number_id,
        queued_at=time.time(),
    )
    key = _pending_key(config.client_id, message.wa_id)
    redis = _get_store_redis()

    if redis is not None:
        try:
            await redis.rpush(key, json.dumps(_pending_message_to_dict(pending)))
            await redis.expire(key, PENDING_BUFFER_TTL_SECONDS)
            count = int(await redis.llen(key))
            logger.info(
                "WHATSAPP_CLOUD_PENDING_BUFFERED storage=redis client_id=%s wa_id=%s count=%d",
                config.client_id,
                message.wa_id,
                count,
            )
            return
        except Exception as exc:
            logger.warning(
                "WHATSAPP_CLOUD_PENDING_BUFFER_REDIS_ERROR error=%s",
                exc.__class__.__name__,
            )

    async with _pending_memory_guard:
        messages = _pending_memory.setdefault(key, [])
        messages.append(_pending_message_to_dict(pending))
        logger.info(
            "WHATSAPP_CLOUD_PENDING_BUFFERED storage=memory client_id=%s wa_id=%s count=%d",
            config.client_id,
            message.wa_id,
            len(messages),
        )


async def _pop_pending_text_messages(
    client_id: str,
    wa_id: str,
) -> list[WhatsAppCloudPendingTextMessage]:
    key = _pending_key(client_id, wa_id)
    redis = _get_store_redis()

    if redis is not None:
        try:
            raw_messages = await redis.lrange(key, 0, -1)
            await redis.delete(key)
            return [
                message
                for raw_message in _deserialize_pending_message_items(raw_messages)
                if (message := _pending_message_from_dict(raw_message)) is not None
            ]
        except Exception as exc:
            logger.warning(
                "WHATSAPP_CLOUD_PENDING_POP_REDIS_ERROR error=%s",
                exc.__class__.__name__,
            )

    async with _pending_memory_guard:
        raw_messages = _pending_memory.pop(key, [])

    return [
        message
        for raw_message in raw_messages
        if (message := _pending_message_from_dict(raw_message)) is not None
    ]


async def _has_pending_text_messages(client_id: str, wa_id: str) -> bool:
    key = _pending_key(client_id, wa_id)
    redis = _get_store_redis()

    if redis is not None:
        try:
            return int(await redis.llen(key)) > 0
        except Exception as exc:
            logger.warning(
                "WHATSAPP_CLOUD_PENDING_EXISTS_REDIS_ERROR error=%s",
                exc.__class__.__name__,
            )

    async with _pending_memory_guard:
        return bool(_pending_memory.get(key))


async def _acquire_pending_lock(client_id: str, wa_id: str) -> bool:
    lock_key = _pending_lock_key(client_id, wa_id)
    lock_ttl_seconds = _get_lock_ttl_seconds()
    redis = _get_store_redis()

    if redis is not None:
        try:
            return bool(await redis.set(lock_key, "1", ex=lock_ttl_seconds, nx=True))
        except Exception as exc:
            logger.warning(
                "WHATSAPP_CLOUD_PENDING_LOCK_REDIS_ERROR error=%s",
                exc.__class__.__name__,
            )

    now = time.time()
    async with _pending_memory_guard:
        locked_until = _pending_memory_locks.get(lock_key, 0)
        if locked_until > now:
            return False
        _pending_memory_locks[lock_key] = now + lock_ttl_seconds
        return True


async def _release_pending_lock(client_id: str, wa_id: str) -> None:
    lock_key = _pending_lock_key(client_id, wa_id)
    redis = _get_store_redis()

    if redis is not None:
        try:
            await redis.delete(lock_key)
            return
        except Exception as exc:
            logger.warning(
                "WHATSAPP_CLOUD_PENDING_UNLOCK_REDIS_ERROR error=%s",
                exc.__class__.__name__,
            )

    async with _pending_memory_guard:
        _pending_memory_locks.pop(lock_key, None)


def _deserialize_pending_message_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []

    messages: list[dict[str, Any]] = []
    for raw_item in raw_items:
        try:
            parsed = json.loads(raw_item)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            messages.append(parsed)
    return messages


def _pending_message_to_dict(message: WhatsAppCloudPendingTextMessage) -> dict[str, Any]:
    return {
        "wa_id": message.wa_id,
        "message_id": message.message_id,
        "timestamp": message.timestamp,
        "text_body": message.text_body,
        "phone_number_id": message.phone_number_id,
        "queued_at": message.queued_at,
    }


def _pending_message_from_dict(data: dict[str, Any]) -> WhatsAppCloudPendingTextMessage | None:
    wa_id = data.get("wa_id")
    message_id = data.get("message_id")
    text_body = data.get("text_body")
    if not isinstance(wa_id, str) or not isinstance(message_id, str):
        return None
    if not isinstance(text_body, str) or not text_body.strip():
        return None

    timestamp = data.get("timestamp")
    phone_number_id = data.get("phone_number_id")
    queued_at = data.get("queued_at")
    return WhatsAppCloudPendingTextMessage(
        wa_id=wa_id,
        message_id=message_id,
        timestamp=timestamp if isinstance(timestamp, str) else None,
        text_body=text_body,
        phone_number_id=phone_number_id if isinstance(phone_number_id, str) else None,
        queued_at=queued_at if isinstance(queued_at, (int, float)) else time.time(),
    )


async def _send_whatsapp_cloud_reply(
    message: WhatsAppCloudInboundTextMessage,
    reply: str,
    config: WhatsAppCloudConfig,
) -> None:
    send_to = resolve_whatsapp_cloud_send_to(message.wa_id)
    await send_whatsapp_cloud_text(
        to=send_to,
        text=reply,
        phone_number_id=config.phone_number_id,
        access_token=config.access_token,
        api_version=config.api_version,
    )


async def _send_whatsapp_cloud_reply_with_outbox(
    message: WhatsAppCloudInboundTextMessage,
    reply: str,
    config: WhatsAppCloudConfig,
) -> None:
    try:
        await _send_whatsapp_cloud_reply(message, reply, config)
    except WhatsAppCloudSendError as exc:
        await _save_failed_send_to_outbox(message, reply, config, exc)
        raise


async def _save_failed_send_to_outbox(
    message: WhatsAppCloudInboundTextMessage,
    reply: str,
    config: WhatsAppCloudConfig,
    exc: Exception,
) -> None:
    item = WhatsAppCloudOutboxItem(
        id=str(uuid.uuid4()),
        client_id=config.client_id,
        wa_id=message.wa_id,
        send_to=resolve_whatsapp_cloud_send_to(message.wa_id),
        phone_number_id=config.phone_number_id,
        message_id=message.message_id,
        reply_text=reply,
        created_at=datetime.now(timezone.utc).isoformat(),
        last_error=_safe_outbox_error(exc),
        attempts=1,
    )
    await save_failed_outbox_item(item)


def _safe_outbox_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").replace("\r", " ").strip()
    safe_error = f"{exc.__class__.__name__}: {message}" if message else exc.__class__.__name__
    return safe_error[:500]


def _build_whatsapp_prompt_override(client) -> str:
    base_prompt = client.whatsapp_system_prompt or client.system_prompt or ""
    return f"{base_prompt}{WHATSAPP_CLOUD_RESPONSE_POLICY}"


def _combine_pending_text_messages(messages: list[WhatsAppCloudPendingTextMessage]) -> str:
    return "\n".join(message.text_body.strip() for message in messages if message.text_body.strip())


def _normalize_whatsapp_reply(reply: str) -> str:
    normalized = _remove_banned_whatsapp_reply_phrases(" ".join(reply.split()).strip())
    max_chars = 600
    if len(normalized) <= max_chars:
        return normalized

    clipped = normalized[:max_chars].rstrip()
    sentence_end = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if sentence_end >= 350:
        return clipped[: sentence_end + 1]
    return clipped.rstrip(" ,.;:") + "..."


def _apply_manager_fallback_rules(
    *,
    user_text: str,
    reply: str,
    history_before_reply: list[dict],
) -> str:
    if reply == SAFE_CLAUDE_FALLBACK:
        return reply
    if _client_requested_manager(user_text):
        return SAFE_CLAUDE_FALLBACK
    if reply == EMPTY_CLAUDE_FALLBACK and _last_assistant_reply(history_before_reply) == EMPTY_CLAUDE_FALLBACK:
        return SAFE_CLAUDE_FALLBACK
    return reply


def _client_requested_manager(user_text: str) -> bool:
    lowered = user_text.lower()
    return any(marker in lowered for marker in ("менеджер", "оператор", "человек", "сотрудник"))


def _last_assistant_reply(history: list[dict]) -> str | None:
    for message in reversed(history):
        if message.get("role") == "assistant":
            content = message.get("content")
            return content if isinstance(content, str) else None
    return None


def _remove_banned_whatsapp_reply_phrases(reply: str) -> str:
    cleaned = reply
    for phrase in BANNED_WHATSAPP_REPLY_PHRASES:
        cleaned = re_sub_case_insensitive(phrase, "", cleaned)
    return " ".join(cleaned.split()).strip()


def re_sub_case_insensitive(pattern: str, replacement: str, text: str) -> str:
    import re

    return re.sub(re.escape(pattern), replacement, text, flags=re.IGNORECASE)


def _track_background_task(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("WHATSAPP_CLOUD_BACKGROUND_ERROR cancelled=true")
    except Exception as exc:
        logger.error("WHATSAPP_CLOUD_BACKGROUND_ERROR error=%s", exc, exc_info=True)


async def _enqueue_text_message(message: WhatsAppCloudInboundTextMessage) -> None:
    config = _get_processing_config(message.phone_number_id)
    if config is None:
        return

    should_process = await _mark_message_for_processing(message.message_id)
    if not should_process:
        return

    await _append_pending_text_message(config, message)

    if not await _acquire_pending_lock(config.client_id, message.wa_id):
        logger.info(
            "WHATSAPP_CLOUD_PENDING_WORKER_EXISTS client_id=%s wa_id=%s message_id=%s",
            config.client_id,
            message.wa_id,
            message.message_id,
        )
        return

    try:
        await _process_pending_text_messages(config, message.wa_id)
    finally:
        await _release_pending_lock(config.client_id, message.wa_id)


async def _process_pending_text_messages(config: WhatsAppCloudConfig, wa_id: str) -> None:
    while True:
        await asyncio.sleep(_get_debounce_delay_seconds())
        messages = await _pop_pending_text_messages(config.client_id, wa_id)
        if not messages:
            return

        await _process_text_message_batch(config, messages)

        if not await _has_pending_text_messages(config.client_id, wa_id):
            return


async def _process_text_message(message: WhatsAppCloudInboundTextMessage) -> None:
    config = _get_processing_config(message.phone_number_id)
    if config is None:
        return

    should_process = await _mark_message_for_processing(message.message_id)
    if not should_process:
        return

    pending = WhatsAppCloudPendingTextMessage(
        wa_id=message.wa_id,
        message_id=message.message_id,
        timestamp=message.timestamp,
        text_body=message.text_body,
        phone_number_id=message.phone_number_id,
        queued_at=time.time(),
    )
    await _process_text_message_batch(config, [pending])


async def _process_text_message_batch(
    config: WhatsAppCloudConfig,
    messages: list[WhatsAppCloudPendingTextMessage],
) -> None:
    if not messages:
        return

    first_message = messages[0]
    latest_message = messages[-1]
    combined_text = _combine_pending_text_messages(messages)
    if not combined_text:
        return

    if async_session_factory is None:
        logger.error("WHATSAPP_CLOUD_PROCESSING_SKIP db_configured=false")
        return

    async with async_session_factory() as db:
        client = await client_service.get_by_id(db, config.client_id)

    if client is None:
        logger.warning(
            "WHATSAPP_CLOUD_PROCESSING_SKIP client_found=false client_id=%s",
            config.client_id,
        )
        return

    if client.status != "active":
        logger.warning(
            "WHATSAPP_CLOUD_PROCESSING_SKIP client_id=%s status=%s",
            config.client_id,
            client.status,
        )
        return

    cache_key = f"whatsapp_cloud:{config.client_id}:{first_message.wa_id}"
    user_ref = f"wa_cloud:{first_message.wa_id}"

    await _store.append(cache_key, "user", combined_text)
    history = await _store.get(cache_key)

    if client.whatsapp_system_prompt:
        logger.info(
            "WHATSAPP_CLOUD_PROMPT using=whatsapp_system_prompt client_id=%s",
            config.client_id,
        )
    else:
        logger.info(
            "WHATSAPP_CLOUD_PROMPT using=system_prompt client_id=%s",
            config.client_id,
        )
    prompt_override = _build_whatsapp_prompt_override(client)

    reply, is_hot_lead, temperature = await ask_claude(
        first_message.wa_id,
        combined_text,
        client,
        history,
        system_prompt_override=prompt_override,
    )
    reply = _apply_manager_fallback_rules(
        user_text=combined_text,
        reply=reply,
        history_before_reply=history,
    )
    reply = _normalize_whatsapp_reply(reply)
    await _store.append(cache_key, "assistant", reply)

    lead_id = None
    async with async_session_factory() as db:
        conversation = await client_service.get_or_create_conversation(
            db,
            client.id,
            user_ref,
        )
        await client_service.save_message(db, conversation, "user", combined_text)
        await client_service.save_message(db, conversation, "assistant", reply)

        if is_hot_lead:
            lead = await client_service.save_lead(
                db,
                client.id,
                conversation,
                user_ref,
                temperature,
                combined_text,
            )
            lead_id = lead.id

    if is_hot_lead:
        recent = await _store.get(cache_key)
        await send_lead_notification(
            sender_id=first_message.wa_id,
            ai_reply=reply,
            temperature=temperature,
            telegram_chat_id=client.telegram_manager_chat_id or "",
            whatsapp_link=client.whatsapp_link or "",
            recent_messages=recent,
        )
        if lead_id is not None:
            async with async_session_factory() as db:
                await db.execute(
                    sa_update(Lead)
                    .where(Lead.id == lead_id)
                    .values(notified_to_telegram=True)
                )
                await db.commit()

    outbound_message = WhatsAppCloudInboundTextMessage(
        wa_id=first_message.wa_id,
        message_id=latest_message.message_id,
        timestamp=latest_message.timestamp,
        message_type="text",
        text_body=combined_text,
        phone_number_id=latest_message.phone_number_id,
    )
    await _send_whatsapp_cloud_reply_with_outbox(outbound_message, reply, config)

    logger.info(
        "WHATSAPP_CLOUD_PROCESSING_OK client_id=%s wa_id=%s message_count=%d last_message_id=%s temp=%s hot=%s text_len=%d reply_len=%d",
        config.client_id,
        first_message.wa_id,
        len(messages),
        latest_message.message_id,
        temperature,
        is_hot_lead,
        len(combined_text),
        len(reply),
    )


@router.get("/webhook")
async def verify_whatsapp_cloud_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")
    expected_token = _get_env(WHATSAPP_CLOUD_VERIFY_TOKEN_ENV)

    if not expected_token:
        logger.warning("WHATSAPP_CLOUD_VERIFY_FAILED verify_token_configured=false")
        raise HTTPException(status_code=403)

    if mode == "subscribe" and hmac.compare_digest(verify_token, expected_token):
        return PlainTextResponse(challenge)

    raise HTTPException(status_code=403)


@router.get("/health")
async def whatsapp_cloud_health():
    access_token_configured = bool(_get_env(WHATSAPP_CLOUD_ACCESS_TOKEN_ENV))
    phone_number_id_configured = bool(_get_env(WHATSAPP_CLOUD_PHONE_NUMBER_ID_ENV))
    client_map_configured = bool(_get_env(WHATSAPP_CLOUD_CLIENT_MAP_ENV))
    recipient_overrides_configured = bool(_get_env(WHATSAPP_CLOUD_RECIPIENT_OVERRIDES_ENV))
    client_id_configured = _is_whatsapp_cloud_client_configured()
    app_secret_configured = bool(_get_env(WHATSAPP_CLOUD_APP_SECRET_ENV))
    production = _is_production_environment()
    configured = access_token_configured and phone_number_id_configured and client_id_configured
    production_ready = configured and (
        not production or (app_secret_configured and not recipient_overrides_configured)
    )
    outbox_failed_count = await count_outbox_items()

    return {
        "ok": production_ready,
        "configured": configured,
        "production": production,
        "production_ready": production_ready,
        "access_token_configured": access_token_configured,
        "phone_number_id_configured": phone_number_id_configured,
        "client_id_configured": client_id_configured,
        "client_map_configured": client_map_configured,
        "recipient_overrides_configured": recipient_overrides_configured,
        "app_secret_configured": app_secret_configured,
        "redis_available": outbox_failed_count is not None,
        "outbox_failed_count": outbox_failed_count,
        "api_version": _get_cloud_api_version(),
    }


@router.post("/webhook")
async def receive_whatsapp_cloud_webhook(request: Request):
    raw_body = await request.body()
    await _verify_signature_if_configured(request, raw_body)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("WHATSAPP_CLOUD_WEBHOOK_RECEIVED invalid_json=true")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(payload, dict):
        logger.warning("WHATSAPP_CLOUD_WEBHOOK_RECEIVED invalid_payload_type=true")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    metadata = _extract_webhook_metadata(payload)
    logger.info(
        "WHATSAPP_CLOUD_WEBHOOK_RECEIVED object=%s entries=%d messages_exist=%s message_type=%s",
        metadata.object_name,
        metadata.entry_count,
        metadata.messages_exist,
        metadata.message_type,
    )

    messages = _extract_text_messages(payload)
    if not messages:
        return {"status": "ok"}

    for message in messages:
        task = asyncio.create_task(_enqueue_text_message(message))
        task.add_done_callback(_track_background_task)

    return {"status": "ok"}
