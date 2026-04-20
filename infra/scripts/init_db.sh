#!/usr/bin/env bash
# Initialize Sentinel database schema using Alembic
set -e

cd "$(dirname "$0")/../../backend"

echo "→ Running database migrations..."
python -m alembic upgrade head

echo "→ Database ready."
