#!/bin/bash
# MTO Treasury System — Docker Entrypoint
# Waits for the database, runs Alembic migrations, then starts the API server.
set -e

echo "========================================"
echo "  MTO Treasury System — Startup"
echo "========================================"

# ---------------------------------------------------------------------------
# 1. Wait for the database to be ready
#    MariaDB takes 5–15 seconds to initialise after the container starts.
#    Without this wait, alembic upgrade head fails with "Can't connect".
# ---------------------------------------------------------------------------
echo "[1/3] Waiting for database to be ready..."

MAX_ATTEMPTS=30   # 30 × 2s = 60 seconds max wait
ATTEMPT=0

until python -c "
import sys
sys.path.insert(0, '.')
from backend.database import engine
from sqlalchemy import text
try:
    with engine.connect() as c:
        c.execute(text('SELECT 1'))
    sys.exit(0)
except Exception as e:
    print(f'  DB not ready: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]; then
        echo "  FATAL: Database did not become ready after ${MAX_ATTEMPTS} attempts."
        echo "  Check that MariaDB is running and DB_HOST/DB_USER/DB_PASSWORD are correct."
        exit 1
    fi
    echo "  Attempt ${ATTEMPT}/${MAX_ATTEMPTS} — retrying in 2s..."
    sleep 2
done

echo "  Database is ready."

# ---------------------------------------------------------------------------
# 2. Run Alembic migrations
#    alembic upgrade head is idempotent — safe to run on every startup.
#    env.py reads the DB URL from utils.config + secrets_manager so no
#    credentials are stored in alembic.ini.
#
#    In Kubernetes, migrations are handled by the initContainer (see
#    k8s/deployment.yaml). Set SKIP_MIGRATIONS=true to skip this step.
# ---------------------------------------------------------------------------
if [ "${SKIP_MIGRATIONS:-false}" = "true" ]; then
    echo "[2/3] Skipping migrations (SKIP_MIGRATIONS=true — handled by initContainer)."
else
    echo "[2/3] Running Alembic database migrations..."
    alembic upgrade head
    echo "  Migrations complete."
fi

# ---------------------------------------------------------------------------
# 3. Start the API server
# ---------------------------------------------------------------------------
echo "[3/3] Starting API server on port 8001..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8001
