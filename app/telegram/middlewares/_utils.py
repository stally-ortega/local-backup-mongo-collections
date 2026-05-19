"""Shared utilities for Telegram middlewares.

Provides type-safe extraction of update context (user, chat, topic, command)
from any aiogram event object, plus a topic resolver backed by
:class:`~app.config.AppConfig`.
"""

import contextlib
from dataclasses import dataclass
from typing import Any

from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.config import AppConfig
from app.domain.value_objects.enums import TopicType


@dataclass(frozen=True)
class UpdateContext:
    """Normalized context extracted from an incoming Telegram update."""

    update_id: int | None
    user_id: int | None
    chat_id: int | None
    topic_id: int | None


def extract_context(event: TelegramObject) -> UpdateContext:
    """Extract ``update_id``, ``user_id``, ``chat_id`` and ``topic_id``.

    Works with :class:`~aiogram.types.Update` (outer-middleware payload) as
    well as concrete event types such as :class:`~aiogram.types.Message` or
    :class:`~aiogram.types.CallbackQuery`.
    """
    update_id: int | None = None
    user_id: int | None = None
    chat_id: int | None = None
    topic_id: int | None = None

    if isinstance(event, Update):
        update_id = event.update_id
        sub = (
            event.message
            or event.edited_message
            or event.callback_query
            or event.channel_post
            or event.edited_channel_post
        )
        if sub is not None:
            inner = extract_context(sub)
            user_id = inner.user_id
            chat_id = inner.chat_id
            topic_id = inner.topic_id
    elif isinstance(event, Message):
        user_id = event.from_user.id if event.from_user else None
        chat_id = event.chat.id
        topic_id = event.message_thread_id
    elif isinstance(event, CallbackQuery):
        user_id = event.from_user.id if event.from_user else None
        msg = event.message
        if isinstance(msg, Message):
            chat_id = msg.chat.id
            topic_id = msg.message_thread_id

    return UpdateContext(
        update_id=update_id,
        user_id=user_id,
        chat_id=chat_id,
        topic_id=topic_id,
    )


def extract_command(event: TelegramObject) -> str | None:
    """Derive a domain command name from the update payload.

    Returns ``None`` when the event is not a recognised command or callback.
    """
    msg: Message | None = None
    cb: CallbackQuery | None = None

    if isinstance(event, Update):
        msg = event.message or event.edited_message
        cb = event.callback_query
    elif isinstance(event, Message):
        msg = event
    elif isinstance(event, CallbackQuery):
        cb = event

    if msg is not None and msg.text is not None:
        text = msg.text.strip()
        if text.startswith("/"):
            raw = text.split()[0][1:].split("@")[0].upper()
            return _map_telegram_command(raw)

    if cb is not None and cb.data is not None:
        return _map_callback_data(cb.data)

    return None


def _map_telegram_command(cmd: str) -> str | None:
    """Map a raw Telegram command to the domain command vocabulary."""
    mapping: dict[str, str] = {
        "BACKUP": "BACKUP",
        "SIZE": "SIZE_QUERY",
        "CANCEL": "CANCEL_JOB",
        "JOBS": "LIST_JOBS",
        "ADMIN": "MANAGE_USERS",
        "USERS": "MANAGE_USERS",
    }
    return mapping.get(cmd)


def _map_callback_data(data: str) -> str | None:
    """Map callback-query payload prefixes to domain commands."""
    if data.startswith("backup"):
        return "BACKUP"
    if data.startswith("size"):
        return "SIZE_QUERY"
    if data.startswith("cancel"):
        return "CANCEL_JOB"
    if data.startswith("jobs"):
        return "LIST_JOBS"
    if data.startswith("admin"):
        return "MANAGE_USERS"
    return None


def resolve_topic(topic_id: int | None, config: AppConfig) -> str:
    """Resolve a numeric ``message_thread_id`` to a topic enum name.

    Falls back to ``"GENERAL"`` for DMs or unknown topics.
    """
    mapping: dict[int | None, str] = {
        config.topic_backup_requests: TopicType.BACKUP_REQUESTS.value,
        config.topic_size_ask: TopicType.SIZE_ASK.value,
        config.topic_execution_errors: TopicType.EXECUTION_ERRORS.value,
        config.topic_admin: TopicType.ADMIN.value,
    }
    return mapping.get(topic_id, "GENERAL")


async def safe_send_message(
    data: dict[str, Any],
    chat_id: int | str,
    text: str,
    *,
    topic_id: int | None = None,
) -> None:
    """Fire-and-forget helper that sends a Telegram message swallowing errors.

    Useful in middlewares where a send failure must not cascade into the
    rest of the processing chain.
    """
    from aiogram import Bot

    bot = data.get("bot")
    if not isinstance(bot, Bot):
        return
    with contextlib.suppress(Exception):
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            message_thread_id=topic_id,
        )
