from __future__ import annotations

import logging
import os

from app.services.whatsapp_cloud_outbox import (
    delete_outbox_item,
    increment_outbox_item_attempts,
    load_outbox_item,
)
from app.services.whatsapp_cloud_service import (
    DEFAULT_WHATSAPP_CLOUD_API_VERSION,
    WhatsAppCloudSendError,
    send_whatsapp_cloud_text,
)

logger = logging.getLogger(__name__)

WHATSAPP_CLOUD_ACCESS_TOKEN_ENV = "WHATSAPP_CLOUD_ACCESS_TOKEN"
WHATSAPP_CLOUD_API_VERSION_ENV = "WHATSAPP_CLOUD_API_VERSION"
WHATSAPP_CLOUD_OUTBOX_MAX_ATTEMPTS_ENV = "WHATSAPP_CLOUD_OUTBOX_MAX_ATTEMPTS"
DEFAULT_OUTBOX_MAX_ATTEMPTS = 5


async def retry_outbox_item(item_id: str) -> bool:
    item = await load_outbox_item(item_id)
    if item is None:
        logger.info("WHATSAPP_CLOUD_OUTBOX_RETRY_SKIP item_found=false item_id=%s", item_id)
        return False

    max_attempts = _get_max_attempts()
    if item.attempts >= max_attempts:
        logger.warning(
            "WHATSAPP_CLOUD_OUTBOX_RETRY_SKIP max_attempts_reached=true item_id=%s attempts=%d max_attempts=%d",
            item_id,
            item.attempts,
            max_attempts,
        )
        return False

    access_token = os.getenv(WHATSAPP_CLOUD_ACCESS_TOKEN_ENV, "").strip()
    if not access_token:
        await increment_outbox_item_attempts(item_id, "Missing WHATSAPP_CLOUD_ACCESS_TOKEN")
        logger.warning("WHATSAPP_CLOUD_OUTBOX_RETRY_SKIP access_token_configured=false item_id=%s", item_id)
        return False

    api_version = os.getenv(WHATSAPP_CLOUD_API_VERSION_ENV, "").strip()
    if not api_version:
        api_version = DEFAULT_WHATSAPP_CLOUD_API_VERSION

    try:
        await send_whatsapp_cloud_text(
            to=item.send_to,
            text=item.reply_text,
            phone_number_id=item.phone_number_id,
            access_token=access_token,
            api_version=api_version,
        )
    except WhatsAppCloudSendError as exc:
        await increment_outbox_item_attempts(item_id, _safe_retry_error(exc))
        logger.warning(
            "WHATSAPP_CLOUD_OUTBOX_RETRY_FAILED item_id=%s attempts=%d",
            item_id,
            item.attempts + 1,
        )
        return False
    except Exception as exc:
        await increment_outbox_item_attempts(item_id, _safe_retry_error(exc))
        logger.warning(
            "WHATSAPP_CLOUD_OUTBOX_RETRY_ERROR item_id=%s error=%s",
            item_id,
            exc.__class__.__name__,
        )
        return False

    await delete_outbox_item(item_id)
    logger.info("WHATSAPP_CLOUD_OUTBOX_RETRY_OK item_id=%s", item_id)
    return True


def _safe_retry_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").replace("\r", " ").strip()
    safe_error = f"{exc.__class__.__name__}: {message}" if message else exc.__class__.__name__
    return safe_error[:500]


def _get_max_attempts() -> int:
    raw = os.getenv(WHATSAPP_CLOUD_OUTBOX_MAX_ATTEMPTS_ENV, "").strip()
    if not raw:
        return DEFAULT_OUTBOX_MAX_ATTEMPTS
    try:
        value = int(raw)
    except ValueError:
        logger.warning("WHATSAPP_CLOUD_OUTBOX_MAX_ATTEMPTS_INVALID")
        return DEFAULT_OUTBOX_MAX_ATTEMPTS
    return max(1, min(value, 20))
