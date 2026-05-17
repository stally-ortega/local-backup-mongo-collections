"""Unit tests for the admin router.

Each handler is exercised in isolation with mocked aiogram events and
synthetic :class:`TelegramDependencies` so that no real database or Telegram
network call is required.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, Chat, Message
from aiogram.types import User as TelegramUser

from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.value_objects.enums import BackupType, JobStatus, UserRole
from app.telegram.dependencies import TelegramDependencies
from app.telegram.keyboards.jobs_keyboards import JobActionCallback, JobPageCallback
from app.telegram.keyboards.users_keyboards import (
    UserPageCallback,
    UserRoleCallback,
    UserToggleCallback,
)
from app.telegram.routers.admin import (
    _render_job_detail,
    cmd_auth,
    cmd_cancel,
    cmd_health,
    cmd_jobs,
    cmd_stats,
    cmd_users,
    on_job_action,
    on_job_page,
    on_user_page,
    on_user_role,
    on_user_toggle,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: UserRole = UserRole.ADMIN) -> User:
    return User(telegram_id=42, username="alice", role=role)


def _make_deps() -> TelegramDependencies:
    config = MagicMock()
    config.cluster_uri_hash = "abc123def"

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=session)

    mongo_meta = AsyncMock()
    redis_conn = MagicMock()
    aioredis_client = AsyncMock()
    fs_utils = AsyncMock()
    perms = MagicMock()

    return TelegramDependencies(
        config=config,
        session_factory=session_factory,
        mongo_metadata=mongo_meta,
        mongo_connection=MagicMock(),
        redis_connection=redis_conn,
        aioredis_client=aioredis_client,
        fs_utils=fs_utils,
        permission_service=perms,
    )


def _make_message(text: str = "/jobs") -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.message_thread_id = 1
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = -100
    msg.from_user = MagicMock(spec=TelegramUser)
    msg.from_user.id = 42
    msg.text = text
    return msg


def _make_callback() -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.message_thread_id = 1
    cb.message.chat = MagicMock(spec=Chat)
    cb.message.chat.id = -100
    cb.answer = AsyncMock()
    cb.from_user = MagicMock(spec=TelegramUser)
    cb.from_user.id = 42
    return cb


def _make_job(job_id: str = "job-123", status: JobStatus = JobStatus.QUEUED) -> BackupJob:
    return BackupJob(
        id=job_id,
        requester_telegram_id=42,
        backup_type=BackupType.FULL,
        status=status,
        cluster_uri_hash="abc123def",
        created_at=datetime(2026, 5, 10, 12, 0, 0),
    )


# ---------------------------------------------------------------------------
# _render_job_detail
# ---------------------------------------------------------------------------


class TestRenderJobDetail:
    def test_escapes_html_in_error_log(self) -> None:
        job = _make_job()
        job.error_log = "<script>alert('xss')</script>"
        text = _render_job_detail(job)
        assert "<script>" not in text
        assert "&lt;script&gt;" in text


# ---------------------------------------------------------------------------
# cmd_jobs
# ---------------------------------------------------------------------------


class TestCmdJobs:
    async def test_renders_job_list(self) -> None:
        message = _make_message("/jobs")
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.admin.build_list_jobs_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(jobs=[_make_job()], page=1, page_size=10)
            )
            mock_builder.return_value = mock_use_case

            await cmd_jobs(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "Jobs" in text

    async def test_blocks_non_admin(self) -> None:
        message = _make_message("/jobs")
        deps = _make_deps()
        user = _make_user(UserRole.OPERATOR)

        await cmd_jobs(message, deps, user)

        message.answer.assert_awaited_once_with("No tienes permiso para gestionar jobs.")


# ---------------------------------------------------------------------------
# cmd_users
# ---------------------------------------------------------------------------


class TestCmdUsers:
    async def test_renders_user_list_for_admin(self) -> None:
        message = _make_message("/users")
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        with patch("app.telegram.routers.admin.build_list_users_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(
                    users=[_make_user()],
                    page=1,
                    page_size=10,
                    total=1,
                )
            )
            mock_builder.return_value = mock_use_case

            await cmd_users(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "Usuarios" in text

    async def test_blocks_non_admin(self) -> None:
        message = _make_message("/users")
        deps = _make_deps()
        user = _make_user(UserRole.OPERATOR)

        await cmd_users(message, deps, user)

        message.answer.assert_awaited_once_with("No tienes permiso para gestionar usuarios.")


# ---------------------------------------------------------------------------
# cmd_cancel
# ---------------------------------------------------------------------------


class TestCmdCancel:
    async def test_cancels_job_with_id(self) -> None:
        message = _make_message("/cancel job-123")
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.admin.build_cancel_job_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(
                    job_id="job-123",
                    status=JobStatus.CANCELLED,
                )
            )
            mock_builder.return_value = mock_use_case

            await cmd_cancel(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "job-123" in text
        assert "CANCELLED" in text

    async def test_warns_when_no_argument(self) -> None:
        message = _make_message("/cancel")
        deps = _make_deps()
        user = _make_user()

        await cmd_cancel(message, deps, user)

        message.answer.assert_awaited_once_with("Uso: /cancel <job_id>")


# ---------------------------------------------------------------------------
# on_job_page
# ---------------------------------------------------------------------------


class TestOnJobPage:
    async def test_navigates_page(self) -> None:
        callback = _make_callback()
        callback_data = JobPageCallback(page=2)
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.admin.build_list_jobs_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(jobs=[_make_job()], page=2, page_size=10)
            )
            mock_builder.return_value = mock_use_case

            await on_job_page(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()

    async def test_blocks_non_admin(self) -> None:
        callback = _make_callback()
        callback_data = JobPageCallback(page=2)
        deps = _make_deps()
        user = _make_user(UserRole.OPERATOR)

        await on_job_page(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once_with(
            "No tienes permiso para gestionar jobs."
        )


# ---------------------------------------------------------------------------
# on_job_action
# ---------------------------------------------------------------------------


class TestOnJobAction:
    async def test_shows_job_detail(self) -> None:
        callback = _make_callback()
        callback_data = JobActionCallback(job_id="job-123", action="detail")
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.admin.build_get_job_detail_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(return_value=MagicMock(job=_make_job("job-123")))
            mock_builder.return_value = mock_use_case

            await on_job_action(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()
        text = callback.message.edit_text.await_args.args[0]
        assert "job-123" in text

    async def test_cancels_job(self) -> None:
        callback = _make_callback()
        callback_data = JobActionCallback(job_id="job-123", action="cancel")
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.admin.build_cancel_job_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(
                    job_id="job-123",
                    status=JobStatus.CANCELLED,
                )
            )
            mock_builder.return_value = mock_use_case

            await on_job_action(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()
        text = callback.message.edit_text.await_args.args[0]
        assert "job-123" in text


# ---------------------------------------------------------------------------
# on_user_page
# ---------------------------------------------------------------------------


class TestOnUserPage:
    async def test_navigates_page_for_admin(self) -> None:
        callback = _make_callback()
        callback_data = UserPageCallback(page=2)
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        with patch("app.telegram.routers.admin.build_list_users_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(
                    users=[_make_user()],
                    page=2,
                    page_size=10,
                    total=1,
                )
            )
            mock_builder.return_value = mock_use_case

            await on_user_page(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()

    async def test_blocks_non_admin(self) -> None:
        callback = _make_callback()
        callback_data = UserPageCallback(page=2)
        deps = _make_deps()
        user = _make_user(UserRole.OPERATOR)

        await on_user_page(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once_with(
            "No tienes permiso para gestionar usuarios."
        )


# ---------------------------------------------------------------------------
# on_user_toggle
# ---------------------------------------------------------------------------


class TestOnUserToggle:
    async def test_toggles_user_active(self) -> None:
        callback = _make_callback()
        callback_data = UserToggleCallback(telegram_id=99)
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        with (
            patch(
                "app.infrastructure.persistence.sql_user_repository.SQLUserRepository"
            ) as MockRepo,
            patch("app.telegram.routers.admin.build_list_users_use_case") as mock_builder,
        ):
            mock_repo = AsyncMock()
            mock_repo.toggle_active = AsyncMock(return_value=_make_user(UserRole.ADMIN))
            MockRepo.return_value = mock_repo

            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(
                    users=[_make_user()],
                    page=1,
                    page_size=10,
                    total=1,
                )
            )
            mock_builder.return_value = mock_use_case

            await on_user_toggle(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        mock_repo.toggle_active.assert_awaited_once_with(99)

    async def test_blocks_non_admin(self) -> None:
        callback = _make_callback()
        callback_data = UserToggleCallback(telegram_id=99)
        deps = _make_deps()
        user = _make_user(UserRole.OPERATOR)

        await on_user_toggle(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once_with(
            "No tienes permiso para gestionar usuarios."
        )


# ---------------------------------------------------------------------------
# on_user_role
# ---------------------------------------------------------------------------


class TestOnUserRole:
    async def test_cycles_role(self) -> None:
        callback = _make_callback()
        callback_data = UserRoleCallback(telegram_id=99, current_role="ADMIN")
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        with (
            patch(
                "app.infrastructure.persistence.sql_user_repository.SQLUserRepository"
            ) as MockRepo,
            patch("app.telegram.routers.admin.build_list_users_use_case") as mock_builder,
        ):
            mock_repo = AsyncMock()
            mock_repo.update_role = AsyncMock(return_value=_make_user(UserRole.DBA))
            MockRepo.return_value = mock_repo

            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(
                    users=[_make_user(UserRole.DBA)],
                    page=1,
                    page_size=10,
                    total=1,
                )
            )
            mock_builder.return_value = mock_use_case

            await on_user_role(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        mock_repo.update_role.assert_awaited_once_with(99, UserRole.DBA)

    async def test_blocks_non_admin(self) -> None:
        callback = _make_callback()
        callback_data = UserRoleCallback(telegram_id=99, current_role="ADMIN")
        deps = _make_deps()
        user = _make_user(UserRole.OPERATOR)

        await on_user_role(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once_with(
            "No tienes permiso para gestionar usuarios."
        )


# ---------------------------------------------------------------------------
# cmd_auth
# ---------------------------------------------------------------------------


class TestCmdAuth:
    async def test_adds_user_with_valid_args(self) -> None:
        message = _make_message("/auth 123456789 alice OPERATOR")
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        with patch("app.telegram.routers.admin.build_add_user_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(
                    telegram_id=123456789,
                    username="alice",
                    role=UserRole.OPERATOR,
                    is_new=True,
                )
            )
            mock_builder.return_value = mock_use_case

            await cmd_auth(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "123456789" in text
        assert "alice" in text
        assert "OPERATOR" in text

    async def test_blocks_non_admin(self) -> None:
        message = _make_message("/auth 123456789 alice OPERATOR")
        deps = _make_deps()
        user = _make_user(UserRole.OPERATOR)

        await cmd_auth(message, deps, user)

        message.answer.assert_awaited_once_with("No tienes permiso para gestionar usuarios.")

    async def test_warns_when_missing_args(self) -> None:
        message = _make_message("/auth")
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        await cmd_auth(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "Uso:" in text

    async def test_warns_when_invalid_telegram_id(self) -> None:
        message = _make_message("/auth abc alice OPERATOR")
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        await cmd_auth(message, deps, user)

        message.answer.assert_awaited_once_with("telegram_id debe ser un número entero.")

    async def test_warns_when_invalid_role(self) -> None:
        message = _make_message("/auth 123456789 alice SUPERADMIN")
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        await cmd_auth(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "no válido" in text


# ---------------------------------------------------------------------------
# cmd_health
# ---------------------------------------------------------------------------


class TestCmdHealth:
    async def test_renders_health_for_admin(self) -> None:
        message = _make_message("/health")
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        with patch("app.telegram.routers.admin.build_health_check_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(
                    mongodb=True,
                    redis=True,
                    disk_free_bytes=107_374_182_400,
                    disk_total_bytes=214_748_364_800,
                    running_jobs=2,
                )
            )
            mock_builder.return_value = mock_use_case

            await cmd_health(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "Health Check" in text
        assert "MongoDB" in text
        assert "Redis" in text

    async def test_blocks_non_admin(self) -> None:
        message = _make_message("/health")
        deps = _make_deps()
        user = _make_user(UserRole.OPERATOR)

        await cmd_health(message, deps, user)

        message.answer.assert_awaited_once_with("No tienes permiso para este comando.")


# ---------------------------------------------------------------------------
# cmd_stats
# ---------------------------------------------------------------------------


class TestCmdStats:
    async def test_renders_metrics_for_admin(self) -> None:
        message = _make_message("/stats")
        deps = _make_deps()
        user = _make_user(UserRole.ADMIN)

        with patch("app.telegram.routers.admin.build_query_metrics_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=MagicMock(
                    jobs_today=1,
                    jobs_week=5,
                    jobs_month=20,
                    success_rate_percent=95.0,
                    avg_duration_seconds=120.5,
                    storage_bytes=10_737_418_240,
                )
            )
            mock_builder.return_value = mock_use_case

            await cmd_stats(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "Métricas" in text
        assert "Hoy" in text
        assert "95.0%" in text

    async def test_blocks_non_admin(self) -> None:
        message = _make_message("/stats")
        deps = _make_deps()
        user = _make_user(UserRole.OPERATOR)

        await cmd_stats(message, deps, user)

        message.answer.assert_awaited_once_with("No tienes permiso para este comando.")
