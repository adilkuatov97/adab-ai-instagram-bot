import os
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse
import anthropic

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "AdabAI2026$")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MANAGER_INSTAGRAM_ID = os.getenv("MANAGER_INSTAGRAM_ID", "")

# ID Instagram аккаунта бота (adab_ai_agency)
# Бот отвечает ТОЛЬКО на сообщения, которые приходят на этот аккаунт
BOT_INSTAGRAM_ID = os.getenv("BOT_INSTAGRAM_ID", "17841479977199535")

SYSTEM_PROMPT = """Ты — дружелюбный AI-ассистент. Отвечай кратко и по делу на любом языке собеседника."""

conversation_history = {}


async def send_message(recipient_id: str, text: str):
    # Для токенов IGAA... используется graph.instagram.com
    url = "https://graph.instagram.com/v23.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }
    headers = {
        "Authorization": f"Bearer {PAGE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers=headers)
        print(f"SEND RESULT: {r.status_code} {r.text}")
        return r.json()


async def ask_claude(sender_id: str, user_text: str) -> str:
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        if sender_id not in conversation_history:
            conversation_history[sender_id] = []
        conversation_history[sender_id].append({"role": "user", "content": user_text})
        history = conversation_history[sender_id][-10:]
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=history
        )
        reply = response.content[0].text
        conversation_history[sender_id].append({"role": "assistant", "content": reply})
        print(f"CLAUDE REPLY: {reply}")
        return reply
    except Exception as e:
        print(f"CLAUDE ERROR: {e}")
        return f"Ошибка Claude: {str(e)}"


@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403)


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    print(f"INCOMING: {body}")
    try:
        for entry in body.get("entry", []):
            # entry["id"] — это ID аккаунта-получателя сообщения
            account_id = entry.get("id")
            
            # Игнорируем сообщения, которые пришли НЕ на бот-аккаунт
            if account_id != BOT_INSTAGRAM_ID:
                print(f"SKIP: message for account {account_id}, not for bot {BOT_INSTAGRAM_ID}")
                continue
            
            for messaging in entry.get("messaging", []):
                sender_id = messaging["sender"]["id"]
                
                # Игнорируем эхо (сообщения, отправленные самим ботом)
                if messaging.get("message", {}).get("is_echo"):
                    print(f"SKIP: echo message")
                    continue
                
                # Игнорируем сообщения, отправленные с самого бот-аккаунта
                if sender_id == BOT_INSTAGRAM_ID:
                    print(f"SKIP: message from bot itself")
                    continue
                
                # Игнорируем события read/delivery (не сообщения)
                text = messaging.get("message", {}).get("text", "")
                if not text:
                    print(f"SKIP: no text (read/delivery event)")
                    continue
                
                print(f"MSG FROM {sender_id}: {text}")
                reply = await ask_claude(sender_id, text)
                await send_message(sender_id, reply)
    except Exception as e:
        print(f"WEBHOOK ERROR: {e}")
    return {"status": "ok"}


@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return "<h1>Privacy Policy</h1><p>We only process messages to respond to user inquiries.</p>"


@app.get("/")
async def root():
    return {"status": "Bot is running!"}
