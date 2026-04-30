import os
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse
import anthropic

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_secret_token")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MANAGER_INSTAGRAM_ID = os.getenv("MANAGER_INSTAGRAM_ID", "")

KINDERGARTEN_INFO = """
Детский сад "Ansarik" — частный детский сад.

ОСНОВНАЯ ИНФОРМАЦИЯ:
- Возраст детей: от 1.5 до 7 лет
- Адрес: [2-й переулок С. Датова 11]
- Телефон: [+77004088588,+77004518053]
- Instagram: @ansarik.balabaqsha

РЕЖИМ РАБОТЫ:
- Пн–Пт: 07:30 – 19:00
- Сб–Вс: выходной

СТОИМОСТЬ (в месяц):
- Полный день (7:30–19:00): [30000 тг]
- Короткий день (7:30–14:00): [20000 тг]
- Питание включено в стоимость

ЗАПИСЬ НА ЭКСКУРСИЮ:
- Экскурсии проводятся Пн–Пт в 10:00 и 16:00
- Запись через Instagram Direct или по телефону
- Экскурсия бесплатная, длится ~30 минут
"""

conversation_history: dict[str, list] = {}

SYSTEM_PROMPT = f"""Ты — дружелюбный AI-ассистент частного детского сада Ansarik. 
Твоя задача — помогать родителям получить информацию и записаться на экскурсию.

{KINDERGARTEN_INFO}

ПРАВИЛА ОБЩЕНИЯ:
1. Отвечай тепло и дружелюбно
2. Используй язык собеседника (русский, казахский, английский и др.)
3. Отвечай кратко — 2–4 предложения
4. Используй эмодзи умеренно (1–2 на сообщение) 🌟

ЗАПИСЬ НА ЭКСКУРСИЮ:
Когда родитель хочет записаться, попроси:
1. Имя родителя
2. Имя и возраст ребёнка  
3. Удобное время (Пн–Пт, 10:00 или 16:00)
4. Номер телефона
После получения данных напиши: "ЗАПИСЬ_ОФОРМЛЕНА: [данные]"

ЭСКАЛАЦИЯ:
Если вопрос сложный — напиши: "НУЖЕН_МЕНЕДЖЕР: [причина]"
"""

async def send_instagram_message(recipient_id: str, text: str):
    url = f"https://graph.facebook.com/v19.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "access_token": PAGE_ACCESS_TOKEN
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        return response.json()

async def notify_manager(sender_id: str, reason: str, user_message: str):
    if MANAGER_INSTAGRAM_ID:
        manager_text = (
            f"⚠️ Новый запрос!\n"
            f"От: {sender_id}\n"
            f"Причина: {reason}\n"
            f"Сообщение: {user_message}"
        )
        await send_instagram_message(MANAGER_INSTAGRAM_ID, manager_text)

async def process_message(sender_id: str, user_text: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    if sender_id not in conversation_history:
        conversation_history[sender_id] = []
    
    conversation_history[sender_id].append({
        "role": "user",
        "content": user_text
    })
    
    history = conversation_history[sender_id][-10:]
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=history
    )
    
    assistant_reply = response.content[0].text
    
    conversation_history[sender_id].append({
        "role": "assistant",
        "content": assistant_reply
    })
    
    if "НУЖЕН_МЕНЕДЖЕР:" in assistant_reply:
        reason = assistant_reply.split("НУЖЕН_МЕНЕДЖЕР:")[1].strip()
        await notify_manager(sender_id, reason, user_text)
        assistant_reply = (
            "Ваш вопрос требует индивидуального подхода 🤝\n"
            "Передала менеджеру — свяжется с вами в ближайшее время!"
        )
    elif "ЗАПИСЬ_ОФОРМЛЕНА:" in assistant_reply:
        booking_data = assistant_reply.split("ЗАПИСЬ_ОФОРМЛЕНА:")[1].strip()
        await notify_manager(sender_id, f"Новая запись: {booking_data}", user_text)
        assistant_reply = (
            "Вы записаны на экскурсию 🎉\n"
            "Менеджер подтвердит время по телефону. Ждём вас!"
        )
    
    return assistant_reply

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if (params.get("hub.mode") == "subscribe" and 
        params.get("hub.verify_token") == VERIFY_TOKEN):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook")
async def handle_webhook(request: Request):
    body = await request.json()
    try:
        for entry in body.get("entry", []):
            for messaging in entry.get("messaging", []):
                sender_id = messaging["sender"]["id"]
                if messaging.get("message", {}).get("is_echo"):
                    continue
                message = messaging.get("message", {})
                user_text = message.get("text", "")
                if not user_text:
                    continue
                reply = await process_message(sender_id, user_text)
                await send_instagram_message(sender_id, reply)
    except Exception as e:
    import traceback
    print(f"Ошибка: {e}")
    print(traceback.format_exc())
    return {"status": "ok"}

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Политика конфиденциальности — Ansarik Bot</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; }
            h1 { color: #073B4C; }
            h2 { color: #06D6A0; margin-top: 30px; }
        </style>
    </head>
    <body>
        <h1>Политика конфиденциальности</h1>
        <p>Последнее обновление: 30 апреля 2026 года</p>

        <h2>1. Сбор данных</h2>
        <p>Наш бот обрабатывает только сообщения, которые пользователи отправляют через Instagram Direct. Мы не собираем личные данные без вашего ведома.</p>

        <h2>2. Использование данных</h2>
        <p>Данные используются исключительно для ответа на вопросы о детском саде Ansarik и записи на экскурсию.</p>

        <h2>3. Хранение данных</h2>
        <p>История диалогов хранится временно в оперативной памяти сервера и удаляется при перезапуске.</p>

        <h2>4. Передача данных</h2>
        <p>Мы не передаём ваши данные третьим лицам, за исключением случаев когда это необходимо для ответа на ваш запрос.</p>

        <h2>5. Контакты</h2>
        <p>По вопросам конфиденциальности: @ansarik.balabaqsha в Instagram</p>
    </body>
    </html>
    """

@app.get("/")
async def root():
    return {"status": "Ansarik детский сад AI-агент работает! 🌟"}
