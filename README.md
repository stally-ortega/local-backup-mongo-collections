# MongoDB Atlas Operations Automation Platform

Enterprise platform for MongoDB Atlas operational automation using Telegram as the operational interface.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Poetry](https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json)](https://python-poetry.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Architecture

- **Clean Architecture** + **Hexagonal Architecture**
- **Domain-Driven Design** principles
- **Async-first** with aiogram, motor, and SQLAlchemy async
- **Job Queue** with Redis + RQ
- **RBAC** security model with whitelist
- **Structured logging** with correlation IDs

## Quick Start

### Prerequisites

- Python 3.10+
- Poetry
- Redis 7+
- MongoDB Database Tools (`mongodump`)

### Installation

```bash
poetry install
poetry run python scripts/init_db.py
```

### Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required variables:
- `MONGO_OPS_TELEGRAM_TOKEN`
- `MONGO_OPS_TELEGRAM_CHAT_ID`
- `MONGO_OPS_MONGODB_URI`
- `MONGO_OPS_REDIS_URL`
- `MONGO_OPS_BACKUP_BASE_PATH`

### Running

Start the bot:
```bash
poetry run python -m app
```

Start the worker (in a separate terminal):
```bash
poetry run python app/workers/backup_worker.py
```

## Testing

```bash
poetry run pytest
```

## Commands

| Command | Topic | Role | Description |
|---------|-------|------|-------------|
| `/backup` | BACKUP_REQUESTS | Admin/DBA/Operator | Start backup flow |
| `/size` | SIZE_ASK | All | Query cluster size |
| `/jobs` | ADMIN | All | List recent jobs |
| `/users` | ADMIN | Admin | Manage whitelist |
| `/auth` | ADMIN | Admin | Add user to whitelist |
| `/cancel <job_id>` | BACKUP_REQUESTS | Admin/DBA/Operator | Cancel a job |
| `/health` | ADMIN | Admin | System health check |
| `/stats` | ADMIN | Admin | Job metrics |

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Operations](docs/operations.md)
- [Security](docs/security.md)

## License

MIT
