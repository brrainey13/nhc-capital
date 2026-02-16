#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "Starting backend..."
cd backend
pip install -q -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

echo "Starting frontend..."
cd frontend
npm install --silent
npm run dev &
FRONTEND_PID=$!
cd ..

echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3000"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
