from __future__ import annotations

import json
import os
import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Conversation

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


async def ask_claude(
    sender_id: str,
    user_text: str,
    client: Client,
    conversation_history: list[dict],
) -> tuple[str, bool, str]:
    """
    Returns (reply, is_hot_lead, temperature).
    conversation_history: list of {role, content} dicts for this sender.
    """
    whatsapp_link = client.whatsapp_link or ""
    system_prompt = (client.system_prompt or "").replace("{whatsapp_link}", whatsapp_link)

    # Inject whatsapp_link into the format instruction at the end of the prompt
    format_block = f"""

═══════════════════════════════════════
ТЕХНИЧЕСКИЙ ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО)

Отвечай ТОЛЬКО валидным JSON без markdown-обёртки:
{{"reply": "текст ответа клиенту", "lead_temperature": "cold"}}

Правила определения lead_temperature:
• "hot" — явно готов покупать: хочет/берёт/готов/просит созвониться/оставляет телефон
• "warm" — проявляет конкретный интерес: цена, сроки, примеры, как работает
• "cold" — просто разведка: привет, что вы делаете, расскажите

Если lead_temperature = "hot" или "warm" → в reply напиши что передаёшь менеджеру, укажи WhatsApp {whatsapp_link}.
Если lead_temperature = "cold" → отвечай по sales-логике."""

    full_system = system_prompt + format_block

    # Build message history (last 10 turns)
    history = conversation_history[-10:]

    try:
        anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=full_system,
            messages=history,
        )
        raw = _strip_fences(response.content[0].text.strip())
        print(f"CLAUDE RAW: {raw}")

        parsed = json.loads(raw)
        reply = parsed.get("reply", "")
        temperature = parsed.get("lead_temperature", "cold")
        is_hot_lead = temperature in ("hot", "warm")

        print(f"CLAUDE REPLY: {reply} | TEMP: {temperature} | HOT: {is_hot_lead}")
        return reply, is_hot_lead, temperature

    except json.JSONDecodeError:
        print("CLAUDE JSON PARSE ERROR, using raw text as reply")
        raw_reply = response.content[0].text.strip() if "response" in dir() else "Произошла ошибка, попробуйте ещё раз."
        return raw_reply, False, "cold"
    except Exception as e:
        print(f"CLAUDE ERROR: {e}")
        return f"Ошибка: {str(e)}", False, "cold"
