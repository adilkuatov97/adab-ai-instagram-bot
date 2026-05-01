import os
import json
from datetime import datetime
import pytz
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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_MANAGER_CHAT_ID = os.getenv("TELEGRAM_MANAGER_CHAT_ID", "")
REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_TTL = 30 * 24 * 60 * 60  # 30 days

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
который понимает боль бизнеса и закрывает сделки.

═══════════════════════════════════════
ПРАВИЛА ВЗАИМОДЕЙСТВИЯ

• При первом сообщении всегда представляйся: "Здравствуйте! Я AI-помощник Adab AI Agency"
• Всегда задавай 1-2 уточняющих вопроса перед тем как предлагать решение
• Никогда не пиши длиннее 5 строк
• Если клиент уклоняется от вопроса о бизнесе — мягко возвращай в тему
• Если клиент 3 сообщения подряд игнорирует WhatsApp — смени тактику: предложи кейс или конкретный быстрый инсайт

═══════════════════════════════════════
ЯЗЫК ОБЩЕНИЯ

• Определяй язык клиента и отвечай на том же языке
• Если клиент пишет на казахском — отвечай на казахском
• Если клиент пишет на английском — отвечай на английском
• По умолчанию — русский

═══════════════════════════════════════
ТЕХНИЧЕСКИЙ ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО)

Отвечай ТОЛЬКО валидным JSON без markdown-обёртки:
{{"reply": "текст ответа клиенту", "lead_temperature": "cold"}}

Правила определения lead_temperature:
• "hot" — явно готов покупать: "хочу", "беру", "готов", "мой WhatsApp", "созвонимся", "когда можем начать", оставляет телефон, просит встречу
• "warm" — проявляет конкретный интерес: спрашивает цену, сроки, примеры работ, как работает процесс
• "cold" — просто разведка: привет, что вы делаете, расскажите подробнее

Если lead_temperature = "hot" или "warm" → в поле reply напиши клиенту что передаёшь его менеджеру и он свяжется в ближайшее время, укажи WhatsApp {WHATSAPP_LINK}.
Если lead_temperature = "cold" → в поле reply отвечай по стандартной sales-логике выше."""

class ConversationStore:
    def __init__(self):
        self._client = None
        self._fallback: dict = {}
        self._redis_failed = False

    def _connect(self):
        if self._client is not None:
            return self._client
        if not REDIS_URL or self._redis_failed:
            return None
        try:
            import redis
            client = redis.from_url(REDIS_URL, decode_responses=True)
            client.ping()
            self._client = client
            print("REDIS: connected successfully")
        except Exception as e:
            print(f"REDIS WARNING: connection failed ({type(e).__name__}: {e}), using in-memory fallback")
            self._redis_failed = True
        return self._client

    def get_history(self, user_id: str) -> list:
        r = self._connect()
        if r:
            try:
                raw = r.get(f"conv:{user_id}")
                return json.loads(raw)[-20:] if raw else []
            except Exception as e:
                print(f"REDIS GET ERROR: {e}")
        return list(self._fallback.get(user_id, []))[-20:]

    def add_message(self, user_id: str, role: str, content: str):
        r = self._connect()
        if r:
            try:
                key = f"conv:{user_id}"
                raw = r.get(key)
                history = json.loads(raw) if raw else []
                history.append({"role": role, "content": content})
                r.set(key, json.dumps(history), ex=REDIS_TTL)
                return
            except Exception as e:
                print(f"REDIS SET ERROR: {e}")
        if user_id not in self._fallback:
            self._fallback[user_id] = []
        self._fallback[user_id].append({"role": role, "content": content})


store = ConversationStore()


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_telegram_notification(sender_id: str, ai_reply: str, temperature: str = "hot"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_MANAGER_CHAT_ID:
        print("TELEGRAM: not configured, skipping notification")
        return

    temp_label = "🔥 ГОРЯЧИЙ ЛИД" if temperature == "hot" else "🌡️ ТЁПЛЫЙ ЛИД"

    almaty_tz = pytz.timezone("Asia/Almaty")
    now = datetime.now(almaty_tz).strftime("%d.%m.%Y %H:%M")

    history = store.get_history(sender_id)
    context_lines = []
    for msg in history[-3:]:
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
                {"text": "📱 Написать в WhatsApp", "url": WHATSAPP_LINK},
            ],
            [
                {"text": "📋 Скопировать ID клиента", "callback_data": f"copy_id:{sender_id}"},
            ],
        ]
    }

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_MANAGER_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                print(f"TELEGRAM OK: notification sent for {sender_id} ({temperature})")
            else:
                resp_data = r.json()
                print(f"TELEGRAM ERROR {r.status_code}: {resp_data.get('description', r.text)}")
    except Exception as e:
        print(f"TELEGRAM EXCEPTION: {type(e).__name__}: {e}")


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


async def ask_claude(sender_id: str, user_text: str) -> tuple[str, bool, str]:
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        store.add_message(sender_id, "user", user_text)
        history = store.get_history(sender_id)[-10:]
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=history
        )
        raw = response.content[0].text.strip()
        print(f"CLAUDE RAW: {raw}")

        # Strip markdown code fences if Claude wrapped the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        parsed = json.loads(raw)
        reply = parsed.get("reply", "")
        temperature = parsed.get("lead_temperature", "cold")
        is_hot_lead = temperature in ("hot", "warm")

        store.add_message(sender_id, "assistant", reply)
        print(f"CLAUDE REPLY: {reply} | TEMP: {temperature} | HOT: {is_hot_lead}")
        return reply, is_hot_lead, temperature

    except json.JSONDecodeError:
        print(f"CLAUDE JSON PARSE ERROR, using raw text as reply")
        reply = response.content[0].text.strip() if 'response' in dir() else "Произошла ошибка, попробуйте ещё раз."
        store.add_message(sender_id, "assistant", reply)
        return reply, False, "cold"
    except Exception as e:
        print(f"CLAUDE ERROR: {e}")
        return f"Ошибка Claude: {str(e)}", False, "cold"


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
                reply, is_hot_lead, temperature = await ask_claude(sender_id, text)
                await send_message(sender_id, reply)

                if is_hot_lead:
                    await send_telegram_notification(sender_id, reply, temperature)

    except Exception as e:
        print(f"WEBHOOK ERROR: {e}")
    return {"status": "ok"}


@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return "<h1>Privacy Policy</h1><p>We only process messages to respond to user inquiries.</p>"


@app.get("/")
async def root():
    return {"status": "Adab AI Sales Bot is running!"}
