"""Telegram router exports."""

from aiogram import Router

from app.telegram.routers.admin import admin_router
from app.telegram.routers.backup import backup_router
from app.telegram.routers.errors import error_router
from app.telegram.routers.size import size_router

__all__ = ["get_routers"]


_routers: list[Router] | None = None


def get_routers() -> list[Router]:
    """Return the full router list.

    Lazily initialised so that router objects are not created at import
    time, which simplifies patching during tests.
    """
    global _routers
    if _routers is None:
        _routers = [
            backup_router,
            size_router,
            admin_router,
            error_router,
        ]
    return _routers
