#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== NH Capital Admin Dashboard ==="

# Install backend deps
echo "[backend] Installing Python dependencies..."
pip install -q -r "$DIR/backend/requirements.txt"

# Install frontend deps
echo "[frontend] Installing npm dependencies..."
cd "$DIR/frontend" && npm install --silent

# Start backend
echo "[backend] Starting FastAPI on :8000..."
cd "$DIR/backend"
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start frontend
echo "[frontend] Starting Vite dev server on :3000..."
cd "$DIR/frontend"
npm run dev &
FRONTEND_PID=$!

# Cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

echo ""
echo "Dashboard: http://localhost:3000"
echo "API:       http://localhost:8000/api/health"
echo ""
echo "Press Ctrl+C to stop."

wait
