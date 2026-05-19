#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

poetry run python app/workers/backup_worker.py
