"""Inline keyboards for the backup FSM conversational flow.

Every keyboard is built from aiogram 3.x ``CallbackData`` subclasses so
that payload parsing is type-safe and automatic.
"""

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class BackupTypeCallback(CallbackData, prefix="backup_type"):
    """Payload for the initial backup-type selection."""

    action: str


class DatabaseCallback(CallbackData, prefix="db"):
    """Payload for database toggles and navigation."""

    database: str
    action: str


class CollectionCallback(CallbackData, prefix="coll"):
    """Payload for collection toggles."""

    database: str
    collection: str
    action: str


class PageCallback(CallbackData, prefix="page"):
    """Payload for collection-pagination navigation."""

    page: int


class ConfirmCallback(CallbackData, prefix="confirm"):
    """Payload for confirmation / cancellation actions."""

    action: str


def build_backup_type_keyboard() -> InlineKeyboardMarkup:
    """Return a two-button keyboard: Full | Custom."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Full",
        callback_data=BackupTypeCallback(action="full").pack(),
    )
    builder.button(
        text="Custom",
        callback_data=BackupTypeCallback(action="custom").pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def build_database_keyboard(
    databases: list[str],
    selected: set[str],
) -> InlineKeyboardMarkup:
    """Return a checkbox-style keyboard for database multi-selection.

    The last row is a ``Continuar →`` button that advances to collection
    selection.
    """
    builder = InlineKeyboardBuilder()
    for db in databases:
        prefix = "✅" if db in selected else "⬜"
        builder.button(
            text=f"{prefix} {db}",
            callback_data=DatabaseCallback(database=db, action="toggle").pack(),
        )
    builder.button(
        text="Continuar →",
        callback_data=DatabaseCallback(database="_", action="continuar").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def build_collection_keyboard(
    collections: list[tuple[str, str]],
    selected: set[str],
    page: int,
    page_size: int = 10,
) -> InlineKeyboardMarkup:
    """Return a paginated checkbox-style keyboard for collection selection.

    Parameters
    ----------
    collections:
        Full sorted list of ``(database, collection)`` tuples.
    selected:
        Set of ``database.collection`` strings already checked.
    page:
        Zero-based page index.
    page_size:
        Number of collections per page (default 10).
    """
    builder = InlineKeyboardBuilder()
    start = page * page_size
    end = start + page_size
    page_items = collections[start:end]

    for db, coll in page_items:
        key = f"{db}.{coll}"
        prefix = "✅" if key in selected else "⬜"
        builder.button(
            text=f"{prefix} {db}.{coll}",
            callback_data=CollectionCallback(database=db, collection=coll, action="toggle").pack(),
        )

    nav_buttons: list[InlineKeyboardButton] = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="← Anterior",
                callback_data=PageCallback(page=page - 1).pack(),
            )
        )
    if end < len(collections):
        nav_buttons.append(
            InlineKeyboardButton(
                text="Siguiente →",
                callback_data=PageCallback(page=page + 1).pack(),
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.button(
        text="✅ Confirmar selección",
        callback_data=ConfirmCallback(action="confirmar").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def build_confirm_keyboard() -> InlineKeyboardMarkup:
    """Return the final confirmation keyboard: Ejecutar | Cancelar."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Ejecutar",
        callback_data=ConfirmCallback(action="ejecutar").pack(),
    )
    builder.button(
        text="❌ Cancelar",
        callback_data=ConfirmCallback(action="cancelar").pack(),
    )
    builder.adjust(2)
    return builder.as_markup()
