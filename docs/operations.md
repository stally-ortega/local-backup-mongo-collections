# Operations

## Administrative Commands

### Add a User to Whitelist

Via CLI:
```bash
poetry run python scripts/add_user.py 123456789 alice OPERATOR
```

Via Telegram (ADMIN only):
```
/auth 123456789 alice OPERATOR
```

### Check System Health

```
/health
```

Reports status of Telegram API, MongoDB, Redis, disk space, and running jobs.

### Manage Whitelist Users

```
/users
```

Lists all whitelisted users with roles and activity status (ADMIN only).

## Available Commands

| Command | Topic | Role | Description |
|---------|-------|------|-------------|
| `/backup` | BACKUP_REQUESTS | Admin / DBA / Operator | Start full or custom backup flow |
| `/size` | SIZE_ASK | All roles | Query cluster, database, or collection sizes |
| `/users` | ADMIN | Admin | Manage whitelist users |
| `/auth` | ADMIN | Admin | Add user to whitelist |
| `/health` | ADMIN | Admin | System health check |

## Upcoming Commands

These commands are planned for future releases:

| Command | Topic | Role | Description |
|---------|-------|------|-------------|
| `/jobs` | ADMIN | All | List recent jobs with current statuses |
| `/cancel <job_id>` | BACKUP_REQUESTS | Admin / DBA / Operator | Cancel a queued or running job |
| `/stats` | ADMIN | Admin | Job metrics, success rate, storage consumption |

## Reading Logs

Logs are stored in `logs/` with daily rotation:
- `ops.log` — INFO+ operational logs (30 days retention)
- `errors.log` — ERROR+ logs (90 days retention)
- `audit.log` — audit trail (1 year retention)

```bash
tail -f logs/ops.log
```

When running with Docker Compose:

```bash
docker compose logs -f bot
docker compose logs -f worker
```

## Restarting Services

Docker Compose:

```bash
docker compose restart bot
docker compose restart worker
```

Systemd:

```bash
sudo systemctl restart mongo-ops-bot
sudo systemctl restart mongo-ops-worker
```

## Troubleshooting

### Bot not responding
- Check bot service status: `docker compose ps` or `systemctl status mongo-ops-bot`
- Verify Telegram token in `.env`
- Check `logs/errors.log`

### Jobs stuck in QUEUED
- Verify Redis is running: `docker compose ps redis` or `redis-cli ping`
- Check worker status: `docker compose ps worker` or `systemctl status mongo-ops-worker`
- Restart worker if needed

### MongoDB connection errors
- Verify `MONGO_OPS_MONGODB_URI` is correct
- Check network connectivity to Atlas cluster
- Review `logs/errors.log` for authentication failures

### Disk space warnings
- Run retention cleanup manually: check `RetentionManager` logs
- Verify `MONGO_OPS_BACKUP_BASE_PATH` has sufficient space
- For Docker: ensure the host volume has space (bind mounts share host filesystem)
