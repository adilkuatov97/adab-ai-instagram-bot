from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_WHATSAPP_CLOUD_API_VERSION = "v25.0"
WHATSAPP_CLOUD_SEND_TIMEOUT = 10.0


class WhatsAppCloudSendError(RuntimeError):
    pass


async def send_whatsapp_cloud_text(
    to: str,
    text: str,
    phone_number_id: str,
    access_token: str,
    api_version: str = DEFAULT_WHATSAPP_CLOUD_API_VERSION,
) -> None:
    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=WHATSAPP_CLOUD_SEND_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.error(
            "WHATSAPP_CLOUD_SEND_ERROR to=%s phone_number_id=%s error=%s text_len=%d",
            to,
            phone_number_id,
            exc.__class__.__name__,
            len(text),
        )
        raise WhatsAppCloudSendError("WhatsApp Cloud send request failed") from exc

    if response.status_code < 200 or response.status_code >= 300:
        logger.error(
            "WHATSAPP_CLOUD_SEND_ERROR to=%s phone_number_id=%s status=%s body_len=%d text_len=%d",
            to,
            phone_number_id,
            response.status_code,
            len(response.text),
            len(text),
        )
        raise WhatsAppCloudSendError(
            f"WhatsApp Cloud send failed: status={response.status_code}"
        )

    logger.info(
        "WHATSAPP_CLOUD_SEND_OK to=%s phone_number_id=%s status=%s text_len=%d",
        to,
        phone_number_id,
        response.status_code,
        len(text),
    )
