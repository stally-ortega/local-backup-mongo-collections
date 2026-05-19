# Security

## Authentication Sources

The platform supports dual-source authorization with OR logic:

1. **Telegram Native Roles (Primary)** — Users with CREATOR or ADMINISTRATOR
   status in the configured group are granted ADMIN access automatically.
   Results are cached in-memory with a 10-minute TTL to avoid rate-limiting
   the Telegram Bot API.
2. **Local SQLite Whitelist (Fallback)** — Traditional RBAC for operators
   without elevated Telegram group roles.

If either source grants access, the user proceeds. If both deny, the request
receives `"No autorizado"` and an `AUTH_DENIED` audit event is logged.

## RBAC Model

| Action | Admin | DBA | Operator | ReadOnly |
|--------|:-----:|:---:|:--------:|:--------:|
| Backup Full | ✅ | ✅ | ✅ | ❌ |
| Backup Custom | ✅ | ✅ | ✅ | ❌ |
| Cancel Job (own) | ✅ | ✅ | ✅ | ❌ |
| Cancel Job (foreign) | ✅ | ✅ | ❌ | ❌ |
| Query Size | ✅ | ✅ | ✅ | ✅ |
| View Jobs | ✅ | ✅ | ✅ | ✅ |
| Manage Users | ✅ | ❌ | ❌ | ❌ |

## Rate Limiting

- Commands per user: 30 per 60 seconds.
- Backed by Redis sorted sets with automatic TTL expiration.
- Telegram message edits are additionally throttled to one edit every 4 seconds
  per job to avoid FloodWait penalties.

## Distributed Locks

| Lock | Scope | TTL | Purpose |
|------|-------|-----|---------|
| `backup:global` | Global | 1 hour | Prevent concurrent backups |
| `backup:cluster:{hash}` | Per cluster | 1 hour | Cluster-level exclusivity |
| `size_query:global` | Global | 5 minutes | Protect MongoDB from stat saturation |

## Secret Management

- `mongodb_uri` is never stored in plain text in the local database.
- SHA-256 hash is used for cluster identification.
- Full URI lives only in memory (env var).
- `.env` and `config.json` are gitignored.
- Log files are created with `0o600` permissions; failures are logged as debug
  instead of crashing (Docker bind mounts may restrict chmod).

## Auditing

Every sensitive action is logged to `audit.log`:
- `BACKUP_REQUESTED`
- `BACKUP_STARTED`
- `BACKUP_COMPLETED` / `BACKUP_PARTIAL` / `BACKUP_FAILED`
- `SIZE_QUERIED`
- `USER_ADDED`
- `JOB_CANCELLED`
- `AUTH_DENIED`
- `PERMISSION_DENIED`

Retention: 1 year for operational compliance.
