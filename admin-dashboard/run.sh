#!/bin/bash
# Start the admin dashboard — binds to localhost ONLY (Cloudflare Tunnel handles public access)
cd "$(dirname "$0")/backend"
exec python3 -m uvicorn main:app --host "${DASHBOARD_HOST:-127.0.0.1}" --port "${DASHBOARD_PORT:-8000}"
