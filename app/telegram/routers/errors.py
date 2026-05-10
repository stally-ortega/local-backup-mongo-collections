"""Router for the EXECUTION_ERRORS topic.

This router is read-only (only the bot posts here).
It exists for structural completeness and future error-reply handlers.
"""

from aiogram import Router

error_router = Router(name="error")
