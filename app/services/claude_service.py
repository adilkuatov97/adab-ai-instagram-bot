from __future__ import annotations

import json
import logging
import os
import re
import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Conversation

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SAFE_CLAUDE_FALLBACK = "Здравствуйте! Сейчас менеджер подключится и ответит вам вручную."

logger = logging.getLogger(__name__)


def _extract_json(raw: str) -> str:
    """Strip markdown fences and any leading/trailing text outside the JSON object."""
    # Remove ```json ... ``` or ``` ... ``` fences
    if "```" in raw:
        inner = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if inner:
            raw = inner.group(1).strip()

    # If still not starting with '{', find the first '{' … last '}'
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]

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
        if not ANTHROPIC_API_KEY:
            logger.error("CLAUDE_ERROR anthropic_api_key_missing sender_id=%s", sender_id)
            return SAFE_CLAUDE_FALLBACK, False, "cold"

        anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=full_system,
            messages=history,
        )
        raw_text = response.content[0].text.strip()
        print(f"CLAUDE RAW: {raw_text}")
        raw = _extract_json(raw_text)

        parsed = json.loads(raw)
        reply = parsed.get("reply", "")
        temperature = parsed.get("lead_temperature", "cold")
        is_hot_lead = temperature in ("hot", "warm")

        print(f"CLAUDE REPLY: {reply} | TEMP: {temperature} | HOT: {is_hot_lead}")
        return reply, is_hot_lead, temperature

    except json.JSONDecodeError:
        logger.error("CLAUDE_ERROR json_parse_failed sender_id=%s", sender_id, exc_info=True)
        return SAFE_CLAUDE_FALLBACK, False, "cold"
    except Exception as e:
        logger.error("CLAUDE_ERROR sender_id=%s error=%s", sender_id, e, exc_info=True)
        return SAFE_CLAUDE_FALLBACK, False, "cold"
