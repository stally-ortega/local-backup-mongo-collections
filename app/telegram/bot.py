"""Telegram bot and dispatcher factory.

Wires together the :class:`~app.infrastructure.telegram.aiogram_bot.AiogramBot`
wrapper, the aiogram :class:`Dispatcher` with Redis-backed FSM storage, and the
full middleware + router stack.
"""

import logging
from typing import Any, cast

import redis.asyncio as aioredis
from aiogram import BaseMiddleware, Dispatcher, Router
from aiogram.fsm.storage.redis import RedisEventIsolation, RedisStorage

from app.config import AppConfig
from app.infrastructure.telegram.aiogram_bot import AiogramBot
from app.telegram.middlewares import MiddlewareDependencies, get_global_middlewares
from app.telegram.routers import get_routers

logger = logging.getLogger(__name__)


class BotBuilder:
    """Factory that creates and wires the aiogram ``Bot`` + ``Dispatcher``.

    Parameters
    ----------
    config:
        Validated application settings.
    middleware_deps:
        Optional dependency container for the middleware stack.  When
        omitted, DB-dependent middlewares fall back to pass-through mode,
        which is useful for lightweight unit tests.
    """

    def __init__(
        self,
        config: AppConfig,
        middleware_deps: MiddlewareDependencies | None = None,
    ) -> None:
        self._config = config
        self._middleware_deps = middleware_deps
        self._telegram_deps: Any = None
        self._timeout_monitor: Any = None

    def create_dispatcher(
        self,
        *,
        routers: list[Router] | None = None,
        middlewares: list[BaseMiddleware] | None = None,
    ) -> Dispatcher:
        """Build a :class:`Dispatcher` with Redis FSM and the full stack.

        Parameters
        ----------
        routers:
            Override the default router list (useful in tests).
        middlewares:
            Override the default middleware list (useful in tests).

        Returns
        -------
        A fully configured aiogram ``Dispatcher``.
        """
        redis_client = aioredis.Redis.from_url(self._config.redis_url)

        dp = Dispatcher(
            storage=RedisStorage(redis=redis_client),
            events_isolation=RedisEventIsolation(redis=redis_client),
        )

        for mw in middlewares or get_global_middlewares(self._middleware_deps):
            dp.update.outer_middleware(mw)
            logger.debug(
                "Registered global middleware %s",
                mw.__class__.__name__,
            )

        for router in routers or get_routers():
            dp.include_router(router)
            logger.debug("Registered router %s", router.name)

        logger.info(
            "Dispatcher ready: %d middlewares, %d routers",
            len(middlewares or list(get_global_middlewares())),
            len(routers or list(get_routers())),
        )
        return dp

    async def start(self) -> tuple[AiogramBot, Dispatcher]:
        """Create and start the bot, dispatcher, and FSM timeout monitor.

        Returns
        -------
        ``(bot, dispatcher)`` pair ready for polling or webhook mode.
        """
        bot = AiogramBot.from_config(self._config)
        bot.start()

        # Wire TelegramDependencies into the backup router before the
        # dispatcher includes it.
        if self._middleware_deps is not None:
            from app.telegram.dependencies import (
                DependencyInjectionMiddleware,
                build_telegram_dependencies,
            )
            from app.telegram.fsm_timeout import FSMTimeoutMonitor
            from app.telegram.routers.backup import backup_router
            from app.telegram.routers.size import size_router

            self._telegram_deps = build_telegram_dependencies(
                config=self._config,
                session_factory=self._middleware_deps.session_factory,
            )
            di_mw = DependencyInjectionMiddleware(self._telegram_deps)
            backup_router.message.middleware(di_mw)
            backup_router.callback_query.middleware(di_mw)
            size_router.message.middleware(di_mw)
            size_router.callback_query.middleware(di_mw)
            logger.debug("Wired DependencyInjectionMiddleware to backup_router and size_router")

        dp = self.create_dispatcher()

        if self._middleware_deps is not None:
            storage = cast("RedisStorage", dp.storage)
            self._timeout_monitor = FSMTimeoutMonitor(
                bot=bot.bot,
                storage=storage,
                config=self._config,
            )
            self._timeout_monitor.start()
            logger.debug("FSMTimeoutMonitor started")

        logger.info("Bot and dispatcher ready")
        return bot, dp

    async def shutdown(self, bot: AiogramBot, dp: Dispatcher) -> None:
        """Gracefully shut down the bot, dispatcher, and FSM monitor."""
        if self._timeout_monitor is not None:
            await self._timeout_monitor.stop()
            logger.debug("FSMTimeoutMonitor stopped")

        if self._telegram_deps is not None:
            self._telegram_deps.mongo_connection.close()
            self._telegram_deps.redis_connection.close()
            await self._telegram_deps.aioredis_client.close()
            logger.debug("TelegramDependencies connections closed")

        await bot.shutdown()
        logger.info("Bot and dispatcher shut down")
