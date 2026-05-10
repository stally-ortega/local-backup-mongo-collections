"""Global error-handler middleware.

Wraps the entire inner middleware chain + handler in a try/except boundary.
Unhandled exceptions are logged at CRITICAL level, forwarded to the
``EXECUTION_ERRORS`` topic, and swallowed so that a single bad update does
not crash the dispatcher polling loop.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.config import AppConfig
from app.infrastructure.logging.structured_logger import get_logger
from app.telegram.middlewares._utils import extract_context, safe_send_message


class ErrorHandlerMiddleware(BaseMiddleware):
    """Catch-all exception boundary around the handler invocation."""

    def __init__(self, *, config: AppConfig | None = None) -> None:
        self._config = config
        self._logger = get_logger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:
            ctx = extract_context(event)

            self._logger.critical(
                "unhandled_exception_in_handler",
                exc_info=exc,
                update_id=ctx.update_id,
                user_id=ctx.user_id,
                chat_id=ctx.chat_id,
                topic_id=ctx.topic_id,
            )

            # Avoid infinite error loops: do not re-post to EXECUTION_ERRORS
            # when the update itself originated there.
            if self._config is not None and ctx.topic_id != self._config.topic_execution_errors:
                await safe_send_message(
                    data,
                    chat_id=self._config.telegram_chat_id,
                    text=(
                        f"Execution error\n"
                        f"User: {ctx.user_id}\n"
                        f"Topic: {ctx.topic_id}\n"
                        f"Exception: {type(exc).__name__}: {exc}"
                    ),
                    topic_id=self._config.topic_execution_errors,
                )

            # Swallow the exception so polling continues.
            return None
