#!/usr/bin/env bash
# MTO Treasury System — Linux/macOS Stop Script
# Equivalent to stop_system.bat for non-Windows environments.
#
# Usage:
#   chmod +x stop_system.sh
#   ./stop_system.sh

set -e

echo "============================================================="
echo "          STOPPING ALL MTO BACKGROUND SERVICES"
echo "============================================================="
echo ""

# Stop Docker Compose services if running
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    echo "[1/3] Stopping Docker Compose services..."
    docker compose down
else
    echo "[1/3] Docker not running — skipping."
fi

# Kill uvicorn / FastAPI backend
echo "[2/3] Stopping FastAPI backend (uvicorn)..."
pkill -f "uvicorn backend.main:app" 2>/dev/null && echo "      Stopped." || echo "      Not running."

# Kill Next.js dev server
echo "[3/3] Stopping Next.js frontend..."
pkill -f "next dev" 2>/dev/null && echo "      Stopped." || echo "      Not running."

echo ""
echo "============================================================="
echo "  All services stopped."
echo "============================================================="
