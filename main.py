import os
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
import anthropic

app = FastAPI()

# ─── Конфигурация (заполните своими данными) ──────────────────────────────────
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_secret_token")      # любой токен, придумайте сами
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")            # из Meta Developer Console
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")            # из console.anthropic.com
MANAGER_INSTAGRAM_ID = os.getenv("MANAGER_INSTAGRAM_ID", "")      # ID аккаунта менеджера

# ─── Информация о вашем детском саде (заполните!) ────────────────────────────
KINDERGARTEN_INFO = """
Детский сад "Солнышко" — частный детский сад в [ВАШЕ_ГОРОД].

ОСНОВНАЯ ИНФОРМАЦИЯ:
- Возраст детей: от 1.5 до 7 лет
- Группы: ясельная (1.5–3 года), младшая (3–4), средняя (4–5), старшая (5–7)
- Адрес: [ВАШ_АДРЕС]
- Телефон: [ВАШ_ТЕЛЕФОН]
- Instagram: @[ВАШ_АККАУНТ]

РЕЖИМ РАБОТЫ:
- Пн–Пт: 07:30 – 19:00
- Сб–Вс: выходной

СТОИМОСТЬ (в месяц):
- Полный день (7:30–19:00): [ЦЕНА] руб.
- Короткий день (7:30–14:00): [ЦЕНА] руб.
- Адаптационная группа (2–3 часа): [ЦЕНА] руб.
- Питание включено в стоимость

ПРОГРАММА:
- Развивающие занятия: математика, чтение, творчество
- Английский язык с 3 лет
- Физкультура, музыка, танцы
- Прогулки 2 раза в день
- Сон для малышей до 5 лет

ПИТАНИЕ:
- 4-разовое: завтрак, второй завтрак, обед, полдник
- Меню составляет диетолог
- Учитываются аллергии и предпочтения

ДОКУМЕНТЫ ДЛЯ ПОСТУПЛЕНИЯ:
- Свидетельство о рождении (копия)
- Медицинская карта (форма 026/у)
- Прививочный сертификат
- Справка от педиатра

ЗАПИСЬ НА ЭКСКУРСИЮ:
- Экскурсии проводятся Пн–Пт в 10:00 и 16:00
- Запись через Instagram Direct или по телефону
- Экскурсия бесплатная, длится ~30 минут
"""

# ─── Хранилище истории диалогов (в памяти, простое решение) ──────────────────
conversation_history: dict[str, list] = {}

# ─── Системный промпт для агента ──────────────────────────────────────────────
SYSTEM_PROMPT = f"""Ты — дружелюбный AI-ассистент частного детского сада. 
Твоя задача — помогать родителям получить информацию и записаться на экскурсию.

{KINDERGARTEN_INFO}

ПРАВИЛА ОБЩЕНИЯ:
1. Отвечай тепло и дружелюбно, как заботливый сотрудник садика
2. Используй язык собеседника (русский, казахский, английский и др.)
3. Отвечай кратко — 2–4 предложения, без лишней воды
4. Используй эмодзи умеренно (1–2 на сообщение) 🌟

ЗАПИСЬ НА ЭКСКУРСИЮ:
Когда родитель хочет записаться, попроси:
1. Имя родителя
2. Имя и возраст ребёнка  
3. Удобное время (Пн–Пт, 10:00 или 16:00)
4. Номер телефона для подтверждения
После получения всех данных напиши: "ЗАПИСЬ_ОФОРМЛЕНА: [данные]"

ЭСКАЛАЦИЯ К МЕНЕДЖЕРУ:
Если вопрос касается:
- Индивидуальных скидок или переговоров о цене
- Проблем или жалоб
- Медицинских особенностей ребёнка
- Юридических или договорных вопросов
- Чего-то, чего ты не знаешь
Напиши: "НУЖЕН_МЕНЕДЖЕР: [причина]"

Не придумывай информацию, которой нет в базе знаний выше.
"""

async def send_instagram_message(recipient_id: str, text: str):
    """Отправить сообщение в Instagram Direct"""
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
    """Уведомить менеджера о сложном вопросе"""
    if MANAGER_INSTAGRAM_ID:
        manager_text = (
            f"⚠️ Новый запрос требует вашего внимания!\n\n"
            f"От пользователя: {sender_id}\n"
            f"Причина: {reason}\n"
            f"Сообщение: {user_message}"
        )
        await send_instagram_message(MANAGER_INSTAGRAM_ID, manager_text)

async def process_message(sender_id: str, user_text: str) -> str:
    """Обработать сообщение через Claude"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    # Получить или создать историю диалога
    if sender_id not in conversation_history:
        conversation_history[sender_id] = []
    
    # Добавить сообщение пользователя
    conversation_history[sender_id].append({
        "role": "user",
        "content": user_text
    })
    
    # Ограничить историю последними 10 сообщениями
    history = conversation_history[sender_id][-10:]
    
    # Запрос к Claude
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=history
    )
    
    assistant_reply = response.content[0].text
    
    # Добавить ответ в историю
    conversation_history[sender_id].append({
        "role": "assistant",
        "content": assistant_reply
    })
    
    # Проверить специальные команды
    if "НУЖЕН_МЕНЕДЖЕР:" in assistant_reply:
        reason = assistant_reply.split("НУЖЕН_МЕНЕДЖЕР:")[1].strip()
        await notify_manager(sender_id, reason, user_text)
        # Заменить техническую фразу на человеческий ответ
        assistant_reply = (
            "Ваш вопрос требует индивидуального подхода 🤝\n"
            "Я уже передала его нашему менеджеру — он свяжется с вами в ближайшее время!"
        )
    elif "ЗАПИСЬ_ОФОРМЛЕНА:" in assistant_reply:
        booking_data = assistant_reply.split("ЗАПИСЬ_ОФОРМЛЕНА:")[1].strip()
        await notify_manager(sender_id, f"Новая запись на экскурсию: {booking_data}", user_text)
        assistant_reply = (
            "Отлично! Вы записаны на экскурсию 🎉\n"
            "Наш менеджер подтвердит время по телефону. Ждём вас!"
        )
    
    return assistant_reply

# ─── Webhook эндпоинты ─────────────────────────────────────────────────────────

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Верификация webhook от Meta"""
    params = dict(request.query_params)
    if (params.get("hub.mode") == "subscribe" and 
        params.get("hub.verify_token") == VERIFY_TOKEN):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook")
async def handle_webhook(request: Request):
    """Обработка входящих сообщений из Instagram"""
    body = await request.json()
    
    try:
        for entry in body.get("entry", []):
            for messaging in entry.get("messaging", []):
                sender_id = messaging["sender"]["id"]
                
                # Игнорировать эхо собственных сообщений
                if messaging.get("message", {}).get("is_echo"):
                    continue
                
                # Получить текст сообщения
                message = messaging.get("message", {})
                user_text = message.get("text", "")
                
                if not user_text:
                    continue
                
                # Получить ответ от AI
                reply = await process_message(sender_id, user_text)
                
                # Отправить ответ
                await send_instagram_message(sender_id, reply)
    
    except Exception as e:
        print(f"Ошибка обработки webhook: {e}")
    
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "Детский сад AI-агент работает! 🌟"}
