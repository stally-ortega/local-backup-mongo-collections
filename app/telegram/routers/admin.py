"""Router for the ADMIN topic.

Handles ``/users``, ``/jobs``, ``/logs``, ``/config`` commands.
Actual handlers are registered in subsequent tasks.
"""

from aiogram import Router

admin_router = Router(name="admin")
