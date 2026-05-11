# Security

## RBAC Model

| Acción | Admin | DBA | Operator | ReadOnly |
|--------|:-----:|:---:|:--------:|:--------:|
| Backup Full | ✅ | ✅ | ✅ | ❌ |
| Backup Custom | ✅ | ✅ | ✅ | ❌ |
| Cancel Job (propio) | ✅ | ✅ | ✅ | ❌ |
| Cancel Job (ajeno) | ✅ | ✅ | ❌ | ❌ |
| Query Size | ✅ | ✅ | ✅ | ✅ |
| Ver Jobs | ✅ | ✅ | ✅ | ✅ |
| Gestionar Usuarios | ✅ | ❌ | ❌ | ❌ |

## Whitelist

- No user can interact with the bot unless explicitly whitelisted.
- Source of truth is the local SQL database.
- Only ADMIN can add users via `/auth`.

## Rate Limiting

- Commands per user: 30 per 60 seconds.
- Backed by Redis sorted sets with automatic TTL expiration.

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

## Auditing

Every sensitive action is logged to `audit_logs`:
- `BACKUP_REQUESTED`
- `SIZE_QUERIED`
- `USER_ADDED`
- `JOB_CANCELLED`

Retention: 1 year for legal compliance.
