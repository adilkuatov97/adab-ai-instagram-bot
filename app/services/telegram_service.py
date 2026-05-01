import os
from datetime import datetime
import pytz
import httpx

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_lead_notification(
    sender_id: str,
    ai_reply: str,
    temperature: str,
    telegram_chat_id: str,
    whatsapp_link: str,
    recent_messages: list[dict],
) -> None:
    if not TELEGRAM_BOT_TOKEN or not telegram_chat_id:
        print("TELEGRAM: bot token or chat_id not set, skipping")
        return

    temp_label = "🔥 ГОРЯЧИЙ ЛИД" if temperature == "hot" else "🌡️ ТЁПЛЫЙ ЛИД"

    almaty_tz = pytz.timezone("Asia/Almaty")
    now = datetime.now(almaty_tz).strftime("%d.%m.%Y %H:%M")

    context_lines = []
    for msg in recent_messages[-3:]:
        role_label = "Клиент" if msg["role"] == "user" else "Бот"
        context_lines.append(f"<b>{role_label}:</b> {_html_escape(msg['content'])}")
    context_block = "\n".join(context_lines) if context_lines else "(нет истории)"

    text = (
        f"<b>{temp_label}</b>\n\n"
        f"👤 Instagram ID: <code>{sender_id}</code>\n"
        f"⏰ Время: {now}\n\n"
        f"📜 <b>Последние сообщения:</b>\n"
        f"{context_block}\n\n"
        f"💬 <b>Ответ бота отправлен:</b>\n"
        f"<i>{_html_escape(ai_reply)}</i>"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "💬 Открыть Instagram", "url": f"https://instagram.com/direct/t/{sender_id}"},
                {"text": "📱 Написать в WhatsApp", "url": whatsapp_link},
            ],
            [
                {"text": "📋 Скопировать ID клиента", "callback_data": f"copy_id:{sender_id}"},
            ],
        ]
    }

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                print(f"TELEGRAM OK: notified chat {telegram_chat_id} ({temperature})")
            else:
                resp_data = r.json()
                print(f"TELEGRAM ERROR {r.status_code}: {resp_data.get('description', r.text)}")
    except Exception as e:
        print(f"TELEGRAM EXCEPTION: {type(e).__name__}: {e}")
