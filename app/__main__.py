"""Application entry point for ``python -m app``.

Bootstraps logging, database, Redis, and the aiogram bot, then enters the
polling loop.  Gracefully shuts down every subsystem on exit.
"""

import asyncio
import logging
from pathlib import Path

from app.application.services.permission_service import PermissionService
from app.config import AppConfig
from app.infrastructure.logging.structured_logger import configure_logging
from app.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
    dispose_engine,
    init_database,
)
from app.infrastructure.queue.redis_connection import RedisConnection
from app.telegram.bot import BotBuilder
from app.telegram.middlewares import MiddlewareDependencies

logger = logging.getLogger(__name__)


async def main() -> None:
    """Run the full application lifecycle."""
    config = AppConfig()
    configure_logging(log_dir=Path("logs"), level=config.log_level)

    logger.info("Starting MongoDB Ops Platform...")

    engine = await create_engine(config)
    await init_database(engine)
    session_factory = await create_session_factory(engine)

    redis_conn = RedisConnection.from_config(config)
    redis_conn.connect()

    middleware_deps = MiddlewareDependencies(
        config=config,
        session_factory=session_factory,
        permission_service=PermissionService(),
        redis_connection=redis_conn,
    )

    builder = BotBuilder(config, middleware_deps)
    bot, dp = await builder.start()

    try:
        logger.info("Bot polling started")
        await dp.start_polling(bot.bot)
    finally:
        logger.info("Shutting down...")
        await builder.shutdown(bot, dp)
        await dispose_engine(engine)
        redis_conn.close()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
