from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import update as sa_update

from app.db.database import async_session_factory
from app.db.models import Lead
from app.services import client_service
from app.services.claude_service import ask_claude
from app.services.conversation_store import ConversationStore
from app.services.telegram_service import send_lead_notification

logger = logging.getLogger(__name__)

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "")

router = APIRouter()
_store = ConversationStore(REDIS_URL)


class WhatsAppMessageRequest(BaseModel):
    phone: str
    message: str
    client_id: str


def _check_admin_key(x_admin_key: str) -> None:
    if not ADMIN_API_KEY or not hmac.compare_digest(x_admin_key, ADMIN_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid admin key")


@router.post("/message")
async def whatsapp_message(
    body: WhatsAppMessageRequest,
    x_admin_key: str = Header(...),
):
    _check_admin_key(x_admin_key)

    if async_session_factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        # 1. Get client from DB
        async with async_session_factory() as db:
            client = await client_service.get_by_id(db, body.client_id)

        if client is None:
            raise HTTPException(status_code=404, detail="Client not found")

        if client.status != "active":
            raise HTTPException(status_code=403, detail=f"Client status is {client.status}")

        # Redis key: conv:whatsapp:{client_id}:{phone}
        cache_key = f"whatsapp:{body.client_id}:{body.phone}"
        # "wa:{phone}" prefix keeps WhatsApp users separate from Instagram IDs in the DB
        user_ref = f"wa:{body.phone}"

        # 2+3. Append user message; fetch history (now includes current turn)
        await _store.append(cache_key, "user", body.message)
        history = await _store.get(cache_key)

        # 4. Call Claude — prefer whatsapp_system_prompt, fallback to system_prompt
        if client.whatsapp_system_prompt:
            logger.info("WHATSAPP_PROMPT using=whatsapp_system_prompt client_id=%s", body.client_id)
            prompt_override = client.whatsapp_system_prompt
        else:
            logger.info("WHATSAPP_PROMPT using=system_prompt (fallback) client_id=%s", body.client_id)
            prompt_override = None

        reply, is_hot_lead, temperature = await ask_claude(
            body.phone, body.message, client, history,
            system_prompt_override=prompt_override,
        )

        # 5. Save assistant reply to Redis
        await _store.append(cache_key, "assistant", reply)

        # 6. Save user + assistant messages to DB
        lead_id = None
        async with async_session_factory() as db:
            conversation = await client_service.get_or_create_conversation(
                db, client.id, user_ref
            )
            await client_service.save_message(db, conversation, "user", body.message)
            await client_service.save_message(db, conversation, "assistant", reply)

            if is_hot_lead:
                lead = await client_service.save_lead(
                    db, client.id, conversation, user_ref, temperature, body.message
                )
                lead_id = lead.id

        # 7. Telegram notification for hot/warm leads
        if is_hot_lead:
            recent = await _store.get(cache_key)
            await send_lead_notification(
                sender_id=body.phone,
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

        logger.info(
            "WHATSAPP_OK phone=%s client_id=%s temp=%s hot=%s reply_len=%d",
            body.phone, body.client_id, temperature, is_hot_lead, len(reply),
        )
        return {"reply": reply}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "WHATSAPP_ERROR phone=%s client_id=%s error=%s",
            body.phone, body.client_id, e, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
