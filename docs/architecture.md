# Architecture

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    INTERFACES / ADAPTERS                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │   Telegram   │  │     CLI      │  │  API REST (fut)  │   │
│  │   (aiogram)  │  │   (argparse) │  │   (FastAPI)      │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
└─────────┼─────────────────┼───────────────────┼─────────────┘
          │                 │                   │
          ▼                 ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                   APPLICATION / USE CASES                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │   Backup     │  │   Size       │  │     Job          │   │
│  │ Orchestrator │  │   Query      │  │   Manager        │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │                 │                   │             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │        Application Services (Permission, Audit)      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                       DOMAIN / CORE                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │   Entities   │  │  Value       │  │    Domain        │   │
│  │  (Job, User) │  │  Objects     │  │   Services       │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Repository  │  │   Events     │  │   Exceptions     │   │
│  │  Interfaces  │  │  (Domain)    │  │   (Domain)       │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                  INFRASTRUCTURE / ADAPTERS                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │   MongoDB    │  │   Redis/RQ   │  │   SQLite/PSQL    │   │
│  │   (pymongo)  │  │   (Job Q)    │  │   (SQLAlchemy)   │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │   mongodump  │  │   Telegram   │  │   File System    │   │
│  │   Engine     │  │   Bot API    │  │   (aiofiles)     │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Key Decisions

### ADR-001: aiogram vs python-telegram-bot
**Decision:** aiogram 3.x
**Reasons:** FSM native, router-based handlers, full typing, async-first, native Telegram Topics support.

### ADR-002: RQ vs Celery
**Decision:** RQ for MVP
**Reasons:** Single responsibility, simple debugging, lightweight workers. Celery to be evaluated if multi-broker needed.

### ADR-003: SQLite → PostgreSQL
**Decision:** SQLite MVP, PostgreSQL-ready architecture
**Reasons:** Zero-config development, SQLAlchemy 2.x async ORM abstracts the engine.

## Data Flow

See `work_plan.md` section 3.2 for the detailed backup demand flow diagram.
