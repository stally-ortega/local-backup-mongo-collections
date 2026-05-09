"""Bootstrap script: create all database tables from ORM metadata.

Usage::

    poetry run python scripts/init_db.py

The script loads configuration from environment variables (``MONGO_OPS_*``)
and then issues ``CREATE TABLE`` statements for every model registered on
``Base.metadata``.
"""

import asyncio

from app.config import AppConfig
from app.infrastructure.persistence.database import (
    create_engine,
    dispose_engine,
    init_database,
)

# Ensure models are imported so they register on Base.metadata
from app.infrastructure.persistence.models import (  # noqa: F401
    AuditLogORM,
    JobORM,
    RateLimitORM,
    UserORM,
)


async def _main() -> None:
    config = AppConfig()  # type: ignore[call-arg]
    engine = await create_engine(config)
    try:
        await init_database(engine)
        print("Database initialized successfully.")
    finally:
        await dispose_engine(engine)


if __name__ == "__main__":
    asyncio.run(_main())
