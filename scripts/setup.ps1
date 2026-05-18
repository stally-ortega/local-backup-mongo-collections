# MongoDB Ops Platform - Windows Setup Script
# Note: Redis for Windows requires WSL2 or Docker.

Write-Host "=== MongoDB Ops Platform Setup (Windows) ===" -ForegroundColor Cyan

# Check Python
$pythonVersion = python --version 2> $null
if (-not $?) {
    Write-Error "Python is not installed. Please install Python 3.10+ from https://www.python.org/downloads/"
    exit 1
}
Write-Host "Python found: $pythonVersion"

# Check Poetry
$poetryVersion = poetry --version 2> $null
if (-not $?) {
    Write-Host "Installing Poetry..."
    # Pinning version ensures reproducibility and leverages PyPI hash verification.
    python -m pip install --user poetry==1.8.3
    $env:PATH = "$env:APPDATA\Python\Scripts;$env:PATH"
}
Write-Host "Poetry found: $poetryVersion"

# Create directories
New-Item -ItemType Directory -Force -Path backups, logs | Out-Null

# Install dependencies
Write-Host "Installing Python dependencies..."
poetry install

# Initialize database
Write-Host "Initializing database..."
poetry run python scripts/init_db.py

Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "1. Copy .env.example to .env and configure your variables."
Write-Host "2. Ensure Redis is available (WSL2, Docker, or remote)."
Write-Host "3. Run 'poetry run python -m app' to start the bot."
Write-Host "4. Run 'poetry run python app/workers/backup_worker.py' to start the worker."
