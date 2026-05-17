# Deployment Guide

## MongoDB Atlas Operations Automation Platform — MVP

Guía definitiva para desplegar la plataforma en entornos Linux (producción) y Windows (desarrollo).

---

## 1. Servicios Requeridos (Background Services)

Antes de arrancar la aplicación, los siguientes servicios deben estar corriendo y accesibles:

| Servicio | Versión recomendada | Propósito | ¿Es obligatorio? |
|----------|--------------------|-----------|-----------------|
| **Redis** | 7.x | Job queue (RQ), FSM storage, distributed locks, rate-limiting sorted sets | Sí |
| **MongoDB Atlas** | 5.0+ | Cluster de origen para backups y consultas de tamaño | Sí (remoto) |
| **MongoDB Database Tools** | 100.x | `mongodump` ejecutable en `$PATH` para el backup engine | Sí (binario) |
| **SQLite** | — | Base local MVP (file-based, no requiere servicio) | Sí (embebido) |

**Nota:** la aplicación no requiere un servicio MongoDB local; se conecta directamente a MongoDB Atlas vía URI.

---

## 2. Variables de Entorno Completas (.env)

Copia `.env.example` a `.env` y rellena los valores reales.

```bash
cp .env.example .env
```

### Formato exacto del archivo `.env`

```dotenv
# =============================================================================
# MongoDB Atlas Operations Automation Platform
# Environment Configuration
# =============================================================================
# NUNCA commitees un archivo .env real al control de versiones.
# Copia este bloque a un archivo .env y rellena tus secretos.
#
# NOTA DE SEGURIDAD:
#   mongodb_uri se lee en memoria al iniciar y NUNCA se escribe a la base
#   de datos local.  Toda persistencia usa cluster_uri_hash (SHA-256).
# =============================================================================

# ---------------------------------------------------------------------------
# Telegram Bot
# ---------------------------------------------------------------------------
# Obtén el token desde @BotFather en Telegram.
MONGO_OPS_TELEGRAM_BOT_TOKEN=<TU_BOT_TOKEN_AQUI>

# ID del grupo o chat donde opera el bot. Puede ser negativo para grupos.
# Para obtenerlo: añade el bot a un grupo y visita
# https://api.telegram.org/bot<TOKEN>/getUpdates
MONGO_OPS_TELEGRAM_CHAT_ID=<TU_CHAT_ID>

# ---------------------------------------------------------------------------
# MongoDB Atlas
# ---------------------------------------------------------------------------
# URI completa del cluster de Atlas (incluye usuario, password y base).
# Formato: mongodb+srv://user:password@cluster.mongodb.net/
MONGO_OPS_MONGODB_URI=mongodb+srv://<USUARIO>:<PASSWORD>@<CLUSTER>.mongodb.net/?retryWrites=true&w=majority

# ---------------------------------------------------------------------------
# Redis (Job Queue + FSM Storage + Locks + Rate Limiting)
# ---------------------------------------------------------------------------
# URL de conexión de Redis. En desarrollo local suele ser localhost.
# En producción apunta a tu instancia de Redis (o Redis Cloud / ElastiCache).
MONGO_OPS_REDIS_URL=redis://localhost:6379/0

# ---------------------------------------------------------------------------
# Base de Datos Local (SQLite — MVP)
# ---------------------------------------------------------------------------
# URL async de SQLAlchemy. SQLite es suficiente para el MVP.
# Para PostgreSQL futuro: postgresql+asyncpg://user:pass@host/db
MONGO_OPS_DATABASE_URL=sqlite+aiosqlite:///./mongo_ops.db

# ---------------------------------------------------------------------------
# Almacenamiento de Backups
# ---------------------------------------------------------------------------
# Ruta base donde se guardarán los archivos comprimidos de backup.
# Debe tener permisos de escritura para el usuario del proceso.
MONGO_OPS_BACKUP_BASE_PATH=./backups

# ---------------------------------------------------------------------------
# Política de Retención
# ---------------------------------------------------------------------------
# Semanas de retención para backups full y custom, y límite total en GB.
MONGO_OPS_RETENTION_FULL_WEEKS=4
MONGO_OPS_RETENTION_CUSTOM_WEEKS=2
MONGO_OPS_RETENTION_MAX_GB=50

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Nivel de logging: DEBUG, INFO, WARNING, ERROR, CRITICAL
MONGO_OPS_LOG_LEVEL=INFO

# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------
# Máximo de requests por usuario por ventana de tiempo.
MONGO_OPS_RATE_LIMIT_MAX_REQUESTS=10
MONGO_OPS_RATE_LIMIT_WINDOW_SECONDS=60

# ---------------------------------------------------------------------------
# Concurrencia
# ---------------------------------------------------------------------------
# Máximo de jobs de backup que pueden ejecutarse simultáneamente.
MONGO_OPS_MAX_CONCURRENT_BACKUPS=3

# ---------------------------------------------------------------------------
# Topic IDs de Telegram (obtenidos desde el grupo de Telegram)
# ---------------------------------------------------------------------------
# Estos IDs corresponden a los "Topics" (hilos) dentro de un grupo de Telegram.
# Se configuran como 1, 2, 3, 4 por defecto pero deben coincidir con los IDs
# reales del grupo. Puedes obtenerlos via getUpdates de la API de Telegram.
MONGO_OPS_TOPIC_BACKUP_REQUESTS=1
MONGO_OPS_TOPIC_SIZE_ASK=2
MONGO_OPS_TOPIC_EXECUTION_ERRORS=3
MONGO_OPS_TOPIC_ADMIN=4
```

---

## 3. Guía de Arranque Paso a Paso (Linux / Ubuntu)

### 3.1 Prerrequisitos del sistema

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3-pip redis-server git
```

Instala MongoDB Database Tools:
```bash
# Descarga desde https://www.mongodb.com/docs/database-tools/installation/
# Asegúrate de que `mongodump` esté en tu $PATH:
mongodump --version
```

### 3.2 Instalar Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"
```

### 3.3 Clonar e instalar dependencias

```bash
git clone <repo-url> local-backup-mongo-collections
cd local-backup-mongo-collections
poetry install --no-interaction
```

### 3.4 Crear directorios necesarios

```bash
mkdir -p backups logs
```

### 3.5 Configurar variables de entorno

```bash
cp .env.example .env
# Edita .env con nano/vim y rellena los valores reales
nano .env
```

### 3.6 Inicializar la base de datos local

```bash
poetry run python scripts/init_db.py
```

### 3.7 Inyectar el primer usuario administrador (whitelist)

Reemplaza `123456789` con tu propio `telegram_id` (obtenlo hablando con @userinfobot en Telegram).

```bash
poetry run python scripts/add_user.py <TU_TELEGRAM_ID> tu_username ADMIN
```

Verás:
```
Added user 123456789 (tu_username) with role ADMIN.
```

### 3.8 Arrancar servicios en segundo plano

**Opción A — Systemd (recomendado para producción):**

Crea los archivos de servicio (ver `docs/deployment.md` para plantillas exactas de systemd) y arranca:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mongo-ops-bot
sudo systemctl enable --now mongo-ops-worker
```

**Opción B — Manual en terminales separadas:**

Terminal 1 — Bot:
```bash
poetry run python -m app
```

Terminal 2 — Worker:
```bash
poetry run python app/workers/backup_worker.py
```

**Opción C — Scripts de conveniencia:**

```bash
bash scripts/start_bot.sh      # en una terminal
bash scripts/start_worker.sh   # en otra terminal
```

### 3.9 Verificar estado

En Telegram, dentro del grupo/topic ADMIN, ejecuta:

```
/health
```

Debe responder con el estado de Telegram API, MongoDB, Redis, disco y jobs corriendo.

---

## 4. Guía de Arranque Paso a Paso (Windows 10 / 11)

### 4.1 Prerrequisitos

- Python 3.10+ instalado desde [python.org](https://www.python.org/downloads/)
- Git para Windows
- Redis disponible vía **WSL2** o **Docker Desktop** (Redis nativo para Windows no es soportado oficialmente)

### 4.2 Redis en WSL2 (recomendado)

En una terminal de WSL2 (Ubuntu):

```bash
sudo apt update
sudo apt install -y redis-server
sudo service redis-server start
```

Verifica con:
```bash
redis-cli ping
```

Debe responder `PONG`.

### 4.3 Instalar Poetry

En PowerShell (como administrador):

```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
```

Añade Poetry al PATH si es necesario:
```powershell
$env:PATH = "$env:APPDATA\Python\Scripts;$env:PATH"
```

### 4.4 Clonar e instalar

```powershell
git clone <repo-url> local-backup-mongo-collections
cd local-backup-mongo-collections
poetry install --no-interaction
```

### 4.5 Crear directorios

```powershell
New-Item -ItemType Directory -Force -Path backups, logs
```

### 4.6 Configurar variables de entorno

```powershell
copy .env.example .env
# Edita .env con tu editor favorito (VS Code, Notepad, etc.)
code .env
```

### 4.7 Inicializar base de datos

```powershell
poetry run python scripts/init_db.py
```

### 4.8 Inyectar el primer administrador

```powershell
poetry run python scripts/add_user.py <TU_TELEGRAM_ID> tu_username ADMIN
```

### 4.9 Arrancar servicios

**Terminal 1 — Bot:**
```powershell
poetry run python -m app
```

**Terminal 2 — Worker:**
```powershell
poetry run python app/workers/backup_worker.py
```

**Alternativa:** usa el script de conveniencia para Windows:
```powershell
.\scripts\setup.ps1
```

### 4.10 Verificar

En Telegram, dentro del topic ADMIN:

```
/health
```

---

## 5. Despliegue con Docker Compose

Esta es la forma más rápida de levantar toda la plataforma en cualquier entorno
(Linux, Windows con WSL2, macOS o servidores cloud) sin instalar Python,
Poetry ni Redis nativamente.

### 5.1 Prerrequisitos

- **Docker** 24.0+ y **Docker Compose** (viene con Docker Desktop).

### 5.2 Ajustar variables de entorno

Copia `.env.example` a `.env` y modifica **dos valores clave** para Docker:

```dotenv
# Apunta al servicio 'redis' definido en docker-compose.yml
MONGO_OPS_REDIS_URL=redis://redis:6379/0

# La ruta relativa sigue funcionando porque el WORKDIR del contenedor es /app
MONGO_OPS_BACKUP_BASE_PATH=./backups
```

> **Importante:** los demás secretos (`MONGO_OPS_TELEGRAM_BOT_TOKEN`,
> `MONGO_OPS_MONGODB_URI`, `MONGO_OPS_TELEGRAM_CHAT_ID`, etc.) deben
> conservarse con tus valores reales.

### 5.3 Construir la imagen

```bash
docker compose build
```

La imagen instala internamente `mongodb-database-tools` (incluye `mongodump`)
y las dependencias de Poetry en una sola capa optimizada.

### 5.4 Inicializar la base de datos local

El volumen `./mongo_ops.db:/app/mongo_ops.db` requiere que el archivo SQLite
exista previamente en el host; de lo contrario Docker crearía un directorio.

```bash
docker compose run --rm bot python scripts/init_db.py
```

Verás:
```
Database initialized successfully.
```

### 5.5 Inyectar el primer administrador

Reemplaza `123456789` con tu `telegram_id` real.

```bash
docker compose run --rm bot python scripts/add_user.py 123456789 tu_username ADMIN
```

### 5.6 Arrancar la plataforma

```bash
docker compose up -d
```

Esto levanta tres contenedores:

| Contenedor | Servicio | Descripción |
|------------|----------|-------------|
| `mongo_ops_redis` | Redis | Cola de jobs, FSM y locks |
| `mongo_ops_bot` | Bot | Polling de Telegram |
| `mongo_ops_worker` | Worker | Consumo de jobs de backup vía RQ |

### 5.7 Verificar estado

En Telegram, dentro del topic **ADMIN**, ejecuta:

```
/health
```

Debe responder con el estado de todos los subsistemas.

### 5.8 Ver logs

```bash
# Todos los servicios
docker compose logs -f

# Solo el bot
docker compose logs -f bot

# Solo el worker
docker compose logs -f worker
```

### 5.9 Detener la plataforma

```bash
docker compose down
```

Para borrar también el volumen de Redis (datos de cola):

```bash
docker compose down -v
```

---

## Resumen de Puertos y Conectividad

| Recurso | Puerto / Protocolo | Notas |
|---------|-------------------|-------|
| Redis local | `6379/tcp` | Debe ser accesible desde el host donde corre el bot y el worker. |
| MongoDB Atlas | `27017/tcp` (o SRV) | Saliente desde el servidor; Atlas maneja el firewall. |
| Telegram API | `443/tcp` (HTTPS) | Saliente hacia `api.telegram.org`. |
| SQLite local | — | File-based; no requiere puerto. |

---

## Troubleshooting Rápido

| Síntoma | Causa probable | Solución |
|---------|---------------|----------|
| `RedisConnection not open` | Redis no está corriendo | `sudo service redis-server start` (Linux) o `sudo service redis-server start` (WSL2) |
| `PermissionError` al usar comandos | Usuario no está en whitelist | Ejecuta `scripts/add_user.py` con rol adecuado |
| Bot no responde a `/health` | Token de Telegram inválido | Verifica `MONGO_OPS_TELEGRAM_BOT_TOKEN` en `.env` |
| Jobs stuck en `QUEUED` | Worker no está corriendo | Arranca el worker en una segunda terminal |
| `mongodump` not found | MongoDB Database Tools no instalados | Instala desde https://www.mongodb.com/docs/database-tools/installation/ |

---

*Documento generado a partir del blueprint arquitectónico y del código fuente del MVP.*
