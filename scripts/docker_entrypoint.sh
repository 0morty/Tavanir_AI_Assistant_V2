#!/usr/bin/env bash
set -eo pipefail

# Short-circuit help queries without requiring database connectivity
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    exec python scripts/extract_and_ingest_historical_suggestions.py "$@"
fi

# If first argument starts with a dash or is empty, execute standard ingestion pipeline
if [ -z "$1" ] || [ "${1#-}" != "$1" ]; then
    echo "[Entrypoint] Step 1/3: Verifying PostgreSQL readiness and provisioning database..."
    python scripts/setup_postgres.py

    echo "[Entrypoint] Step 2/3: Applying database migrations (alembic upgrade head)..."
    alembic upgrade head

    echo "[Entrypoint] Step 3/3: Launching cold-start suggestion ingestion..."
    exec python scripts/extract_and_ingest_historical_suggestions.py "$@"
else
    # Passthrough execution for arbitrary commands (bash, pytest, tsql, alembic)
    exec "$@"
fi
