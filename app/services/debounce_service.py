from __future__ import annotations

import json
import logging
import os
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

DEBOUNCE_DELAY: float = float(os.getenv("DEBOUNCE_DELAY_SECONDS", "3.0"))
_BUFFER_TTL: int = 30  # seconds — longer than any realistic debounce window


class DebounceService:
    """
    Buffers incoming messages per (client_id, user_id) in Redis.
    Falls back to an in-memory dict when Redis is unavailable.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis: aioredis.Redis | None = (
            aioredis.from_url(redis_url, decode_responses=True) if redis_url else None
        )
        self._mem_buffers: dict[str, list] = {}
        self._mem_ts: dict[str, float] = {}

    # ── Key helpers ────────────────────────────────────────────────────────────

    def _buffer_key(self, client_id: str, user_id: str) -> str:
        return f"msg_buffer:{client_id}:{user_id}"

    def _ts_key(self, client_id: str, user_id: str) -> str:
        return f"msg_last_ts:{client_id}:{user_id}"

    # ── Public API ─────────────────────────────────────────────────────────────

    async def add_message_to_buffer(
        self,
        client_id: str,
        user_id: str,
        message_text: str,
        is_voice: bool = False,
    ) -> float:
        """Append a message to the buffer. Returns the assigned timestamp."""
        buf_key = self._buffer_key(client_id, user_id)
        ts_key = self._ts_key(client_id, user_id)
        ts = time.time()

        if self._redis is not None:
            try:
                existing = await self._redis.get(buf_key)
                messages: list = json.loads(existing) if existing else []
                messages.append({"text": message_text, "is_voice": is_voice, "ts": ts})
                await self._redis.set(buf_key, json.dumps(messages), ex=_BUFFER_TTL)
                await self._redis.set(ts_key, str(ts), ex=_BUFFER_TTL)
                logger.info(
                    "DEBOUNCE [redis]: buffered msg #%d client=%s user=%s ts=%.3f",
                    len(messages), client_id, user_id, ts,
                )
                return ts
            except Exception as exc:
                logger.warning("DEBOUNCE: Redis write failed (%s), falling back to memory", exc)

        # ── In-memory fallback ─────────────────────────────────────────────────
        msgs = self._mem_buffers.get(buf_key, [])
        msgs.append({"text": message_text, "is_voice": is_voice, "ts": ts})
        self._mem_buffers[buf_key] = msgs
        self._mem_ts[ts_key] = ts
        logger.info(
            "DEBOUNCE [memory]: buffered msg #%d client=%s user=%s ts=%.3f",
            len(msgs), client_id, user_id, ts,
        )
        return ts

    async def is_still_latest(
        self,
        client_id: str,
        user_id: str,
        my_timestamp: float,
    ) -> bool:
        """
        Return True only when my_timestamp is still the latest stored,
        meaning no newer message arrived while we were sleeping.
        """
        ts_key = self._ts_key(client_id, user_id)

        if self._redis is not None:
            try:
                stored = await self._redis.get(ts_key)
                if not stored:
                    return False
                result = abs(float(stored) - my_timestamp) < 0.001
                if not result:
                    logger.info(
                        "DEBOUNCE: superseded user=%s stored=%s mine=%.3f",
                        user_id, stored, my_timestamp,
                    )
                return result
            except Exception as exc:
                logger.warning("DEBOUNCE: Redis read failed in is_still_latest (%s)", exc)

        # ── In-memory fallback ─────────────────────────────────────────────────
        stored_mem = self._mem_ts.get(ts_key)
        if stored_mem is None:
            return False
        result = abs(stored_mem - my_timestamp) < 0.001
        if not result:
            logger.info(
                "DEBOUNCE [memory]: superseded user=%s stored=%.3f mine=%.3f",
                user_id, stored_mem, my_timestamp,
            )
        return result

    async def get_and_clear_buffer(
        self,
        client_id: str,
        user_id: str,
    ) -> list[dict]:
        """Read all buffered messages and atomically clear the buffer."""
        buf_key = self._buffer_key(client_id, user_id)
        ts_key = self._ts_key(client_id, user_id)

        if self._redis is not None:
            try:
                existing = await self._redis.get(buf_key)
                messages: list = json.loads(existing) if existing else []
                await self._redis.delete(buf_key, ts_key)
                logger.info(
                    "DEBOUNCE [redis]: cleared %d message(s) for user=%s",
                    len(messages), user_id,
                )
                return messages
            except Exception as exc:
                logger.warning("DEBOUNCE: Redis read failed in get_and_clear_buffer (%s)", exc)

        # ── In-memory fallback ─────────────────────────────────────────────────
        messages = self._mem_buffers.pop(buf_key, [])
        self._mem_ts.pop(ts_key, None)
        logger.info(
            "DEBOUNCE [memory]: cleared %d message(s) for user=%s",
            len(messages), user_id,
        )
        return messages
