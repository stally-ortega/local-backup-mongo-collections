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
│  │   Backup     │  │   Size       │  │     Job            │   │
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

### ADR-004: Telegram Native Roles + SQLite Whitelist
**Decision:** Dual-source authorization with OR logic  
**Reasons:** After database recreation, the primary admin was locked out. Rather than depending solely on a local whitelist, the platform now queries Telegram Bot API for CREATOR/ADMINISTRATOR status with an in-memory TTL cache (600s). SQLite remains as a fallback for operators without elevated Telegram roles.

### ADR-005: In-Place Message Edits for Progress
**Decision:** `edit_message_text` instead of `send_message` for status updates  
**Reasons:** Prevents chat clutter during long-running backups. Throttled to one edit every 4 seconds per job to avoid FloodWait.

## Data Flow: Backup Request

1. **Router** captures the callback message ID and stores it as `status_message_id`.
2. **RequestBackupUseCase** persists the job with that message ID.
3. **JobManager** enqueues the job in Redis/RQ, forwarding the message ID in the payload.
4. **Worker** retrieves the job, the backup engine streams `mongodump` output, and after each collection the use case edits the original message with live progress (throttled).
5. On completion, the same message is edited with the final status, metrics, and size.
