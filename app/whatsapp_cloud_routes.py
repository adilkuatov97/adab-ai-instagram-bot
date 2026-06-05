from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

WHATSAPP_CLOUD_VERIFY_TOKEN_ENV = "WHATSAPP_CLOUD_VERIFY_TOKEN"
WHATSAPP_CLOUD_APP_SECRET_ENV = "WHATSAPP_CLOUD_APP_SECRET"
WHATSAPP_CLOUD_ACCESS_TOKEN_ENV = "WHATSAPP_CLOUD_ACCESS_TOKEN"
WHATSAPP_CLOUD_PHONE_NUMBER_ID_ENV = "WHATSAPP_CLOUD_PHONE_NUMBER_ID"

router = APIRouter()


@dataclass(frozen=True)
class WhatsAppCloudWebhookMetadata:
    object_name: str | None
    entry_count: int
    messages_exist: bool
    message_type: str | None


def _get_env(name: str) -> str:
    return os.getenv(name, "").strip()


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

    return {"status": "ok"}
