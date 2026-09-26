#!/usr/bin/env bash
# Verify Alembic migrations apply, match the models, and reverse cleanly.
set -euo pipefail

DB="$(mktemp -u).db"
export DATABASE_URL="sqlite:///${DB}"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export ENV="test"
export AUTH_DEV_MODE="true"

python -m alembic upgrade head
python -m alembic check
python -m alembic downgrade base

echo "Migration checks passed (upgrade, parity, downgrade)."
