"""CLI script to seed a user into the platform whitelist.

Usage::

    python scripts/add_user.py <telegram_id> <username> <role>

Example::

    python scripts/add_user.py 123456789 alice ADMIN

Roles allowed: ADMIN, DBA, OPERATOR, READONLY.
"""

import argparse
import asyncio
import sys

from app.config import AppConfig
from app.domain.entities.user import User
from app.domain.value_objects.enums import UserRole
from app.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
    init_database,
)
from app.infrastructure.persistence.sql_user_repository import SQLUserRepository


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add a Telegram user to the MongoOps whitelist",
    )
    parser.add_argument(
        "telegram_id",
        type=int,
        help="Telegram user ID (positive integer)",
    )
    parser.add_argument(
        "username",
        type=str,
        help="Telegram username or display name",
    )
    parser.add_argument(
        "role",
        type=str,
        choices=[r.value for r in UserRole],
        help="RBAC role",
    )
    return parser.parse_args()


async def _add_user(telegram_id: int, username: str, role: UserRole) -> None:
    config = AppConfig()  # type: ignore[call-arg]
    engine = await create_engine(config)
    await init_database(engine)
    session_factory = await create_session_factory(engine)

    async with session_factory() as session:
        repo = SQLUserRepository(session)

        existing = await repo.get_by_telegram_id(telegram_id)
        if existing is not None:
            print(f"User {telegram_id} already exists (role={existing.role.value}).")
            await engine.dispose()
            sys.exit(1)

        user = User(
            telegram_id=telegram_id,
            username=username,
            role=role,
            is_active=True,
        )
        await repo.save(user)
        await session.commit()
        print(f"Added user {telegram_id} ({username}) with role {role.value}.")

    await engine.dispose()


def main() -> None:
    args = _parse_args()
    if args.telegram_id <= 0:
        print("Error: telegram_id must be a positive integer.")
        sys.exit(1)
    asyncio.run(_add_user(args.telegram_id, args.username, UserRole(args.role)))


if __name__ == "__main__":
    main()
