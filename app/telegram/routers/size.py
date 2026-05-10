"""Router for the SIZE_ASK topic.

Handles ``/size``, ``/size_db``, ``/size_collection`` commands.
Actual handlers are registered in subsequent tasks.
"""

from aiogram import Router

size_router = Router(name="size")
