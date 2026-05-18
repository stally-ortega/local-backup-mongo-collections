"""Concrete :class:`~app.application.ports.ports.INotifier` adapter using aiogram.

Features:
- **HTML parse mode** by default (safer than MarkdownV2 for dynamic templates).
- **Global rate limiting**: sliding-window, max 30 messages/second.
- **Retry with exponential backoff**: up to 3 attempts.
- **Graceful degradation**: exceptions are logged and swallowed so that a
  Telegram outage does not crash backup workflows.
"""

import asyncio
import html
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, Protocol, TypeVar

from aiogram.types import FSInputFile

from app.infrastructure.telegram.aiogram_bot import AiogramBot

logger = logging.getLogger(__name__)

_MAX_MESSAGES_PER_SECOND: int = 30
_WINDOW_SECONDS: float = 1.0
_MAX_RETRIES: int = 3
_BACKOFF_BASE_SECONDS: float = 1.0

_T = TypeVar("_T")


class _RateLimiter(Protocol):
    async def acquire(self) -> None: ...


class _InMemoryRateLimiter:
    """Sliding-window rate limiter enforcing *limit* calls per *window*."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            # Discard timestamps that fell outside the window.
            while self._timestamps and (now - self._timestamps[0]) >= self._window:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._limit:
                sleep_time = self._window - (now - self._timestamps[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    now = loop.time()
                    while self._timestamps and (now - self._timestamps[0]) >= self._window:
                        self._timestamps.popleft()
            self._timestamps.append(now)


class _RedisGlobalRateLimiter:
    """Distributed sliding-window rate limiter backed by Redis.

    Uses a single sorted set per instance so that multi-process or
    multi-container deployments share a global counter.
    """

    def __init__(
        self,
        redis_client: Any,
        limit: int,
        window_seconds: float,
        key: str = "telegram_notifier:rate_limit",
    ) -> None:
        self._client = redis_client
        self._limit = limit
        self._window = window_seconds
        self._key = key
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now_ms = int(time.time() * 1000)
            window_start_ms = now_ms - int(self._window * 1000)

            # Trim old entries outside the sliding window.
            await self._client.zremrangebyscore(self._key, 0, window_start_ms)
            current = int(await self._client.zcard(self._key))

            if current >= self._limit:
                # Wait until the oldest entry expires.
                oldest = await self._client.zrange(self._key, 0, 0, withscores=True)
                if oldest:
                    oldest_ms = int(oldest[0][1])
                    sleep_time = (oldest_ms + int(self._window * 1000) - now_ms) / 1000.0
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                        # Re-check after sleeping.
                        now_ms = int(time.time() * 1000)
                        window_start_ms = now_ms - int(self._window * 1000)
                        await self._client.zremrangebyscore(self._key, 0, window_start_ms)

            # Record the current request.
            member = f"{now_ms}:{uuid.uuid4().hex[:8]}"
            await self._client.zadd(self._key, {member: now_ms})
            await self._client.expire(self._key, int(self._window) + 1)


class TelegramNotifier:
    """Send Telegram messages via aiogram with resilience controls."""

    def __init__(
        self,
        aiogram_bot: AiogramBot,
        *,
        base_path: Path | None = None,
        rate_limiter: _RateLimiter | None = None,
    ) -> None:
        self._bot = aiogram_bot
        self._base_path = base_path
        self._rate_limiter = rate_limiter or _InMemoryRateLimiter(
            _MAX_MESSAGES_PER_SECOND,
            _WINDOW_SECONDS,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _execute_with_retry(
        self,
        operation: str,
        fn: Callable[[], Coroutine[Any, Any, _T]],
    ) -> _T | None:
        """Acquire a rate-limit slot, run *fn*, and retry on failure.

        Returns ``None`` when all attempts are exhausted so that callers
        (e.g. use cases) are not forced to handle Telegram errors.
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            await self._rate_limiter.acquire()
            try:
                return await fn()
            except Exception as exc:
                logger.warning(
                    "%s failed (attempt %d/%d): %s",
                    operation,
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )
                if attempt < _MAX_RETRIES:
                    backoff = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)
        logger.error("%s failed after %d attempts", operation, _MAX_RETRIES)
        return None

    # ------------------------------------------------------------------
    # INotifier implementation
    # ------------------------------------------------------------------

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        safe_text = html.escape(text)

        async def _call() -> None:
            await self._bot.bot.send_message(
                chat_id=chat_id,
                text=safe_text,
                message_thread_id=topic_id,
            )

        await self._execute_with_retry("send_message", _call)

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        safe_text = html.escape(text)

        async def _call() -> None:
            await self._bot.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=safe_text,
            )

        await self._execute_with_retry("edit_message", _call)

    async def send_document(
        self,
        chat_id: int,
        file_path: Path,
        *,
        caption: str | None = None,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        resolved = file_path.resolve()
        if self._base_path is not None and not resolved.is_relative_to(self._base_path.resolve()):
            raise ValueError(f"File path {resolved} is outside the authorized base path")

        safe_caption = html.escape(caption) if caption is not None else None

        async def _call() -> None:
            await self._bot.bot.send_document(
                chat_id=chat_id,
                document=FSInputFile(str(resolved)),
                caption=safe_caption,
                message_thread_id=topic_id,
            )

        await self._execute_with_retry("send_document", _call)
