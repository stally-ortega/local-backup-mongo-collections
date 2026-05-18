"""Router for the SIZE_ASK topic.

Handles ``/size``, ``/size_db``, and ``/size_collection`` commands.
All handlers are stateless; pagination is driven entirely by callback
payloads so that no FSM context is required.
"""

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.application.dtos import QuerySizeDto, QuerySizeResult, UserPrincipalDto
from app.domain.entities.size_report import CollectionSize
from app.domain.entities.user import User
from app.infrastructure.logging.structured_logger import get_logger
from app.telegram.dependencies import TelegramDependencies, build_query_size_use_case
from app.telegram.keyboards.size_keyboards import (
    SizeCollPageCallback,
    SizeDbCallback,
    build_size_collection_keyboard,
    build_size_db_keyboard,
)

size_router = Router(name="size")
_logger = get_logger(__name__)

_SIZE_COLLECTION_PAGE_SIZE: int = 20


def _format_size(bytes_value: int) -> str:
    """Human-readable byte count."""
    if bytes_value >= 1_073_741_824:
        return f"{bytes_value / 1_073_741_824:.2f} GB"
    if bytes_value >= 1_048_576:
        return f"{bytes_value / 1_048_576:.2f} MB"
    return f"{bytes_value:,} B"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_cluster_size(result: QuerySizeResult) -> str:
    db_lines = "\n".join(
        f"  • {db.database}: {_format_size(db.size_bytes)}" for db in (result.databases or [])
    )
    return (
        f"<b>Tamaño del Cluster</b>\n"
        f"Cluster: <code>{result.cluster_uri_hash[:8]}…</code>\n\n"
        f"<b>Total:</b> {_format_size(result.total_size_bytes)}\n"
        f"<b>Bases de datos:</b> {len(result.databases or [])}\n"
        f"<b>Colecciones:</b> {sum(db.collection_count for db in (result.databases or []))}\n\n"
        f"{db_lines}"
    )


def _render_database_sizes(result: QuerySizeResult) -> str:
    databases = result.databases or []
    total = result.total_size_bytes or 1  # avoid div-by-zero
    lines: list[str] = []
    for db in databases:
        pct = (db.size_bytes / total) * 100
        lines.append(f"  • {db.database}: {_format_size(db.size_bytes)} ({pct:.1f}%)")
    return (
        f"<b>Tamaño por Base de Datos</b>\n"
        f"Cluster: <code>{result.cluster_uri_hash[:8]}…</code>\n\n"
        f"<b>Total:</b> {_format_size(total)}\n"
        f"<b>Bases:</b> {len(databases)}\n\n" + "\n".join(lines)
    )


def _render_collections(
    database: str,
    collections: list[CollectionSize],
    page: int,
    page_size: int,
    total_count: int,
) -> str:
    lines: list[str] = []
    for coll in collections:
        lines.append(
            f"  • {coll.collection}: {_format_size(coll.size_bytes)} ({coll.document_count:,} docs)"
        )
    header = (
        f"<b>Colecciones: {database}</b>\n"
        f"Página {page + 1} de {(total_count + page_size - 1) // page_size}\n\n"
    )
    return header + "\n".join(lines)


async def _run_size_query(
    deps: TelegramDependencies,
    user: User,
    scope: str,
    *,
    database_name: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> QuerySizeResult:
    """Execute :class:`QuerySizeUseCase` inside a transactional session.

    Returns the :class:`QuerySizeResult` so callers can format the output.
    """
    dto = QuerySizeDto(
        user=UserPrincipalDto.from_user(user),
        scope=scope,
        cluster_uri_hash=deps.config.cluster_uri_hash,
        database_name=database_name,
        page=page,
        page_size=page_size,
        topic="SIZE_ASK",
        command=scope.upper(),
    )
    async with deps.session_factory() as session:
        use_case = build_query_size_use_case(deps, session)
        result = await use_case.execute(dto)
        await session.commit()
    return result


# ---------------------------------------------------------------------------
# /size — cluster scope
# ---------------------------------------------------------------------------


@size_router.message(Command("size"))
async def cmd_size(
    message: Message,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Return the full cluster size breakdown in HTML."""
    result = await _run_size_query(telegram_deps, user, scope="cluster")
    await message.answer(_render_cluster_size(result))


# ---------------------------------------------------------------------------
# /size_db — database scope
# ---------------------------------------------------------------------------


@size_router.message(Command("size_db"))
async def cmd_size_db(
    message: Message,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Return every database with its size and percentage of total."""
    result = await _run_size_query(telegram_deps, user, scope="database")
    await message.answer(_render_database_sizes(result))


# ---------------------------------------------------------------------------
# /size_collection — collection scope
# ---------------------------------------------------------------------------


@size_router.message(Command("size_collection"))
async def cmd_size_collection(
    message: Message,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """Handle ``/size_collection [database]``.

    When a database name is provided as an argument, render the first page
    of collections directly.  When no argument is given, present an inline
    keyboard so the user can pick a database.
    """
    args = message.text.split(maxsplit=1) if message.text else []
    db_name = args[1].strip() if len(args) > 1 else None

    if db_name:
        await _send_collection_page(
            chat_id=message.chat.id,
            thread_id=message.message_thread_id,
            deps=telegram_deps,
            user=user,
            database=db_name,
            page=0,
            edit_message=None,
            bot=message.bot,
        )
        return

    # No argument — show database selector.
    databases = await telegram_deps.mongo_metadata.list_databases(
        telegram_deps.config.cluster_uri_hash,
    )
    if not databases:
        await message.answer("No se encontraron bases de datos.")
        return

    await message.answer(
        "Selecciona una base de datos:",
        reply_markup=build_size_db_keyboard(databases),
    )


async def _send_collection_page(
    *,
    chat_id: int,
    thread_id: int | None,
    deps: TelegramDependencies,
    user: User,
    database: str,
    page: int,
    edit_message: Message | None,
    bot: Bot | None = None,
) -> None:
    """Fetch and render a paginated collection-size page.

    When *edit_message* is supplied the existing message is updated in
    place; otherwise a new message is sent.
    """
    result = await _run_size_query(
        deps,
        user,
        scope="collection",
        database_name=database,
        page=page + 1,  # QuerySizeDto uses 1-based pages.
    )
    collections = result.collections or []
    total_count = len(collections)

    # The use-case already paginates; determine the real total by asking
    # for all collections (page=1, large page_size) when the count looks
    # like it might be truncated.  For performance we only do this on the
    # first page or when the keyboard needs total_pages.
    if page == 0 or total_count == _SIZE_COLLECTION_PAGE_SIZE:
        full_result = await _run_size_query(
            deps,
            user,
            scope="collection",
            database_name=database,
            page=1,
            page_size=200,
        )
        total_count = len(full_result.collections or [])
        collections = (full_result.collections or [])[
            page * _SIZE_COLLECTION_PAGE_SIZE : (page + 1) * _SIZE_COLLECTION_PAGE_SIZE
        ]

    text = _render_collections(
        database=database,
        collections=collections,
        page=page,
        page_size=_SIZE_COLLECTION_PAGE_SIZE,
        total_count=total_count,
    )

    keyboard = (
        build_size_collection_keyboard(
            database=database,
            collection_count=total_count,
            page=page,
            page_size=_SIZE_COLLECTION_PAGE_SIZE,
        )
        if total_count > _SIZE_COLLECTION_PAGE_SIZE
        else None
    )

    if edit_message is not None:
        await edit_message.edit_text(
            text=text,
            reply_markup=keyboard,
        )
    elif bot is not None:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            message_thread_id=thread_id,
        )
    else:
        _logger.warning(
            "_send_collection_page called without edit_message and without bot; "
            "no message could be sent."
        )


# ---------------------------------------------------------------------------
# Callbacks — database selection + pagination
# ---------------------------------------------------------------------------


@size_router.callback_query(SizeDbCallback.filter())
async def on_size_db_selected(
    callback: CallbackQuery,
    callback_data: SizeDbCallback,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """User picked a database from the inline list."""
    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    await _send_collection_page(
        chat_id=callback.message.chat.id,
        thread_id=callback.message.message_thread_id,
        deps=telegram_deps,
        user=user,
        database=callback_data.database,
        page=0,
        edit_message=callback.message,
    )


@size_router.callback_query(SizeCollPageCallback.filter())
async def on_size_collection_page(
    callback: CallbackQuery,
    callback_data: SizeCollPageCallback,
    telegram_deps: TelegramDependencies,
    user: User,
) -> None:
    """User clicked a pagination button for collection sizes."""
    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    await _send_collection_page(
        chat_id=callback.message.chat.id,
        thread_id=callback.message.message_thread_id,
        deps=telegram_deps,
        user=user,
        database=callback_data.database,
        page=callback_data.page,
        edit_message=callback.message,
    )
