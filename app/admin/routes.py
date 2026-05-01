import os
from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services import client_service

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

router = APIRouter()


def _require_admin(x_admin_key: str = Header(...)):
    if not ADMIN_API_KEY or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin key")


# ── Clients ──────────────────────────────────────────────────────────────────

@router.post("/clients", status_code=201, dependencies=[Depends(_require_admin)])
async def create_client(body: dict[str, Any], db: AsyncSession = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    required = {"business_name", "owner_email", "instagram_account_id", "instagram_access_token"}
    missing = required - body.keys()
    if missing:
        raise HTTPException(422, f"Missing fields: {missing}")
    client = await client_service.create(db, dict(body))
    return _client_dict(client)


@router.get("/clients", dependencies=[Depends(_require_admin)])
async def list_clients(db: AsyncSession = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    clients = await client_service.list_all(db)
    return [_client_dict(c) for c in clients]


@router.get("/clients/{client_id}", dependencies=[Depends(_require_admin)])
async def get_client(client_id: str, db: AsyncSession = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    client = await client_service.get_by_id(db, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return _client_dict(client)


@router.patch("/clients/{client_id}", dependencies=[Depends(_require_admin)])
async def update_client(client_id: str, body: dict[str, Any], db: AsyncSession = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    client = await client_service.update(db, client_id, dict(body))
    if not client:
        raise HTTPException(404, "Client not found")
    return _client_dict(client)


@router.delete("/clients/{client_id}", dependencies=[Depends(_require_admin)])
async def delete_client(client_id: str, db: AsyncSession = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    ok = await client_service.soft_delete(db, client_id)
    if not ok:
        raise HTTPException(404, "Client not found")
    return {"status": "paused"}


# ── Leads & Conversations ─────────────────────────────────────────────────────

@router.get("/clients/{client_id}/leads", dependencies=[Depends(_require_admin)])
async def get_leads(client_id: str, db: AsyncSession = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    leads = await client_service.get_leads(db, client_id)
    return [_lead_dict(l) for l in leads]


@router.get("/clients/{client_id}/conversations", dependencies=[Depends(_require_admin)])
async def get_conversations(client_id: str, db: AsyncSession = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    convs = await client_service.get_conversations(db, client_id)
    return [_conv_dict(c) for c in convs]


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", dependencies=[Depends(_require_admin)])
async def get_stats(db: AsyncSession = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    return await client_service.get_stats(db)


# ── Serializers ───────────────────────────────────────────────────────────────

def _client_dict(c) -> dict:
    return {
        "id": str(c.id),
        "business_name": c.business_name,
        "owner_email": c.owner_email,
        "instagram_account_id": c.instagram_account_id,
        "instagram_username": c.instagram_username,
        "whatsapp_link": c.whatsapp_link,
        "telegram_manager_chat_id": c.telegram_manager_chat_id,
        "plan": c.plan,
        "status": c.status,
        "trial_ends_at": c.trial_ends_at.isoformat() if c.trial_ends_at else None,
        "created_by": c.created_by,
        "notes": c.notes,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


def _lead_dict(l) -> dict:
    return {
        "id": str(l.id),
        "client_id": str(l.client_id),
        "conversation_id": str(l.conversation_id),
        "instagram_user_id": l.instagram_user_id,
        "temperature": l.temperature,
        "triggered_at": l.triggered_at.isoformat(),
        "notified_to_telegram": l.notified_to_telegram,
        "last_message": l.last_message,
    }


def _conv_dict(c) -> dict:
    return {
        "id": str(c.id),
        "client_id": str(c.client_id),
        "instagram_user_id": c.instagram_user_id,
        "created_at": c.created_at.isoformat(),
        "last_message_at": c.last_message_at.isoformat(),
        "messages_count": c.messages_count,
        "highest_temperature": c.highest_temperature,
    }
