#!/bin/bash
# MTO Treasury System — Docker Entrypoint
# Runs Alembic migrations before starting the API server.
set -e

echo "========================================"
echo "  MTO Treasury System — Startup"
echo "========================================"

echo "[1/2] Running Alembic database migrations..."
alembic upgrade head
echo "  Migrations complete."

echo "[2/2] Starting API server on port 8001..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8001
