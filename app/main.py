from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
import pytz
import httpx
from fastapi import Depends, FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.routes import router as admin_router
from app.db.database import get_db, async_session_factory
from app.db.models import Client, Lead
from app.services import client_service
from app.services.claude_service import ask_claude
from app.services.crypto_service import decrypt
from app.services.debounce_service import DebounceService, DEBOUNCE_DELAY
from app.services.instagram_service import send_message
from app.services.telegram_service import send_lead_notification
from app.services.voice_service import transcribe_audio

logger = logging.getLogger(__name__)

# ── Env ───────────────────────────────────────────────────────────────────────

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "AdabAI2026$")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Legacy single-tenant fallback (used when DB is empty / not configured)
_LEGACY_INSTAGRAM_ACCOUNT_ID = os.getenv("BOT_INSTAGRAM_ID", "")
_LEGACY_PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
_LEGACY_WHATSAPP_LINK = os.getenv("WHATSAPP_LINK", "https://wa.me/7XXXXXXXXXX")
_LEGACY_TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_MANAGER_CHAT_ID", "")
_LEGACY_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_TTL = 30 * 24 * 60 * 60

_debounce = DebounceService(REDIS_URL)

# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="Adab AI Instagram Bot")
app.include_router(admin_router, prefix="/admin", tags=["admin"])

# ── Conversation cache (Redis or in-memory) ───────────────────────────────────

class _ConversationStore:
    """Redis-backed cache with in-memory fallback. Key: '{client_id}:{user_id}'"""

    def __init__(self):
        self._client = None
        self._fallback: dict = {}
        self._failed = False
        self._seen_mids: set = set()

    def _connect(self):
        if self._client is not None:
            return self._client
        if not REDIS_URL or self._failed:
            return None
        try:
            import redis
            c = redis.from_url(REDIS_URL, decode_responses=True)
            c.ping()
            self._client = c
            print("REDIS: connected")
        except Exception as e:
            print(f"REDIS WARNING: {type(e).__name__}: {e}, using in-memory")
            self._failed = True
        return self._client

    def get(self, key: str) -> list:
        r = self._connect()
        if r:
            try:
                raw = r.get(f"conv:{key}")
                return json.loads(raw)[-20:] if raw else []
            except Exception as e:
                print(f"REDIS GET ERROR: {e}")
        return list(self._fallback.get(key, []))[-20:]

    def is_seen(self, mid: str) -> bool:
        """Return True if mid was already processed (duplicate). Marks it seen atomically."""
        r = self._connect()
        if r:
            try:
                added = r.setnx(f"seen:{mid}", "1")
                if added:
                    r.expire(f"seen:{mid}", 86400)
                return not bool(added)
            except Exception as e:
                print(f"REDIS SETNX ERROR: {e}")
        if mid in self._seen_mids:
            return True
        self._seen_mids.add(mid)
        if len(self._seen_mids) > 10000:
            self._seen_mids.clear()
        return False

    def append(self, key: str, role: str, content: str):
        r = self._connect()
        if r:
            try:
                cache_key = f"conv:{key}"
                raw = r.get(cache_key)
                history = json.loads(raw) if raw else []
                history.append({"role": role, "content": content})
                r.set(cache_key, json.dumps(history), ex=REDIS_TTL)
                return
            except Exception as e:
                print(f"REDIS SET ERROR: {e}")
        if key not in self._fallback:
            self._fallback[key] = []
        self._fallback[key].append({"role": role, "content": content})


_store = _ConversationStore()

# ── Legacy fallback client ────────────────────────────────────────────────────

class _LegacyClient:
    """Synthetic client built from env vars when DB has no matching record."""

    def __init__(self):
        self.id = "legacy"
        self.instagram_account_id = _LEGACY_INSTAGRAM_ACCOUNT_ID
        self.instagram_access_token_encrypted = None
        self._token = _LEGACY_PAGE_ACCESS_TOKEN
        self.system_prompt = _load_legacy_prompt()
        self.whatsapp_link = _LEGACY_WHATSAPP_LINK
        self.telegram_manager_chat_id = _LEGACY_TELEGRAM_CHAT_ID
        self.groq_api_key_encrypted = None
        self._groq_key = _LEGACY_GROQ_API_KEY
        self.status = "active"

    def get_token(self) -> str:
        return self._token

    def get_groq_key(self) -> str:
        return self._groq_key


def _load_legacy_prompt() -> str:
    """Load the system prompt from the old main.py SYSTEM_PROMPT string."""
    whatsapp = _LEGACY_WHATSAPP_LINK
    return f"""Ты — AI Sales & Conversion Agent в Adab AI Agency.

Работаешь в Instagram Direct. Твоя единственная цель:
→ превратить переписку в квалифицированного лида → WhatsApp → продажа

Ведёшь себя как сильный sales-менеджер, не как саппорт-бот.

═══════════════════════════════════════
КОНТЕКСТ КОМПАНИИ

Adab AI Agency предоставляет:
• AI чат-боты (Instagram / WhatsApp / Telegram)
• Автоматизация бизнес-процессов
• AI контент-фабрика (видео/контент)
• Интеграции CRM + AI
• AI обучение

Целевая аудитория:
• Малый и средний бизнес
• Клиники, кофейни, сервисный бизнес
• Предприниматели в Казахстане (русскоязычные)

═══════════════════════════════════════
ПРАВИЛА ВЗАИМОДЕЙСТВИЯ

• При первом сообщении всегда представляйся: "Здравствуйте! Я AI-помощник Adab AI Agency"
• Всегда задавай 1-2 уточняющих вопроса перед тем как предлагать решение
• Никогда не пиши длиннее 5 строк
• Если клиент уклоняется от вопроса о бизнесе — мягко возвращай в тему
• Если клиент 3 сообщения подряд игнорирует WhatsApp — смени тактику

═══════════════════════════════════════
ЯЗЫК ОБЩЕНИЯ

• Определяй язык клиента и отвечай на том же языке
• По умолчанию — русский

═══════════════════════════════════════
ЦЕЛЬ КОНВЕРСИИ

ВСЕГДА веди клиента в WhatsApp:
"Давайте разберём ваш кейс — напишите в WhatsApp 👇
{whatsapp}"

ЦЕНЫ (после уточнения задачи):
• Чат-бот: 150 000 – 400 000 KZT
• Автоматизация: 300 000 – 1 200 000 KZT
• Контент: 100 000 – 300 000 KZT/мес
• Обучение: 100 000 – 250 000 KZT"""


def _get_legacy_client() -> _LegacyClient | None:
    if _LEGACY_INSTAGRAM_ACCOUNT_ID and _LEGACY_PAGE_ACCESS_TOKEN:
        return _LegacyClient()
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cache_key(client_id, sender_id: str) -> str:
    return f"{client_id}:{sender_id}"


def _resolve_token(client) -> str:
    if isinstance(client, _LegacyClient):
        return client.get_token()
    return client_service.get_decrypted_token(client)


def _resolve_groq_key(client) -> str:
    if isinstance(client, _LegacyClient):
        return client.get_groq_key()
    key = client_service.get_decrypted_groq_key(client)
    return key or GROQ_API_KEY


# ── Debounce processor ────────────────────────────────────────────────────────

async def process_after_debounce(
    *,
    client,
    sender_id: str,
    my_timestamp: float,
    access_token: str,
    telegram_chat_id: str,
    whatsapp_link: str,
) -> None:
    try:
        await asyncio.sleep(DEBOUNCE_DELAY)

        client_id_str = str(client.id)

        if not await _debounce.is_still_latest(client_id_str, sender_id, my_timestamp):
            return

        buffer_messages = await _debounce.get_and_clear_buffer(client_id_str, sender_id)
        if not buffer_messages:
            logger.info("DEBOUNCE: empty buffer for %s, nothing to process", sender_id)
            return

        n = len(buffer_messages)
        combined_text = "\n".join(m["text"] for m in buffer_messages)
        logger.info(
            "DEBOUNCE: processing %d message(s) for %s: %r",
            n, sender_id, combined_text[:80],
        )

        use_db = not isinstance(client, _LegacyClient) and async_session_factory is not None
        cache_key = _cache_key(client.id, sender_id)

        # ── DB: save each user message as a separate record ───────────────────
        if use_db:
            async with async_session_factory() as db:
                conversation = await client_service.get_or_create_conversation(
                    db, client.id, sender_id
                )
                for msg in buffer_messages:
                    await client_service.save_message(
                        db, conversation, "user", msg["text"], msg["is_voice"]
                    )

        # ── Cache: add combined user turn, get history for Claude ─────────────
        _store.append(cache_key, "user", combined_text)
        history = _store.get(cache_key)

        # ── Claude ────────────────────────────────────────────────────────────
        reply, is_hot_lead, temperature = await ask_claude(
            sender_id, combined_text, client, history
        )
        _store.append(cache_key, "assistant", reply)

        # ── DB: save assistant reply + lead ───────────────────────────────────
        lead_id = None
        if use_db:
            async with async_session_factory() as db:
                conversation = await client_service.get_or_create_conversation(
                    db, client.id, sender_id
                )
                await client_service.save_message(db, conversation, "assistant", reply)
                if is_hot_lead:
                    lead = await client_service.save_lead(
                        db, client.id, conversation, sender_id, temperature, combined_text
                    )
                    lead_id = lead.id

        # ── Instagram ─────────────────────────────────────────────────────────
        await send_message(sender_id, reply, access_token)

        # ── Telegram notification + mark lead notified ────────────────────────
        if is_hot_lead:
            recent = _store.get(cache_key)
            await send_lead_notification(
                sender_id=sender_id,
                ai_reply=reply,
                temperature=temperature,
                telegram_chat_id=telegram_chat_id,
                whatsapp_link=whatsapp_link,
                recent_messages=recent,
            )
            if use_db and lead_id is not None:
                async with async_session_factory() as db:
                    await db.execute(
                        sa_update(Lead)
                        .where(Lead.id == lead_id)
                        .values(notified_to_telegram=True)
                    )
                    await db.commit()

    except Exception as e:
        logger.error("DEBOUNCE PROCESSOR ERROR: %s", e, exc_info=True)


# ── Webhook ───────────────────────────────────────────────────────────────────

@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403)


@app.post("/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    print(f"INCOMING: {body}")
    try:
        for entry in body.get("entry", []):
            account_id = entry.get("id")

            # ── Resolve client ─────────────────────────────────────────────
            client = None
            if db is not None:
                client = await client_service.get_by_instagram_id(db, account_id)
                if client is not None:
                    print(f"CLIENT SOURCE: DB | id={client.id} | business={client.business_name} | prompt_len={len(client.system_prompt) if client.system_prompt else 0}")

            if client is None:
                client = _get_legacy_client()
                if client is None or client.instagram_account_id != account_id:
                    print(f"CLIENT SOURCE: NOT FOUND | account_id={account_id}")
                    continue
                print(f"CLIENT SOURCE: ENV (synthetic fallback) | account_id={account_id}")

            if client.status != "active" and not isinstance(client, _LegacyClient):
                print(f"SKIP: client {account_id} status={client.status}")
                continue

            access_token = _resolve_token(client)
            groq_key = _resolve_groq_key(client)
            telegram_chat_id = client.telegram_manager_chat_id or ""
            whatsapp_link = client.whatsapp_link or _LEGACY_WHATSAPP_LINK
            client_id = client.id

            # ── Process messages ───────────────────────────────────────────
            for messaging in entry.get("messaging", []):
                sender_id = messaging["sender"]["id"]

                if messaging.get("message", {}).get("is_echo"):
                    print("SKIP: echo message")
                    continue

                if sender_id == account_id:
                    print("SKIP: message from bot itself")
                    continue

                msg = messaging.get("message", {})
                mid = msg.get("mid", "")
                if mid and _store.is_seen(mid):
                    print(f"SKIP: duplicate mid={mid}")
                    continue

                text = msg.get("text", "")
                is_voice = False

                if not text:
                    for att in msg.get("attachments", []):
                        if att.get("type") == "audio":
                            audio_url = att.get("payload", {}).get("url", "")
                            transcribed = await transcribe_audio(audio_url, groq_key) if audio_url else None
                            if transcribed:
                                text = transcribed
                                is_voice = True
                            else:
                                await send_message(sender_id, "Извините, не смог распознать голосовое. Напишите текстом, пожалуйста 🙏", access_token)
                            break

                if not text:
                    print("SKIP: no text or supported attachment")
                    continue

                print(f"MSG FROM {sender_id}{' (voice)' if is_voice else ''}: {text}")

                # ── Debounce: buffer message, schedule processing ──────────
                my_ts = await _debounce.add_message_to_buffer(
                    client_id=str(client_id),
                    user_id=sender_id,
                    message_text=text,
                    is_voice=is_voice,
                )
                asyncio.create_task(
                    process_after_debounce(
                        client=client,
                        sender_id=sender_id,
                        my_timestamp=my_ts,
                        access_token=access_token,
                        telegram_chat_id=telegram_chat_id,
                        whatsapp_link=whatsapp_link,
                    )
                )

    except Exception as e:
        print(f"WEBHOOK ERROR: {e}")
    return {"status": "ok"}


# ── Static ────────────────────────────────────────────────────────────────────

@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return "<h1>Privacy Policy</h1><p>We only process messages to respond to user inquiries.</p>"


@app.get("/")
async def root():
    return {"status": "Adab AI Sales Bot is running (multi-tenant)"}
