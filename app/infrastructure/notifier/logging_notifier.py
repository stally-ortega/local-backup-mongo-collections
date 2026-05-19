"""Minimal :class:`~app.application.ports.ports.INotifier` adapter that logs messages.

Intended as a fallback when no real notification channel (Telegram, email,
webhook) is configured.  Every call is logged at ``INFO`` level with full
context so operators can still observe what would have been sent.
"""

import logging
from pathlib import Path

from app.application.ports.ports import INotifier

logger = logging.getLogger(__name__)


class LoggingNotifier(INotifier):
    """Logs every notification instead of sending it to an external channel."""

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        logger.info(
            "[NOTIFY] chat_id=%s topic_id=%s correlation_id=%s: %s",
            chat_id,
            topic_id,
            correlation_id,
            text,
        )

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        logger.info(
            "[NOTIFY-EDIT] chat_id=%s message_id=%s correlation_id=%s: %s",
            chat_id,
            message_id,
            correlation_id,
            text,
        )

    async def send_document(
        self,
        chat_id: int,
        file_path: Path,
        *,
        caption: str | None = None,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        logger.info(
            "[NOTIFY-DOC] chat_id=%s file=%s caption=%s topic_id=%s correlation_id=%s",
            chat_id,
            file_path,
            caption,
            topic_id,
            correlation_id,
        )
