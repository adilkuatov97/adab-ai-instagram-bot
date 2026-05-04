import logging

import httpx

logger = logging.getLogger(__name__)


class InstagramSendError(RuntimeError):
    pass


async def send_message(recipient_id: str, text: str, access_token: str) -> dict:
    url = "https://graph.instagram.com/v23.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers=headers)
        body = r.text
        if r.status_code < 200 or r.status_code >= 300:
            logger.error(
                "INSTAGRAM_SEND_ERROR recipient_id=%s status=%s body=%s",
                recipient_id,
                r.status_code,
                body,
            )
            raise InstagramSendError(f"Instagram send failed: status={r.status_code}")

        logger.info(
            "INSTAGRAM_SEND_OK recipient_id=%s status=%s body=%s",
            recipient_id,
            r.status_code,
            body,
        )
        return r.json()
