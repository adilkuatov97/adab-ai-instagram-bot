from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_WHATSAPP_CLOUD_API_VERSION = "v25.0"
WHATSAPP_CLOUD_SEND_TIMEOUT = 10.0


class WhatsAppCloudSendError(RuntimeError):
    pass


def _extract_graph_api_error(response: httpx.Response) -> dict[str, str | int | None]:
    empty = {
        "code": None,
        "details": None,
        "message": None,
        "type": None,
        "fbtrace_id": None,
        "error_subcode": None,
    }

    try:
        body: Any = response.json()
    except ValueError:
        return empty

    if not isinstance(body, dict):
        return empty

    error = body.get("error")
    if not isinstance(error, dict):
        return empty

    return {
        "code": _safe_graph_api_error_value(error.get("code")),
        "details": _safe_graph_api_error_value(error.get("details")),
        "message": _safe_graph_api_error_value(error.get("message")),
        "type": _safe_graph_api_error_value(error.get("type")),
        "fbtrace_id": _safe_graph_api_error_value(error.get("fbtrace_id")),
        "error_subcode": _safe_graph_api_error_value(error.get("error_subcode")),
    }


def _safe_graph_api_error_value(value: Any) -> str | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str | int):
        return value
    return None


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
        "recipient_type": "individual",
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
        graph_error = _extract_graph_api_error(response)
        if any(value is not None for value in graph_error.values()):
            logger.error(
                "WHATSAPP_CLOUD_SEND_ERROR to=%s phone_number_id=%s status=%s body_len=%d text_len=%d "
                "error_code=%s error_details=%s error_message=%s error_type=%s fbtrace_id=%s error_subcode=%s",
                to,
                phone_number_id,
                response.status_code,
                len(response.text),
                len(text),
                graph_error["code"],
                graph_error["details"],
                graph_error["message"],
                graph_error["type"],
                graph_error["fbtrace_id"],
                graph_error["error_subcode"],
            )
        else:
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
