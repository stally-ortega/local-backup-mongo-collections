# ------------------------------------------------------------------------------
# Stage 1: Python dependencies
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app
ENV PYTHONPATH=/app

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock* ./

RUN poetry install --only main --no-root --no-interaction --no-ansi

# ------------------------------------------------------------------------------
# Stage 2: MongoDB Database Tools (binary download)
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS tools

ARG MONGODB_TOOLS_VERSION=100.9.4
ARG MONGODB_TOOLS_URL=https://fastdl.mongodb.org/tools/db/mongodb-database-tools-ubuntu2204-x86_64-${MONGODB_TOOLS_VERSION}.tgz
ARG MONGODB_TOOLS_SHA256=0F9AEC14C0272B97DFFBD0339769091022400EFF6EE124285F2B182236945EE6

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates tar \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "${MONGODB_TOOLS_URL}" -o /tmp/mongodb-tools.tgz \
    && echo "${MONGODB_TOOLS_SHA256}  /tmp/mongodb-tools.tgz" | sha256sum -c - \
    && tar -xzf /tmp/mongodb-tools.tgz -C /tmp \
    && mv /tmp/mongodb-database-tools-*/bin/mongodump /usr/local/bin/mongodump \
    && chmod +x /usr/local/bin/mongodump \
    && rm -rf /tmp/mongodb-tools.tgz /tmp/mongodb-database-tools-* \
    && mongodump --version

# ------------------------------------------------------------------------------
# Stage 3: Runtime
# ------------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:${PATH}"

# Install runtime system dependencies required by the precompiled mongodump binary
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgssapi-krb5-2 libcurl4 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# Copy mongodump binary from tools stage
COPY --from=tools /usr/local/bin/mongodump /usr/local/bin/mongodump

# Copy application code and helper scripts
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY pyproject.toml poetry.lock* ./

# Create persistent directories (overridden by volumes at runtime)
RUN mkdir -p /app/backups /app/logs

# Security: run as non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Default entrypoint is the Telegram bot; overridden by docker-compose for worker
CMD ["python", "-m", "app"]
