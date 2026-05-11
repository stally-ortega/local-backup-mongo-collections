# Deployment

## System Requirements

- Ubuntu 22.04+ (recommended)
- Python 3.10+
- Redis 7+
- MongoDB Database Tools (`mongodump`)

## Installation Steps

### 1. System Dependencies

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3-pip redis-server
```

Install MongoDB Database Tools from the official repository.

### 2. Project Setup

```bash
git clone <repo-url>
cd local-backup-mongo-collections
poetry install
poetry run python scripts/init_db.py
```

### 3. Environment Configuration

```bash
cp .env.example .env
# Edit .env with your tokens and URIs
```

### 4. Systemd Services

Create `/etc/systemd/system/mongo-ops-bot.service`:

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

Create `/etc/systemd/system/mongo-ops-worker.service`:

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

## Windows Development

For Windows development, use WSL2 or Docker for Redis. See `scripts/setup.ps1` for an automated setup script.
