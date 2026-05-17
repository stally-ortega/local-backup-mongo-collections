"""Global error-handler middleware.

Wraps the entire inner middleware chain + handler in a try/except boundary.
Unhandled exceptions are logged at CRITICAL level, forwarded to the
``EXECUTION_ERRORS`` topic, and swallowed so that a single bad update does
not crash the dispatcher polling loop.
"""

import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import BufferedInputFile, CallbackQuery, Message, TelegramObject, Update

from app.config import AppConfig, settings
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
            target_chat = int(settings.telegram_chat_id)
            target_topic = int(settings.topic_execution_errors)
            if ctx.topic_id != target_topic:
                error_details = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
                log_file = BufferedInputFile(
                    error_details.encode("utf-8"),
                    filename=f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                )
                origen_chat = f"{ctx.chat_id}" if ctx.chat_id is not None else "N/A"
                origen_topic = f"{ctx.topic_id}" if ctx.topic_id is not None else "N/A"
                caption = (
                    f"🚨 <b>ERROR FATAL</b>\n"
                    f"Origen: Chat <code>{origen_chat}</code> | "
                    f"Topic <code>{origen_topic}</code>\n"
                    f"Tipo: <code>{type(exc).__name__}</code>"
                )
                bot = data.get("bot")
                if isinstance(bot, Bot):
                    self._logger.error(
                        "Intentando enviar error fatal a chat=%s topic=%s",
                        target_chat,
                        target_topic,
                    )
                    try:
                        await bot.send_document(
                            chat_id=target_chat,
                            document=log_file,
                            caption=caption,
                            message_thread_id=target_topic,
                            parse_mode="HTML",
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
