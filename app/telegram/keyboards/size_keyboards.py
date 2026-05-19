"""Inline keyboards for the size-query conversational flow.

All keyboards are stateless: every callback carries the full context
required to render the next view, so no FSM state is needed.
"""

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class SizeDbCallback(CallbackData, prefix="size_db"):
    """Payload emitted when the user picks a database from the list."""

    database: str


class SizeCollPageCallback(CallbackData, prefix="size_coll_page"):
    """Payload emitted when the user navigates collection pagination."""

    database: str
    page: int


def build_size_db_keyboard(databases: list[str]) -> InlineKeyboardMarkup:
    """Return a vertical list of database buttons for /size_collection."""
    builder = InlineKeyboardBuilder()
    for db in databases:
        builder.button(
            text=db,
            callback_data=SizeDbCallback(database=db).pack(),
        )
    builder.adjust(1)
    return builder.as_markup()


def build_size_collection_keyboard(
    database: str,
    collection_count: int,
    page: int,
    page_size: int = 20,
) -> InlineKeyboardMarkup:
    """Return a keyboard with collection-pagination buttons only.

    Parameters
    ----------
    database:
        Name of the database whose collections are displayed.
    collection_count:
        Total number of collections in the database.
    page:
        Zero-based page index.
    page_size:
        Number of collections per page (default 20).
    """
    builder = InlineKeyboardBuilder()
    total_pages = (collection_count + page_size - 1) // page_size

    nav_buttons: list[InlineKeyboardButton] = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="← Anterior",
                callback_data=SizeCollPageCallback(database=database, page=page - 1).pack(),
            )
        )
    if page + 1 < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Siguiente →",
                callback_data=SizeCollPageCallback(database=database, page=page + 1).pack(),
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    return builder.as_markup()
