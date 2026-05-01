import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Conversation, Lead, Message
from app.services.crypto_service import encrypt, decrypt


async def get_by_instagram_id(db: AsyncSession, instagram_account_id: str) -> Client | None:
    result = await db.execute(
        select(Client).where(Client.instagram_account_id == instagram_account_id)
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, client_id: str) -> Client | None:
    result = await db.execute(
        select(Client).where(Client.id == uuid.UUID(client_id))
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, data: dict) -> Client:
    token = data.pop("instagram_access_token")
    groq_key = data.pop("groq_api_key", None)

    client = Client(
        **data,
        instagram_access_token_encrypted=encrypt(token),
        groq_api_key_encrypted=encrypt(groq_key) if groq_key else None,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


async def update(db: AsyncSession, client_id: str, data: dict) -> Client | None:
    client = await get_by_id(db, client_id)
    if not client:
        return None

    if "instagram_access_token" in data:
        client.instagram_access_token_encrypted = encrypt(data.pop("instagram_access_token"))
    if "groq_api_key" in data:
        raw = data.pop("groq_api_key")
        client.groq_api_key_encrypted = encrypt(raw) if raw else None

    for key, value in data.items():
        if hasattr(client, key):
            setattr(client, key, value)

    client.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(client)
    return client


async def soft_delete(db: AsyncSession, client_id: str) -> bool:
    client = await get_by_id(db, client_id)
    if not client:
        return False
    client.status = "paused"
    client.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def list_all(db: AsyncSession) -> list[Client]:
    result = await db.execute(select(Client).order_by(Client.created_at.desc()))
    return list(result.scalars().all())


def get_decrypted_token(client: Client) -> str:
    return decrypt(client.instagram_access_token_encrypted)


def get_decrypted_groq_key(client: Client) -> str | None:
    if not client.groq_api_key_encrypted:
        return None
    return decrypt(client.groq_api_key_encrypted)


async def get_leads(db: AsyncSession, client_id: str) -> list[Lead]:
    result = await db.execute(
        select(Lead)
        .where(Lead.client_id == uuid.UUID(client_id))
        .order_by(Lead.triggered_at.desc())
    )
    return list(result.scalars().all())


async def get_conversations(db: AsyncSession, client_id: str) -> list[Conversation]:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.client_id == uuid.UUID(client_id))
        .order_by(Conversation.last_message_at.desc())
    )
    return list(result.scalars().all())


async def get_stats(db: AsyncSession) -> dict[str, Any]:
    total_clients = (await db.execute(select(func.count(Client.id)))).scalar()
    active_clients = (await db.execute(
        select(func.count(Client.id)).where(Client.status == "active")
    )).scalar()
    total_conversations = (await db.execute(select(func.count(Conversation.id)))).scalar()
    total_leads = (await db.execute(select(func.count(Lead.id)))).scalar()
    hot_leads = (await db.execute(
        select(func.count(Lead.id)).where(Lead.temperature == "hot")
    )).scalar()

    return {
        "total_clients": total_clients,
        "active_clients": active_clients,
        "total_conversations": total_conversations,
        "total_leads": total_leads,
        "hot_leads": hot_leads,
    }


async def get_or_create_conversation(
    db: AsyncSession, client_id: uuid.UUID, instagram_user_id: str
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.client_id == client_id,
            Conversation.instagram_user_id == instagram_user_id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        return conv
    conv = Conversation(client_id=client_id, instagram_user_id=instagram_user_id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def save_message(
    db: AsyncSession,
    conversation: Conversation,
    role: str,
    content: str,
    is_voice: bool = False,
) -> Message:
    msg = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        is_voice=is_voice,
    )
    db.add(msg)
    conversation.messages_count += 1
    conversation.last_message_at = datetime.now(timezone.utc)
    await db.commit()
    return msg


async def save_lead(
    db: AsyncSession,
    client_id: uuid.UUID,
    conversation: Conversation,
    instagram_user_id: str,
    temperature: str,
    last_message: str,
) -> Lead:
    lead = Lead(
        client_id=client_id,
        conversation_id=conversation.id,
        instagram_user_id=instagram_user_id,
        temperature=temperature,
        last_message=last_message,
    )
    db.add(lead)

    temp_order = {"hot": 2, "warm": 1, "cold": 0}
    if temp_order.get(temperature, 0) > temp_order.get(conversation.highest_temperature, 0):
        conversation.highest_temperature = temperature

    await db.commit()
    await db.refresh(lead)
    return lead


async def mark_lead_notified(db: AsyncSession, lead: Lead) -> None:
    lead.notified_to_telegram = True
    await db.commit()
