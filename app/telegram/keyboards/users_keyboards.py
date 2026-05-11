"""Inline keyboards for the /users conversational flow.

All keyboards are stateless: every callback carries the full context
required to render the next view, so no FSM state is needed.
"""

from collections.abc import Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.domain.entities.user import User
from app.domain.value_objects.enums import UserRole


class UserPageCallback(CallbackData, prefix="user_page"):
    """Payload emitted when the user navigates user pagination."""

    page: int


class UserToggleCallback(CallbackData, prefix="user_toggle"):
    """Payload emitted when the admin toggles a user's active state."""

    telegram_id: int


class UserRoleCallback(CallbackData, prefix="user_role"):
    """Payload emitted when the admin cycles a user's role."""

    telegram_id: int
    current_role: str


def build_users_keyboard(
    users: Sequence[User],
    page: int,
    page_size: int = 10,
) -> InlineKeyboardMarkup:
    """Return a keyboard listing users with toggle-active + change-role buttons.

    Parameters
    ----------
    users:
        List of :class:`~app.domain.entities.user.User` instances.
    page:
        One-based page index.
    page_size:
        Number of users per page (default 10).
    """
    builder = InlineKeyboardBuilder()

    for user in users:
        active_emoji = "🟢" if user.is_active else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"{active_emoji} {user.username or user.telegram_id}",
                callback_data=UserToggleCallback(telegram_id=user.telegram_id).pack(),
            ),
            InlineKeyboardButton(
                text=f"Rol: {user.role.value}",
                callback_data=UserRoleCallback(
                    telegram_id=user.telegram_id,
                    current_role=user.role.value,
                ).pack(),
            ),
        )

    nav_buttons: list[InlineKeyboardButton] = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="← Anterior",
                callback_data=UserPageCallback(page=page - 1).pack(),
            )
        )
    if len(users) == page_size:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Siguiente →",
                callback_data=UserPageCallback(page=page + 1).pack(),
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    return builder.as_markup()


_ROLE_CYCLE: list[UserRole] = [
    UserRole.ADMIN,
    UserRole.DBA,
    UserRole.OPERATOR,
    UserRole.READONLY,
]


def next_role(current: UserRole) -> UserRole:
    """Return the next role in the cyclic ADMIN → DBA → OPERATOR → READONLY list."""
    try:
        idx = _ROLE_CYCLE.index(current)
    except ValueError:
        return UserRole.READONLY
    return _ROLE_CYCLE[(idx + 1) % len(_ROLE_CYCLE)]
