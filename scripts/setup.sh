#!/usr/bin/env bash
set -euo pipefail

echo "=== MongoDB Ops Platform Setup ==="

# Detect OS
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "This script is designed for Ubuntu/Linux. For Windows, use setup.ps1"
    exit 1
fi

# Update system
echo "Updating package lists..."
sudo apt-get update

# Install Python 3.10+ if not present
if ! command -v python3.10 &> /dev/null; then
    echo "Installing Python 3.10..."
    sudo apt-get install -y python3.10 python3.10-venv python3-pip
fi

# Install Poetry if not present
if ! command -v poetry &> /dev/null; then
    echo "Installing Poetry..."
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install Redis if not present
if ! command -v redis-server &> /dev/null; then
    echo "Installing Redis..."
    sudo apt-get install -y redis-server
    sudo systemctl enable redis-server
    sudo systemctl start redis-server
fi

# Harden Redis
echo "Applying basic Redis hardening..."
sudo sed -i 's/^#\?bind .*/bind 127.0.0.1/' /etc/redis/redis.conf
sudo sed -i 's/^#\?protected-mode .*/protected-mode yes/' /etc/redis/redis.conf
if ! grep -q '^requirepass' /etc/redis/redis.conf; then
    echo "WARNING: remember to set 'requirepass' in /etc/redis/redis.conf manually."
fi
sudo systemctl restart redis-server

# Install MongoDB Database Tools
echo "Please ensure MongoDB Database Tools (mongodump) are installed."
echo "See: https://www.mongodb.com/docs/database-tools/installation/"

# Create directories
echo "Creating project directories..."
mkdir -p backups logs

# Install dependencies
echo "Installing Python dependencies..."
poetry install

# Initialize database
echo "Initializing database..."
poetry run python scripts/init_db.py

echo "=== Setup complete ==="
echo "Next steps:"
echo "1. Copy .env.example to .env and configure your variables."
echo "2. Run 'poetry run python -m app' to start the bot."
echo "3. Run 'poetry run python app/workers/backup_worker.py' to start the worker."
