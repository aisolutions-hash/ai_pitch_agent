# Verify Alembic migrations apply, match the models, and reverse cleanly.
$ErrorActionPreference = "Stop"

$db = Join-Path $env:TEMP "kalisoft_migration_check.db"
Remove-Item $db -ErrorAction SilentlyContinue

$env:DATABASE_URL = "sqlite:///" + ($db -replace "\\", "/")
$env:SECRET_KEY = "verify-" + [guid]::NewGuid().ToString("N")
$env:ENV = "test"
$env:AUTH_DEV_MODE = "true"

python -m alembic upgrade head
python -m alembic check
python -m alembic downgrade base

Write-Host "Migration checks passed (upgrade, parity, downgrade)."
