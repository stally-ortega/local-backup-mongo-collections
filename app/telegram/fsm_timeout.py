"""Background task that monitors FSM sessions for inactivity.

Runs every 5 minutes.  Any user whose last interaction is older than 10
minutes has their FSM state reset to ``idle`` and receives a Telegram
message explaining the timeout.
"""

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage

from app.config import AppConfig
from app.telegram.states.backup_states import BackupStates

logger = logging.getLogger(__name__)

_FSM_ACTIVE_KEY: str = "fsm:backup:active"
_TIMEOUT_SECONDS: int = 600
_CHECK_INTERVAL_SECONDS: int = 300


class FSMTimeoutMonitor:
    """Periodic task that cleans up stale backup FSM sessions."""

    def __init__(
        self,
        bot: Bot,
        storage: RedisStorage,
        config: AppConfig,
    ) -> None:
        self._bot = bot
        self._storage = storage
        self._config = config
        self._redis: aioredis.Redis = aioredis.Redis.from_url(config.redis_url)
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Spawn the background monitoring task."""
        if self._task is not None and not self._task.done():
            logger.warning("FSMTimeoutMonitor already running")
            return
        self._task = asyncio.create_task(self._run())
        logger.info("FSMTimeoutMonitor started")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
            try:
                await self._check_timeouts()
            except Exception as exc:
                logger.exception("FSM timeout check failed: %s", exc)

    async def _check_timeouts(self) -> None:
        now = datetime.now(tz=timezone.utc).timestamp()
        cutoff = now - _TIMEOUT_SECONDS

        expired = await self._redis.zrangebyscore(_FSM_ACTIVE_KEY, 0, cutoff)
        if not expired:
            return

        for member in expired:
            user_id_str = member.decode() if isinstance(member, bytes) else str(member)
            try:
                user_id = int(user_id_str)
            except ValueError:
                continue

            key = StorageKey(
                bot_id=self._bot.id,
                chat_id=int(self._config.telegram_chat_id),
                user_id=user_id,
            )
            ctx = FSMContext(storage=self._storage, key=key)
            current_state = await ctx.get_state()
            if current_state is not None and current_state != BackupStates.idle.state:
                await ctx.set_state(BackupStates.idle)
                await ctx.set_data({})
                try:
                    await self._bot.send_message(
                        chat_id=self._config.telegram_chat_id,
                        text=(
                            "Sesión de backup expirada por inactividad (>10 min). "
                            "Usa /backup para reiniciar."
                        ),
                        message_thread_id=self._config.topic_backup_requests,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to notify user %s of timeout: %s",
                        user_id,
                        exc,
                    )
                logger.info("Reset FSM for user %s due to inactivity", user_id)

        await self._redis.zremrangebyscore(_FSM_ACTIVE_KEY, 0, cutoff)

    async def stop(self) -> None:
        """Cancel the monitoring task and close the Redis connection."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._redis.close()
        logger.info("FSMTimeoutMonitor stopped")

    @staticmethod
    async def touch(redis: aioredis.Redis, user_id: int) -> None:
        """Record an interaction timestamp for *user_id*."""
        now = datetime.now(tz=timezone.utc).timestamp()
        await redis.zadd(_FSM_ACTIVE_KEY, {str(user_id): now})
