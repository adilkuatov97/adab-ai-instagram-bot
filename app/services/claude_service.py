from __future__ import annotations

import json
import logging
import os
import re
import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Conversation

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SAFE_CLAUDE_FALLBACK = (
    "Понял вас. Сейчас не могу корректно ответить автоматически, поэтому лучше подключу "
    "менеджера. Напишите, пожалуйста, что важнее обсудить: цену, сроки или как бот будет работать?"
)
EMPTY_CLAUDE_FALLBACK = (
    "Понял вас. Уточните, пожалуйста, что именно хотите узнать — цену, сроки запуска "
    "или как бот будет работать?"
)
MAX_WHATSAPP_REPLY_CHARS = 700
TEMPERATURE_BY_LABEL = {"cold": 0, "warm": 1, "hot": 2}

logger = logging.getLogger(__name__)

# Module-level async singleton — created once, reused for every call
_anthropic_client: anthropic.AsyncAnthropic | None = (
    anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
)


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


def _parse_claude_response(raw_text: str, *, whatsapp_reply: bool = False) -> tuple[str, bool, int]:
    raw = _strip_code_fences(raw_text).strip()
    if not raw:
        return EMPTY_CLAUDE_FALLBACK, False, 0

    parsed = _try_parse_json(raw)
    if parsed is not None:
        reply = _sanitize_reply(str(parsed.get("reply") or ""), whatsapp_reply=whatsapp_reply)
        if not reply:
            reply = EMPTY_CLAUDE_FALLBACK
        temperature = _normalize_temperature(parsed.get("lead_temperature"))
        return reply, temperature > 0, temperature

    reply = _sanitize_reply(raw, whatsapp_reply=whatsapp_reply)
    if not reply:
        reply = EMPTY_CLAUDE_FALLBACK
    return reply, False, 0


def _try_parse_json(raw: str) -> dict | None:
    candidates = [raw]

    fenced = _extract_fenced_json(raw)
    if fenced:
        candidates.append(fenced)

    object_candidate = _extract_json_object(raw)
    if object_candidate:
        candidates.append(object_candidate)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _extract_fenced_json(raw: str) -> str | None:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def _extract_json_object(raw: str) -> str | None:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return raw[start : end + 1].strip()


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json|markdown|text)?\s*([\s\S]*?)```", stripped, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return stripped.replace("```json", "").replace("```", "").strip()


def _sanitize_reply(reply: str, *, whatsapp_reply: bool = False) -> str:
    cleaned = _strip_code_fences(reply)
    cleaned = " ".join(cleaned.split()).strip()
    if whatsapp_reply or len(cleaned) > MAX_WHATSAPP_REPLY_CHARS:
        return _truncate_reply(cleaned, MAX_WHATSAPP_REPLY_CHARS)
    return cleaned


def _truncate_reply(reply: str, max_chars: int) -> str:
    if len(reply) <= max_chars:
        return reply
    clipped = reply[:max_chars].rstrip()
    sentence_end = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if sentence_end >= max_chars // 2:
        return clipped[: sentence_end + 1]
    return clipped[: max_chars - 3].rstrip(" ,.;:") + "..."


def _normalize_temperature(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, min(value, 2))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized.isdigit():
            return max(0, min(int(normalized), 2))
        return TEMPERATURE_BY_LABEL.get(normalized, 0)
    return 0


def _is_whatsapp_response(system_prompt_override: str | None) -> bool:
    prompt = (system_prompt_override or "").lower()
    if "whatsapp response policy" in prompt or "whatsapp" in prompt:
        return True
    return False


async def ask_claude(
    sender_id: str,
    user_text: str,
    client: Client,
    conversation_history: list[dict],
    system_prompt_override: str | None = None,
) -> tuple[str, bool, int]:
    """
    Returns (reply, is_hot_lead, temperature), where temperature is 0=cold, 1=warm, 2=hot.
    conversation_history: list of {role, content} dicts for this sender.
    system_prompt_override: if provided, replaces client.system_prompt.
    """
    whatsapp_link = client.whatsapp_link or ""
    raw_prompt = system_prompt_override if system_prompt_override is not None else (client.system_prompt or "")
    system_prompt = raw_prompt.replace("{whatsapp_link}", whatsapp_link)

    # Inject whatsapp_link into the format instruction at the end of the prompt
    format_block = f"""

═══════════════════════════════════════
ТЕХНИЧЕСКИЙ ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО)

Отвечай ТОЛЬКО валидным JSON без markdown-обёртки:
{{"reply": "текст ответа клиенту", "lead_temperature": "cold"}}

ЯЗЫК ОТВЕТА (ГЛОБАЛЬНОЕ ПРАВИЛО ДЛЯ ВСЕХ АККАУНТОВ):
• Определи язык последнего сообщения клиента и пиши reply на этом же языке.
• Это правило работает для любого языка: русский, казахский, английский, турецкий, узбекский, арабский и т.д.
• Если клиент пишет на смеси языков — отвечай на основном языке последнего сообщения.
• Если язык невозможно определить — отвечай на русском.
• Это правило имеет приоритет над локальными языковыми ограничениями в prompt клиента.
• Поля JSON всегда оставляй на английском: "reply" и "lead_temperature".

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
        if not _anthropic_client:
            logger.error("CLAUDE_ERROR anthropic_api_key_missing sender_id=%s", sender_id)
            return SAFE_CLAUDE_FALLBACK, False, 0

        response = await _anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=[{"type": "text", "text": full_system, "cache_control": {"type": "ephemeral"}}],
            messages=history,
        )
        raw_text = _extract_response_text(response)
        parsed_as_json = _try_parse_json(_strip_code_fences(raw_text).strip()) is not None
        reply, is_hot_lead, temperature = _parse_claude_response(
            raw_text,
            whatsapp_reply=_is_whatsapp_response(system_prompt_override),
        )
        if not parsed_as_json:
            logger.warning(
                "CLAUDE_PARSE_FALLBACK sender_id=%s raw_len=%d error=%s",
                sender_id,
                len(raw_text),
                "JSONDecodeError",
            )

        logger.info("CLAUDE_OK sender_id=%s temp=%s hot=%s reply_len=%d", sender_id, temperature, is_hot_lead, len(reply))
        return reply, is_hot_lead, temperature

    except Exception as e:
        logger.error(
            "CLAUDE_ERROR sender_id=%s error_type=%s",
            sender_id,
            e.__class__.__name__,
            exc_info=True,
        )
        return SAFE_CLAUDE_FALLBACK, False, 0


def _extract_response_text(response) -> str:
    content = getattr(response, "content", None)
    if not content:
        return ""
    first = content[0]
    text = getattr(first, "text", "")
    return text if isinstance(text, str) else ""
