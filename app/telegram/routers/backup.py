"""Router for the BACKUP_REQUESTS topic.

Handles ``/backup`` and the backup-selection FSM callbacks.
Actual handlers are registered in subsequent tasks.
"""

from aiogram import Router

backup_router = Router(name="backup")
