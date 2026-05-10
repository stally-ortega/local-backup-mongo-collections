"""Topic filter middleware.

Rejects updates whose ``message_thread_id`` does not match one of the
configured operational topics.  DMs and unknown topics receive a polite
"Usar topics designados" reply and are then dropped.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.config import AppConfig
from app.infrastructure.logging.structured_logger import get_logger
from app.telegram.middlewares._utils import extract_context, safe_send_message


class TopicFilterMiddleware(BaseMiddleware):
    """Validates ``message_thread_id`` against the configured topic whitelist."""

    def __init__(self, *, config: AppConfig | None = None) -> None:
        self._config = config
        self._logger = get_logger(__name__)
        if config is not None:
            self._allowed_topics = {
                config.topic_backup_requests,
                config.topic_size_ask,
                config.topic_execution_errors,
                config.topic_admin,
            }
        else:
            self._allowed_topics = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # When no configuration is wired (e.g. lightweight tests) let everything through.
        if self._config is None:
            return await handler(event, data)

        ctx = extract_context(event)

        # DM or group message without a topic.
        if ctx.topic_id is None:
            self._logger.debug(
                "ignoring_dm_or_group_without_topic",
                user_id=ctx.user_id,
                chat_id=ctx.chat_id,
            )
            if ctx.chat_id is not None:
                await safe_send_message(
                    data,
                    chat_id=ctx.chat_id,
                    text="Usar topics designados",
                )
            return None

        if ctx.topic_id not in self._allowed_topics:
            self._logger.debug(
                "ignoring_unknown_topic",
                topic_id=ctx.topic_id,
                user_id=ctx.user_id,
                chat_id=ctx.chat_id,
            )
            if ctx.chat_id is not None:
                await safe_send_message(
                    data,
                    chat_id=ctx.chat_id,
                    text="Usar topics designados",
                    topic_id=ctx.topic_id,
                )
            return None

        return await handler(event, data)
