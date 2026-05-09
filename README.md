# MongoDB Atlas Operations Automation Platform

Enterprise platform for MongoDB Atlas operational automation using Telegram as the operational interface.

## Architecture

- **Clean Architecture** + **Hexagonal Architecture**
- **Domain-Driven Design** principles
- **Async-first** with aiogram, motor, and SQLAlchemy async
- **Job Queue** with Redis + RQ
- **RBAC** security model with whitelist
- **Structured logging** with correlation IDs

## Development

```bash
poetry install
poetry run pytest
```

## License

MIT
