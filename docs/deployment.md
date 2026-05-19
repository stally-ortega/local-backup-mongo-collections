# Deployment

## System Requirements

- Ubuntu 22.04+ (recommended for production)
- Docker 24.0+ and Docker Compose (recommended)
- Python 3.10+, Poetry, Redis 7+ (alternative: local development)
- MongoDB Database Tools (`mongodump`)

## Docker Compose (Recommended)

Docker Compose is the fastest way to deploy the full stack on any environment
(Linux, Windows with WSL2, macOS, or cloud VMs).

### 1. Clone and configure

```bash
git clone <repo-url> local-backup-mongo-collections
cd local-backup-mongo-collections
cp .env.example .env
# Edit .env with your secrets
```

**Docker-specific adjustments to `.env`:**

```dotenv
# Point to the Redis service defined in docker-compose.yml
MONGO_OPS_REDIS_URL=redis://redis:6379/0

# Relative path works because WORKDIR in the container is /app
MONGO_OPS_BACKUP_BASE_PATH=./backups
```

### 2. Build and initialize

```bash
docker compose build
docker compose run --rm bot python scripts/init_db.py
```

### 3. Create the first admin

Replace `123456789` with your real `telegram_id` (obtain it from @userinfobot).

```bash
docker compose run --rm bot python scripts/add_user.py 123456789 your_username ADMIN
```

### 4. Start the platform

```bash
docker compose up -d
```

Containers:

| Container | Service | Description |
|-----------|---------|-------------|
| `mongo_ops_redis` | Redis | Job queue, FSM storage, distributed locks, rate-limiting |
| `mongo_ops_bot` | Bot | Telegram polling dispatcher |
| `mongo_ops_worker` | Worker | RQ backup worker consuming jobs |

### 5. Verify

In Telegram, inside the **ADMIN** topic, run:

```
/health
```

It should report the status of Telegram API, MongoDB, Redis, disk space, and running jobs.

### 6. Logs

```bash
# All services
docker compose logs -f

# Single service
docker compose logs -f bot
docker compose logs -f worker
```

### 7. Stop

```bash
docker compose down
```

To also remove the Redis volume (queue data):

```bash
docker compose down -v
```

---

## Systemd (Alternative for Linux)

If you prefer native processes over containers, create the following systemd units.

`/etc/systemd/system/mongo-ops-bot.service`:

```ini
[Unit]
Description=MongoDB Ops Telegram Bot
After=network.target redis.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/mongo-ops-platform
ExecStart=/home/ubuntu/.local/bin/poetry run python -m app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/mongo-ops-worker.service`:

```ini
[Unit]
Description=MongoDB Ops Backup Worker
After=network.target redis.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/mongo-ops-platform
ExecStart=/home/ubuntu/.local/bin/poetry run python app/workers/backup_worker.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mongo-ops-bot mongo-ops-worker
```

---

## Windows Development

For Windows development, use WSL2 or Docker Desktop. Redis is available via
WSL2 (`sudo service redis-server start`). A convenience PowerShell setup script
is available at `scripts/setup.ps1`.

## Resource Summary

| Resource | Port / Protocol | Notes |
|----------|----------------|-------|
| Redis local | `6379/tcp` | Accessible from bot and worker |
| MongoDB Atlas | `27017/tcp` (or SRV) | Outbound; Atlas handles firewall |
| Telegram API | `443/tcp` (HTTPS) | Outbound to `api.telegram.org` |
| SQLite local | — | File-based; no port required |

## Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| `RedisConnection not open` | Redis not running | `sudo service redis-server start` (Linux/WSL2) |
| `PermissionError` on commands | User not in whitelist | Run `scripts/add_user.py` with appropriate role |
| Bot does not respond to `/health` | Invalid Telegram token | Verify `MONGO_OPS_TELEGRAM_BOT_TOKEN` in `.env` |
| Jobs stuck in `QUEUED` | Worker not running | Start worker in a second terminal or container |
| `mongodump` not found | MongoDB Database Tools missing | Install from https://www.mongodb.com/docs/database-tools/ |
