from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_TTL = 30 * 24 * 60 * 60


class ConversationStore:
    """Async Redis-backed conversation cache with in-memory fallback. Key: '{client_id}:{user_id}'"""

    def __init__(self, redis_url: str = REDIS_URL):
        self._redis = None
        self._fallback: dict = {}
        self._seen_mids: set = set()
        if redis_url:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(redis_url, decode_responses=True)
                logger.info("CONV_STORE aioredis_client_initialized")
            except Exception as e:
                logger.warning("CONV_STORE aioredis_init_failed error=%s using_memory=true", e)

    async def get(self, key: str) -> list:
        if self._redis is not None:
            try:
                raw = await self._redis.get(f"conv:{key}")
                return json.loads(raw)[-20:] if raw else []
            except Exception as e:
                logger.warning("CONV_STORE get_error error=%s", e)
        return list(self._fallback.get(key, []))[-20:]

    async def is_seen(self, mid: str) -> bool:
        """Return True if mid was already processed (duplicate). Marks it seen atomically."""
        if self._redis is not None:
            try:
                added = await self._redis.setnx(f"seen:{mid}", "1")
                if added:
                    await self._redis.expire(f"seen:{mid}", 86400)
                return not bool(added)
            except Exception as e:
                logger.warning("CONV_STORE setnx_error error=%s", e)
        if mid in self._seen_mids:
            return True
        self._seen_mids.add(mid)
        if len(self._seen_mids) > 10000:
            self._seen_mids.clear()
        return False

    async def append(self, key: str, role: str, content: str) -> None:
        if self._redis is not None:
            try:
                cache_key = f"conv:{key}"
                raw = await self._redis.get(cache_key)
                history = json.loads(raw) if raw else []
                history.append({"role": role, "content": content})
                await self._redis.set(cache_key, json.dumps(history), ex=REDIS_TTL)
                return
            except Exception as e:
                logger.warning("CONV_STORE set_error error=%s", e)
        if key not in self._fallback:
            self._fallback[key] = []
        self._fallback[key].append({"role": role, "content": content})
