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

### View Job Metrics

```
/stats
```

Shows jobs today/week/month, success rate, average duration, and storage consumption.

## Reading Logs

Logs are stored in `logs/` with daily rotation:
- `ops.log` — INFO+ operational logs (30 days retention)
- `errors.log` — ERROR+ logs (90 days retention)
- `audit.log` — audit trail (1 year retention)

```bash
tail -f logs/ops.log
```

## Restarting Workers

```bash
sudo systemctl restart mongo-ops-worker
```

## Troubleshooting

### Bot not responding
- Check `mongo-ops-bot` service status: `systemctl status mongo-ops-bot`
- Verify Telegram token in `.env`
- Check `logs/errors.log`

### Jobs stuck in QUEUED
- Verify Redis is running: `redis-cli ping`
- Check worker status: `systemctl status mongo-ops-worker`
- Restart worker if needed

### MongoDB connection errors
- Verify `MONGO_OPS_MONGODB_URI` is correct
- Check network connectivity to Atlas cluster
- Review `logs/errors.log` for authentication failures

### Disk space warnings
- Run retention cleanup manually: check `RetentionManager` logs
- Verify `MONGO_OPS_BACKUP_BASE_PATH` has sufficient space
