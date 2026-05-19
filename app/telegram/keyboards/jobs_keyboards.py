"""Inline keyboards for the /jobs conversational flow.

All keyboards are stateless: every callback carries the full context
required to render the next view, so no FSM state is needed.
"""

from collections.abc import Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.domain.entities.backup_job import BackupJob
from app.domain.value_objects.enums import JobStatus


class JobPageCallback(CallbackData, prefix="job_page"):
    """Payload emitted when the user navigates job pagination."""

    page: int


class JobActionCallback(CallbackData, prefix="job_action"):
    """Payload emitted when the user selects a job action."""

    job_id: str
    action: str


def build_jobs_keyboard(
    jobs: Sequence[BackupJob],
    page: int,
    page_size: int = 10,
) -> InlineKeyboardMarkup:
    """Return a keyboard listing jobs with detail + cancel buttons.

    Parameters
    ----------
    jobs:
        List of :class:`~app.domain.entities.backup_job.BackupJob` instances.
    page:
        One-based page index.
    page_size:
        Number of jobs per page (default 10).
    """
    builder = InlineKeyboardBuilder()

    for job in jobs:
        status_emoji = _status_emoji(job.status)
        builder.row(
            InlineKeyboardButton(
                text=f"{status_emoji} {job.id[:8]}…",
                callback_data=JobActionCallback(job_id=job.id, action="detail").pack(),
            ),
            InlineKeyboardButton(
                text="❌ Cancelar",
                callback_data=JobActionCallback(job_id=job.id, action="cancel").pack(),
            ),
        )

    nav_buttons: list[InlineKeyboardButton] = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="← Anterior",
                callback_data=JobPageCallback(page=page - 1).pack(),
            )
        )
    if len(jobs) == page_size:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Siguiente →",
                callback_data=JobPageCallback(page=page + 1).pack(),
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    return builder.as_markup()


def _status_emoji(status: JobStatus) -> str:
    """Map a job status to a compact visual indicator."""
    mapping: dict[JobStatus, str] = {
        JobStatus.PENDING: "⏳",
        JobStatus.QUEUED: "🕐",
        JobStatus.RUNNING: "🔄",
        JobStatus.SUCCESS: "✅",
        JobStatus.FAILED: "❌",
        JobStatus.PARTIAL_SUCCESS: "⚠️",
        JobStatus.CANCELLED: "🚫",
    }
    return mapping.get(status, "❓")
