# MongoDB Atlas Operations Automation Platform

Enterprise-grade platform for automating MongoDB Atlas operations through Telegram.
Designed for teams that need scheduled and on-demand backups, size monitoring, and
operational oversight without direct cluster access.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Poetry](https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json)](https://python-poetry.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

The platform exposes a Telegram bot as the primary operational interface. Authorized
operators can request backups, query cluster sizes, and monitor system health from
any device. Backups run asynchronously in a Redis-backed job queue, with live
progress updates edited in-place on the original status message.

Authentication supports two sources:
1. **Telegram native roles** — users with CREATOR or ADMINISTRATOR status in the
   configured group are granted full access automatically.
2. **Local SQLite whitelist** — traditional RBAC for operators without elevated
   Telegram roles.

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Interface | aiogram 3.x | Telegram bot with FSM, routers, and native Topics support |
| Application | Python 3.10+, Poetry | Use cases, DTOs, services, and ports |
| Domain | Pydantic | Entities, value objects, events, and FSM state guards |
| Persistence | SQLAlchemy 2.x async + aiosqlite | Local job/user/audit storage (SQLite MVP) |
| Queue | Redis 7 + RQ | Async job execution, distributed locks, rate limiting |
| Backup Engine | mongodump (MongoDB Database Tools) | BSON dumps with async subprocess streaming |
| Infrastructure | Docker, Docker Compose | Containerized deployment with log rotation |

## Functional Capabilities

- **Backup Orchestration** — Full or custom collection backups via `mongodump`,
  with per-collection error isolation (partial success instead of total failure).
- **Live Progress Tracking** — The original "PENDING" message is edited in-place
  to reflect IN_PROGRESS, SUCCESS, FAILED, or PARTIAL_SUCCESS states.
- **RBAC Security** — Four roles (ADMIN, DBA, OPERATOR, READONLY) with
  command-level and topic-level permission matrices.
- **Rate Limiting** — Sliding-window throttling per user and action, backed by
  Redis with automatic TTL expiration.
- **Audit Logging** — Every sensitive action is logged to a dedicated audit stream
  with correlation IDs and structured JSON output.
- **Retention Management** — Automatic cleanup of old backups by age and total
  storage cap.

## Prerequisites

### For Docker Compose (recommended)

- Docker 24.0+ and Docker Compose
- Telegram Bot Token (from @BotFather)
- MongoDB Atlas URI
- Redis (provided by `docker-compose.yml`)

### For Local Development

- Python 3.10+
- Poetry
- Redis 7+
- MongoDB Database Tools (`mongodump` in `$PATH`)

## Installation

### Docker Compose (Production)

```bash
git clone <repo-url> local-backup-mongo-collections
cd local-backup-mongo-collections
```

Copy the example environment file and fill in your secrets:

```bash
cp .env.example .env
# Edit .env with your tokens and URIs
```

Build the image and initialize the database:

```bash
docker compose build
docker compose run --rm bot python scripts/init_db.py
docker compose run --rm bot python scripts/add_user.py <YOUR_TELEGRAM_ID> your_username ADMIN
```

Start the platform:

```bash
docker compose up -d
```

Services:
- `mongo_ops_redis` — Job queue, FSM storage, locks
- `mongo_ops_bot` — Telegram polling bot
- `mongo_ops_worker` — RQ backup worker

### Local Development

```bash
poetry install
poetry run python scripts/init_db.py
poetry run python scripts/add_user.py <YOUR_TELEGRAM_ID> your_username ADMIN
```

Start the bot and worker in separate terminals:

```bash
# Terminal 1
poetry run python -m app

# Terminal 2
poetry run python app/workers/backup_worker.py
```

## Configuration

All configuration is injected via environment variables in `.env`:

| Variable | Description |
|----------|-------------|
| `MONGO_OPS_TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `MONGO_OPS_TELEGRAM_CHAT_ID` | Group/chat ID where the bot operates |
| `MONGO_OPS_MONGODB_URI` | MongoDB Atlas connection URI |
| `MONGO_OPS_REDIS_URL` | Redis connection URL |
| `MONGO_OPS_DATABASE_URL` | SQLite URL (default: `sqlite+aiosqlite:///./mongo_ops.db`) |
| `MONGO_OPS_BACKUP_BASE_PATH` | Directory for backup archives |
| `MONGO_OPS_RETENTION_FULL_WEEKS` | Retention period for full backups |
| `MONGO_OPS_RETENTION_CUSTOM_WEEKS` | Retention period for custom backups |
| `MONGO_OPS_RETENTION_MAX_GB` | Maximum total backup storage (GB) |
| `MONGO_OPS_LOG_LEVEL` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `MONGO_OPS_RATE_LIMIT_MAX_REQUESTS` | Max requests per user per window |
| `MONGO_OPS_RATE_LIMIT_WINDOW_SECONDS` | Rate limit window (seconds) |
| `MONGO_OPS_TOPIC_BACKUP_REQUESTS` | Telegram Topic ID for backups |
| `MONGO_OPS_TOPIC_SIZE_ASK` | Telegram Topic ID for size queries |
| `MONGO_OPS_TOPIC_EXECUTION_ERRORS` | Telegram Topic ID for alerts |
| `MONGO_OPS_TOPIC_ADMIN` | Telegram Topic ID for admin commands |

## Deployment

See [docs/deployment.md](docs/deployment.md) for:
- Docker Compose deployment with production-ready logging limits
- Systemd service templates (optional)
- Windows/WSL2 development setup
- Post-deployment verification steps

## Commands

### Available Now

| Command | Topic | Role | Description |
|---------|-------|------|-------------|
| `/backup` | BACKUP_REQUESTS | Admin / DBA / Operator | Start backup flow (full or custom) |
| `/size` | SIZE_ASK | All roles | Query cluster/database/collection sizes |
| `/users` | ADMIN | Admin | Manage whitelist users |
| `/auth` | ADMIN | Admin | Add user to whitelist |
| `/health` | ADMIN | Admin | System health check (APIs, disk, jobs) |

### Coming Soon

| Command | Topic | Role | Description |
|---------|-------|------|-------------|
| `/jobs` | ADMIN | All | List recent jobs with statuses |
| `/cancel <job_id>` | BACKUP_REQUESTS | Admin / DBA / Operator | Cancel a queued or running job |
| `/stats` | ADMIN | Admin | Job metrics and storage consumption |

## Architecture

See [docs/architecture.md](docs/architecture.md) for the layer diagram, key
architectural decisions (ADRs), and data flow.

## Security

See [docs/security.md](docs/security.md) for the RBAC matrix, rate limiting
details, distributed lock reference, and secret management policies.

## Operations

See [docs/operations.md](docs/operations.md) for administrative commands, log
reading, and troubleshooting.

## Testing

```bash
poetry run pytest
```

Coverage report is generated automatically in `htmlcov/`.

## License

[LICENSE MIT](LICENSE)
