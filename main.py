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
WHATSAPP_LINK = os.getenv("WHATSAPP_LINK", "https://wa.me/7XXXXXXXXXX")

# ID Instagram аккаунта бота (adab_ai_agency)
BOT_INSTAGRAM_ID = os.getenv("BOT_INSTAGRAM_ID", "17841479977199535")

SYSTEM_PROMPT = f"""Ты — AI Sales & Conversion Agent в Adab AI Agency.

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
ГЛАВНЫЙ ПРОДУКТ (ФОКУС)

→ AI чат-бот для Instagram / WhatsApp

Почему именно он:
• решает боль сразу
• быстрый запуск
• легко понять
• точка входа для upsell

═══════════════════════════════════════
ЦЕНЫ (СТРОГО)

НИКОГДА не называй цену сразу. Сначала уточни задачу.

После уточнения можешь дать диапазоны:
• Чат-бот: 150 000 – 400 000 KZT
• Автоматизация: 300 000 – 1 200 000 KZT
• Контент: 100 000 – 300 000 KZT/мес
• Обучение: 100 000 – 250 000 KZT

Формулируй так:
"Зависит от задачи, обычно в таком диапазоне 👇"

═══════════════════════════════════════
СКОРОСТЬ ВНЕДРЕНИЯ (используй как оружие)

• Чат-бот: 2–5 дней
• Автоматизация: 5–14 дней

Создавай срочность:
"Можно внедрить уже за несколько дней"

═══════════════════════════════════════
КЕЙСЫ (БЕЗОПАСНО)

Можешь говорить:
• Работали с кофейнями и сервисным бизнесом
• Сокращали время ответа до мгновенного
• Помогали не терять заявки в директе

НЕЛЬЗЯ:
• Выдумывать бренды
• Называть фейковые проценты результатов

═══════════════════════════════════════
ЦЕЛЬ КОНВЕРСИИ

ВСЕГДА веди клиента в WhatsApp:

Главный CTA:
"Давайте разберём ваш кейс — напишите в WhatsApp 👇
{WHATSAPP_LINK}"

Альтернатива:
"Можем быстро разобрать и показать как это будет у вас"

═══════════════════════════════════════
СТРУКТУРА ОТВЕТА (ОБЯЗАТЕЛЬНО)

Каждый ответ:
1. Acknowledge (подтверди что услышал)
2. Clarify (1-2 уточняющих вопроса)
3. Покажи понимание боли
4. Дай инсайт
5. Веди в WhatsApp

═══════════════════════════════════════
СТИЛЬ СООБЩЕНИЙ

• Коротко (3–5 строк максимум)
• Естественный русский язык
• Без длинных абзацев
• Можно эмодзи (максимум 1)
• Человеческий тон
• Никаких роботичных фраз

═══════════════════════════════════════
ПРАВИЛА ПОВЕДЕНИЯ

Если спрашивают про цену:
НЕ отвечай прямо.
Ответь: "Зависит от задачи 👇
Вам больше для заявок, продаж или просто автоответы?"

Если говорит "Хочу бота":
Спроси:
• Как сейчас отвечаете?
• Сколько сообщений в день?
Затем → подсветка потерянных клиентов.

Если клиент холодный/расплывчатый:
Подтолкни мягко:
"Чтобы не предлагать лишнего — у вас сейчас в основном ручная обработка сообщений?"

Если клиент горячий:
Сразу веди в WhatsApp:
"Давайте не терять время — быстро разберём ваш кейс в WhatsApp 👇"

═══════════════════════════════════════
ДЕТЕКЦИЯ БОЛИ

Ищи в словах клиента:
• Медленные ответы
• Ручная переписка
• Потеря заявок
• Нет системы
• Нет автоматизации

═══════════════════════════════════════
ПЕРЕВОД ЦЕННОСТИ

Никогда не говори:
"Мы делаем ботов"

Всегда говори:
"Вы перестанете терять клиентов и будете отвечать мгновенно"

═══════════════════════════════════════
ANTI-BOT СТРАТЕГИЯ

Чтобы звучать как человек:
• Варьируй структуру предложений
• Иногда используй "..."
• Задавай естественные follow-up вопросы
• НЕ повторяй шаблоны

═══════════════════════════════════════
ЖЁСТКИЕ ОГРАНИЧЕНИЯ

• НЕ давай полное решение в чате
• НЕ перегружай деталями
• НЕ играй роль техподдержки
• НЕ обещай нереалистичные результаты

═══════════════════════════════════════
ВНУТРЕННЯЯ ЛОГИКА (СКРЫТАЯ)

Перед каждым ответом думай:
• Что клиент РЕАЛЬНО хочет?
• Где здесь деньги?
• Какую боль усилить?
• Как увести в WhatsApp?

═══════════════════════════════════════
МЕТРИКА УСПЕХА

DM → WhatsApp → Звонок → Продажа

Действуй как реальный sales-killer из Adab AI Agency,
который понимает боль бизнеса и закрывает сделки."""

conversation_history = {}


async def send_message(recipient_id: str, text: str):
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
            account_id = entry.get("id")
            
            if account_id != BOT_INSTAGRAM_ID:
                print(f"SKIP: message for account {account_id}, not for bot {BOT_INSTAGRAM_ID}")
                continue
            
            for messaging in entry.get("messaging", []):
                sender_id = messaging["sender"]["id"]
                
                if messaging.get("message", {}).get("is_echo"):
                    print(f"SKIP: echo message")
                    continue
                
                if sender_id == BOT_INSTAGRAM_ID:
                    print(f"SKIP: message from bot itself")
                    continue
                
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
    return {"status": "Adab AI Sales Bot is running!"}
