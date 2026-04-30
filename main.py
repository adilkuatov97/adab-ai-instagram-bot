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

SYSTEM_PROMPT = """Ты — дружелюбный AI-ассистент. Отвечай кратко и по делу на любом языке собеседника."""

conversation_history = {}


async def send_message(recipient_id: str, text: str):
    url = "https://graph.facebook.com/v19.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "access_token": PAGE_ACCESS_TOKEN
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload)
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
            for messaging in entry.get("messaging", []):
                sender_id = messaging["sender"]["id"]
                if messaging.get("message", {}).get("is_echo"):
                    continue
                text = messaging.get("message", {}).get("text", "")
                if not text:
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
