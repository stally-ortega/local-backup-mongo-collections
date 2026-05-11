"""Router for the ADMIN topic.

Handles ``/jobs``, ``/users``, and ``/cancel <job_id>`` commands.
All handlers are stateless; pagination is driven entirely by callback
payloads so that no FSM context is required.
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.application.dtos import (
    CancelJobDto,
    CancelJobResult,
    QueryJobsDto,
    QueryJobsResult,
    QueryUsersDto,
    QueryUsersResult,
)
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import JobNotFoundError
from app.domain.value_objects.enums import UserRole
from app.infrastructure.logging.structured_logger import get_logger
from app.telegram.dependencies import (
    TelegramDependencies,
    build_cancel_job_use_case,
    build_list_jobs_use_case,
    build_list_users_use_case,
)
from app.telegram.keyboards.jobs_keyboards import (
    JobActionCallback,
    JobPageCallback,
    build_jobs_keyboard,
)
from app.telegram.keyboards.users_keyboards import (
    UserPageCallback,
    UserRoleCallback,
    UserToggleCallback,
    build_users_keyboard,
    next_role,
)

admin_router = Router(name="admin")
_logger = get_logger(__name__)

_JOBS_PAGE_SIZE: int = 10
_USERS_PAGE_SIZE: int = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_job_detail(job: BackupJob) -> str:
    """Human-readable job summary in HTML."""
    lines: list[str] = [
        f"<b>Job:</b> <code>{job.id}</code>",
        f"<b>Estado:</b> {job.status.value}",
        f"<b>Tipo:</b> {job.backup_type.value}",
        f"<b>Solicitante:</b> {job.requester_telegram_id}",
    ]
    if job.started_at:
        lines.append(f"<b>Iniciado:</b> {job.started_at.isoformat()}")
    if job.completed_at:
        lines.append(f"<b>Completado:</b> {job.completed_at.isoformat()}")
    if job.error_log:
        lines.append(f"<b>Error:</b> {job.error_log[:200]}")
    return "\n".join(lines)


def _render_jobs_list(result: QueryJobsResult) -> str:
    """HTML header for the paginated job list."""
    return (
        f"<b>Jobs</b>\n"
        f"Página {result.page}\n"
        f"Mostrando {len(result.jobs)} job(s)\n\n"
        "Selecciona una acción:"
    )


def _render_users_list(result: QueryUsersResult) -> str:
    """HTML header for the paginated user list."""
    total_pages = (result.total + result.page_size - 1) // result.page_size
    return (
        f"<b>Usuarios</b>\n"
        f"Página {result.page} de {total_pages}\n"
        f"Total: {result.total}\n\n"
        "Toca un usuario para alternar activo / cambiar rol:"
    )


async def _run_jobs_query(
    deps: TelegramDependencies,
    user: User,
    page: int = 1,
) -> QueryJobsResult:
    """Execute :class:`QueryJobsUseCase` inside a transactional session."""
    dto = QueryJobsDto(
        user=user,
        page=page,
        page_size=_JOBS_PAGE_SIZE,
        topic="ADMIN",
        command="LIST_JOBS",
    )
    async with deps.session_factory() as session:
        use_case = build_list_jobs_use_case(deps, session)
        result = await use_case.execute(dto)
        await session.commit()
    return result


async def _run_users_query(
    deps: TelegramDependencies,
    user: User,
    page: int = 1,
) -> QueryUsersResult:
    """Execute :class:`QueryUsersUseCase` inside a transactional session."""
    dto = QueryUsersDto(
        user=user,
        page=page,
        page_size=_USERS_PAGE_SIZE,
        topic="ADMIN",
        command="LIST_USERS",
    )
    async with deps.session_factory() as session:
        use_case = build_list_users_use_case(deps, session)
        result = await use_case.execute(dto)
        await session.commit()
    return result


async def _run_cancel_job(
    deps: TelegramDependencies,
    user: User,
    job_id: str,
) -> CancelJobResult:
    """Execute :class:`CancelJobUseCase` inside a transactional session."""
    dto = CancelJobDto(
        user=user,
        job_id=job_id,
        topic="BACKUP_REQUESTS",
        command="CANCEL",
    )
    async with deps.session_factory() as session:
        use_case = build_cancel_job_use_case(deps, session)
        result = await use_case.execute(dto)
        await session.commit()
    return result


async def _send_jobs_page(
    *,
    edit_message: Message,
    deps: TelegramDependencies,
    user: User,
    page: int,
) -> None:
    """Fetch and render a paginated job list, editing *edit_message* in place."""
    result = await _run_jobs_query(deps, user, page=page)
    text = _render_jobs_list(result)
    keyboard = build_jobs_keyboard(result.jobs, page=page, page_size=_JOBS_PAGE_SIZE)
    await edit_message.edit_text(
        text=text,
        reply_markup=keyboard,
    )


async def _send_users_page(
    *,
    edit_message: Message,
    deps: TelegramDependencies,
    user: User,
    page: int,
) -> None:
    """Fetch and render a paginated user list, editing *edit_message* in place."""
    result = await _run_users_query(deps, user, page=page)
    text = _render_users_list(result)
    keyboard = build_users_keyboard(result.users, page=page, page_size=_USERS_PAGE_SIZE)
    await edit_message.edit_text(
        text=text,
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# /jobs
# ---------------------------------------------------------------------------


@admin_router.message(Command("jobs"))
async def cmd_jobs(
    message: Message,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Return the first page of recent backup jobs."""
    result = await _run_jobs_query(telegram_deps, user, page=1)
    text = _render_jobs_list(result)
    keyboard = build_jobs_keyboard(result.jobs, page=1, page_size=_JOBS_PAGE_SIZE)
    await message.answer(text, reply_markup=keyboard)


# ---------------------------------------------------------------------------
# /users
# ---------------------------------------------------------------------------


@admin_router.message(Command("users"))
async def cmd_users(
    message: Message,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Return the first page of registered users (ADMIN only)."""
    if not user.has_role(UserRole.ADMIN):
        await message.answer("No tienes permiso para gestionar usuarios.")
        return

    result = await _run_users_query(telegram_deps, user, page=1)
    text = _render_users_list(result)
    keyboard = build_users_keyboard(result.users, page=1, page_size=_USERS_PAGE_SIZE)
    await message.answer(text, reply_markup=keyboard)


# ---------------------------------------------------------------------------
# /cancel
# ---------------------------------------------------------------------------


@admin_router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Cancel a running or queued job by its identifier.

    Usage: ``/cancel <job_id>``
    """
    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2:
        await message.answer("Uso: /cancel <job_id>")
        return

    job_id = args[1].strip()

    try:
        result = await _run_cancel_job(telegram_deps, user, job_id)
    except JobNotFoundError:
        await message.answer(f"Job <code>{job_id}</code> no encontrado.")
        return
    except PermissionError:
        await message.answer("No tienes permiso para cancelar este job.")
        return

    await message.answer(
        f"✅ Job <code>{result.job_id}</code> cancelado.\n"
        f"Nuevo estado: <b>{result.status.value}</b>"
    )


# ---------------------------------------------------------------------------
# Callbacks — jobs pagination + actions
# ---------------------------------------------------------------------------


@admin_router.callback_query(JobPageCallback.filter())
async def on_job_page(
    callback: CallbackQuery,
    callback_data: JobPageCallback,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """User clicked a pagination button for the job list."""
    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    await _send_jobs_page(
        edit_message=callback.message,
        deps=telegram_deps,
        user=user,
        page=callback_data.page,
    )


@admin_router.callback_query(JobActionCallback.filter())
async def on_job_action(
    callback: CallbackQuery,
    callback_data: JobActionCallback,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """User clicked either *detail* or *cancel* on a job row."""
    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    if callback_data.action == "detail":
        from app.infrastructure.persistence.sql_job_repository import SQLJobRepository

        async with telegram_deps.session_factory() as session:
            repo = SQLJobRepository(session)
            job = await repo.get_by_id(callback_data.job_id)
            if job is None:
                await callback.message.edit_text(
                    f"Job <code>{callback_data.job_id}</code> no encontrado."
                )
                return
            text = _render_job_detail(job)
            await callback.message.edit_text(text)
        return

    if callback_data.action == "cancel":
        try:
            result = await _run_cancel_job(telegram_deps, user, callback_data.job_id)
        except JobNotFoundError:
            await callback.message.edit_text(
                f"Job <code>{callback_data.job_id}</code> no encontrado."
            )
            return
        except PermissionError:
            await callback.message.edit_text("No tienes permiso para cancelar este job.")
            return

        await callback.message.edit_text(
            f"✅ Job <code>{result.job_id}</code> cancelado.\n"
            f"Nuevo estado: <b>{result.status.value}</b>"
        )
        return


# ---------------------------------------------------------------------------
# Callbacks — users pagination + actions
# ---------------------------------------------------------------------------


@admin_router.callback_query(UserPageCallback.filter())
async def on_user_page(
    callback: CallbackQuery,
    callback_data: UserPageCallback,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """User clicked a pagination button for the user list."""
    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    if not user.has_role(UserRole.ADMIN):
        await callback.message.edit_text("No tienes permiso para gestionar usuarios.")
        return

    await _send_users_page(
        edit_message=callback.message,
        deps=telegram_deps,
        user=user,
        page=callback_data.page,
    )


@admin_router.callback_query(UserToggleCallback.filter())
async def on_user_toggle(
    callback: CallbackQuery,
    callback_data: UserToggleCallback,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Admin toggled a user's active flag."""
    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    if not user.has_role(UserRole.ADMIN):
        await callback.message.edit_text("No tienes permiso para gestionar usuarios.")
        return

    from app.infrastructure.persistence.sql_user_repository import SQLUserRepository

    async with telegram_deps.session_factory() as session:
        repo = SQLUserRepository(session)
        updated = await repo.toggle_active(callback_data.telegram_id)
        if updated is None:
            await callback.message.edit_text("Usuario no encontrado.")
            return
        await session.commit()

    # Refresh the current page (re-use the helper).
    # We extract the current page from the message text as a best-effort fallback.
    # A cleaner approach would be to store page in FSM or callback data, but this
    # router is intentionally stateless.  For simplicity we jump back to page 1.
    result = await _run_users_query(telegram_deps, user, page=1)
    text = _render_users_list(result)
    keyboard = build_users_keyboard(result.users, page=1, page_size=_USERS_PAGE_SIZE)
    await callback.message.edit_text(text=text, reply_markup=keyboard)


@admin_router.callback_query(UserRoleCallback.filter())
async def on_user_role(
    callback: CallbackQuery,
    callback_data: UserRoleCallback,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Admin cycled a user's role to the next value in the ring."""
    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    if not user.has_role(UserRole.ADMIN):
        await callback.message.edit_text("No tienes permiso para gestionar usuarios.")
        return

    from app.infrastructure.persistence.sql_user_repository import SQLUserRepository

    async with telegram_deps.session_factory() as session:
        repo = SQLUserRepository(session)
        current_role = UserRole(callback_data.current_role)
        new_role = next_role(current_role)
        updated = await repo.update_role(callback_data.telegram_id, new_role)
        if updated is None:
            await callback.message.edit_text("Usuario no encontrado.")
            return
        await session.commit()

    result = await _run_users_query(telegram_deps, user, page=1)
    text = _render_users_list(result)
    keyboard = build_users_keyboard(result.users, page=1, page_size=_USERS_PAGE_SIZE)
    await callback.message.edit_text(text=text, reply_markup=keyboard)
