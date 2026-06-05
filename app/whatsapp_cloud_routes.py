from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import update as sa_update

from app.db.database import async_session_factory
from app.db.models import Lead
from app.services import client_service
from app.services.claude_service import ask_claude
from app.services.conversation_store import ConversationStore
from app.services.telegram_service import send_lead_notification
from app.services.whatsapp_cloud_service import (
    DEFAULT_WHATSAPP_CLOUD_API_VERSION,
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
REDIS_URL = os.getenv("REDIS_URL", "")

router = APIRouter()
_store = ConversationStore(REDIS_URL)


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
class WhatsAppCloudConfig:
    access_token: str
    default_client_id: str
    phone_number_id: str
    api_version: str


def _get_env(name: str) -> str:
    return os.getenv(name, "").strip()


def _get_cloud_api_version() -> str:
    return _get_env(WHATSAPP_CLOUD_API_VERSION_ENV) or DEFAULT_WHATSAPP_CLOUD_API_VERSION


def resolve_whatsapp_cloud_send_to(wa_id: str) -> str:
    overrides = _get_env(WHATSAPP_CLOUD_RECIPIENT_OVERRIDES_ENV)
    if not overrides:
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


def _get_processing_config(payload_phone_number_id: str | None) -> WhatsAppCloudConfig | None:
    access_token = _get_env(WHATSAPP_CLOUD_ACCESS_TOKEN_ENV)
    default_client_id = _get_env(WHATSAPP_CLOUD_DEFAULT_CLIENT_ID_ENV)
    phone_number_id = payload_phone_number_id or _get_env(WHATSAPP_CLOUD_PHONE_NUMBER_ID_ENV)
    missing = []
    if not access_token:
        missing.append(WHATSAPP_CLOUD_ACCESS_TOKEN_ENV)
    if not default_client_id:
        missing.append(WHATSAPP_CLOUD_DEFAULT_CLIENT_ID_ENV)
    if not phone_number_id:
        missing.append(WHATSAPP_CLOUD_PHONE_NUMBER_ID_ENV)

    if missing:
        logger.error("WHATSAPP_CLOUD_CONFIG_MISSING vars=%s", ",".join(missing))
        return None

    return WhatsAppCloudConfig(
        access_token=access_token,
        default_client_id=default_client_id,
        phone_number_id=phone_number_id,
        api_version=_get_cloud_api_version(),
    )


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
        logger.warning("WHATSAPP_CLOUD_SIG_SKIP app_secret_configured=false")
        return

    signature = request.headers.get("x-hub-signature-256", "")
    if not _is_valid_signature(raw_body, signature, app_secret):
        raise HTTPException(status_code=403, detail="Invalid WhatsApp Cloud signature")


async def _mark_message_for_processing(message_id: str) -> bool:
    redis_key = f"whatsapp_cloud:processed:{message_id}"
    mark_result = await _store.mark_once_redis(redis_key)
    if mark_result is None:
        logger.warning("WHATSAPP_CLOUD_IDEMPOTENCY_UNAVAILABLE message_id=%s", message_id)
        return True
    if not mark_result:
        logger.info("WHATSAPP_CLOUD_DUPLICATE_SKIPPED message_id=%s", message_id)
        return False
    return True


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


def _track_background_task(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("WHATSAPP_CLOUD_BACKGROUND_ERROR cancelled=true")
    except Exception as exc:
        logger.error("WHATSAPP_CLOUD_BACKGROUND_ERROR error=%s", exc, exc_info=True)


async def _process_text_message(message: WhatsAppCloudInboundTextMessage) -> None:
    config = _get_processing_config(message.phone_number_id)
    if config is None:
        return

    should_process = await _mark_message_for_processing(message.message_id)
    if not should_process:
        return

    if async_session_factory is None:
        logger.error("WHATSAPP_CLOUD_PROCESSING_SKIP db_configured=false")
        return

    async with async_session_factory() as db:
        client = await client_service.get_by_id(db, config.default_client_id)

    if client is None:
        logger.warning(
            "WHATSAPP_CLOUD_PROCESSING_SKIP client_found=false client_id=%s",
            config.default_client_id,
        )
        return

    if client.status != "active":
        logger.warning(
            "WHATSAPP_CLOUD_PROCESSING_SKIP client_id=%s status=%s",
            config.default_client_id,
            client.status,
        )
        return

    cache_key = f"whatsapp_cloud:{config.default_client_id}:{message.wa_id}"
    user_ref = f"wa_cloud:{message.wa_id}"

    await _store.append(cache_key, "user", message.text_body)
    history = await _store.get(cache_key)

    if client.whatsapp_system_prompt:
        logger.info(
            "WHATSAPP_CLOUD_PROMPT using=whatsapp_system_prompt client_id=%s",
            config.default_client_id,
        )
        prompt_override = client.whatsapp_system_prompt
    else:
        logger.info(
            "WHATSAPP_CLOUD_PROMPT using=system_prompt client_id=%s",
            config.default_client_id,
        )
        prompt_override = None

    reply, is_hot_lead, temperature = await ask_claude(
        message.wa_id,
        message.text_body,
        client,
        history,
        system_prompt_override=prompt_override,
    )
    await _store.append(cache_key, "assistant", reply)

    lead_id = None
    async with async_session_factory() as db:
        conversation = await client_service.get_or_create_conversation(
            db,
            client.id,
            user_ref,
        )
        await client_service.save_message(db, conversation, "user", message.text_body)
        await client_service.save_message(db, conversation, "assistant", reply)

        if is_hot_lead:
            lead = await client_service.save_lead(
                db,
                client.id,
                conversation,
                user_ref,
                temperature,
                message.text_body,
            )
            lead_id = lead.id

    if is_hot_lead:
        recent = await _store.get(cache_key)
        await send_lead_notification(
            sender_id=message.wa_id,
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

    await _send_whatsapp_cloud_reply(message, reply, config)

    logger.info(
        "WHATSAPP_CLOUD_PROCESSING_OK client_id=%s wa_id=%s message_id=%s temp=%s hot=%s text_len=%d reply_len=%d",
        config.default_client_id,
        message.wa_id,
        message.message_id,
        temperature,
        is_hot_lead,
        len(message.text_body),
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
        task = asyncio.create_task(_process_text_message(message))
        task.add_done_callback(_track_background_task)

    return {"status": "ok"}
