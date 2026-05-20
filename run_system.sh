#!/usr/bin/env bash
# MTO Treasury System — Linux/macOS Launcher
# Equivalent to run_system.bat for non-Windows environments.
#
# Usage:
#   chmod +x run_system.sh
#   ./run_system.sh
#
# For Docker deployments (recommended for production):
#   docker compose up -d
#
# For local development without Docker:
#   ./run_system.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================="
echo "          MTO TREASURY PORTAL — SYSTEM LAUNCHER"
echo "============================================================="
echo ""

# ---------------------------------------------------------------------------
# 1. Backend API
# ---------------------------------------------------------------------------
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    echo "[DOCKER] Starting API and database via Docker Compose..."
    docker compose up -d
    echo "[DOCKER] Services started. Run 'docker compose logs -f' to follow logs."
else
    echo "[LOCAL] Docker not running. Starting native API server..."

    # Activate virtual environment if it exists
    if [ -f "venv/bin/activate" ]; then
        # shellcheck disable=SC1091
        source venv/bin/activate
    elif [ -f ".venv/bin/activate" ]; then
        # shellcheck disable=SC1091
        source .venv/bin/activate
    fi

    echo "[1/3] Starting FastAPI backend on port 8000..."
    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!
    echo "      Backend PID: $BACKEND_PID"

    # ---------------------------------------------------------------------------
    # 2. Frontend portal
    # ---------------------------------------------------------------------------
    if [ -d "frontend/node_modules" ]; then
        echo "[2/3] Starting Next.js frontend on port 3000..."
        (cd frontend && npm run dev) &
        FRONTEND_PID=$!
        echo "      Frontend PID: $FRONTEND_PID"
    else
        echo "[2/3] Skipping frontend — run 'cd frontend && npm install && npm run dev' manually."
    fi

    # ---------------------------------------------------------------------------
    # 3. Desktop app (optional — only on systems with a display)
    # ---------------------------------------------------------------------------
    echo "[3/3] Waiting for backend to start (5 seconds)..."
    sleep 5

    if [ -n "$DISPLAY" ] || [ "$(uname)" = "Darwin" ]; then
        echo "      Starting desktop cashier app..."
        python clients/desktop/main.py &
    else
        echo "      No display detected — skipping desktop app."
        echo "      Access the web portal at http://localhost:3000"
    fi

    echo ""
    echo "============================================================="
    echo "  Backend PID : ${BACKEND_PID:-N/A}"
    echo "  Frontend PID: ${FRONTEND_PID:-N/A}"
    echo "  To stop     : kill \$BACKEND_PID \$FRONTEND_PID"
    echo "             or: ./stop_system.sh"
    echo "============================================================="
fi
