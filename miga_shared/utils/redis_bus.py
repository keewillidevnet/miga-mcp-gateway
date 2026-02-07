"""Redis pub/sub event bus — v1 inter-service messaging (v2 migrates to AGNTCY SLIM)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Coroutine
from typing import Any, Optional

logger = logging.getLogger("miga.redis_bus")

Handler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class RedisPubSub:
    """Async Redis pub/sub for cross-platform event distribution."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("MIGA_REDIS_URL", "redis://redis:6379/0")
        self._redis = None
        self._pubsub = None
        self._handlers: dict[str, list[Handler]] = {}
        self._task: Optional[asyncio.Task] = None

    async def connect(self):
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            self._pubsub = self._redis.pubsub()
            logger.info("Redis connected: %s", self.redis_url)
        except ImportError:
            logger.warning("redis package not installed — pub/sub disabled")
        except Exception as e:
            logger.error("Redis connect failed: %s", e)

    async def publish(self, channel: str, data: dict[str, Any]) -> int:
        if not self._redis:
            return 0
        try:
            return await self._redis.publish(channel, json.dumps(data, default=str))
        except Exception as e:
            logger.error("Publish to %s failed: %s", channel, e)
            return 0

    async def subscribe(self, channel: str, handler: Handler):
        self._handlers.setdefault(channel, []).append(handler)
        if self._pubsub:
            await self._pubsub.subscribe(channel)

    async def start_listening(self):
        if self._pubsub:
            self._task = asyncio.create_task(self._listen())

    async def _listen(self):
        if not self._pubsub:
            return
        try:
            async for msg in self._pubsub.listen():
                if msg["type"] != "message":
                    continue
                ch = msg["channel"]
                try:
                    data = json.loads(msg["data"])
                except json.JSONDecodeError:
                    data = {"raw": msg["data"]}
                for handler in self._handlers.get(ch, []):
                    try:
                        await handler(ch, data)
                    except Exception as e:
                        logger.error("Handler error on %s: %s", ch, e)
        except asyncio.CancelledError:
            pass

    async def close(self):
        if self._task:
            self._task.cancel()
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    # Convenience channels
    async def publish_event(self, event: dict) -> int:
        return await self.publish("miga:events:correlated", event)

    async def publish_alert(self, alert: dict) -> int:
        return await self.publish("miga:alerts:security", alert)

    async def request_approval(self, data: dict) -> int:
        return await self.publish("miga:approval:request", data)

    async def publish_telemetry(self, platform: str, data: dict) -> int:
        return await self.publish(f"miga:telemetry:{platform}", data)
