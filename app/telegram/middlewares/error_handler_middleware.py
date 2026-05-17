"""Global error-handler middleware.

Wraps the entire inner middleware chain + handler in a try/except boundary.
Unhandled exceptions are logged at CRITICAL level, forwarded to the
``EXECUTION_ERRORS`` topic, and swallowed so that a single bad update does
not crash the dispatcher polling loop.
"""

import html
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

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

            # A. Notify the user so the UI is not left hanging.
            await self._notify_user(event, data)

            # B. Send detailed report to the execution-errors topic.
            if self._config is not None and ctx.topic_id != self._config.topic_execution_errors:
                error_details = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
                safe_error = html.escape(error_details)[:3800]
                bot = data.get("bot")
                if isinstance(bot, Bot):
                    try:
                        await bot.send_message(
                            chat_id=self._config.telegram_chat_id,
                            text=f"🚨 <b>ERROR FATAL</b>\n<pre>{safe_error}</pre>",
                            message_thread_id=self._config.topic_execution_errors,
                        )
                    except Exception as inner_e:
                        self._logger.error(
                            "No se pudo enviar la alerta a Telegram: %s",
                            inner_e,
                        )

            # Swallow the exception so polling continues.
            return None

    async def _notify_user(
        self,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> None:
        """Edit or send a cancellation notice so the user knows something failed."""
        msg: Message | None = None
        if isinstance(event, Update):
            cb = event.callback_query
            if isinstance(cb, CallbackQuery) and isinstance(cb.message, Message):
                msg = cb.message
            elif isinstance(event.message, Message):
                msg = event.message
        elif isinstance(event, CallbackQuery) and isinstance(event.message, Message):
            msg = event.message
        elif isinstance(event, Message):
            msg = event

        if msg is None:
            return

        try:
            await msg.edit_text(text="❌ CANCELADA por un error de sistema")
        except Exception:
            # Fallback: if editing fails (e.g. message too old), send a new one.
            await safe_send_message(
                data,
                chat_id=msg.chat.id,
                text="❌ CANCELADA por un error de sistema",
                topic_id=msg.message_thread_id,
            )
