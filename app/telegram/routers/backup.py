"""Router for the BACKUP_REQUESTS topic.

Handles ``/backup`` and the full conversational backup FSM.
"""

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.application.dtos import RequestBackupDto
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import (
    DiskSpaceError,
    PermissionError,
    RateLimitError,
)
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import BackupType
from app.infrastructure.logging.structured_logger import get_logger
from app.telegram.dependencies import TelegramDependencies, build_request_backup_use_case
from app.telegram.fsm_timeout import FSMTimeoutMonitor
from app.telegram.keyboards.backup_keyboards import (
    BackupTypeCallback,
    CollectionCallback,
    ConfirmCallback,
    DatabaseCallback,
    PageCallback,
    build_backup_type_keyboard,
    build_collection_keyboard,
    build_confirm_keyboard,
    build_database_keyboard,
)
from app.telegram.states.backup_states import BackupStates

backup_router = Router(name="backup")
_logger = get_logger(__name__)


def _format_size(bytes_value: int) -> str:
    """Human-readable byte count."""
    if bytes_value >= 1_073_741_824:
        return f"{bytes_value / 1_073_741_824:.2f} GB"
    if bytes_value >= 1_048_576:
        return f"{bytes_value / 1_048_576:.2f} MB"
    return f"{bytes_value:,} B"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@backup_router.message(Command("backup"))
async def cmd_backup(
    message: Message,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Present the backup type selection keyboard."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )
    await state.set_state(BackupStates.selecting_backup_type)
    await state.set_data(
        {
            "chat_id": message.chat.id,
            "topic_id": message.message_thread_id,
        }
    )
    await message.answer(
        "Selecciona el tipo de backup:",
        reply_markup=build_backup_type_keyboard(),
    )


# ---------------------------------------------------------------------------
# selecting_backup_type → confirming (full) or selecting_databases (custom)
# ---------------------------------------------------------------------------


@backup_router.callback_query(
    BackupTypeCallback.filter(F.action == "full"),
    StateFilter(BackupStates.selecting_backup_type),
)
async def on_full_type(
    callback: CallbackQuery,
    callback_data: BackupTypeCallback,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """User chose Full – skip selection and go straight to confirmation."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )
    await callback.answer()

    await state.set_state(BackupStates.confirming)
    await state.update_data(backup_type="FULL")

    size_report = await telegram_deps.mongo_metadata.get_size_stats(
        telegram_deps.config.cluster_uri_hash,
    )
    total_size = sum(db.size_bytes for db in size_report.databases)

    summary = (
        "Resumen del backup\n\n"
        f"Tipo: Full\n"
        f"Cluster: {telegram_deps.config.cluster_uri_hash[:8]}…\n"
        f"Estimación: {_format_size(total_size)}\n"
    )

    if not isinstance(callback.message, Message):
        return
    await callback.message.edit_text(
        text=summary,
        reply_markup=build_confirm_keyboard(),
    )


@backup_router.callback_query(
    BackupTypeCallback.filter(F.action == "custom"),
    StateFilter(BackupStates.selecting_backup_type),
)
async def on_custom_type(
    callback: CallbackQuery,
    callback_data: BackupTypeCallback,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """User chose Custom – list databases for multi-select."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )
    await callback.answer()

    databases = await telegram_deps.mongo_metadata.list_databases(
        telegram_deps.config.cluster_uri_hash,
    )

    await state.set_state(BackupStates.selecting_databases)
    await state.update_data(
        backup_type="CUSTOM",
        selected_databases=[],
        all_databases=databases,
    )

    if not isinstance(callback.message, Message):
        return
    await callback.message.edit_text(
        text="Selecciona las bases de datos:",
        reply_markup=build_database_keyboard(databases, set()),
    )


# ---------------------------------------------------------------------------
# selecting_databases toggles + continuar
# ---------------------------------------------------------------------------


@backup_router.callback_query(
    DatabaseCallback.filter(F.action == "toggle"),
    StateFilter(BackupStates.selecting_databases),
)
async def on_db_toggle(
    callback: CallbackQuery,
    callback_data: DatabaseCallback,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Toggle a database checkbox and refresh the keyboard."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )
    await callback.answer()

    data = await state.get_data()
    selected: set[str] = set(data.get("selected_databases", []))
    databases: list[str] = data.get("all_databases", [])

    db = callback_data.database
    if db in selected:
        selected.remove(db)
    else:
        selected.add(db)

    await state.update_data(selected_databases=list(selected))

    if not isinstance(callback.message, Message):
        return
    await callback.message.edit_text(
        text="Selecciona las bases de datos:",
        reply_markup=build_database_keyboard(databases, selected),
    )


@backup_router.callback_query(
    DatabaseCallback.filter(F.action == "continuar"),
    StateFilter(BackupStates.selecting_databases),
)
async def on_db_continuar(
    callback: CallbackQuery,
    callback_data: DatabaseCallback,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Advance to collection selection after validating at least one DB."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )

    data = await state.get_data()
    selected_databases: list[str] = data.get("selected_databases", [])

    if not selected_databases:
        await callback.answer(
            "Selecciona al menos una base de datos",
            show_alert=True,
        )
        return

    await callback.answer()

    all_collections: list[tuple[str, str]] = []
    for db in selected_databases:
        cols = await telegram_deps.mongo_metadata.list_collections(
            telegram_deps.config.cluster_uri_hash,
            db,
        )
        for col in cols:
            all_collections.append((db, col))

    await state.set_state(BackupStates.selecting_collections)
    await state.update_data(
        all_collections=[f"{db}.{col}" for db, col in all_collections],
        selected_collections=[],
        current_page=0,
    )

    if not isinstance(callback.message, Message):
        return

    if not all_collections:
        await state.set_state(BackupStates.confirming)
        await state.update_data(selected_collections=[])
        summary = (
            "Resumen del backup\n\n"
            f"Tipo: Custom\n"
            f"Bases: {', '.join(selected_databases)}\n"
            f"Colecciones: 0\n"
            f"Estimación: 0 B\n"
        )
        await callback.message.edit_text(
            text=summary,
            reply_markup=build_confirm_keyboard(),
        )
        return

    await callback.message.edit_text(
        text="Selecciona las colecciones:",
        reply_markup=build_collection_keyboard(
            all_collections,
            set(),
            page=0,
        ),
    )


# ---------------------------------------------------------------------------
# selecting_collections toggles + pagination + confirmar
# ---------------------------------------------------------------------------


@backup_router.callback_query(
    CollectionCallback.filter(F.action == "toggle"),
    StateFilter(BackupStates.selecting_collections),
)
async def on_coll_toggle(
    callback: CallbackQuery,
    callback_data: CollectionCallback,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Toggle a collection checkbox and refresh the paginated keyboard."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )
    await callback.answer()

    data = await state.get_data()
    selected: set[str] = set(data.get("selected_collections", []))
    all_collections_raw: list[str] = data.get("all_collections", [])
    current_page: int = data.get("current_page", 0)

    key = f"{callback_data.database}.{callback_data.collection}"
    if key in selected:
        selected.remove(key)
    else:
        selected.add(key)

    await state.update_data(selected_collections=list(selected))

    all_collections: list[tuple[str, str]] = []
    for c in all_collections_raw:
        db, _, coll = c.partition(".")
        all_collections.append((db, coll))

    if not isinstance(callback.message, Message):
        return
    await callback.message.edit_text(
        text="Selecciona las colecciones:",
        reply_markup=build_collection_keyboard(
            all_collections,
            selected,
            page=current_page,
        ),
    )


@backup_router.callback_query(
    PageCallback.filter(),
    StateFilter(BackupStates.selecting_collections),
)
async def on_page_nav(
    callback: CallbackQuery,
    callback_data: PageCallback,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Change collection page and refresh keyboard."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )
    await callback.answer()

    data = await state.get_data()
    selected: set[str] = set(data.get("selected_collections", []))
    all_collections_raw: list[str] = data.get("all_collections", [])
    all_collections: list[tuple[str, str]] = []
    for c in all_collections_raw:
        db, _, coll = c.partition(".")
        all_collections.append((db, coll))

    await state.update_data(current_page=callback_data.page)

    if not isinstance(callback.message, Message):
        return
    await callback.message.edit_text(
        text="Selecciona las colecciones:",
        reply_markup=build_collection_keyboard(
            all_collections,
            selected,
            page=callback_data.page,
        ),
    )


@backup_router.callback_query(
    ConfirmCallback.filter(F.action == "confirmar"),
    StateFilter(BackupStates.selecting_collections),
)
async def on_coll_confirmar(
    callback: CallbackQuery,
    callback_data: ConfirmCallback,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Advance to confirmation after validating at least one collection."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )

    data = await state.get_data()
    selected_collections: list[str] = data.get("selected_collections", [])
    selected_databases: list[str] = data.get("selected_databases", [])

    if not selected_collections:
        await callback.answer(
            "Selecciona al menos una colección",
            show_alert=True,
        )
        return

    await callback.answer()

    size_report = await telegram_deps.mongo_metadata.get_size_stats(
        telegram_deps.config.cluster_uri_hash,
    )
    size_map = {f"{c.database}.{c.collection}": c.size_bytes for c in size_report.collections}
    total_size = sum(size_map.get(c, 0) for c in selected_collections)

    await state.set_state(BackupStates.confirming)

    summary = (
        "Resumen del backup\n\n"
        f"Tipo: Custom\n"
        f"Bases: {', '.join(selected_databases)}\n"
        f"Colecciones: {len(selected_collections)}\n"
        f"Estimación: {_format_size(total_size)}\n"
    )

    if not isinstance(callback.message, Message):
        return
    await callback.message.edit_text(
        text=summary,
        reply_markup=build_confirm_keyboard(),
    )


# ---------------------------------------------------------------------------
# confirming → executing or cancelled
# ---------------------------------------------------------------------------


@backup_router.callback_query(
    ConfirmCallback.filter(F.action == "ejecutar"),
    StateFilter(BackupStates.confirming),
)
async def on_ejecutar(
    callback: CallbackQuery,
    callback_data: ConfirmCallback,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Run RequestBackupUseCase and report the created job ID."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )
    await callback.answer()

    data = await state.get_data()
    backup_type_str: str = data.get("backup_type", "FULL")
    selected_collections: list[str] = data.get("selected_collections", [])
    chat_id: int | None = data.get("chat_id")
    topic_id: int | None = data.get("topic_id")

    target_collections: list[CollectionTarget] | None = None
    if backup_type_str == "CUSTOM" and selected_collections:
        target_collections = [
            CollectionTarget(database=db, collection=coll)
            for db, coll in (c.split(".", 1) for c in selected_collections)
        ]

    dto = RequestBackupDto(
        user=user,
        chat_id=chat_id,
        topic_id=topic_id,
        backup_type=BackupType(backup_type_str),
        cluster_uri_hash=telegram_deps.config.cluster_uri_hash,
        target_collections=target_collections,
        topic="BACKUP_REQUESTS",
        command="BACKUP",
    )

    async with telegram_deps.session_factory() as session:
        use_case = build_request_backup_use_case(telegram_deps, session)
        try:
            result = await use_case.execute(dto)
        except RateLimitError as exc:
            await state.clear()
            if isinstance(callback.message, Message):
                await callback.message.edit_text(
                    text=(
                        f"Rate limit excedido: {exc.message}\n"
                        f"Espera {exc.details.get('window_seconds', 60)} segundos."
                    ),
                )
            return
        except DiskSpaceError as exc:
            await state.clear()
            if isinstance(callback.message, Message):
                await callback.message.edit_text(
                    text=f"Sin espacio en disco: {exc.message}",
                )
            return
        except PermissionError as exc:
            await state.clear()
            if isinstance(callback.message, Message):
                await callback.message.edit_text(
                    text=f"Permisos insuficientes: {exc.message}",
                )
            return
        await session.commit()

    await state.clear()

    if not isinstance(callback.message, Message):
        return
    await callback.message.edit_text(
        text=(
            f"Backup en cola\n\nJob ID: <code>{result.job_id}</code>\nEstado: {result.status.value}"
        ),
    )


@backup_router.callback_query(
    ConfirmCallback.filter(F.action == "cancelar"),
    StateFilter(BackupStates.confirming),
)
async def on_cancelar(
    callback: CallbackQuery,
    callback_data: ConfirmCallback,
    state: FSMContext,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Cancel the backup wizard and return to idle."""
    await FSMTimeoutMonitor.touch(
        telegram_deps.aioredis_client,
        user.telegram_id,
    )
    await callback.answer("Backup cancelado")
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text="Backup cancelado.")
